import os
from typing import Optional

import redis.asyncio as redis
from mcp.server.streamable_http import (
    EventCallback,
    EventId,
    EventMessage,
    EventStore,
    StreamId,
)
from mcp.types import JSONRPCMessage


class RedisEventStore(EventStore):
    def __init__(self, redis_url: Optional[str] = None, ttl: int = 3600):
        self.redis_url = redis_url or os.environ.get("MCP_SESSION_REDIS_URL", "redis://localhost:6379/4")
        self.redis = redis.from_url(self.redis_url, decode_responses=True)
        self.ttl = ttl

    async def store_event(self, stream_id: StreamId, message: JSONRPCMessage) -> EventId:
        """
        Stores an event for later retrieval using Redis Streams.
        """
        # Serialize message
        data = message.model_dump_json(by_alias=True, exclude_none=True)

        # Use Redis Stream to store the event
        # Key: mcp:stream:{stream_id}
        stream_key = f"mcp:stream:{stream_id}"

        # XADD returns the generated ID (e.g., "1638512345678-0")
        redis_id = await self.redis.xadd(stream_key, {"data": data})

        # Set TTL for the stream key to auto-cleanup
        await self.redis.expire(stream_key, self.ttl)

        # Return encoded ID: "{stream_id}:{redis_id}"
        return f"{stream_id}:{redis_id}"

    async def replay_events_after(
        self,
        last_event_id: EventId,
        send_callback: EventCallback,
    ) -> StreamId | None:
        """
        Replays events that occurred after the specified event ID.
        """
        try:
            # Parse stream_id and redis_id from the composite event ID
            stream_id, redis_last_id = last_event_id.rsplit(":", 1)
        except ValueError:
            # Invalid format
            return None

        stream_key = f"mcp:stream:{stream_id}"

        # Check if stream exists
        if not await self.redis.exists(stream_key):
            return None

        # Read from Redis Stream starting after redis_last_id
        # XREAD returns list of [stream_name, list of [id, fields]]
        events = await self.redis.xread({stream_key: redis_last_id})

        if not events:
            return stream_id

        for _, stream_events in events:
            for event_id, event_data in stream_events:
                data_str = event_data.get("data")
                if not data_str:
                    continue

                try:
                    message = JSONRPCMessage.model_validate_json(data_str)
                    full_event_id = f"{stream_id}:{event_id}"
                    await send_callback(EventMessage(message=message, event_id=full_event_id))
                except Exception as e:
                    # Log error but continue replaying
                    print(f"Error parsing event {event_id}: {e}")
                    continue

        return stream_id

    async def session_exists(self, stream_id: StreamId) -> bool:
        """
        Check if a session stream exists in Redis.
        """
        stream_key = f"mcp:stream:{stream_id}"
        return bool(await self.redis.exists(stream_key))
