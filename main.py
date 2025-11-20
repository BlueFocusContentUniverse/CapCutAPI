import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import get_api_router
from db import init_db
from logging_utils import setup_logging
from mcp_stream_server import create_fastmcp_app
from redis_event_store import RedisEventStore

# Load environment variables
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    load_dotenv(env_file)

# Setup logging
setup_logging(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create MCP server instance
mcp_server = create_fastmcp_app()

# Create Redis Event Store for session persistence
# This allows the MCP server to work with multiple workers
try:
    event_store = RedisEventStore()
    logger.info("Initialized RedisEventStore for MCP session persistence")
except Exception as e:
    logger.warning(f"Failed to initialize RedisEventStore: {e}. Falling back to in-memory session storage (single worker only).")
    event_store = None

mcp_app = mcp_server.http_app(path="/mcp")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        init_db()
        logger.info("Database initialization successful")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")

    # Run MCP lifespan within the main app lifespan
    async with mcp_app.lifespan(app):
        yield
    # Shutdown

app = FastAPI(lifespan=lifespan, title="CapCut API Service", version="1.6.3")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount MCP routes
app.mount("/jymcp", mcp_app)

# Include API router
app.include_router(get_api_router())

if __name__ == "__main__":
    import uvicorn

    from settings.local import PORT
    uvicorn.run(app, host="0.0.0.0", port=PORT)

