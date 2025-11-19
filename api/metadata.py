import logging

from fastapi import APIRouter

from logging_utils import api_endpoint_logger
from pyJianYingDraft.metadata import (
    CapCutGroupAnimationType,
    CapCutIntroType,
    CapCutOutroType,
    GroupAnimationType,
    IntroType,
    OutroType,
    TextIntro,
    TextLoopAnim,
    TextOutro,
)
from pyJianYingDraft.metadata.capcut_effect_meta import (
    CapCutVideoCharacterEffectType,
    CapCutVideoSceneEffectType,
)
from pyJianYingDraft.metadata.capcut_mask_meta import CapCutMaskType
from pyJianYingDraft.metadata.capcut_text_animation_meta import (
    CapCutTextIntro,
    CapCutTextLoopAnim,
    CapCutTextOutro,
)
from pyJianYingDraft.metadata.capcut_transition_meta import CapCutTransitionType
from pyJianYingDraft.metadata.filter_meta import FilterType
from pyJianYingDraft.metadata.mask_meta import MaskType
from pyJianYingDraft.metadata.transition_meta import TransitionType
from pyJianYingDraft.metadata.video_effect_meta import (
    VideoCharacterEffectType,
    VideoSceneEffectType,
)
from services.get_audio_effect_types_impl import get_audio_effect_types_impl
from services.get_font_types_impl import get_font_types_impl
from settings.local import IS_CAPCUT_ENV

logger = logging.getLogger(__name__)

router = APIRouter(tags=["metadata"])


@router.get("/get_intro_animation_types")
@api_endpoint_logger
async def get_intro_animation_types():
    result = {"success": True, "output": "", "error": ""}
    try:
        animation_types = []
        if IS_CAPCUT_ENV:
            for name, member in CapCutIntroType.__members__.items():
                animation_types.append({"name": name})
        else:
            for name, member in IntroType.__members__.items():
                animation_types.append({"name": name})
        result["output"] = animation_types
        return result
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting entrance animation types: {e!s}"
        return result


@router.get("/get_outro_animation_types")
@api_endpoint_logger
async def get_outro_animation_types():
    result = {"success": True, "output": "", "error": ""}
    try:
        animation_types = []
        if IS_CAPCUT_ENV:
            for name, member in CapCutOutroType.__members__.items():
                animation_types.append({"name": name})
        else:
            for name, member in OutroType.__members__.items():
                animation_types.append({"name": name})
        result["output"] = animation_types
        return result
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting exit animation types: {e!s}"
        return result


@router.get("/get_combo_animation_types")
@api_endpoint_logger
async def get_combo_animation_types():
    result = {"success": True, "output": "", "error": ""}
    try:
        animation_types = []
        if IS_CAPCUT_ENV:
            for name, member in CapCutGroupAnimationType.__members__.items():
                animation_types.append({"name": name})
        else:
            for name, member in GroupAnimationType.__members__.items():
                animation_types.append({"name": name})
        result["output"] = animation_types
        return result
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting combo animation types: {e!s}"
        return result


@router.get("/get_transition_types")
@api_endpoint_logger
async def get_transition_types():
    result = {"success": True, "output": "", "error": ""}
    try:
        transition_types = []
        if IS_CAPCUT_ENV:
            for name, member in CapCutTransitionType.__members__.items():
                transition_types.append({"name": name})
        else:
            for name, member in TransitionType.__members__.items():
                transition_types.append({"name": name})
        result["output"] = transition_types
        return result
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting transition animation types: {e!s}"
        return result


@router.get("/get_mask_types")
@api_endpoint_logger
async def get_mask_types():
    result = {"success": True, "output": "", "error": ""}
    try:
        mask_types = []
        if IS_CAPCUT_ENV:
            for name, member in CapCutMaskType.__members__.items():
                mask_types.append({"name": name})
        else:
            for name, member in MaskType.__members__.items():
                mask_types.append({"name": name})
        result["output"] = mask_types
        return result
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting mask types: {e!s}"
        return result


@router.get("/get_filter_types")
@api_endpoint_logger
async def get_filter_types():
    result = {"success": True, "output": "", "error": ""}
    try:
        filter_types = []
        for name, member in FilterType.__members__.items():
            filter_types.append({"name": name})
        result["output"] = filter_types
        return result
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting filter types: {e!s}"
        return result


@router.get("/get_audio_effect_types")
@api_endpoint_logger
async def get_audio_effect_types():
    return get_audio_effect_types_impl()


@api_endpoint_logger
@router.get("/get_font_types")
async def get_font_types():
    return get_font_types_impl()


@api_endpoint_logger
@router.get("/get_text_intro_types")
async def get_text_intro_types():
    result = {"success": True, "output": "", "error": ""}
    try:
        text_intro_types = []
        if IS_CAPCUT_ENV:
            for name, member in CapCutTextIntro.__members__.items():
                text_intro_types.append({"name": name})
        else:
            for name, member in TextIntro.__members__.items():
                text_intro_types.append({"name": name})
        result["output"] = text_intro_types
        return result
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting text entrance animation types: {e!s}"
        return result


@api_endpoint_logger
@router.get("/get_text_outro_types")
async def get_text_outro_types():
    result = {"success": True, "output": "", "error": ""}
    try:
        text_outro_types = []
        if IS_CAPCUT_ENV:
            for name, member in CapCutTextOutro.__members__.items():
                text_outro_types.append({"name": name})
        else:
            for name, member in TextOutro.__members__.items():
                text_outro_types.append({"name": name})
        result["output"] = text_outro_types
        return result
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting text exit animation types: {e!s}"
        return result


@api_endpoint_logger
@router.get("/get_text_loop_anim_types")
async def get_text_loop_anim_types():
    result = {"success": True, "output": "", "error": ""}
    try:
        text_loop_anim_types = []
        if IS_CAPCUT_ENV:
            for name, member in CapCutTextLoopAnim.__members__.items():
                text_loop_anim_types.append({"name": name})
        else:
            for name, member in TextLoopAnim.__members__.items():
                text_loop_anim_types.append({"name": name})
        result["output"] = text_loop_anim_types
        return result
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting text loop animation types: {e!s}"
        return result


@router.get("/get_video_scene_effect_types")
@api_endpoint_logger
async def get_video_scene_effect_types():
    result = {"success": True, "output": "", "error": ""}
    try:
        effect_types = []
        if IS_CAPCUT_ENV:
            for name, member in CapCutVideoSceneEffectType.__members__.items():
                effect_types.append({"name": name})
        else:
            for name, member in VideoSceneEffectType.__members__.items():
                effect_types.append({"name": name})
        result["output"] = effect_types
        return result
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting scene effect types: {e!s}"
        return result


@router.get("/get_video_character_effect_types")
@api_endpoint_logger
async def get_video_character_effect_types():
    result = {"success": True, "output": "", "error": ""}
    try:
        effect_types = []
        if IS_CAPCUT_ENV:
            for name, member in CapCutVideoCharacterEffectType.__members__.items():
                effect_types.append({"name": name})
        else:
            for name, member in VideoCharacterEffectType.__members__.items():
                effect_types.append({"name": name})
        result["output"] = effect_types
        return result
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting character effect types: {e!s}"
        return result


