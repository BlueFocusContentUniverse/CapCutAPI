"""
SQLAlchemy async database setup for PostgreSQL (asyncpg only).
Reads DATABASE_URL from environment, provides Base, AsyncSession helpers and init hooks.

Environment Variables for Database Configuration:
- DATABASE_URL: Complete database connection string (overrides individual settings)

Connection Pool Configuration (environment variables):
- DB_POOL_SIZE: Number of persistent connections in pool (default: 15)
- DB_MAX_OVERFLOW: Additional connections beyond pool_size (default: 30)
- DB_POOL_RECYCLE: Recycle connections after N seconds (default: 600)
- DB_POOL_TIMEOUT: Timeout for getting connection from pool (default: 30)

Async driver: defaults to asyncpg via driver rewrite (postgresql -> postgresql+asyncpg).
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

logger = logging.getLogger(__name__)
Base = declarative_base()

# Global async engine instance - created once and reused
_async_engine: AsyncEngine | None = None
_AsyncSessionLocal: async_sessionmaker[AsyncSession] | None = None


# Load .env early so any importers that touch DB use the correct settings
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    try:
        load_dotenv(_env_file)
        logger.info(f"Loaded environment from: {_env_file}")
    except Exception:
        # Best-effort; do not fail module import
        pass


def _database_url() -> str:
    url = os.getenv("DATABASE_URL")
    # Log the effective value (may be None) for debugging but avoid leaking secrets
    logger.info("DATABASE_URL is set" if url else "DATABASE_URL is not set")
    if url:
        return url

    # Fail fast with a clear error message when no database URL is configured
    raise RuntimeError(
        "DATABASE_URL environment variable is not set — a valid database URL must be provided."
    )


def _make_async_url(url: str) -> str:
    """Ensure the URL uses the asyncpg driver."""

    if "+asyncpg" in url:
        return url
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _get_pool_config() -> dict:
    """Get connection pool configuration from environment variables."""
    return {
        "pool_size": int(
            os.getenv("DB_POOL_SIZE", "15")
        ),  # Number of persistent connections
        "max_overflow": int(
            os.getenv("DB_MAX_OVERFLOW", "30")
        ),  # Additional connections beyond pool_size
        "pool_recycle": int(
            os.getenv("DB_POOL_RECYCLE", "600")
        ),  # Recycle connections after N seconds
        "pool_timeout": int(
            os.getenv("DB_POOL_TIMEOUT", "30")
        ),  # Timeout for getting connection from pool
        "pool_pre_ping": True,  # Verify connections before use
    }


def get_async_engine(echo: bool = False) -> AsyncEngine:
    """Get or create the async engine (asyncpg driver)."""

    global _async_engine
    if _async_engine is None:
        pool_config = _get_pool_config()
        logger.info(f"Creating async database engine with pool config: {pool_config}")

        async_url = _make_async_url(_database_url())
        _async_engine = create_async_engine(
            async_url, echo=echo, future=True, **pool_config
        )
        logger.info(f"Created async engine: {_async_engine}")
    return _async_engine


def get_async_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Get or create the async sessionmaker."""

    global _AsyncSessionLocal
    if _AsyncSessionLocal is None:
        engine = get_async_engine()
        _AsyncSessionLocal = async_sessionmaker(
            autocommit=False, autoflush=False, bind=engine
        )
        logger.info("Created async sessionmaker")
    return _AsyncSessionLocal


@asynccontextmanager
async def get_async_session() -> AsyncIterator[AsyncSession]:
    """Get an async database session with proper connection management."""

    SessionLocal = get_async_sessionmaker()
    session: AsyncSession = SessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def init_db_async(engine: AsyncEngine | None = None) -> None:
    """Create tables if they do not exist using the async engine."""

    eng = engine or get_async_engine()
    logger.info(f"Initializing database (async) with engine: {eng}")

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("SELECT 1"))
    logger.info("Async database initialization completed")


async def dispose_async_engine() -> None:
    """Dispose of the async engine and reset async sessionmaker."""

    global _async_engine, _AsyncSessionLocal
    if _async_engine:
        logger.info("Disposing async database engine")
        await _async_engine.dispose()
    _async_engine = None
    _AsyncSessionLocal = None
