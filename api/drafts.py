import logging
from typing import Optional, Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from logging_utils import api_endpoint_logger
from services.create_draft import DraftFramerate, create_draft
from services.save_draft_impl import (
    query_script_impl,
    query_task_status,
    save_draft_impl,
)

router = APIRouter(tags=["drafts"])
logger = logging.getLogger(__name__)


class CreateDraftRequest(BaseModel):
    width: int = 1080
    height: int = 1920
    framerate: int = DraftFramerate.FR_30.value
    name: str = "draft"
    resource: Optional[str] = None  # 'api' or 'mcp'


@router.post("/create_draft")
@api_endpoint_logger
async def create_draft_service(request: CreateDraftRequest):
    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    try:
        _script, draft_id = create_draft(
            width=request.width,
            height=request.height,
            framerate=request.framerate,
            name=request.name,
            resource=request.resource
        )

        result["success"] = True
        result["output"] = {"draft_id": draft_id}
        return result

    except Exception as e:
        result["error"] = f"Error occurred while creating draft: {e!s}."
        return result


class QueryScriptRequest(BaseModel):
    draft_id: str
    force_update: bool = True


@router.post("/query_script")
@api_endpoint_logger
async def query_script(request: QueryScriptRequest):
    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    if not request.draft_id:
        result["error"] = "Hi, the required parameter 'draft_id' is missing. Please add it and try again."
        return result

    try:
        script = query_script_impl(draft_id=request.draft_id, force_update=request.force_update)

        if script is None:
            result["error"] = f"Draft {request.draft_id} does not exist in cache."
            return result

        script_str = script.dumps()

        result["success"] = True
        result["output"] = script_str
        return result

    except Exception as e:
        result["error"] = f"Error occurred while querying script: {e!s}. "
        return result


class SaveDraftRequest(BaseModel):
    draft_id: str
    draft_folder: Optional[str] = None
    draft_version: Optional[int] = None
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    archive_name: Optional[str] = None


@router.post("/save_draft")
@api_endpoint_logger
async def save_draft(request: SaveDraftRequest):
    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    if not request.draft_id:
        result["error"] = "Hi, the required parameter 'draft_id' is missing. Please add it and try again."
        return result

    try:
        draft_result = save_draft_impl(
            draft_id=request.draft_id,
            draft_folder=request.draft_folder,
            draft_version=request.draft_version,
            user_id=request.user_id,
            user_name=request.user_name,
            archive_name=request.archive_name
        )

        result["success"] = True
        result["output"] = draft_result
        return result

    except Exception as e:
        result["error"] = f"Error occurred while saving draft: {e!s}. "
        return result


class QueryDraftStatusRequest(BaseModel):
    task_id: str


@router.post("/query_draft_status")
@api_endpoint_logger
async def query_draft_status_api(request: QueryDraftStatusRequest):
    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    if not request.task_id:
        result["error"] = "Hi, the required parameter 'task_id' is missing. Please add it and try again."
        return result

    try:
        task_status = query_task_status(request.task_id)

        if task_status["status"] == "not_found":
            result["error"] = f"Task with ID {request.task_id} not found. Please check if the task ID is correct."
            return result

        result["success"] = True
        result["output"] = task_status
        return result

    except Exception as e:
        result["error"] = f"Error occurred while querying task status: {e!s}."
        return result


class GenerateDraftUrlRequest(BaseModel):
    draft_id: str


@router.post("/generate_draft_url")
@api_endpoint_logger
async def generate_draft_url(request: GenerateDraftUrlRequest):
    from settings.local import DRAFT_DOMAIN, PREVIEW_ROUTER

    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    if not request.draft_id:
        result["error"] = "Hi, the required parameter 'draft_id' is missing. Please add it and try again."
        return result

    try:
        draft_result = {"draft_url": f"{DRAFT_DOMAIN}{PREVIEW_ROUTER}?={request.draft_id}"}

        result["success"] = True
        result["output"] = draft_result
        return result

    except Exception as e:
        result["error"] = f"Error occurred while saving draft: {e!s}."
        return result



