from typing import Dict, List, Literal, Optional

import pyJianYingDraft as draft
from draft_cache import update_cache
from pyJianYingDraft import (
    CapCutVideoCharacterEffectType,
    CapCutVideoSceneEffectType,
    VideoCharacterEffectType,
    VideoSceneEffectType,
    exceptions,
    trange,
)
from settings import IS_CAPCUT_ENV

from .create_draft import get_or_create_draft


def add_effect_impl(
    effect_type: str,  # Changed to string type
    effect_category: Literal["scene", "character"] = "scene",
    start: float = 0,
    end: float = 3.0,
    draft_id: Optional[str] = None,
    track_name: Optional[str] = "effect_01",
    params: Optional[List[Optional[float]]] = None,
    width: int = 1080,
    height: int = 1920
) -> Dict[str, str]:
    """
    Add an effect to the specified draft
    :param effect_type: Effect type name, will be matched from Video_scene_effect_type or Video_character_effect_type
    :param effect_category: Effect category, "scene" or "character", default "scene"
    :param start: Start time (seconds), default 0
    :param end: End time (seconds), default 3 seconds
    :param draft_id: Draft ID, if None or corresponding zip file not found, a new draft will be created
    :param track_name: Track name, can be omitted when there is only one effect track
    :param params: Effect parameter list, items not provided or None in the parameter list will use default values
    :param width: Video width, default 1080
    :param height: Video height, default 1920
    :return: Updated draft information
    """
    # Get or create draft
    draft_id, script = get_or_create_draft(
        draft_id=draft_id,
        width=width,
        height=height
    )

    # Calculate time range
    duration = end - start
    t_range = trange(f"{start}s", f"{duration}s")

    # Select the corresponding effect type based on effect category and environment
    effect_enum = None
    if IS_CAPCUT_ENV:
        # If in CapCut environment, use CapCut effects
        if effect_category == "scene":
            try:
                effect_enum = CapCutVideoSceneEffectType[effect_type]
            except Exception:
                effect_enum = None
        elif effect_category == "character":
            try:
                effect_enum = CapCutVideoCharacterEffectType[effect_type]
            except Exception:
                effect_enum = None
    else:
        # Default to using JianYing effects
        if effect_category == "scene":
            try:
                effect_enum = VideoSceneEffectType[effect_type]
            except Exception:
                effect_enum = None
        elif effect_category == "character":
            try:
                effect_enum = VideoCharacterEffectType[effect_type]
            except Exception:
                effect_enum = None

    if effect_enum is None:
        raise ValueError(f"Unknown {effect_category} effect type: {effect_type}")

    # Add effect track (only when track doesn't exist)
    if track_name is not None:
        try:
            script.get_imported_track(draft.Track_type.effect, name=track_name)
            # If no exception is thrown, the track already exists
        except exceptions.TrackNotFound:
            # Track doesn't exist, create a new track
            script.add_track(draft.Track_type.effect, track_name=track_name)
    else:
        script.add_track(draft.Track_type.effect)

    # Add effect
    script.add_effect(effect_enum, t_range, params=params, track_name=track_name)

    # Persist updated script
    update_cache(draft_id, script)

    return {
        "draft_id": draft_id,
        # "draft_url": generate_draft_url(draft_id)
    }
