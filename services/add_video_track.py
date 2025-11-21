import asyncio
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import pyJianYingDraft as draft
from draft_cache import update_draft_with_retry
from pyJianYingDraft import ClipSettings, exceptions, trange
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
class VideoSegmentPayload:
    video_url: str
    segment: draft.VideoSegment
    track_name: Optional[str]
    relative_index: int
    mask_type: Optional[str]
    mask_center_x: float
    mask_center_y: float
    mask_size: float
    mask_rotation: float
    mask_feather: float
    mask_invert: bool
    mask_rect_width: Optional[float]
    mask_round_corner: Optional[float]
    filter_type: Optional[str]
    filter_intensity: float
    background_blur: Optional[int]


def _prepare_video_segment_payload(
    *,
    draft_id: str,
    video_url: str,
    draft_folder: Optional[str],
    start: float,
    end: Optional[float],
    mode: str,
    target_duration: Optional[float],
    target_start: float,
    transform_y: float,
    scale_x: float,
    scale_y: float,
    transform_x: float,
    speed: float,
    track_name: Optional[str],
    relative_index: int,
    intro_animation: Optional[str],
    intro_animation_duration: float,
    outro_animation: Optional[str],
    outro_animation_duration: float,
    combo_animation: Optional[str],
    combo_animation_duration: float,
    video_name: Optional[str],
    duration: Optional[float],
    width: int,
    height: int,
    transition: Optional[str],
    transition_duration: Optional[float],
    filter_type: Optional[str],
    filter_intensity: float,
    fade_in_duration: float,
    fade_out_duration: float,
    mask_type: Optional[str],
    mask_center_x: float,
    mask_center_y: float,
    mask_size: float,
    mask_rotation: float,
    mask_feather: float,
    mask_invert: bool,
    mask_rect_width: Optional[float],
    mask_round_corner: Optional[float],
    volume: float,
    background_blur: Optional[int],
    extension: str = ".mp4",
) -> VideoSegmentPayload:
    # ========== Mode validation and speed calculation ==========
    if mode not in ["cover", "fill"]:
        raise ValueError(f"❌ 参数错误：mode={mode} 无效，只支持 'cover' 或 'fill'")

    if mode == "fill":
        if target_duration is None or target_duration <= 0:
            raise ValueError(
                f"❌ 参数错误：mode='fill' 时必须提供有效的 target_duration 参数（当前值：{target_duration}）"
            )
        print(f"✅ 使用 fill 模式：将根据 target_duration={target_duration}秒 自动计算播放速度")
    else:
        print(f"✅ 使用 cover 模式：使用提供的 speed={speed} 参数")

    # ========== 参数验证与时长处理 ==========

    # 1. 验证start参数
    if start < 0:
        raise ValueError(f"❌ 参数错误：start={start}秒不能为负数")

    # 2. 确定视频总时长
    video_duration = -1  # 默认0
    if duration is not None:
        if duration <= 0:
            raise ValueError(f"❌ 参数错误：duration={duration}秒必须为正数")
        video_duration = duration
        print(f"✅ 使用提供的视频时长: {video_duration}秒")

    if video_name:
        material_name = video_name
        logger.debug(f"Using custom video_name '{video_name}' for URL {video_url}")
    else:
        # Generate local filename
        material_name = f"video_{url_to_hash(video_url)}{extension}"

    # Build draft_video_path
    draft_video_path = None
    if draft_folder:
        if is_windows_path(draft_folder):
            windows_drive, windows_path = re.match(r"([a-zA-Z]:)(.*)", draft_folder).groups()
            parts = [p for p in windows_path.split("\\") if p]
            draft_video_path = os.path.join(
                windows_drive, *parts, draft_id, "assets", "video", material_name
            )
            draft_video_path = draft_video_path.replace("/", "\\")
        else:
            draft_video_path = os.path.join(draft_folder, draft_id, "assets", "video", material_name)
        print("replace_path:", draft_video_path)

    # 3. 确定裁剪终点
    if end is None or end <= 0:
        video_end = video_duration
        source_duration = video_end - start
        print(f"📹 裁剪模式：从{start}秒截取到{video_end}秒（共{source_duration}秒）")
    else:
        video_end = end
        source_duration = video_end - start
        print(f"📹 裁剪模式：从{start}秒截取到{video_end}秒（共{source_duration}秒）")

    # 4. 关键验证：防止负数时长（仅在已知时长时检查）
    if video_duration > 0 and source_duration <= 0:
        raise ValueError(
            f"❌ 素材裁剪参数错误：计算出的source_duration={source_duration}秒 ≤ 0\n"
            f"参数检查：start={start}, end={video_end}, video_duration={video_duration}\n"
            f"建议：\n"
            f"  - 确保 end > start（当前 {video_end} - {start} = {source_duration}）\n"
            f"  - 如需截取到视频末尾，设置 end=0 并提供 duration 参数\n"
            f"  - 示例：start=10, end=0, duration=60 → 截取第10-60秒"
        )

    # 5. 边界检查（仅在已知时长时检查）
    if video_duration > 0:
        if start >= video_duration:
            raise ValueError(
                f"❌ 参数错误：start={start}秒 >= 视频总时长{video_duration}秒\n"
                f"建议：start应小于{video_duration}秒"
            )
        if video_end > video_duration:
            print(
                f"⚠️  警告：end={video_end}秒超出视频总时长{video_duration}秒，自动调整为{video_duration}秒"
            )
            video_end = video_duration
            source_duration = video_end - start

    # 6. 根据模式计算speed和target_duration
    if mode == "fill":
        if source_duration > 0:
            calculated_speed = source_duration / target_duration  # type: ignore[arg-type]
            speed = calculated_speed
            final_target_duration = target_duration
            print(
                f"📊 Fill模式计算结果：source_duration={source_duration}秒 / target_duration={target_duration}秒 = speed={speed:.3f}x"
            )
        else:
            final_target_duration = target_duration
            print("⚠️  警告：视频时长未知，speed将在下载后自动计算")
    else:
        final_target_duration = source_duration / speed if source_duration > 0 else 0

    # 7. 输出处理信息
    if video_duration > 0:
        print(
            f"""
            📹 视频素材处理信息：
            - 素材URL: {video_url}
            - 视频总时长: {video_duration}秒
            - 裁剪参数: start={start}秒, end={video_end}秒
            - 裁剪时长: {source_duration}秒
            - 播放速度: {speed}x
            - 成片时长: {final_target_duration}秒
            - 时间线位置: target_start={target_start}秒
            - 模式: {mode}
            """
        )

    # Create video material
    if draft_video_path:
        video_material = draft.VideoMaterial(
            material_type="video",
            replace_path=draft_video_path,
            remote_url=video_url,
            material_name=material_name,
            duration=int(video_duration * 1e6),
            width=width,
            height=height
        )
    else:
        video_material = draft.VideoMaterial(
            material_type="video",
            remote_url=video_url,
            material_name=material_name,
            duration=int(video_duration * 1e6),
            width=width,
            height=height
        )

    source_timerange = trange(f"{start}s", f"{source_duration}s")
    target_timerange = trange(f"{target_start}s", f"{final_target_duration}s")

    video_segment = draft.VideoSegment(
        material=video_material,
        target_timerange=target_timerange,
        source_timerange=source_timerange,
        speed=speed,
        clip_settings=ClipSettings(
            transform_y=transform_y,
            scale_x=scale_x,
            scale_y=scale_y,
            transform_x=transform_x,
        ),
        volume=volume,
    )

     # Add entrance animation (prioritize intro_animation, then use animation)
    if intro_animation:
        try:
            if IS_CAPCUT_ENV:
                animation_type = getattr(draft.CapCutIntroType, intro_animation)
            else:
                animation_type = getattr(draft.IntroType, intro_animation)
            video_segment.add_animation(animation_type, intro_animation_duration * 1e6)
        except AttributeError:
            raise ValueError(
                f"Warning: Unsupported entrance animation type {intro_animation}, this parameter will be ignored"
            )

     # Add exit animation
    if outro_animation:
        try:
            if IS_CAPCUT_ENV:
                outro_type = getattr(draft.CapCutOutroType, outro_animation)
            else:
                outro_type = getattr(draft.OutroType, outro_animation)
            video_segment.add_animation(outro_type, outro_animation_duration * 1e6)
        except AttributeError:
            raise ValueError(
                f"Warning: Unsupported exit animation type {outro_animation}, this parameter will be ignored"
            )

    # Add combo animation
    if combo_animation:
        try:
            if IS_CAPCUT_ENV:
                combo_type = getattr(draft.CapCutGroupAnimationType, combo_animation)
            else:
                combo_type = getattr(draft.GroupAnimationType, combo_animation)
            video_segment.add_animation(combo_type, combo_animation_duration * 1e6)
        except AttributeError:
            raise ValueError(
                f"Warning: Unsupported combo animation type {combo_animation}, this parameter will be ignored"
            )

    # Add transition effect
    if transition:
        try:
            if IS_CAPCUT_ENV:
                transition_type = getattr(draft.CapCutTransitionType, transition)
            else:
                transition_type = getattr(draft.TransitionType, transition)
            duration_microseconds = int((transition_duration or 0) * 1e6)
            video_segment.add_transition(transition_type, duration=duration_microseconds)
        except AttributeError:
            raise ValueError(f"Unsupported transition type: {transition}, transition setting skipped")

    # Add fade effect
    if fade_in_duration > 0 or fade_out_duration > 0:
        video_segment.add_fade(fade_in_duration, fade_out_duration)

    return VideoSegmentPayload(
        video_url=video_url,
        segment=video_segment,
        track_name=track_name,
        relative_index=relative_index,
        mask_type=mask_type,
        mask_center_x=mask_center_x,
        mask_center_y=mask_center_y,
        mask_size=mask_size,
        mask_rotation=mask_rotation,
        mask_feather=mask_feather,
        mask_invert=mask_invert,
        mask_rect_width=mask_rect_width,
        mask_round_corner=mask_round_corner,
        filter_type=filter_type,
        filter_intensity=filter_intensity,
        background_blur=background_blur,
    )


