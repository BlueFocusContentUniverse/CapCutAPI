"""
Rate Limit Middleware
Automatically intercepts all requests for rate limiting checks.
M2M (machine-to-machine) tokens are exempt from rate limiting.
"""

import logging
from typing import List, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette import status as starlette_status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from util.rate_limit import get_identifier_from_request, get_rate_limiter

logger = logging.getLogger(__name__)


def is_m2m_token(request: Request) -> bool:
    """
    Check if the request contains an M2M (machine-to-machine) token.

    Cognito M2M tokens (client_credentials flow) typically:
    - Have token_use: "access"
    - Have scope claims
    - Do NOT have 'sub' claim with user ID (or sub equals client_id)
    - Do NOT have 'username' or 'cognito:username' claims

    We check the Authorization header and try to decode the JWT claims
    without full verification (just to check token type).

    Args:
        request: The incoming request

    Returns:
        True if the token appears to be an M2M token, False otherwise
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return False

    token = auth_header[7:].strip()
    if not token:
        return False

    try:
        # Import jose for JWT decoding (without verification)
        from jose import jwt

        # Decode without verification to inspect claims
        # This is safe because we're only checking token type, not authenticating
        claims = jwt.get_unverified_claims(token)

        # M2M tokens from Cognito client_credentials flow characteristics:
        # 1. token_use is "access"
        # 2. Has 'client_id' claim
        # 3. Does NOT have 'username' or 'cognito:username' claims
        # 4. 'sub' claim equals 'client_id' (or is absent in some configs)

        token_use = claims.get("token_use")
        client_id = claims.get("client_id")
        username = claims.get("username") or claims.get("cognito:username")
        sub = claims.get("sub")

        # If it has a username, it's a user token, not M2M
        if username:
            return False

        # M2M token: access token with client_id but no username
        # and sub equals client_id (machine identity)
        if token_use == "access" and client_id and (sub == client_id or sub is None):
            logger.debug(f"M2M token detected for client_id: {client_id}")
            return True

        return False

    except Exception as e:
        # If we can't decode the token, assume it's not M2M
        logger.debug(f"Failed to decode token for M2M check: {e}")
        return False


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware that uses Redis for distributed rate limiting.

    Features:
    - Configurable excluded paths
    - M2M tokens bypass rate limiting
    - Adds rate limit headers to responses
    - Fail-open strategy on errors
    """

    def __init__(
        self,
        app,
        exclude_paths: Optional[List[str]] = None,
    ):
        """
        Initialize the rate limit middleware.

        Args:
            app: The ASGI application
            exclude_paths: List of path prefixes to exclude from rate limiting
        """
        super().__init__(app)
        self.exclude_paths = exclude_paths or [
            "/jymcp",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/health",
            "/mcp",
        ]

    def _should_skip_rate_limit(self, request: Request) -> bool:
        """
        Determine if the request should skip rate limiting.

        Args:
            request: The incoming request

        Returns:
            True if rate limiting should be skipped
        """
        # Skip root path
        if request.url.path == "/":
            return True

        # Skip excluded paths
        if any(request.url.path.startswith(path) for path in self.exclude_paths):
            return True

        # Skip M2M tokens (machine-to-machine authentication)
        if is_m2m_token(request):
            logger.debug(f"Skipping rate limit for M2M token on {request.url.path}")
            return True

        return False

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """
        Process the request and apply rate limiting.

        Args:
            request: The incoming request
            call_next: The next middleware/endpoint to call

        Returns:
            The response
        """
        # Check if rate limiting should be skipped
        if self._should_skip_rate_limit(request):
            return await call_next(request)

        # Get rate limiter instance
        limiter = get_rate_limiter()
        if not limiter.enabled:
            return await call_next(request)

        # Extract identifier from request (IP, token hash, client_id, etc.)
        identifier = get_identifier_from_request(request)

        # Check rate limit
        try:
            limiter.check_rate_limit(identifier)
        except HTTPException as e:
            # Return 429 response directly to avoid FastAPI exception handling causing 500 errors
            if e.status_code == 429:
                logger.warning(
                    f"Rate limit exceeded: {identifier} on {request.url.path}"
                )
                return JSONResponse(
                    status_code=starlette_status.HTTP_429_TOO_MANY_REQUESTS,
                    content=e.detail,
                    headers=e.headers,
                )
            raise
        except Exception as e:
            logger.error(f"Rate limit check failed: {e}", exc_info=True)
            # Fail-open strategy: if rate limit check fails, allow request to continue

        # Continue processing request
        response = await call_next(request)

        # Add rate limit info to response headers
        try:
            rate_limit_info = limiter.get_rate_limit_info(identifier)
            response.headers["X-RateLimit-Limit"] = str(rate_limit_info["limit"])
            response.headers["X-RateLimit-Remaining"] = str(
                rate_limit_info["remaining"]
            )
        except Exception as e:
            logger.error(f"Failed to add rate limit headers: {e}", exc_info=True)

        return response
