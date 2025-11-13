"""Service implementation for getting audio effect types."""

import logging
from typing import Any, Dict

from pyJianYingDraft.metadata import (
    AudioSceneEffectType,
    SpeechToSongType,
    ToneEffectType,
)
from pyJianYingDraft.metadata.capcut_audio_effect_meta import (
    CapCutSpeechToSongEffectType,
    CapCutVoiceCharactersEffectType,
    CapCutVoiceFiltersEffectType,
)
from settings import IS_CAPCUT_ENV

logger = logging.getLogger(__name__)


def get_audio_effect_types_impl() -> Dict[str, Any]:
    """Core logic for getting audio effect types (without Flask dependency).

    Returns:
        Dictionary with success status and audio effect types or error message
    """
    result = {"success": True, "output": "", "error": ""}
    try:
        audio_effect_types = []
        if IS_CAPCUT_ENV:
            logger.info("Fetching CapCut audio effect types")
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
            logger.info("Fetching standard audio effect types")
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
        logger.info(f"Successfully fetched {len(audio_effect_types)} audio effect types")
        return result
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting audio effect types: {e!s}"
        logger.error(f"Failed to get audio effect types: {e!s}", exc_info=True)
        return result


