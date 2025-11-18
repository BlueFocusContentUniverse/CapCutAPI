import logging

from flask import Blueprint, jsonify, request

from logging_utils import api_endpoint_logger
from services.add_audio_track import add_audio_track, batch_add_audio_track

logger = logging.getLogger(__name__)
bp = Blueprint("audio", __name__)


@bp.route("/add_audio", methods=["POST"])
@api_endpoint_logger
def add_audio():
    data = request.get_json()

    audio_url = data.get("audio_url")
    audio_name = data.get("audio_name")
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
        return jsonify(result), 400

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
            audio_name=audio_name,
            duration=duration
        )

        result["success"] = True
        result["output"] = draft_result
        return jsonify(result)

    except Exception as e:
        result["error"] = f"Error occurred while processing audio: {e!s}."
        return jsonify(result), 400


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
        return jsonify(result), 400

    try:
        batch_result = batch_add_audio_track(
            audios=audios,
            draft_folder=data.get("draft_folder"),
            draft_id=draft_id,
            volume=volume,
            track_name=track_name,
            speed=data.get("speed", 1.0),
            sound_effects=sound_effects,
        )

        result["success"] = True
        result["output"] = batch_result["outputs"]
        if batch_result["skipped"]:
            skipped_descriptions = [
                entry.get("audio_url") or f"index {entry.get('index')}"
                for entry in batch_result["skipped"]
            ]
            result["error"] = f"Skipped audios: {skipped_descriptions}"
            result["success"] = False
            return jsonify(result), 400
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error occurred while processing batch audios: {e!s}", exc_info=True)
        result["error"] = f"Error occurred while processing batch audios: {e!s}."
        return jsonify(result), 400


