from flask import Blueprint, jsonify

from logging_utils import api_endpoint_logger
from pyJianYingDraft.metadata import (
    AudioSceneEffectType,
    CapCutGroupAnimationType,
    CapCutIntroType,
    CapCutOutroType,
    GroupAnimationType,
    IntroType,
    OutroType,
    SpeechToSongType,
    TextIntro,
    TextLoopAnim,
    TextOutro,
    ToneEffectType,
)
from pyJianYingDraft.metadata.capcut_audio_effect_meta import (
    CapCutSpeechToSongEffectType,
    CapCutVoiceCharactersEffectType,
    CapCutVoiceFiltersEffectType,
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
from pyJianYingDraft.metadata.font_meta import FontType
from pyJianYingDraft.metadata.mask_meta import MaskType
from pyJianYingDraft.metadata.transition_meta import TransitionType
from pyJianYingDraft.metadata.video_effect_meta import (
    VideoCharacterEffectType,
    VideoSceneEffectType,
)
from settings.local import IS_CAPCUT_ENV

bp = Blueprint("metadata", __name__)


@bp.route("/get_intro_animation_types", methods=["GET"])
@api_endpoint_logger
def get_intro_animation_types():
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
        return jsonify(result)
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting entrance animation types: {e!s}"
        return jsonify(result)


@bp.route("/get_outro_animation_types", methods=["GET"])
@api_endpoint_logger
def get_outro_animation_types():
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
        return jsonify(result)
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting exit animation types: {e!s}"
        return jsonify(result)


@bp.route("/get_combo_animation_types", methods=["GET"])
@api_endpoint_logger
def get_combo_animation_types():
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
        return jsonify(result)
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting combo animation types: {e!s}"
        return jsonify(result)


@bp.route("/get_transition_types", methods=["GET"])
@api_endpoint_logger
def get_transition_types():
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
        return jsonify(result)
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting transition animation types: {e!s}"
        return jsonify(result)


@bp.route("/get_mask_types", methods=["GET"])
@api_endpoint_logger
def get_mask_types():
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
        return jsonify(result)
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting mask types: {e!s}"
        return jsonify(result)


@bp.route("/get_filter_types", methods=["GET"])
@api_endpoint_logger
def get_filter_types():
    result = {"success": True, "output": "", "error": ""}
    try:
        filter_types = []
        for name, member in FilterType.__members__.items():
            filter_types.append({"name": name})
        result["output"] = filter_types
        return jsonify(result)
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting filter types: {e!s}"
        return jsonify(result)


def get_audio_effect_types_logic():
    """Core logic for getting audio effect types (without Flask dependency)."""
    result = {"success": True, "output": "", "error": ""}
    try:
        audio_effect_types = []
        if IS_CAPCUT_ENV:
            for name, member in CapCutVoiceFiltersEffectType.__members__.items():
                params_info = []
                for param in member.value.params:
                    params_info.append({
                        "name": param.name,
                        "default_value": param.default_value * 100,
                        "min_value": param.min_value * 100,
                        "max_value": param.max_value * 100,
                    })
                audio_effect_types.append({"name": name, "type": "Voice_filters", "params": params_info})

            for name, member in CapCutVoiceCharactersEffectType.__members__.items():
                params_info = []
                for param in member.value.params:
                    params_info.append({
                        "name": param.name,
                        "default_value": param.default_value * 100,
                        "min_value": param.min_value * 100,
                        "max_value": param.max_value * 100,
                    })
                audio_effect_types.append({"name": name, "type": "Voice_characters", "params": params_info})

            for name, member in CapCutSpeechToSongEffectType.__members__.items():
                params_info = []
                for param in member.value.params:
                    params_info.append({
                        "name": param.name,
                        "default_value": param.default_value * 100,
                        "min_value": param.min_value * 100,
                        "max_value": param.max_value * 100,
                    })
                audio_effect_types.append({"name": name, "type": "Speech_to_song", "params": params_info})
        else:
            for name, member in ToneEffectType.__members__.items():
                params_info = []
                for param in member.value.params:
                    params_info.append({
                        "name": param.name,
                        "default_value": param.default_value * 100,
                        "min_value": param.min_value * 100,
                        "max_value": param.max_value * 100,
                    })
                audio_effect_types.append({"name": name, "type": "Tone", "params": params_info})

            for name, member in AudioSceneEffectType.__members__.items():
                params_info = []
                for param in member.value.params:
                    params_info.append({
                        "name": param.name,
                        "default_value": param.default_value * 100,
                        "min_value": param.min_value * 100,
                        "max_value": param.max_value * 100,
                    })
                audio_effect_types.append({"name": name, "type": "Audio_scene", "params": params_info})

            for name, member in SpeechToSongType.__members__.items():
                params_info = []
                for param in member.value.params:
                    params_info.append({
                        "name": param.name,
                        "default_value": param.default_value * 100,
                        "min_value": param.min_value * 100,
                        "max_value": param.max_value * 100,
                    })
                audio_effect_types.append({"name": name, "type": "Speech_to_song", "params": params_info})
        result["output"] = audio_effect_types
        return result
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting audio effect types: {e!s}"
        return result


@bp.route("/get_audio_effect_types", methods=["GET"])
@api_endpoint_logger
def get_audio_effect_types():
    return jsonify(get_audio_effect_types_logic())


def get_font_types_logic():
    """Core logic for getting font types (without Flask dependency)."""
    result = {"success": True, "output": "", "error": ""}
    try:
        font_types = []
        for name, member in FontType.__members__.items():
            font_types.append({"name": name})
        result["output"] = font_types
        return result
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting font types: {e!s}"
        return result


@api_endpoint_logger
@bp.route("/get_font_types", methods=["GET"])
def get_font_types():
    return jsonify(get_font_types_logic())


@api_endpoint_logger
@bp.route("/get_text_intro_types", methods=["GET"])
def get_text_intro_types():
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
        return jsonify(result)
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting text entrance animation types: {e!s}"
        return jsonify(result)


@api_endpoint_logger
@bp.route("/get_text_outro_types", methods=["GET"])
def get_text_outro_types():
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
        return jsonify(result)
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting text exit animation types: {e!s}"
        return jsonify(result)


@api_endpoint_logger
@bp.route("/get_text_loop_anim_types", methods=["GET"])
def get_text_loop_anim_types():
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
        return jsonify(result)
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting text loop animation types: {e!s}"
        return jsonify(result)


@bp.route("/get_video_scene_effect_types", methods=["GET"])
@api_endpoint_logger
def get_video_scene_effect_types():
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
        return jsonify(result)
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting scene effect types: {e!s}"
        return jsonify(result)


@bp.route("/get_video_character_effect_types", methods=["GET"])
@api_endpoint_logger
def get_video_character_effect_types():
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
        return jsonify(result)
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting character effect types: {e!s}"
        return jsonify(result)


