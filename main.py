import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import get_api_router
from db import init_db_async
from mcp_services import create_fastmcp_app
from middleware import LoggingMiddleware, RateLimitMiddleware
from repositories.redis_draft_cache import (
    init_redis_draft_cache,
    shutdown_redis_draft_cache,
)
from services.draft_queue_manager import get_queue_manager
from util.memory_debug import start_memory_debug_task
from util.otel_setup import setup_opentelemetry, shutdown_opentelemetry
from util.rate_limit import get_rate_limiter

# Load environment variables
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    load_dotenv(env_file, override=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Create MCP server instance
mcp_server = create_fastmcp_app()

mcp_app = mcp_server.http_app(path="/mcp")

# 初始化 OpenTelemetry SDK（在应用创建之前）
fastapi_instrumentor = None
try:
    fastapi_instrumentor = setup_opentelemetry()
    if fastapi_instrumentor:
        logger.info("OpenTelemetry SDK 初始化成功")
    else:
        logger.info("OpenTelemetry 未启用或初始化失败")
except Exception as e:
    logger.error(f"OpenTelemetry 初始化失败: {e}", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    memory_task = None
    # Startup
    try:
        await init_db_async()
        logger.info("Database initialization successful")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")

    # Optional: memory growth diagnostics
    try:
        memory_task = start_memory_debug_task(logger)
    except Exception as e:
        logger.warning(f"Failed to start MEMORY_DEBUG task: {e}")

    # 初始化Redis缓存（如果可用）
    try:
        redis_cache = await init_redis_draft_cache()
        if redis_cache:
            logger.info("Redis草稿缓存初始化成功")
        else:
            logger.info("Redis草稿缓存不可用，将使用PostgreSQL作为主要存储")
    except Exception as e:
        logger.warning(f"Redis草稿缓存初始化失败: {e}，将降级到PostgreSQL")

    # 启动草稿队列管理器（用于解决并发竞态问题）
    try:
        queue_manager = get_queue_manager()
        await queue_manager.start()
        logger.info("草稿队列管理器启动成功")
    except Exception as e:
        logger.warning(f"草稿队列管理器启动失败: {e}")

    # Run MCP lifespan within the main app lifespan
    async with mcp_app.lifespan(app):
        yield

    # Shutdown
    # 关闭草稿队列管理器
    try:
        queue_manager = get_queue_manager()
        await queue_manager.shutdown()
        logger.info("草稿队列管理器已关闭")
    except Exception as e:
        logger.error(f"关闭草稿队列管理器时出错: {e}")

    # 停止Redis缓存后台同步任务
    try:
        await shutdown_redis_draft_cache()
    except Exception as e:
        logger.error(f"关闭Redis缓存时出错: {e}")

    if memory_task is not None:
        memory_task.cancel()
        try:
            await memory_task
        except Exception:
            pass
    
    # 关闭 OpenTelemetry
    try:
        shutdown_opentelemetry()
    except Exception as e:
        logger.error(f"关闭 OpenTelemetry 时出错: {e}")


# 根据环境变量决定是否关闭 API 文档
environment = os.getenv("ENVIRONMENT", "").lower()
is_production = environment in ("production", "prod")

app = FastAPI(
    lifespan=lifespan,
    title="CapCut API Service",
    version="1.9.0",
    docs_url=None if is_production else "/docs",  # 生产环境关闭 Swagger UI
    redoc_url=None if is_production else "/redoc",  # 生产环境关闭 ReDoc
    openapi_url=None
    if is_production
    else "/openapi.json",  # 生产环境关闭 OpenAPI 规范文档
)

# 在应用创建后立即进行 FastAPI 插桩（必须在中间件添加之前）
if fastapi_instrumentor:
    try:
        fastapi_instrumentor.instrument_app(app)
        logger.info("OpenTelemetry FastAPI 插桩已启用")
    except Exception as e:
        logger.error(f"FastAPI 插桩失败: {e}", exc_info=True)

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
    logger.info(
        f"Rate Limit middleware enabled: {rate_limiter.requests_per_minute} requests/minute"
    )
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

    # 配置 uvicorn 日志级别
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
