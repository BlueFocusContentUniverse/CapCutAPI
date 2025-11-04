import logging
import os
import re
from typing import Dict, Optional

import pyJianYingDraft as draft
from draft_cache import update_draft_with_retry
from pyJianYingDraft import ClipSettings, exceptions, trange
from settings.local import IS_CAPCUT_ENV
from util.helpers import is_windows_path, url_to_hash

from .create_draft import get_draft

logger = logging.getLogger(__name__)


def add_video_track(
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
    Add video track to specified draft
    :param draft_folder: Draft folder path, optional parameter
    :param video_url: Video URL
    :param start: Source video start time (seconds), default 0
    :param end: Source video end time (seconds), default None (use total video duration)
    :param mode: Mode for speed calculation, "cover" (default, use speed parameter) or "fill" (calculate speed from target_duration)
    :param target_duration: Target duration for fill mode (seconds), required when mode="fill", used to calculate speed automatically
    :param target_start: Target video start time (seconds), default 0
    :param draft_id: Draft ID, if None or corresponding zip file not found, create new draft
    :param transform_y: Y-axis transform, default 0
    :param scale_x: X-axis scale, default 1
    :param scale_y: Y-axis scale, default 1
    :param transform_x: X-axis transform, default 0
    :param speed: Video playback speed, default 1.0
    :param duration: Video duration (seconds), if provided, skip duration detection
    :param track_name: When there is only one video, track name can be omitted
    :param relative_index: Track rendering order index, default 0
    :param intro_animation: New entrance animation parameter, higher priority than animation
    :param intro_animation_duration: New entrance animation duration (seconds), default 0.5 seconds
    :param outro_animation: Exit animation parameter
    :param outro_animation_duration: Exit animation duration (seconds), default 0.5 seconds
    :param combo_animation: Combo animation parameter
    :param combo_animation_duration: Combo animation duration (seconds), default 0.5 seconds
    :param transition: Transition type, optional parameter
    :param transition_duration: Transition duration (seconds), default uses the default duration of transition type
    :param filter_type: Filter type, optional parameter
    :param filter_intensity: Filter intensity, default 100.0
    :param fade_in_duration: Fade in duration (seconds), default 0.0
    :param fade_out_duration: Fade out duration (seconds), default 0.0
    :param mask_type: Mask type (linear, mirror, circle, rectangle, heart, star), optional parameter
    :param mask_center_x: Mask center X coordinate (0-1), default 0.5
    :param mask_center_y: Mask center Y coordinate (0-1), default 0.5
    :param mask_size: Mask size (0-1), default 1.0
    :param mask_rotation: Mask rotation angle (degrees), default 0.0
    :param mask_feather: Mask feather level (0-1), default 0.0
    :param mask_invert: Whether to invert mask, default False
    :param mask_rect_width: Rectangle mask width, only allowed when mask type is rectangle, represented as a proportion of material width
    :param mask_round_corner: Rectangle mask rounded corner parameter, only allowed when mask type is rectangle, range 0~100
    :param volume: Volume level, default 1.0 (0.0 is mute, 1.0 is original volume)
    :param background_blur: Background blur level, optional values: 1 (light), 2 (medium), 3 (strong), 4 (maximum), default None (no background blur)
    :return: Updated draft information, including draft_id and draft_url
    """
    # Get or create draft (initial fetch for validation only)
    draft_id, _ = get_draft(draft_id=draft_id)
    logger.info(f"Starting video track addition to draft {draft_id}")

    # ========== Mode validation and speed calculation ==========
    # Validate mode parameter
    if mode not in ["cover", "fill"]:
        raise ValueError(f"❌ 参数错误：mode={mode} 无效，只支持 'cover' 或 'fill'")
    # Validate fill mode requirements
    if mode == "fill":
        if target_duration is None or target_duration <= 0:
            raise ValueError(f"❌ 参数错误：mode='fill' 时必须提供有效的 target_duration 参数（当前值：{target_duration}）")
        print(f"✅ 使用 fill 模式：将根据 target_duration={target_duration}秒 自动计算播放速度")
    else:
        print(f"✅ 使用 cover 模式：使用提供的 speed={speed} 参数")

    # Prepare parameters for the modifier function
    # We'll capture all the parameters needed for modification in the closure

    # ========== 参数验证与时长处理 ==========

    # 1. 验证start参数
    if start < 0:
        raise ValueError(f"❌ 参数错误：start={start}秒不能为负数")

    # 2. 确定视频总时长
    if duration is not None:
        if duration <= 0:
            raise ValueError(f"❌ 参数错误：duration={duration}秒必须为正数")
        video_duration = duration
        print(f"✅ 使用提供的视频时长: {video_duration}秒")
    else:
        # 使用-1标记"未知时长"，后续在save_draft_impl中获取
        video_duration = -1.0
        print("⚠️  警告：未提供duration参数，视频时长将在下载时自动获取（可能耗时较长）")

    # Generate local filename
    material_name = f"video_{url_to_hash(video_url)}.mp4"
    # local_video_path = download_video(video_url, draft_dir)

    # Build draft_video_path
    draft_video_path = None
    if draft_folder:
        # Detect input path type and process
        if is_windows_path(draft_folder):
            # Windows path processing
            windows_drive, windows_path = re.match(r"([a-zA-Z]:)(.*)", draft_folder).groups()
            parts = [p for p in windows_path.split("\\") if p]  # Split path and filter empty parts
            draft_video_path = os.path.join(windows_drive, *parts, draft_id, "assets", "video", material_name)
            # Normalize path (ensure consistent separators)
            draft_video_path = draft_video_path.replace("/", "\\")
        else:
            # macOS/Linux path processing
            draft_video_path = os.path.join(draft_folder, draft_id, "assets", "video", material_name)

        # Print path information
        print("replace_path:", draft_video_path)

    # ========== 计算裁剪时长（增强验证） ==========

    # 3. 确定裁剪终点
    if end is None or end <= 0:
        # end为None/0/负数时，表示截取到视频末尾
        if video_duration == -1.0:
            # 时长未知，使用0标记"使用完整时长"
            video_end = 0
            source_duration = 0  # 占位符，实际时长在下载时计算
            print(f"📹 裁剪模式：从{start}秒截取到视频末尾（时长待获取）")
        else:
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
            print(f"⚠️  警告：end={video_end}秒超出视频总时长{video_duration}秒，自动调整为{video_duration}秒")
            video_end = video_duration
            source_duration = video_end - start

    # 6. 根据模式计算speed和target_duration
    if mode == "fill":
        # Fill模式：根据source_duration和target_duration计算speed
        if source_duration > 0:
            # speed = source_duration / target_duration (播放source_duration秒的内容需要target_duration秒)
            calculated_speed = source_duration / target_duration
            speed = calculated_speed
            final_target_duration = target_duration
            print(f"📊 Fill模式计算结果：source_duration={source_duration}秒 / target_duration={target_duration}秒 = speed={speed:.3f}x")
        else:
            # 时长未知时，无法计算speed，保留占位符
            final_target_duration = target_duration
            print(f"⚠️  警告：视频时长未知，speed将在下载后自动计算")
    else:
        # Cover模式：使用提供的speed计算target_duration
        final_target_duration = source_duration / speed if source_duration > 0 else 0

    # 7. 输出处理信息
    if video_duration > 0:
        # 智能截断URL：保留开头和结尾，避免截断重要信息
        url_display = video_url if len(video_url) <= 80 else f"{video_url[:40]}...{video_url[-37:]}"
        print(f"""
            📹 视频素材处理信息：
            - 素材URL: {url_display}
            - 视频总时长: {video_duration}秒
            - 裁剪参数: start={start}秒, end={video_end}秒
            - 裁剪时长: {source_duration}秒
            - 播放速度: {speed}x
            - 成片时长: {final_target_duration}秒
            - 时间线位置: target_start={target_start}秒
            - 模式: {mode}
            """)

    # Create video clip
    if draft_video_path:
        video_material = draft.Video_material(material_type="video", replace_path=draft_video_path, remote_url=video_url, material_name=material_name, duration=video_duration, width=0, height=0)
    else:
        video_material = draft.Video_material(material_type="video", remote_url=video_url, material_name=material_name, duration = video_duration, width=0, height=0)

    # Create source_timerange and target_timerange
    source_timerange = trange(f"{start}s", f"{source_duration}s")
    target_timerange = trange(f"{target_start}s", f"{final_target_duration}s")

    video_segment = draft.VideoSegment(
        video_material,
        target_timerange=target_timerange,
        source_timerange=source_timerange,
        speed=speed,
        clip_settings=ClipSettings(
            transform_y=transform_y,
            scale_x=scale_x,
            scale_y=scale_y,
            transform_x=transform_x
        ),
        volume=volume
    )

     # Add entrance animation (prioritize intro_animation, then use animation)
    if intro_animation:
        try:
            if IS_CAPCUT_ENV:
                animation_type = getattr(draft.CapCutIntroType, intro_animation)
            else:
                animation_type = getattr(draft.IntroType, intro_animation)
            video_segment.add_animation(animation_type, intro_animation_duration * 1e6)  # Use microsecond unit for animation duration
        except AttributeError:
            raise ValueError(f"Warning: Unsupported entrance animation type {intro_animation}, this parameter will be ignored")

     # Add exit animation
    if outro_animation:
        try:
            if IS_CAPCUT_ENV:
                outro_type = getattr(draft.CapCutOutroType, outro_animation)
            else:
                outro_type = getattr(draft.OutroType, outro_animation)
            video_segment.add_animation(outro_type, outro_animation_duration * 1e6)  # Use microsecond unit for animation duration
        except AttributeError:
            raise ValueError(f"Warning: Unsupported exit animation type {outro_animation}, this parameter will be ignored")

    # Add combo animation
    if combo_animation:
        try:
            if IS_CAPCUT_ENV:
                combo_type = getattr(draft.CapCutGroupAnimationType, combo_animation)
            else:
                combo_type = getattr(draft.GroupAnimationType, combo_animation)
            video_segment.add_animation(combo_type, combo_animation_duration * 1e6)  # Use microsecond unit for animation duration
        except AttributeError:
            raise ValueError(f"Warning: Unsupported combo animation type {combo_animation}, this parameter will be ignored")

    # Add transition effect
    if transition:
        try:
            # Get transition type
            if IS_CAPCUT_ENV:
                transition_type = getattr(draft.CapCutTransitionType, transition)
            else:
                transition_type = getattr(draft.TransitionType, transition)

            # Set transition duration (convert to microseconds)
            duration_microseconds = int(transition_duration * 1e6)

            # Add transition
            video_segment.add_transition(transition_type, duration=duration_microseconds)
        except AttributeError:
            raise ValueError(f"Unsupported transition type: {transition}, transition setting skipped")


    # Add fade effect
    if fade_in_duration > 0 or fade_out_duration > 0:
        video_segment.add_fade(fade_in_duration, fade_out_duration)

    # Define modifier function that will be called with retry logic
    def modify_draft(script):
        """Modifier function that adds video track to the draft"""
        logger.debug(f"Applying video track modifications to draft {draft_id}")

        # Check if video track exists, if not, add a default video track
        try:
            script.get_track(draft.Track_type.video, track_name=None)
        except exceptions.TrackNotFound:
            script.add_track(draft.Track_type.video, relative_index=0)
            logger.debug("Added default video track")
        except NameError:
            # If multiple video tracks exist (NameError), do nothing
            pass

        # Add video track (only when track doesn't exist)
        if track_name is not None:
            try:
                script.get_imported_track(draft.Track_type.video, name=track_name)
                # If no exception is thrown, the track already exists
                logger.debug(f"Video track '{track_name}' already exists")
            except exceptions.TrackNotFound:
                # Track doesn't exist, create new track
                script.add_track(draft.Track_type.video, track_name=track_name, relative_index=relative_index)
                logger.debug(f"Created new video track '{track_name}'")
        else:
            script.add_track(draft.Track_type.video, relative_index=relative_index)
            logger.debug("Added video track with default name")

        # Add mask effect (requires script object)
        if mask_type:
            try:
                if IS_CAPCUT_ENV:
                    mask_type_enum = getattr(draft.CapCutMaskType, mask_type)
                else:
                    mask_type_enum = getattr(draft.MaskType, mask_type)
                video_segment.add_mask(
                    script,
                    mask_type_enum,
                    center_x=mask_center_x,
                    center_y=mask_center_y,
                    size=mask_size,
                    rotation=mask_rotation,
                    feather=mask_feather,
                    invert=mask_invert,
                    rect_width=mask_rect_width,
                    round_corner=mask_round_corner
                )
                logger.debug(f"Added mask effect: {mask_type}")
            except Exception as e:
                raise ValueError(f"{e}, Unsupported mask type {mask_type}, supported types include: {', '.join([mask.name for mask in draft.MaskType])}") from e

        # Add filter effect
        if filter_type:
            try:
                filter_type_enum = getattr(draft.FilterType, filter_type)
                video_segment.add_filter(filter_type_enum, filter_intensity)
                logger.debug(f"Added filter effect: {filter_type}")
            except Exception as e:
                raise ValueError(f"Unsupported filter type {filter_type}, supported types include: linear, mirror, circle, rectangle, heart, star") from e

        # Add background blur effect
        if background_blur is not None:
            # Validate if background blur level is valid
            if background_blur not in [1, 2, 3, 4]:
                raise ValueError(f"Invalid background blur level: {background_blur}, valid values are: 1, 2, 3, 4")

            # Map blur level to specific blur values
            blur_values = {
                1: 0.0625,  # Light blur
                2: 0.375,   # Medium blur
                3: 0.75,    # Strong blur
                4: 1.0      # Maximum blur
            }

            # Add background blur
            video_segment.add_background_filling("blur", blur=blur_values[background_blur])
            logger.debug(f"Added background blur: level {background_blur}")

        # Add video segment to track
        script.add_segment(video_segment, track_name=track_name)
        logger.debug("Added video segment to track")

    # Use retry mechanism to handle concurrent updates
    success = update_draft_with_retry(draft_id, modify_draft)

    if not success:
        error_msg = f"Failed to update draft {draft_id} after multiple retries due to concurrent modifications"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    logger.info(f"Successfully added video track to draft {draft_id}")

    return {
        "draft_id": draft_id,
        # "draft_url": generate_draft_url(draft_id)
    }