def _apply_video_segment_to_script(
    script,
    payload: VideoSegmentPayload,
    draft_id: str,
) -> None:
    logger.debug(f"Applying video track modifications to draft {draft_id}")

    try:
        script.get_track(draft.TrackType.video, track_name=None)
    except exceptions.TrackNotFound:
        script.add_track(draft.TrackType.video, relative_index=0)
        logger.debug("Added default video track")
    except NameError:
        pass

    if payload.track_name is not None:
        try:
            script.get_imported_track(draft.TrackType.video, name=payload.track_name)
            logger.debug(f"Video track '{payload.track_name}' already exists")
        except exceptions.TrackNotFound:
            script.add_track(
                draft.TrackType.video,
                track_name=payload.track_name,
                relative_index=payload.relative_index,
            )
            logger.debug(f"Created new video track '{payload.track_name}'")
    else:
        script.add_track(draft.TrackType.video, relative_index=payload.relative_index)
        logger.debug("Added video track with default name")

    if payload.mask_type:
        try:
            if IS_CAPCUT_ENV:
                mask_type_enum = getattr(draft.CapCutMaskType, payload.mask_type)
            else:
                mask_type_enum = getattr(draft.MaskType, payload.mask_type)
            payload.segment.add_mask(
                script,
                mask_type_enum,
                center_x=payload.mask_center_x,
                center_y=payload.mask_center_y,
                size=payload.mask_size,
                rotation=payload.mask_rotation,
                feather=payload.mask_feather,
                invert=payload.mask_invert,
                rect_width=payload.mask_rect_width,
                round_corner=payload.mask_round_corner,
            )
            logger.debug(f"Added mask effect: {payload.mask_type}")
        except Exception as exc:
            raise ValueError(
                f"{exc}, Unsupported mask type {payload.mask_type}, supported types include: "
                f"{', '.join([mask.name for mask in draft.MaskType])}"
            ) from exc

    if payload.filter_type:
        try:
            filter_type_enum = getattr(draft.FilterType, payload.filter_type)
            payload.segment.add_filter(filter_type_enum, payload.filter_intensity)
            logger.debug(f"Added filter effect: {payload.filter_type}")
        except Exception as exc:
            raise ValueError(
                "Unsupported filter type "
                f"{payload.filter_type}, supported types include: linear, mirror, circle, rectangle, heart, star"
            ) from exc

    if payload.background_blur is not None:
        if payload.background_blur not in [1, 2, 3, 4]:
            raise ValueError(
                f"Invalid background blur level: {payload.background_blur}, valid values are: 1, 2, 3, 4"
            )

        blur_values = {
            1: 0.0625,
            2: 0.375,
            3: 0.75,
            4: 1.0,
        }
        payload.segment.add_background_filling("blur", blur=blur_values[payload.background_blur])
        logger.debug(f"Added background blur: level {payload.background_blur}")

    script.add_segment(payload.segment, track_name=payload.track_name)
    logger.debug("Added video segment to track")


