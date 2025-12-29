import logging
from typing import List, Optional

from fastapi import APIRouter, Response
from pydantic import BaseModel

from services.add_effect_impl import add_effect_impl

logger = logging.getLogger(__name__)
router = APIRouter(tags=["effects"])


class AddEffectRequest(BaseModel):
    effect_type: str
    start: float = 0
    effect_category: str = "scene"
    end: float = 3.0
    draft_id: Optional[str] = None
    track_name: str = "effect_01"
    params: Optional[List[float]] = None


@router.post("/add_effect")
async def add_effect(request: AddEffectRequest, response: Response):
    result = {"success": False, "output": "", "error": ""}

    try:
        draft_result = await add_effect_impl(
            effect_type=request.effect_type,
            effect_category=request.effect_category,
            start=request.start,
            end=request.end,
            draft_id=request.draft_id,
            track_name=request.track_name,
            params=request.params,
        )

        result["success"] = True
        result["output"] = draft_result
        return result

    except Exception as e:
        error_msg = f"Error occurred while adding effect: {e!s}. "
        logger.error(f"添加特效失败: {error_msg}", exc_info=True)
        result["error"] = error_msg
        response.status_code = 400
        return result
