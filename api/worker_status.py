"""Endpoints for inspecting and updating the Celery worker pool health."""

from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from repositories.worker_status_repository import get_worker_status_repository

router = APIRouter(prefix="/api/worker-status", tags=["worker-status"])


class WorkerStatusUpdateRequest(BaseModel):
    worker_name: str
    hostname: Optional[str] = None
    is_available: bool = True
    task_id: Optional[str] = None
    error_message: Optional[str] = None
    traceback: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


@router.get("", summary="List all workers")
async def list_workers() -> dict:
    """Return all workers along with their availability metadata."""
    repo = get_worker_status_repository()
    workers = await repo.list_workers()
    available = [w for w in workers if w.get("is_available")]
    return {
        "total_workers": len(workers),
        "available_workers": len(available),
        "workers": workers,
    }


@router.get("/available", summary="List available worker names")
async def list_available_workers() -> dict:
    """Return only the workers currently marked as available."""
    repo = get_worker_status_repository()
    workers = await repo.list_available_workers()
    return {
        "available_workers": len(workers),
        "worker_names": [w["worker_name"] for w in workers],
        "workers": workers,
    }


@router.post("", summary="Report worker availability")
async def update_worker_status(request: WorkerStatusUpdateRequest):
    """Persist worker liveness information sent by the notification worker."""
    repo = get_worker_status_repository()
    if request.is_available:
        await repo.upsert_worker_status(
            worker_name=request.worker_name,
            hostname=request.hostname,
            is_available=True,
            reason=request.error_message,
            task_id=request.task_id,
            extra=request.extra,
        )
    else:
        await repo.mark_worker_unavailable(
            worker_name=request.worker_name,
            task_id=request.task_id,
            reason=request.error_message or "Unknown error",
            traceback_text=request.traceback,
        )
    return {"success": True}


@router.get("/failure-logs", summary="List worker failure logs")
async def list_failure_logs(
    worker_name: Optional[str] = None, limit: Optional[int] = None
):
    """Return worker failure logs, optionally filtered by worker_name."""
    repo = get_worker_status_repository()
    logs = await repo.list_failure_logs(worker_name=worker_name, limit=limit)
    return {
        "total_logs": len(logs),
        "logs": logs,
    }


@router.delete("/{worker_name}", summary="Delete a worker")
async def delete_worker(worker_name: str):
    """Remove a worker from the WorkerStatus table."""
    repo = get_worker_status_repository()
    success = await repo.delete_worker(worker_name)
    if success:
        return {
            "success": True,
            "message": f"Worker {worker_name} deleted successfully",
        }
    return {"success": False, "message": f"Worker {worker_name} not found"}
