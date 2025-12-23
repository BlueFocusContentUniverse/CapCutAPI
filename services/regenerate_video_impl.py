import json
import logging
from typing import Any, Dict

from models import VideoTaskStatus
from repositories.video_task_repository import VideoTaskRepository
from services.save_draft_impl import query_script_impl
from util.celery_client import get_celery_client

logger = logging.getLogger(__name__)


async def regenerate_video_impl(task_id: str) -> Dict[str, Any]:
    """重新生成视频, 使用现有的task_id.

    Args:
        task_id: 要重新生成的任务ID（video_tasks表的task_id）

    Returns:
        包含成功状态和错误信息的字典
    """
    result: Dict[str, Any] = {"success": False, "output": "", "error": ""}

    if not task_id:
        result["error"] = "The required parameter 'task_id' is missing. Please add it and try again."
        return result

    try:
        # 1. 从video_tasks表获取任务详情
        repository = VideoTaskRepository()
        task = await repository.get_task(task_id)

        if not task:
            result["error"] = f"VideoTask with task_id '{task_id}' not found."
            logger.warning(f"VideoTask not found: {task_id}")
            return result

        # 2. 检查render_status状态，只有非COMPLETED状态才可以重新渲染
        render_status = task.get("render_status")
        if render_status == VideoTaskStatus.COMPLETED.value:
            result["error"] = "This task is already completed and cannot be regenerated."
            logger.info(f"Task {task_id} is already completed (render_status={render_status}), cannot regenerate")
            return result

        # 3. 获取任务参数（从数据库获取，generate时已落库）
        draft_id = task.get("draft_id")
        framerate = task.get("framerate")
        resolution = task.get("resolution")

        if not draft_id:
            result["error"] = "Could not get draft_id from the task."
            logger.error(f"Task {task_id} has no draft_id")
            return result

        # 4. 获取草稿内容（celery任务需要）
        logger.info(f"Fetching draft content for task_id: {task_id}, draft_id: {draft_id}")
        script = await query_script_impl(draft_id, force_update=False)
        if script is None:
            result["error"] = f"Draft {draft_id} not found. Cannot regenerate video without source content."
            logger.error(f"Draft {draft_id} not found for task {task_id}")
            return result

        draft_content = json.loads(script.dumps())
        logger.info(f"Successfully retrieved draft content for task {task_id}")

        # 5. 获取Celery客户端
        try:
            from util.celery_client import CELERY_APP_NAME_REGENERATE

            celery_client = get_celery_client(app_name=CELERY_APP_NAME_REGENERATE)
        except Exception as exc:
            result["error"] = f"Failed to get Celery client: {exc!s}"
            logger.error(f"Failed to get Celery client: {exc}")
            return result

        # 6. 更新任务状态为初始化
        await repository.update_task_status(
            task_id=task_id,
            status="initialized",
            render_status=VideoTaskStatus.INITIALIZED,
            progress=0.0,
            message="Task has been resubmitted for rendering"
        )

        # 7. 使用video_tasks表的task_id提交Celery任务
        task_sig = celery_client.signature(
            "jianying_runner.tasks.process_content_and_generate_video",
            kwargs={
                "draft_content": draft_content,
                "basePath": None,
                "resolution": resolution,
                "framerate": framerate,
            },
            queue="default",
        ).set(task_id=task_id)  # 使用video_tasks表的task_id

        task_result = task_sig.apply_async()
        logger.info(f"Resubmitted Celery task with task_id: {task_id}, celery_task_id: {task_result.id}")

        result["success"] = True
        result["output"] = {"task_id": task_id, "message": "Video regeneration task has been submitted"}
        return result

    except Exception as e:
        logger.error(f"Error occurred while regenerating video: {e}", exc_info=True)
        result["error"] = f"Error occurred while regenerating video: {e!s}"
        return result
