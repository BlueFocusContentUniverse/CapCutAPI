# 导入必要的模块
import asyncio
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import pyJianYingDraft as draft
from draft_cache import update_draft_with_retry
from pyJianYingDraft import (
    AudioSceneEffectType,
    CapCutSpeechToSongEffectType,
    CapCutVoiceCharactersEffectType,
    CapCutVoiceFiltersEffectType,
    SpeechToSongType,
    ToneEffectType,
    exceptions,
    trange,
)
from settings.local import IS_CAPCUT_ENV
from util.helpers import (
    get_extension_from_format,
    get_ffprobe_info,
    is_windows_path,
    url_to_hash,
)

from .create_draft import get_draft

logger = logging.getLogger(__name__)


@dataclass
class AudioSegmentPayload:
    audio_url: str
    segment: draft.AudioSegment
    track_name: Optional[str]
    sound_effects: Optional[List[Tuple[str, Optional[List[Optional[float]]]]]]


def _prepare_audio_segment_payload(
    *,
    draft_id: str,
    audio_url: str,
    draft_folder: Optional[str],
    start: float,
    end: Optional[float],
    target_start: float,
    volume: float,
    track_name: Optional[str],
    speed: float,
    sound_effects: Optional[List[Tuple[str, Optional[List[Optional[float]]]]]],
    audio_name: Optional[str],
    duration: Optional[float],
) -> AudioSegmentPayload:
    """
    Add an audio track to the specified draft
    :param draft_folder: Draft folder path, optional parameter
    :param audio_url: Audio URL
    :param start: Start time (seconds), default 0
    :param end: End time (seconds), default None (use total audio duration)
    :param target_start: Target track insertion position (seconds), default 0
    :param draft_id: Draft ID, if None or corresponding zip file not found, a new draft will be created
    :param volume: Volume level, range 0.0-1.0, default 1.0
    :param track_name: Track name, default "audio_main"
    :param speed: Playback speed, default 1.0
    :param sound_effects: Scene sound effect list, each element is a tuple containing effect type name and parameter list, default None
    :param duration: Audio duration (seconds), if provided, skip duration detection
    :return: Updated draft information
    """
    # If duration parameter is provided, prioritize it; otherwise use default audio duration of 0 seconds, real duration will be obtained during download
    if duration is not None:
        # Use the provided duration, skip duration retrieval and checking
        audio_duration = duration
        logger.debug(f"Using provided audio duration: {audio_duration}s")
    else:
        # Use default audio duration of 0 seconds, real duration will be obtained when downloading the draft
        audio_duration = 0.0  # Default audio duration is 0 seconds
        logger.warning("No duration provided, audio duration will be detected during download")

    if audio_name:
        material_name = audio_name
        logger.debug(f"Using custom audio_name '{audio_name}' for URL {audio_url}")
    else:
        # Generate material name
        material_name = f"audio_{url_to_hash(audio_url)}.mp3"

    # Build draft_audio_path
    draft_audio_path = None
    if draft_folder:
        if is_windows_path(draft_folder):
            # Windows path processing
            windows_drive, windows_path = re.match(r"([a-zA-Z]:)(.*)", draft_folder).groups()
            parts = [p for p in windows_path.split("\\") if p]
            draft_audio_path = os.path.join(windows_drive, *parts, draft_id, "assets", "audio", material_name)
            # Normalize path (ensure consistent separators)
            draft_audio_path = draft_audio_path.replace("/", "\\")
        else:
            # macOS/Linux path processing
            draft_audio_path = os.path.join(draft_folder, draft_id, "assets", "audio", material_name)

        logger.debug(f"Audio replace path: {draft_audio_path}")

    # Set default value for audio end time
    # If end is None or <= 0, use full audio duration
    if end is None or end <= 0:
        audio_end = audio_duration
    else:
        audio_end = end

    # Calculate audio segment duration
    segment_duration = audio_end - start
    logger.debug(f"Audio segment: start={start}s, end={audio_end}s, duration={segment_duration}s")

    # Create audio material
    if draft_audio_path:
        audioMaterial = draft.AudioMaterial(
            replace_path=draft_audio_path,
            remote_url=audio_url,
            material_name=material_name,
            duration=int(audio_duration * 1e6)
        )
    else:
        audioMaterial = draft.AudioMaterial(
            remote_url=audio_url,
            material_name=material_name,
            duration=int(audio_duration * 1e6)
        )

    # Create audio segment
    audio_segment = draft.AudioSegment(
        audioMaterial,
        target_timerange=trange(f"{target_start}s", f"{segment_duration}s"),
        source_timerange=trange(f"{start}s", f"{segment_duration}s"),
        speed=speed,
        volume=volume
    )

    return AudioSegmentPayload(
        audio_url=audio_url,
        segment=audio_segment,
        track_name=track_name,
        sound_effects=sound_effects,
    )


