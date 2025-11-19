import logging
from typing import List, Optional, Any, Tuple

from fastapi import APIRouter, Response
from pydantic import BaseModel

from logging_utils import api_endpoint_logger
from services.add_audio_track import add_audio_track, batch_add_audio_track

logger = logging.getLogger(__name__)
router = APIRouter(tags=["audio"])

class AddAudioRequest(BaseModel):
    audio_url: str
    audio_name: Optional[str] = None
    start: float = 0
    end: Optional[float] = None
    draft_id: Optional[str] = None
    volume: float = 1.0
    target_start: float = 0
    speed: float = 1.0
    track_name: str = "audio_main"
    duration: Optional[float] = None
    effect_type: Optional[str] = None
    effect_params: Optional[List[float]] = None

class AudioItem(BaseModel):
    audio_url: str
    start: float = 0
    end: Optional[float] = None
    target_start: float = 0
    speed: float = 1.0
    duration: Optional[float] = None
    audio_name: Optional[str] = None

class BatchAddAudiosRequest(BaseModel):
    draft_folder: Optional[str] = None
    draft_id: Optional[str] = None
    audios: List[AudioItem]
    
    # Common parameters
    volume: float = 1.0
    track_name: str = "audio_main"
    speed: float = 1.0
    effect_type: Optional[str] = None
    effect_params: Optional[List[float]] = None

@router.post("/add_audio")
@api_endpoint_logger
def add_audio(request: AddAudioRequest, response: Response):
    sound_effects = None
    if request.effect_type is not None:
        sound_effects = [(request.effect_type, request.effect_params)]

    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    try:
        draft_result = add_audio_track(
            audio_url=request.audio_url,
            start=request.start,
            end=request.end,
            target_start=request.target_start,
            draft_id=request.draft_id,
            volume=request.volume,
            track_name=request.track_name,
            speed=request.speed,
            sound_effects=sound_effects,
            audio_name=request.audio_name,
            duration=request.duration
        )

        result["success"] = True
        result["output"] = draft_result
        return result

    except Exception as e:
        result["error"] = f"Error occurred while processing audio: {e!s}."
        response.status_code = 400
        return result


@router.post("/batch_add_audios")
@api_endpoint_logger
def batch_add_audios(request: BatchAddAudiosRequest, response: Response):
    sound_effects = None
    if request.effect_type is not None:
        sound_effects = [(request.effect_type, request.effect_params)]

    result = {
        "success": False,
        "output": [],
        "error": ""
    }

    if not request.audios:
        result["error"] = "Hi, the required parameter 'audios' is missing or empty."
        response.status_code = 400
        return result

    try:
        # Convert Pydantic models to dicts for the service function
        audios_data = [a.dict() for a in request.audios]
        
        batch_result = batch_add_audio_track(
            audios=audios_data,
            draft_folder=request.draft_folder,
            draft_id=request.draft_id,
            volume=request.volume,
            track_name=request.track_name,
            speed=request.speed,
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
            response.status_code = 400
            return result
        return result

    except Exception as e:
        logger.error(f"Error occurred while processing batch audios: {e!s}", exc_info=True)
        result["error"] = f"Error occurred while processing batch audios: {e!s}."
        response.status_code = 400
        return result


