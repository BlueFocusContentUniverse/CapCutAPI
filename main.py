import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette import status as starlette_status

from api import get_api_router
from db import init_db
from logging_utils import setup_logging
from mcp_stream_server import create_fastmcp_app

from util.cognito.auth_middleware import get_auth_middleware
from util.rate_limit import get_identifier_from_request, get_rate_limiter

# Load environment variables
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    load_dotenv(env_file)

# Setup logging
setup_logging(level=logging.INFO)
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

    # Run MCP lifespan within the main app lifespan
    async with mcp_app.lifespan(app):
        yield
    # Shutdown

app = FastAPI(lifespan=lifespan, title="CapCut API Service", version="1.7.0")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化中间件
rate_limiter = get_rate_limiter()
if rate_limiter.enabled:
    logger.info(f"Rate Limit 中间件已启用: {rate_limiter.requests_per_minute} 次/分钟")
else:
    logger.warning("Rate Limit 中间件未启用 (Redis未配置)")

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Rate limit middleware - 自动拦截所有请求进行限流检查"""
    # 排除MCP路由和默认排除路径
    # 注意:先检查精确匹配"/",再检查其他路径的前缀匹配
    if request.url.path == "/":
        return await call_next(request)

    exclude_paths = ["/jymcp", "/docs", "/redoc", "/openapi.json", "/health"]
    if any(request.url.path.startswith(path) for path in exclude_paths):
        return await call_next(request)

    # 获取限流器(使用全局实例)
    limiter = get_rate_limiter()
    if not limiter.enabled:
        return await call_next(request)

    # 从请求中提取标识符(IP、token hash、client_id等)
    identifier = get_identifier_from_request(request)

    # 检查速率限制
    try:
        limiter.check_rate_limit(identifier)
    except HTTPException as e:
        # 在中间件中直接返回429响应,避免FastAPI异常处理导致500错误
        if e.status_code == 429:
            logger.warning(f"Rate limit exceeded: {identifier} on {request.url.path}")
            return JSONResponse(
                status_code=starlette_status.HTTP_429_TOO_MANY_REQUESTS,
                content=e.detail,
                headers=e.headers
            )
        raise
    except Exception as e:
        logger.error(f"Rate limit check failed: {e}", exc_info=True)
        # fail-open策略:如果限流检查出错,允许请求继续

    # 继续处理请求
    response = await call_next(request)

    # 在响应头中添加限流信息
    try:
        rate_limit_info = limiter.get_rate_limit_info(identifier)
        response.headers["X-RateLimit-Limit"] = str(rate_limit_info["limit"])
        response.headers["X-RateLimit-Remaining"] = str(rate_limit_info["remaining"])
    except Exception as e:
        logger.error(f"Failed to add rate limit headers: {e}", exc_info=True)

    return response

# Mount MCP routes
app.mount("/jymcp", mcp_app)

# Include API router
api_router, health_router = get_api_router()
app.include_router(api_router)
app.include_router(health_router)

if __name__ == "__main__":
    import uvicorn

    from settings.local import PORT
    uvicorn.run(app, host="0.0.0.0", port=PORT)