def _apply_audio_segment_to_script(
    script,
    payload: AudioSegmentPayload,
    draft_id: str,
) -> None:
    logger.debug(f"Applying audio track modifications to draft {draft_id}")

    track_name = payload.track_name

    if track_name is not None:
        try:
            script.get_imported_track(draft.TrackType.audio, name=track_name)
            logger.debug(f"Audio track '{track_name}' already exists")
        except exceptions.TrackNotFound:
            script.add_track(draft.TrackType.audio, track_name=track_name)
            logger.debug(f"Created new audio track '{track_name}'")
    else:
        script.add_track(draft.TrackType.audio)
        logger.debug("Added audio track with default name")

    if payload.sound_effects:
        for effect_name, params in payload.sound_effects:
            effect_type = None
            if IS_CAPCUT_ENV:
                for source in (
                    CapCutVoiceFiltersEffectType,
                    CapCutVoiceCharactersEffectType,
                    CapCutSpeechToSongEffectType,
                ):
                    try:
                        effect_type = getattr(source, effect_name)
                        break
                    except AttributeError:
                        continue
            else:
                for source in (
                    AudioSceneEffectType,
                    ToneEffectType,
                    SpeechToSongType,
                ):
                    try:
                        effect_type = getattr(source, effect_name)
                        break
                    except AttributeError:
                        continue

            if effect_type:
                payload.segment.add_effect(effect_type, params)
                logger.debug(f"Added audio effect: {effect_name}")
            else:
                logger.warning(f"Audio effect named {effect_name} not found")

    script.add_segment(payload.segment, track_name=track_name)
    logger.debug("Added audio segment to track")


async def add_audio_track(
    audio_url: str,
    draft_folder: Optional[str] = None,
    start: float = 0,
    end: Optional[float] = None,
    target_start: float = 0,
    draft_id: Optional[str] = None,
    volume: float = 1.0,
    track_name: str = "audio_main",
    speed: float = 1.0,
    sound_effects: Optional[List[Tuple[str, Optional[List[Optional[float]]]]]] = None,
    audio_name: Optional[str] = None,
    duration: Optional[float] = None  # Added duration parameter
) -> Dict[str, str]:
    # Get or create draft (initial fetch for validation only)
    draft_id, _ = get_draft(draft_id=draft_id)
    logger.info(f"Starting audio track addition to draft {draft_id}")

    detected_format = None
    if duration is None:
        duration, detected_format = await _get_audio_metadata(audio_url)

    if audio_name:
        _, ext = os.path.splitext(audio_name)
        if not ext:
            if not detected_format:
                # If duration was provided, we might not have probed yet.
                # Probe now to get the format.
                _, detected_format = await _get_audio_metadata(audio_url)

            ext = get_extension_from_format(detected_format, ".mp3")
            audio_name += ext
            logger.info(f"Appended extension {ext} to audio_name: {audio_name}")

    payload = _prepare_audio_segment_payload(
        draft_id=draft_id,
        audio_url=audio_url,
        draft_folder=draft_folder,
        start=start,
        end=end,
        target_start=target_start,
        volume=volume,
        track_name=track_name,
        speed=speed,
        sound_effects=sound_effects,
        audio_name=audio_name,
        duration=duration,
    )

    def modify_draft(script):
        _apply_audio_segment_to_script(script, payload, draft_id)

    success, last_error = update_draft_with_retry(draft_id, modify_draft, return_error=True)

    if not success:
        error_msg = f"Failed to update draft {draft_id} after multiple retries due to concurrent modifications"
        if last_error:
            error_msg = f"{error_msg}. Last error: {last_error}"
            logger.error(error_msg, exc_info=True)
            raise RuntimeError(error_msg) from last_error
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    logger.info(f"Successfully added audio track to draft {draft_id}")

    return {
        "draft_id": draft_id,
        # "draft_url": generate_draft_url(draft_id)
    }


