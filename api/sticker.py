import logging
from typing import Optional

import requests
from fastapi import APIRouter, Response
from pydantic import BaseModel

from services.add_sticker_impl import add_sticker_impl

logger = logging.getLogger(__name__)
router = APIRouter(tags=["sticker"])


class AddStickerRequest(BaseModel):
    sticker_id: str
    start: float = 0
    end: float = 5.0
    draft_id: Optional[str] = None
    transform_y: float = 0
    transform_x: float = 0
    alpha: float = 1.0
    flip_horizontal: bool = False
    flip_vertical: bool = False
    rotation: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    track_name: str = "sticker_main"
    relative_index: int = 0


class SearchStickerRequest(BaseModel):
    keywords: str


@router.post("/add_sticker")
def add_sticker(request: AddStickerRequest, response: Response):
    result = {"success": False, "output": "", "error": ""}

    try:
        draft_result = add_sticker_impl(
            resource_id=request.sticker_id,
            start=request.start,
            end=request.end,
            draft_id=request.draft_id,
            transform_y=request.transform_y,
            transform_x=request.transform_x,
            alpha=request.alpha,
            flip_horizontal=request.flip_horizontal,
            flip_vertical=request.flip_vertical,
            rotation=request.rotation,
            scale_x=request.scale_x,
            scale_y=request.scale_y,
            track_name=request.track_name,
            relative_index=request.relative_index,
        )

        result["success"] = True
        result["output"] = draft_result
        return result

    except Exception as e:
        result["error"] = f"Error occurred while adding sticker: {e!s}. "
        response.status_code = 400
        return result


@router.post("/search_sticker")
def search_sticker(request: SearchStickerRequest, response: Response):
    result = {
        "error": "",
        "output": {"data": [], "message": ""},
        "purchase_link": "",
        "success": False,
    }

    try:
        # Call external search API
        url = "https://lv-api-sinfonlineb.ulikecam.com/artist/v1/effect/search?aid=3704"
        payload = {
            "count": 50,
            "effect_type": 2,
            "need_recommend": False,
            "offset": 0,
            "query": request.keywords,
        }
        headers = {"Content-Type": "application/json"}

        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        body = resp.json() or {}

        ret_code = str(body.get("ret", ""))
        errmsg = body.get("errmsg", "")
        data_section = body.get("data") or {}
        items = data_section.get("effect_item_list") or []

        mapped_items = []
        for item in items:
            common = item.get("common_attr") or {}
            sticker = item.get("sticker") or {}

            large_image = sticker.get("large_image") or {}
            sticker_package = sticker.get("sticker_package") or {}

            # Determine sticker_id with fallbacks
            sticker_id = (
                str(common.get("effect_id") or "")
                or str(common.get("id") or "")
                or str(common.get("third_resource_id_str") or "")
                or (
                    str(common.get("third_resource_id"))
                    if common.get("third_resource_id") is not None
                    else ""
                )
            )

            mapped_items.append(
                {
                    "sticker": {
                        "large_image": {"image_url": large_image.get("image_url", "")},
                        "preview_cover": sticker.get("preview_cover", ""),
                        "sticker_package": {
                            "height_per_frame": int(
                                sticker_package.get("height_per_frame", 0) or 0
                            ),
                            "size": int(sticker_package.get("size", 0) or 0),
                            "width_per_frame": int(
                                sticker_package.get("width_per_frame", 0) or 0
                            ),
                        },
                        "sticker_type": int(sticker.get("sticker_type", 0) or 0),
                        "track_thumbnail": sticker.get("track_thumbnail", ""),
                    },
                    "sticker_id": sticker_id,
                    "title": common.get("title", ""),
                }
            )

        result["output"]["data"] = mapped_items
        result["output"]["message"] = errmsg or "success"
        result["success"] = ret_code == "0"
        if not result["success"] and not result["error"]:
            result["error"] = errmsg or "Search failed"
        return result
    except Exception as e:
        result["error"] = f"Error occurred while searching sticker: {e!s}. "
        response.status_code = 400
        return result
