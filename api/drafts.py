import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from services.create_draft import DraftFramerate, create_draft
from services.save_draft_impl import (
    query_script_impl,
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
async def create_draft_service(request: CreateDraftRequest):
    result = {"success": False, "output": "", "error": ""}

    try:
        _script, draft_id = await create_draft(
            width=request.width,
            height=request.height,
            framerate=request.framerate,
            name=request.name,
            resource=request.resource,
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
async def query_script(request: QueryScriptRequest):
    result = {"success": False, "output": "", "error": ""}

    if not request.draft_id:
        result["error"] = (
            "Hi, the required parameter 'draft_id' is missing. Please add it and try again."
        )
        return result

    try:
        script = await query_script_impl(
            draft_id=request.draft_id, force_update=request.force_update
        )

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
async def save_draft(request: SaveDraftRequest):
    result = {"success": False, "output": "", "error": ""}

    if not request.draft_id:
        result["error"] = (
            "Hi, the required parameter 'draft_id' is missing. Please add it and try again."
        )
        return result

    try:
        draft_result = save_draft_impl(
            draft_id=request.draft_id,
            draft_folder=request.draft_folder,
            draft_version=request.draft_version,
            user_id=request.user_id,
            user_name=request.user_name,
            archive_name=request.archive_name,
        )

        result["success"] = True
        result["output"] = draft_result
        return result

    except Exception as e:
        result["error"] = f"Error occurred while saving draft: {e!s}. "
        return result
