"""
Patched MCP server components to support distributed sessions via Redis.
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from http import HTTPStatus
from uuid import uuid4

import anyio
from anyio.abc import TaskStatus
from fastmcp.server.http import (
    RequireAuthMiddleware,
    StreamableHTTPASGIApp,
    build_resource_metadata_url,
    create_base_app,
)
from mcp.server.streamable_http import (
    MCP_SESSION_ID_HEADER,
    EventStore,
    StreamableHTTPServerTransport,
)
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import BaseRoute, Route
from starlette.types import Receive, Scope, Send

logger = logging.getLogger(__name__)

class DistributedStreamableHTTPSessionManager(StreamableHTTPSessionManager):
    """
    A subclass of StreamableHTTPSessionManager that checks the EventStore
    for session existence before rejecting a request. This allows multiple
    workers to handle requests for the same session, provided the session
    events are persisted in Redis.
    """

    async def _handle_stateful_request(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """
        Process request in stateful mode - maintaining session state between requests.
        """
        request = Request(scope, receive)
        request_mcp_session_id = request.headers.get(MCP_SESSION_ID_HEADER)

        # Existing session case (in memory)
        if request_mcp_session_id is not None and request_mcp_session_id in self._server_instances:
            transport = self._server_instances[request_mcp_session_id]
            logger.debug("Session already exists in memory, handling request directly")
            await transport.handle_request(scope, receive, send)
            return

        # Check if session exists in EventStore (Redis) but not in memory
        if request_mcp_session_id is not None and self.event_store and hasattr(self.event_store, "session_exists"):
            if await self.event_store.session_exists(request_mcp_session_id):
                logger.info(f"Session {request_mcp_session_id} found in Redis but not in memory. Recreating transport.")
                # Recreate the transport for this worker
                await self._create_and_register_transport(request_mcp_session_id, scope, receive, send)
                return

        if request_mcp_session_id is None:
            # New session case
            logger.debug("Creating new transport")
            new_session_id = uuid4().hex
            await self._create_and_register_transport(new_session_id, scope, receive, send)
        else:
            # Invalid session ID
            response = Response(
                "Bad Request: No valid session ID provided",
                status_code=HTTPStatus.BAD_REQUEST,
            )
            await response(scope, receive, send)

    async def _create_and_register_transport(self, session_id: str, scope: Scope, receive: Receive, send: Send):
        """Helper to create transport, register it, start server task, and handle request."""
        async with self._session_creation_lock:
            # Double check if it was created while waiting for lock
            if session_id in self._server_instances:
                transport = self._server_instances[session_id]
                await transport.handle_request(scope, receive, send)
                return

            http_transport = StreamableHTTPServerTransport(
                mcp_session_id=session_id,
                is_json_response_enabled=self.json_response,
                event_store=self.event_store,
                security_settings=self.security_settings,
            )

            assert http_transport.mcp_session_id is not None
            self._server_instances[http_transport.mcp_session_id] = http_transport
            logger.info(f"Registered transport with session ID: {session_id}")

            # Define the server runner
            async def run_server(*, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
                async with http_transport.connect() as streams:
                    read_stream, write_stream = streams
                    task_status.started()
                    try:
                        await self.app.run(
                            read_stream,
                            write_stream,
                            self.app.create_initialization_options(),
                            stateless=False,  # Stateful mode
                        )
                    except Exception as e:
                        logger.error(
                            f"Session {http_transport.mcp_session_id} crashed: {e}",
                            exc_info=True,
                        )
                    finally:
                        # Only remove from instances if not terminated
                        if (
                            http_transport.mcp_session_id
                            and http_transport.mcp_session_id in self._server_instances
                            and not http_transport.is_terminated
                        ):
                            logger.info(
                                "Cleaning up crashed session "
                                f"{http_transport.mcp_session_id} from "
                                "active instances."
                            )
                            del self._server_instances[http_transport.mcp_session_id]

            # Assert task group is not None for type checking
            if self._task_group is None:
                 raise RuntimeError("Task group is not initialized. Make sure to use run().")

            # Start the server task
            await self._task_group.start(run_server)

            # Handle the HTTP request and return the response
            await http_transport.handle_request(scope, receive, send)


def create_distributed_streamable_http_app(
    server,
    streamable_http_path: str,
    event_store: EventStore | None = None,
    auth = None,
    json_response: bool = False,
    stateless_http: bool = False,
    debug: bool = False,
    routes: list[BaseRoute] | None = None,
    middleware: list[Middleware] | None = None,
):
    """
    Return an instance of the StreamableHTTP server app with distributed session support.
    """
    server_routes: list[BaseRoute] = []
    server_middleware: list[Middleware] = []

    # Create session manager using the provided event store
    # Use our custom DistributedStreamableHTTPSessionManager
    session_manager = DistributedStreamableHTTPSessionManager(
        app=server._mcp_server,
        event_store=event_store,
        json_response=json_response,
        stateless=stateless_http,
    )

    # Create the ASGI app wrapper
    streamable_http_app = StreamableHTTPASGIApp(session_manager)

    # Add StreamableHTTP routes with or without auth
    if auth:
        # Get auth middleware from the provider
        auth_middleware = auth.get_middleware()

        # Get auth provider's own routes (OAuth endpoints, metadata, etc)
        auth_routes = auth.get_routes(mcp_path=streamable_http_path)
        server_routes.extend(auth_routes)
        server_middleware.extend(auth_middleware)

        # Build RFC 9728-compliant metadata URL
        resource_url = auth._get_resource_url(streamable_http_path)
        resource_metadata_url = (
            build_resource_metadata_url(resource_url) if resource_url else None
        )

        # Create protected HTTP endpoint route
        server_routes.append(
            Route(
                streamable_http_path,
                endpoint=RequireAuthMiddleware(
                    streamable_http_app,
                    auth.required_scopes,
                    resource_metadata_url,
                ),
                methods=["GET", "POST", "DELETE"],
            )
        )
    else:
        # No auth required
        server_routes.append(
            Route(
                streamable_http_path,
                endpoint=streamable_http_app,
            )
        )

    # Add custom routes with lowest precedence
    if routes:
        server_routes.extend(routes)
    server_routes.extend(server._get_additional_http_routes())

    # Add middleware
    if middleware:
        server_middleware.extend(middleware)

    # Create a lifespan manager to start and stop the session manager
    @asynccontextmanager
    async def lifespan(app) -> AsyncGenerator[None, None]:
        async with server._lifespan_manager(), session_manager.run():
            yield

    # Create and return the app with lifespan
    app = create_base_app(
        routes=server_routes,
        middleware=server_middleware,
        debug=debug,
        lifespan=lifespan,
    )
    # Store the FastMCP server instance on the Starlette app state
    app.state.fastmcp_server = server

    app.state.path = streamable_http_path

    return app
