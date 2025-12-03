import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from db import get_session
from models import VideoTask

logger = logging.getLogger(__name__)
router = APIRouter(tags=["tasks"])


class CreateTaskRequest(BaseModel):
    task_id: str
    draft_id: str
    extra: Optional[Dict[str, Any]] = None


@router.post("/tasks")
def create_task(request: CreateTaskRequest):
    if not request.task_id or not request.draft_id:
        return JSONResponse(status_code=400, content={"success": False, "error": "task_id and draft_id are required"})

    with get_session() as session:
        existing = session.execute(select(VideoTask).where(VideoTask.task_id == request.task_id)).scalar_one_or_none()
        if existing:
            return {"success": True, "output": {"task_id": existing.task_id}}

        row = VideoTask(task_id=request.task_id, draft_id=request.draft_id, status="initialized", extra=request.extra)
        session.add(row)

    return {"success": True, "output": {"task_id": request.task_id}}


@router.get("/tasks/{task_id}")
def get_task(task_id: str):
    with get_session() as session:
        row = session.execute(select(VideoTask).where(VideoTask.task_id == task_id)).scalar_one_or_none()
        if not row:
            return JSONResponse(status_code=404, content={"success": False, "error": "not_found"})
        return {
            "success": True,
            "output": {
                "task_id": row.task_id,
                "draft_id": row.draft_id,
                "status": row.status,
                "render_status": row.render_status,
                "progress": row.progress,
                "message": row.message,
                "extra": row.extra,
            }
        }


class UpdateTaskRequest(BaseModel):
    status: Optional[str] = None
    progress: Optional[int] = None
    message: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


@router.patch("/tasks/{task_id}")
def update_task(task_id: str, request: UpdateTaskRequest):
    with get_session() as session:
        row = session.execute(select(VideoTask).where(VideoTask.task_id == task_id)).scalar_one_or_none()
        if not row:
            return JSONResponse(status_code=404, content={"success": False, "error": "not_found"})

        data = request.dict(exclude_unset=True)
        allowed = {"status", "progress", "message", "extra"}
        for key, value in data.items():
            if key in allowed:
                setattr(row, key, value)

    return {"success": True, "output": {"task_id": task_id}}


@router.patch("/tasks/by_draft/{draft_id}")
def update_tasks_by_draft(draft_id: str, request: UpdateTaskRequest):
    with get_session() as session:
        rows = session.execute(select(VideoTask).where(VideoTask.draft_id == draft_id)).scalars().all()
        if not rows:
            return JSONResponse(status_code=404, content={"success": False, "error": "not_found"})

        data = request.dict(exclude_unset=True)
        allowed = {"status", "progress", "message", "extra"}
        updates = {k: v for k, v in data.items() if k in allowed}
        if not updates:
            return JSONResponse(status_code=400, content={"success": False, "error": "no_valid_fields"})

        for row in rows:
            for key, value in updates.items():
                setattr(row, key, value)

        updated_task_ids = [row.task_id for row in rows]

    return {
        "success": True,
        "output": {
            "updated": len(updated_task_ids),
            "task_ids": updated_task_ids,
            "draft_id": draft_id
        }
    }