async def add_video_track(
    video_url: str,
    draft_folder: Optional[str] = None,
    start: float = 0,
    end: Optional[float] = None,
    mode: str = "cover",  # Mode: "cover" (use speed parameter) or "fill" (calculate speed from target_duration)
    target_duration: Optional[float] = None,  # Target duration for fill mode (required when mode="fill")
    target_start: float = 0,
    draft_id: Optional[str] = None,
    transform_y: float = 0,
    scale_x: float = 1,
    scale_y: float = 1,
    transform_x: float = 0,
    speed: float = 1.0,
    track_name: str = "main",
    relative_index: int = 0,
    video_name: Optional[str] = None,
    intro_animation: Optional[str] = None,  # New entrance animation parameter, higher priority than animation
    intro_animation_duration: float = 0.5,  # New entrance animation duration parameter, default 0.5 seconds
    outro_animation: Optional[str] = None,  # Exit animation parameter
    outro_animation_duration: float = 0.5,  # Exit animation duration parameter, default 0.5 seconds
    combo_animation: Optional[str] = None,  # Combo animation parameter
    combo_animation_duration: float = 0.5,  # Combo animation duration parameter, default 0.5 seconds
    duration: Optional[float] = None,  # Added duration parameter
    transition: Optional[str] = None,  # Transition type
    transition_duration: Optional[float] = 0.5,  # Transition duration (seconds)
    filter_type: Optional[str] = None,  # Filter type
    filter_intensity: float = 100.0,  # Filter intensity
    fade_in_duration: float = 0.0,  # Fade in duration (seconds)
    fade_out_duration: float = 0.0,  # Fade out duration (seconds)
    # Mask related parameters
    mask_type: Optional[str] = None,  # Mask type
    mask_center_x: float = 0.5,  # Mask center X coordinate (0-1)
    mask_center_y: float = 0.5,  # Mask center Y coordinate (0-1)
    mask_size: float = 1.0,  # Mask size (0-1)
    mask_rotation: float = 0.0,  # Mask rotation angle (degrees)
    mask_feather: float = 0.0,  # Mask feather level (0-1)
    mask_invert: bool = False,  # Whether to invert mask
    mask_rect_width: Optional[float] = None,  # Rectangle mask width (only for rectangle mask)
    mask_round_corner: Optional[float] = None,  # Rectangle mask rounded corner (only for rectangle mask, 0-100)
    volume: float = 1.0,  # Volume level, default 1.0
    background_blur: Optional[int] = None  # Background blur level, optional values: 1 (light), 2 (medium), 3 (strong), 4 (maximum), default None (no background blur)
) -> Dict[str, str]:
    """
    Add video track to specified draft.
    """
    draft_id, _ = get_draft(draft_id=draft_id)
    logger.info(f"Starting video track addition to draft {draft_id}")

    width = 0
    height = 0
    detected_format = None
    if duration is None:
        duration, width, height, detected_format = await _get_video_metadata(video_url)
    else:
        # If duration is provided, we still need width and height
        _, width, height, detected_format = await _get_video_metadata(video_url)

    ext = get_extension_from_format(detected_format, ".mp4")

    if video_name:
        _, name_ext = os.path.splitext(video_name)
        if not name_ext:
            video_name += ext

    payload = _prepare_video_segment_payload(
        draft_id=draft_id,
        video_url=video_url,
        draft_folder=draft_folder,
        start=start,
        end=end,
        mode=mode,
        target_duration=target_duration,
        target_start=target_start,
        transform_y=transform_y,
        scale_x=scale_x,
        scale_y=scale_y,
        transform_x=transform_x,
        speed=speed,
        track_name=track_name,
        relative_index=relative_index,
        intro_animation=intro_animation,
        intro_animation_duration=intro_animation_duration,
        outro_animation=outro_animation,
        outro_animation_duration=outro_animation_duration,
        combo_animation=combo_animation,
        combo_animation_duration=combo_animation_duration,
        video_name=video_name,
        duration=duration,
        width=width,
        height=height,
        transition=transition,
        transition_duration=transition_duration,
        filter_type=filter_type,
        filter_intensity=filter_intensity,
        fade_in_duration=fade_in_duration,
        fade_out_duration=fade_out_duration,
        mask_type=mask_type,
        mask_center_x=mask_center_x,
        mask_center_y=mask_center_y,
        mask_size=mask_size,
        mask_rotation=mask_rotation,
        mask_feather=mask_feather,
        mask_invert=mask_invert,
        mask_rect_width=mask_rect_width,
        mask_round_corner=mask_round_corner,
        volume=volume,
        background_blur=background_blur,
        extension=ext,
    )

    def modify_draft(script):
        _apply_video_segment_to_script(script, payload, draft_id)

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

    logger.info(f"Successfully added video track to draft {draft_id}")

    return {
        "draft_id": draft_id,
    }


