"""
SQLAlchemy database setup for PostgreSQL.
Reads DATABASE_URL from environment, provides Base, Session and init_db.

Environment Variables for Database Configuration:
- DATABASE_URL: Complete database connection string (overrides individual settings)
- POSTGRES_USER: PostgreSQL username (default: postgres)
- POSTGRES_PASSWORD: PostgreSQL password (default: postgres)
- POSTGRES_HOST: PostgreSQL host (default: localhost)
- POSTGRES_PORT: PostgreSQL port (default: 5432)
- POSTGRES_DB: PostgreSQL database name (default: kox)

Connection Pool Configuration (environment variables):
- DB_POOL_SIZE: Number of persistent connections in pool (default: 10)
- DB_MAX_OVERFLOW: Additional connections beyond pool_size (default: 20)
- DB_POOL_RECYCLE: Recycle connections after N seconds (default: 3600)
- DB_POOL_TIMEOUT: Timeout for getting connection from pool (default: 30)
"""

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

logger = logging.getLogger(__name__)
Base = declarative_base()

# Global engine instance - created once and reused
_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


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
    logger.info(f"DATABASE_URL: {url}")
    if url:
        return url
    # Fallback to individual parts if provided
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    dbname = os.getenv("POSTGRES_DB", "kox")
    logger.info(f"POSTGRES_USER: {user}, POSTGRES_PASSWORD: {password}, POSTGRES_HOST: {host}, POSTGRES_PORT: {port}, POSTGRES_DB: {dbname}")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}"


def _get_pool_config() -> dict:
    """Get connection pool configuration from environment variables."""
    return {
        "pool_size": int(os.getenv("DB_POOL_SIZE", "10")),  # Number of persistent connections
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "20")),  # Additional connections beyond pool_size
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "3600")),  # Recycle connections after 1 hour (in seconds)
        "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT", "30")),  # Timeout for getting connection from pool
        "pool_pre_ping": True,  # Verify connections before use
    }


def get_engine(echo: bool = False) -> Engine:
    """Get or create the singleton database engine with proper connection pooling."""
    global _engine
    if _engine is None:
        pool_config = _get_pool_config()
        logger.info(f"Creating database engine with pool config: {pool_config}")

        _engine = create_engine(
            _database_url(),
            echo=echo,
            future=True,
            **pool_config
        )
        logger.info(f"Created engine: {_engine}")
    return _engine


def get_sessionmaker() -> sessionmaker:
    """Get or create the singleton sessionmaker."""
    global _SessionLocal
    if _SessionLocal is None:
        engine = get_engine()
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        logger.info("Created sessionmaker")
    return _SessionLocal


@contextmanager
def get_session() -> Iterator[Session]:
    """Get a database session with proper connection management."""
    SessionLocal = get_sessionmaker()
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(engine: Engine | None = None) -> None:
    """Create tables if they do not exist."""
    eng = engine or get_engine()
    logger.info(f"Initializing database with engine: {eng}")
    # Import models to ensure metadata is populated
    from models import Draft, DraftVersion, Video, VideoTask  # noqa: F401
    Base.metadata.create_all(bind=eng)
    # Simple connectivity check
    with eng.connect() as conn:
        conn.execute(text("SELECT 1"))
        conn.commit()
    logger.info("Database initialization completed")


def get_pool_status() -> dict:
    """Get current connection pool status for monitoring."""
    engine = get_engine()
    pool = engine.pool

    # Get pool statistics (these are internal SQLAlchemy attributes)
    status = {
        "pool_size": getattr(pool, "_pool_size", "N/A"),
        "checked_in": len(getattr(pool, "_checked_in", [])),
        "checked_out": len(getattr(pool, "_checked_out", [])),
        "overflow": getattr(pool, "_overflow", 0),
        "invalid": len(getattr(pool, "_invalid", [])),
    }

    logger.info(f"Pool status: {status}")
    return status


def dispose_engine() -> None:
    """Dispose of the engine and reset global state. Useful for testing or forced cleanup."""
    global _engine, _SessionLocal
    if _engine:
        logger.info("Disposing database engine")
        _engine.dispose()
        _engine = None
    _SessionLocal = None


