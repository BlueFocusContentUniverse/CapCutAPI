import logging
import os
import uuid
from typing import Any, Dict, Literal, Optional

from sqlalchemy import select

from db import get_session
from models import VideoTask, VideoTaskStatus
from services.save_draft_impl import query_script_impl

logger = logging.getLogger(__name__)

ResolutionType = Literal["720P", "1080P", "2K", "4K"]
FramerateType = Literal["30fps", "50fps", "60fps"]

def generate_video_impl(
    draft_id: str,
    resolution: Optional[ResolutionType] = "1080P",
    framerate: Optional[FramerateType] = "30fps",
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """Kick off Celery pipeline to generate a video for a given draft.

    Args:
        draft_id: The draft identifier to render.
        resolution: Target resolution label ("720P", "1080P", "2K", "4K").
        framerate: Target framerate ("30fps", "50fps", "60fps").
        name: Optional override for the draft/video name embedded in content.

    Returns:
        A dict with keys:
        - success: Whether the dispatch was successful.
        - output: {"task_id": str} when successful.
        - error: Error message string when unsuccessful.
    """
    result: Dict[str, Any] = {"success": False, "output": "", "error": ""}

    if not draft_id:
        result["error"] = "Hi, the required parameter 'draft_id' is missing. Please add it and try again."
        return result

    # Validate resolution
    valid_resolutions = ["720P", "1080P", "2K", "4K"]
    if resolution and resolution not in valid_resolutions:
        result["error"] = f"Invalid resolution '{resolution}'. Must be one of: {', '.join(valid_resolutions)}"
        return result

    # Validate framerate
    valid_framerates = ["30fps", "50fps", "60fps"]
    if framerate and framerate not in valid_framerates:
        result["error"] = f"Invalid framerate '{framerate}'. Must be one of: {', '.join(valid_framerates)}"
        return result

    try:
        import json

        from celery import Celery

        script = query_script_impl(draft_id, force_update=False)
        if script is None:
            result["error"] = f"Draft {draft_id} not found in cache. Please create or save the draft first."
            return result

        draft_content = json.loads(script.dumps())
        materials = draft_content.get("materials") if isinstance(draft_content, dict) else None
        material_count = 0
        if isinstance(materials, dict):
            for material_group in materials.values():
                if isinstance(material_group, list):
                    material_count += len(material_group)
                elif isinstance(material_group, dict):
                    material_count += sum(
                        len(sub_group) for sub_group in material_group.values() if isinstance(sub_group, list)
                    )

        if material_count == 0:
            logger.warning(f"Draft {draft_id} contains no materials. Aborting video generation dispatch.")
            result["error"] = (
                "Draft has no materials. Please add at least one media asset before generating a video."
            )
            return result

        if name:
            draft_content["name"] = name

        broker_url = os.getenv("CELERY_BROKER_URL")

        if not broker_url:
            result["error"] = "CELERY_BROKER_URL environment variable is required"
            return result

        celery_client = Celery(broker=broker_url)

        # Pre-generate task id so we can create a DB record before task starts
        final_task_id = uuid.uuid4().hex

        # Create task record BEFORE task starts
        try:
            with get_session() as session:
                existing = session.execute(
                    select(VideoTask).where(VideoTask.task_id == final_task_id)
                ).scalar_one_or_none()
                video_name = draft_content.get("name") if isinstance(draft_content, dict) else None
                if not existing:
                    session.add(
                        VideoTask(
                            task_id=final_task_id,
                            draft_id=draft_id,
                            status="initialized",
                            render_status=VideoTaskStatus.INITIALIZED,
                            video_name=video_name,
                        )
                    )
                else:
                    if video_name:
                        existing.video_name = video_name
                logger.info(f"Created VideoTask {final_task_id} for draft {draft_id}")
        except Exception as e:
            # swallow key errors or other issues caused by draft_content structure
            logger.error(f"Failed to pre-insert video task {final_task_id}: {e}")

        # Use the new combined task
        task_sig = celery_client.signature(
            "jianying_runner.tasks.process_content_and_generate_video",
            kwargs={
                "draft_content": draft_content,
                "basePath": None,
                "resolution": resolution,
                "framerate": framerate,
            },
            queue="default",
        ).set(task_id=final_task_id)

        task_result = task_sig.apply_async()
        logger.info(f"Dispatched Celery task. Task id: {task_result.id}")

        result["success"] = True
        result["output"] = {"task_id": final_task_id}
        return result

    except Exception as e:
        logger.error(f"Error occurred while generating video: {e}")
        result["error"] = f"Error occurred while generating video: {e!s}"
        return result


