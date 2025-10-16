import logging
import os
import threading
import time
import uuid

from flask import Blueprint, jsonify, request
from sqlalchemy import select

from db import get_session
from logging_utils import api_endpoint_logger
from models import VideoTask, VideoTaskStatus
from services.save_draft_impl import query_script_impl

logger = logging.getLogger(__name__)
bp = Blueprint("generate", __name__)


@bp.route("/video_task_status", methods=["GET"])
@api_endpoint_logger
def get_video_task_status():
    task_id = request.args.get("task_id")

    result = {"success": False, "data": None, "error": ""}

    if not task_id:
        result["error"] = "The required parameter 'task_id' is missing. Please add it and try again."
        return jsonify(result)

    try:
        with get_session() as session:
            task = session.execute(
                select(VideoTask).where(VideoTask.task_id == task_id)
            ).scalar_one_or_none()

            if not task:
                result["error"] = f"VideoTask with task_id '{task_id}' not found."
                return jsonify(result)

            # Convert the SQLAlchemy object to a dictionary
            task_data = {
                "id": task.id,
                "task_id": task.task_id,
                "draft_id": task.draft_id,
                "video_name": task.video_name,
                "render_status": task.render_status.value if task.render_status else None,
                "progress": task.progress,
                "message": task.message,
                "draft_url": task.draft_url,
                "extra": task.extra,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            }

            result["success"] = True
            result["data"] = task_data
            return jsonify(result)

    except Exception as e:
        result["error"] = f"Error occurred while retrieving video task status: {e!s}"
        return jsonify(result)


@bp.route("/generate_video", methods=["POST"])
@api_endpoint_logger
def generate_video_api():
    data = request.get_json()

    draft_id = data.get("draft_id")
    resolution = data.get("resolution")
    framerate = data.get("framerate")
    override_name = data.get("name")

    result = {"success": False, "output": "", "error": ""}

    if not draft_id:
        result["error"] = "Hi, the required parameter 'draft_id' is missing. Please add it and try again."
        return jsonify(result)

    try:
        from celery import Celery
        script = query_script_impl(draft_id, force_update=False)
        if script is None:
            result["error"] = f"Draft {draft_id} not found in cache. Please create or save the draft first."
            return jsonify(result)

        import json
        draft_content = json.loads(script.dumps())
        if override_name:
            draft_content["name"] = override_name

        broker_url = os.getenv("CELERY_BROKER_URL") or os.getenv("REDIS_URL")
        backend_url = os.getenv("CELERY_RESULT_BACKEND") or os.getenv("REDIS_URL")

        if not broker_url or not backend_url:
            result["error"] = "CELERY_BROKER_URL and CELERY_RESULT_BACKEND environment variables are required"
            return jsonify(result)

        celery_client = Celery(broker=broker_url, backend=backend_url)
        try:
            insp = celery_client.control.inspect(timeout=1)
            ping_result = insp.ping() if insp else None
        except Exception:
            ping_result = None
        if not ping_result:
            logger.warning("No Celery workers responded to ping. Verify worker is running and connected to the same broker/result backend.")

        process_sig = celery_client.signature(
            "s3_asset_downloader.tasks.process_draft_content",
            kwargs={"draft_content": draft_content},
            queue="default"
        )

        # Pre-generate final task id so we can create a DB record before task starts
        final_task_id = uuid.uuid4().hex

        generate_sig = celery_client.signature(
            "s3_asset_downloader.tasks.generate_video",
            kwargs={"output_path": None, "resolution": resolution, "framerate": framerate},
            queue="default"
        ).set(task_id=final_task_id)

        # Create task record BEFORE generate task starts
        try:
            with get_session() as session:
                existing = session.execute(select(VideoTask).where(VideoTask.task_id == final_task_id)).scalar_one_or_none()
                video_name = draft_content.get("name") if isinstance(draft_content, dict) else None
                if not existing:
                    session.add(VideoTask(task_id=final_task_id, draft_id=draft_id, status="initialized", render_status=VideoTaskStatus.INITIALIZED, video_name=video_name))
                else:
                    if video_name:
                        existing.video_name = video_name
        except Exception as e:
            # swallow key errors or other issues caused by draft_content structure
            logger.error(f"Failed to pre-insert video task {final_task_id}: {e}")

        chain_result = (process_sig | generate_sig).apply_async()
        logger.info(f"Dispatched Celery chain. Final task id: {chain_result.id}")

        first_result = chain_result
        while getattr(first_result, "parent", None) is not None:
            first_result = first_result.parent

        unique_dir_name = None
        try:
            process_task_id = getattr(first_result, "id", None)
            if process_task_id:
                process_async = celery_client.AsyncResult(process_task_id)
                if process_async.ready() and isinstance(process_async.result, dict):
                    unique_dir_name = process_async.result.get("unique_dir_name")
        except Exception:
            unique_dir_name = None

        # Update task record with any early metadata (e.g., unique_dir_name) after dispatch
        try:
            with get_session() as session:
                existing = session.execute(select(VideoTask).where(VideoTask.task_id == final_task_id)).scalar_one_or_none()
                if existing:
                    # Merge extra
                    extra = dict(existing.extra or {})
                    if unique_dir_name:
                        extra["unique_dir_name"] = unique_dir_name
                    existing.extra = extra
        except Exception as e:
            logger.error(f"Failed to update video task {final_task_id} metadata: {e}")

        # Start a background watcher to mark status on completion
        def _watch_and_update_status(task_id: str):
            try:
                async_res = celery_client.AsyncResult(task_id)
                while not async_res.ready():
                    time.sleep(1.0)
                state = async_res.state
                with get_session() as session:
                    row = session.execute(select(VideoTask).where(VideoTask.task_id == task_id)).scalar_one_or_none()
                    if not row:
                        return
                    if state == "SUCCESS":
                        row.status = "completed"
                        row.render_status = VideoTaskStatus.COMPLETED
                    elif state == "PENDING":
                        row.status = "processing"
                        row.render_status = VideoTaskStatus.PROCESSING
                    elif state in ("FAILURE", "REVOKED"):
                        row.status = "failed"
                        row.render_status = VideoTaskStatus.FAILED
                        from contextlib import suppress
                        with suppress(Exception):
                            row.message = str(async_res.result)
            except Exception as e:
                logger.error(f"Task status watcher error for {task_id}: {e}")

        threading.Thread(target=_watch_and_update_status, args=(final_task_id,), daemon=True).start()

        result["success"] = True
        result["output"] = {"final_task_id": final_task_id, "unique_dir_name": unique_dir_name}
        return jsonify(result)

    except Exception as e:
        result["error"] = f"Error occurred while generating video: {e!s}"
        return jsonify(result)