async def batch_add_audio_track(
    audios: List[Dict[str, Any]],
    draft_folder: Optional[str] = None,
    draft_id: Optional[str] = None,
    volume: float = 1.0,
    track_name: str = "audio_main",
    speed: float = 1.0,
    sound_effects: Optional[List[Tuple[str, Optional[List[Optional[float]]]]]] = None,
) -> Dict[str, Any]:
    if not audios:
        raise ValueError("audios parameter must contain at least one audio entry")

    draft_id, _ = get_draft(draft_id=draft_id)
    logger.info(f"Starting batch audio track addition to draft {draft_id} (count={len(audios)})")

    payloads: List[AudioSegmentPayload] = []
    skipped: List[Dict[str, Any]] = []

    # Gather metadata for all audios concurrently
    metadata_tasks = []
    for audio in audios:
        audio_url = audio.get("audio_url")
        if audio_url:
            metadata_tasks.append(_get_audio_metadata(audio_url))
        else:
            metadata_tasks.append(asyncio.sleep(0, result=(0.0, None))) # Dummy task

    metadata_results = await asyncio.gather(*metadata_tasks)

    for idx, audio in enumerate(audios):
        audio_url = audio.get("audio_url")
        if not audio_url:
            logger.warning(f"Audio at index {idx} is missing 'audio_url', skipping.")
            skipped.append({"index": idx, "reason": "missing_audio_url"})
            continue

        duration, detected_format = metadata_results[idx]
        if audio.get("duration") is not None:
            duration = audio.get("duration")

        audio_name = audio.get("audio_name")
        if audio_name:
            _, ext = os.path.splitext(audio_name)
            if not ext:
                ext = get_extension_from_format(detected_format, ".mp3")
                audio_name += ext

        try:
            payload = _prepare_audio_segment_payload(
                draft_id=draft_id,
                audio_url=audio_url,
                draft_folder=audio.get("draft_folder", draft_folder),
                start=audio.get("start", 0),
                end=audio.get("end"),
                target_start=audio.get("target_start", 0),
                volume=audio.get("volume", volume),
                track_name=audio.get("track_name", track_name),
                speed=audio.get("speed", speed),
                sound_effects=audio.get("sound_effects", sound_effects),
                audio_name=audio_name,
                duration=duration,
            )
            payloads.append(payload)
        except Exception as exc:
            logger.error(f"Failed to prepare audio at index {idx}: {exc}", exc_info=True)
            skipped.append(
                {
                    "index": idx,
                    "reason": str(exc),
                    "audio_url": audio_url,
                }
            )

    if not payloads:
        logger.warning("No valid audios were prepared for batch addition.")
        return {
            "draft_id": draft_id,
            "outputs": [],
            "skipped": skipped,
        }

    def modify_draft(script):
        for index, payload in enumerate(payloads):
            try:
                _apply_audio_segment_to_script(script, payload, draft_id)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to apply audio payload at index {index} "
                    f"for URL {payload.audio_url}: {exc}"
                ) from exc

    success, last_error = update_draft_with_retry(draft_id, modify_draft, return_error=True)
    if not success:
        error_msg = (
            f"Failed to update draft {draft_id} after multiple retries due to concurrent modifications"
        )
        if last_error:
            error_msg = f"{error_msg}. Last error: {last_error}"
            logger.error(error_msg, exc_info=True)
            raise RuntimeError(error_msg) from last_error
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    outputs = [
        {
            "audio_url": payload.audio_url,
            "result": {"draft_id": draft_id},
        }
        for payload in payloads
    ]

    return {
        "draft_id": draft_id,
        "outputs": outputs,
        "skipped": skipped,
    }


async def _get_audio_metadata(audio_url: str) -> Tuple[float, Optional[str]]:
    try:
        info = await get_ffprobe_info(
            audio_url,
            select_streams="a:0",
            show_entries=["stream=duration", "format=duration,format_name"]
        )

        format_name = None
        if "format" in info:
             format_name = info["format"].get("format_name")

        if "streams" in info and len(info["streams"]) > 0:
            stream = info["streams"][0]
            duration_str = stream.get("duration") or info["format"].get("duration", "0")
            return float(duration_str), format_name
        else:
            return 0.0, format_name
    except Exception as e:
        logger.error(f"Failed to get audio metadata for {audio_url}: {e}")
        raise ValueError(f"Failed to get audio metadata for {audio_url}. Please check if the URL is valid and accessible.") from e
