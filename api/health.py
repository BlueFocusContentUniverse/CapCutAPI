from datetime import datetime

from fastapi import APIRouter, Response
from sqlalchemy import text

from db import get_async_engine

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check(response: Response):
    try:
        db_status = "unknown"
        try:
            # Try opening a connection
            eng = get_async_engine().sync_engine
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            db_status = "healthy"
        except Exception:
            db_status = "unavailable"

        health_info = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "version": "1.7.0",
            "services": {"postgres": db_status, "api": "healthy"},
        }

        return health_info

    except Exception as e:
        error_info = {
            "status": "unhealthy",
            "timestamp": datetime.now().isoformat(),
            "error": str(e),
        }
        response.status_code = 503
        return error_info