async def batch_add_video_track(
    videos: List[Dict[str, Any]],
    draft_folder: Optional[str] = None,
    draft_id: Optional[str] = None,
    transform_y: float = 0,
    scale_x: float = 1,
    scale_y: float = 1,
    transform_x: float = 0,
    track_name: str = "main",
    relative_index: int = 0,
    transition: Optional[str] = None,
    transition_duration: float = 0.5,
    volume: float = 1.0,
    intro_animation: Optional[str] = None,
    intro_animation_duration: float = 0.5,
    outro_animation: Optional[str] = None,
    outro_animation_duration: float = 0.5,
    combo_animation: Optional[str] = None,
    combo_animation_duration: float = 0.5,
    mask_type: Optional[str] = None,
    mask_center_x: float = 0.5,
    mask_center_y: float = 0.5,
    mask_size: float = 1.0,
    mask_rotation: float = 0.0,
    mask_feather: float = 0.0,
    mask_invert: bool = False,
    mask_rect_width: Optional[float] = None,
    mask_round_corner: Optional[float] = None,
    filter_type: Optional[str] = None,
    filter_intensity: float = 100.0,
    fade_in_duration: float = 0.0,
    fade_out_duration: float = 0.0,
    background_blur: Optional[int] = None,
    default_mode: str = "cover",
) -> Dict[str, Any]:
    """
    Batch add multiple video segments to the same draft using a single persistence call.
    """
    if not videos:
        raise ValueError("videos parameter must contain at least one video entry")

    draft_id, _ = get_draft(draft_id=draft_id)
    logger.info(f"Starting batch video track addition to draft {draft_id} (count={len(videos)})")

    payloads: List[VideoSegmentPayload] = []
    skipped: List[Dict[str, Any]] = []

    # Gather metadata for all videos concurrently
    metadata_tasks = []
    for video in videos:
        video_url = video.get("video_url")
        if video_url:
            metadata_tasks.append(_get_video_metadata(video_url))
        else:
            metadata_tasks.append(asyncio.sleep(0, result=(0.0, 0, 0, None))) # Dummy task

    metadatas = await asyncio.gather(*metadata_tasks)

    for idx, video in enumerate(videos):
        video_url = video.get("video_url")
        if not video_url:
            logger.warning(f"Video at index {idx} is missing 'video_url', skipping.")
            skipped.append(
                {
                    "index": idx,
                    "reason": "missing_video_url",
                }
            )
            continue

        duration, width, height, detected_format = metadatas[idx]
        ext = get_extension_from_format(detected_format, ".mp4")

        # If duration is provided in video dict, use it, but we still need width/height
        if video.get("duration") is not None:
            duration = video.get("duration")

        video_name = video.get("video_name")
        if video_name:
            _, name_ext = os.path.splitext(video_name)
            if not name_ext:
                video_name += ext

        try:
            payload = _prepare_video_segment_payload(
                draft_id=draft_id,
                video_url=video_url,
                draft_folder=video.get("draft_folder", draft_folder),
                start=video.get("start", 0),
                end=video.get("end", 0),
                mode=video.get("mode", default_mode),
                target_duration=video.get("target_duration"),
                target_start=video.get("target_start", 0),
                transform_y=video.get("transform_y", transform_y),
                scale_x=video.get("scale_x", scale_x),
                scale_y=video.get("scale_y", scale_y),
                transform_x=video.get("transform_x", transform_x),
                speed=video.get("speed", 1.0),
                track_name=video.get("track_name", track_name),
                relative_index=video.get("relative_index", relative_index),
                intro_animation=video.get("intro_animation", intro_animation),
                intro_animation_duration=video.get("intro_animation_duration", intro_animation_duration),
                outro_animation=video.get("outro_animation", outro_animation),
                outro_animation_duration=video.get("outro_animation_duration", outro_animation_duration),
                combo_animation=video.get("combo_animation", combo_animation),
                combo_animation_duration=video.get("combo_animation_duration", combo_animation_duration),
                video_name=video_name,
                duration=duration,
                width=width,
                height=height,
                transition=video.get("transition", transition),
                transition_duration=video.get("transition_duration", transition_duration),
                filter_type=video.get("filter_type", filter_type),
                filter_intensity=video.get("filter_intensity", filter_intensity),
                fade_in_duration=video.get("fade_in_duration", fade_in_duration),
                fade_out_duration=video.get("fade_out_duration", fade_out_duration),
                mask_type=video.get("mask_type", mask_type),
                mask_center_x=video.get("mask_center_x", mask_center_x),
                mask_center_y=video.get("mask_center_y", mask_center_y),
                mask_size=video.get("mask_size", mask_size),
                mask_rotation=video.get("mask_rotation", mask_rotation),
                mask_feather=video.get("mask_feather", mask_feather),
                mask_invert=video.get("mask_invert", mask_invert),
                mask_rect_width=video.get("mask_rect_width", mask_rect_width),
                mask_round_corner=video.get("mask_round_corner", mask_round_corner),
                volume=video.get("volume", volume),
                background_blur=video.get("background_blur", background_blur),
                extension=ext,
            )
            payloads.append(payload)
        except Exception as exc:
            logger.error(f"Failed to prepare video at index {idx}: {exc}", exc_info=True)
            skipped.append(
                {
                    "index": idx,
                    "reason": str(exc),
                    "video_url": video_url,
                }
            )

    if not payloads:
        logger.warning("No valid videos were prepared for batch addition.")
        return {
            "draft_id": draft_id,
            "outputs": [],
            "skipped": skipped,
        }

    def modify_draft(script):
        for index, payload in enumerate(payloads):
            try:
                _apply_video_segment_to_script(script, payload, draft_id)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to apply video payload at index {index} "
                    f"for URL {payload.video_url}: {exc}"
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

    logger.info(
        f"Successfully batch added {len(payloads)} video segment(s) to draft {draft_id}. "
        f"Skipped {len(skipped)} item(s)."
    )

    outputs = [
        {
            "video_url": payload.video_url,
            "result": {"draft_id": draft_id},
        }
        for payload in payloads
    ]

    return {
        "draft_id": draft_id,
        "outputs": outputs,
        "skipped": skipped,
    }


async def _get_video_metadata(video_url: str) -> Tuple[float, int, int, Optional[str]]:
    try:
        info = await get_ffprobe_info(video_url)

        format_name = None
        if "format" in info:
             format_name = info["format"].get("format_name")

        if "streams" in info and len(info["streams"]) > 0:
            stream = info["streams"][0]
            width = int(stream.get("width", 0))
            height = int(stream.get("height", 0))
            duration_str = stream.get("duration") or info["format"].get("duration", "0")
            duration = float(duration_str)
            return duration, width, height, format_name
        else:
            return 0.0, 0, 0, format_name
    except Exception as e:
        logger.error(f"Failed to get video metadata for {video_url}: {e}")
        raise ValueError(f"Failed to get video metadata for {video_url}. Please check if the URL is valid and accessible.") from e
