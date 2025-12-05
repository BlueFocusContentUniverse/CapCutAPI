import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import get_api_router
from db import init_db

from mcp_services import create_fastmcp_app
from middleware import LoggingMiddleware, RateLimitMiddleware
from util.rate_limit import get_rate_limiter
from repositories.redis_draft_cache import init_redis_draft_cache, shutdown_redis_draft_cache


# Load environment variables
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    load_dotenv(env_file)

# Setup logging
logger = logging.getLogger(__name__)

# Create MCP server instance
mcp_server = create_fastmcp_app()

mcp_app = mcp_server.http_app(path="/mcp")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        init_db()
        logger.info("Database initialization successful")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
    
    # 初始化Redis缓存（如果可用）
    try:
        redis_cache = init_redis_draft_cache()
        if redis_cache:
            logger.info("Redis草稿缓存初始化成功")
        else:
            logger.info("Redis草稿缓存不可用，将使用PostgreSQL作为主要存储")
    except Exception as e:
        logger.warning(f"Redis草稿缓存初始化失败: {e}，将降级到PostgreSQL")

    # Run MCP lifespan within the main app lifespan
    async with mcp_app.lifespan(app):
        yield
    
    # Shutdown
    # 停止Redis缓存后台同步任务
    try:
        shutdown_redis_draft_cache()
    except Exception as e:
        logger.error(f"关闭Redis缓存时出错: {e}")

app = FastAPI(lifespan=lifespan, title="CapCut API Service", version="1.7.0")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure Logging middleware
app.add_middleware(LoggingMiddleware)
logger.info("Logging middleware enabled")

# Configure Rate Limit middleware
rate_limiter = get_rate_limiter()
if rate_limiter.enabled:
    app.add_middleware(RateLimitMiddleware)
    logger.info(f"Rate Limit middleware enabled: {rate_limiter.requests_per_minute} requests/minute")
else:
    logger.warning("Rate Limit middleware not enabled (Redis not configured)")

# Mount MCP routes
app.mount("/jymcp", mcp_app)

# Include API router
api_router, unprotected_router = get_api_router()
app.include_router(api_router)
app.include_router(unprotected_router)

if __name__ == "__main__":
    import uvicorn

    from settings.local import PORT
    uvicorn.run(app, host="0.0.0.0", port=PORT)

