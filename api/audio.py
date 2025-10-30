import logging

from flask import Blueprint, jsonify, request

from logging_utils import api_endpoint_logger
from services.add_audio_track import add_audio_track

logger = logging.getLogger(__name__)
bp = Blueprint("audio", __name__)


@bp.route("/add_audio", methods=["POST"])
@api_endpoint_logger
def add_audio():
    data = request.get_json()

    audio_url = data.get("audio_url")
    start = data.get("start", 0)
    end = data.get("end", None)
    draft_id = data.get("draft_id")
    volume = data.get("volume", 1.0)
    target_start = data.get("target_start", 0)
    speed = data.get("speed", 1.0)
    track_name = data.get("track_name", "audio_main")
    duration = data.get("duration", None)
    effect_type = data.get("effect_type", None)
    effect_params = data.get("effect_params", None)

    sound_effects = None
    if effect_type is not None:
        sound_effects = [(effect_type, effect_params)]

    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    if not audio_url:
        result["error"] = "Hi, the required parameters 'audio_url' are missing."
        return jsonify(result)

    try:
        draft_result = add_audio_track(
            audio_url=audio_url,
            start=start,
            end=end,
            target_start=target_start,
            draft_id=draft_id,
            volume=volume,
            track_name=track_name,
            speed=speed,
            sound_effects=sound_effects,
            duration=duration
        )

        result["success"] = True
        result["output"] = draft_result
        return jsonify(result)

    except Exception as e:
        result["error"] = f"Error occurred while processing audio: {e!s}."
        return jsonify(result)


@bp.route("/batch_add_audios", methods=["POST"])
@api_endpoint_logger
def batch_add_audios():
    data = request.get_json()

    draft_id = data.get("draft_id")
    audios = data.get("audios", [])

    # Common parameters that apply to all audios
    volume = data.get("volume", 1.0)
    track_name = data.get("track_name", "audio_main")
    effect_type = data.get("effect_type", None)
    effect_params = data.get("effect_params", None)

    sound_effects = None
    if effect_type is not None:
        sound_effects = [(effect_type, effect_params)]

    result = {
        "success": False,
        "output": [],
        "error": ""
    }

    if not audios:
        result["error"] = "Hi, the required parameter 'audios' is missing or empty."
        return jsonify(result)

    try:
        outputs = []
        for idx, audio in enumerate(audios):
            audio_url = audio.get("audio_url")
            start = audio.get("start", 0)
            end = audio.get("end", None)
            target_start = audio.get("target_start", 0)
            speed = audio.get("speed", 1.0)
            duration = audio.get("duration", None)

            if not audio_url:
                logger.warning(f"Audio at index {idx} is missing 'audio_url', skipping.")
                continue

            draft_result = add_audio_track(
                audio_url=audio_url,
                start=start,
                end=end,
                target_start=target_start,
                draft_id=draft_id,
                volume=volume,
                track_name=track_name,
                speed=speed,
                sound_effects=sound_effects,
                duration=duration
            )

            outputs.append({
                "audio_url": audio_url,
                "result": draft_result
            })

            # Update draft_id for subsequent audios
            draft_id = draft_result

        result["success"] = True
        result["output"] = outputs
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error occurred while processing batch audios: {e!s}", exc_info=True)
        result["error"] = f"Error occurred while processing batch audios: {e!s}."
        return jsonify(result)


