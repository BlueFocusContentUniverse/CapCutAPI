import logging

from flask import Blueprint, jsonify, request

from logging_utils import api_endpoint_logger
from services.add_video_keyframe_impl import add_video_keyframe_impl
from services.add_video_track import add_video_track

logger = logging.getLogger(__name__)
bp = Blueprint("video", __name__)


@bp.route("/add_video", methods=["POST"])
@api_endpoint_logger
def add_video():
    data = request.get_json()

    draft_folder = data.get("draft_folder")
    video_url = data.get("video_url")
    start = data.get("start", 0)
    end = data.get("end", 0)
    mode = data.get("mode", "cover")
    target_duration = data.get("target_duration")
    draft_id = data.get("draft_id")
    transform_y = data.get("transform_y", 0)
    scale_x = data.get("scale_x", 1)
    scale_y = data.get("scale_y", 1)
    transform_x = data.get("transform_x", 0)
    speed = data.get("speed", 1.0)
    target_start = data.get("target_start", 0)
    track_name = data.get("track_name", "video_main")
    relative_index = data.get("relative_index", 0)
    duration = data.get("duration")
    transition = data.get("transition")
    transition_duration = data.get("transition_duration", 0.5)
    volume = data.get("volume", 1.0)
    intro_animation = data.get("intro_animation")
    intro_animation_duration = data.get("intro_animation_duration", 0.5)
    outro_animation = data.get("outro_animation")
    outro_animation_duration = data.get("outro_animation_duration", 0.5)
    combo_animation = data.get("combo_animation")
    combo_animation_duration = data.get("combo_animation_duration", 0.5)
    mask_type = data.get("mask_type")
    mask_center_x = data.get("mask_center_x", 0.5)
    mask_center_y = data.get("mask_center_y", 0.5)
    mask_size = data.get("mask_size", 1.0)
    mask_rotation = data.get("mask_rotation", 0.0)
    mask_feather = data.get("mask_feather", 0.0)
    mask_invert = data.get("mask_invert", False)
    mask_rect_width = data.get("mask_rect_width")
    mask_round_corner = data.get("mask_round_corner")
    filter_type = data.get("filter_type")
    filter_intensity = data.get("filter_intensity", 100.0)
    fade_in_duration = data.get("fade_in_duration", 0.0)
    fade_out_duration = data.get("fade_out_duration", 0.0)

    background_blur = data.get("background_blur")

    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    if not video_url:
        result["error"] = "Hi, the required parameters 'video_url' are missing."
        return jsonify(result)

    try:
        draft_result = add_video_track(
            draft_folder=draft_folder,
            video_url=video_url,
            start=start,
            end=end,
            mode=mode,
            target_duration=target_duration,
            target_start=target_start,
            draft_id=draft_id,
            transform_y=transform_y,
            scale_x=scale_x,
            scale_y=scale_y,
            transform_x=transform_x,
            speed=speed,
            track_name=track_name,
            relative_index=relative_index,
            duration=duration,
            intro_animation=intro_animation,
            intro_animation_duration=intro_animation_duration,
            outro_animation=outro_animation,
            outro_animation_duration=outro_animation_duration,
            combo_animation=combo_animation,
            combo_animation_duration=combo_animation_duration,
            transition=transition,
            transition_duration=transition_duration,
            volume=volume,
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
            fade_in_duration=fade_in_duration,
            fade_out_duration=fade_out_duration,
            background_blur=background_blur
        )

        result["success"] = True
        result["output"] = draft_result
        return jsonify(result)

    except Exception as e:
        result["error"] = f"Error occurred while processing video: {e!s}."
        return jsonify(result)


@bp.route("/batch_add_videos", methods=["POST"])
@api_endpoint_logger
def batch_add_videos():
    data = request.get_json()

    draft_folder = data.get("draft_folder")
    draft_id = data.get("draft_id")
    videos = data.get("videos", [])

    # Common parameters that apply to all videos
    transform_y = data.get("transform_y", 0)
    scale_x = data.get("scale_x", 1)
    scale_y = data.get("scale_y", 1)
    transform_x = data.get("transform_x", 0)
    track_name = data.get("track_name", "video_main")
    relative_index = data.get("relative_index", 0)
    transition = data.get("transition")
    transition_duration = data.get("transition_duration", 0.5)
    volume = data.get("volume", 1.0)
    intro_animation = data.get("intro_animation")
    intro_animation_duration = data.get("intro_animation_duration", 0.5)
    outro_animation = data.get("outro_animation")
    outro_animation_duration = data.get("outro_animation_duration", 0.5)
    combo_animation = data.get("combo_animation")
    combo_animation_duration = data.get("combo_animation_duration", 0.5)
    mask_type = data.get("mask_type")
    mask_center_x = data.get("mask_center_x", 0.5)
    mask_center_y = data.get("mask_center_y", 0.5)
    mask_size = data.get("mask_size", 1.0)
    mask_rotation = data.get("mask_rotation", 0.0)
    mask_feather = data.get("mask_feather", 0.0)
    mask_invert = data.get("mask_invert", False)
    mask_rect_width = data.get("mask_rect_width")
    mask_round_corner = data.get("mask_round_corner")
    filter_type = data.get("filter_type")
    filter_intensity = data.get("filter_intensity", 100.0)
    fade_in_duration = data.get("fade_in_duration", 0.0)
    fade_out_duration = data.get("fade_out_duration", 0.0)
    background_blur = data.get("background_blur")

    result = {
        "success": False,
        "output": [],
        "error": ""
    }

    if not videos:
        result["error"] = "Hi, the required parameter 'videos' is missing or empty."
        return jsonify(result)

    try:
        outputs = []
        for idx, video in enumerate(videos):
            video_url = video.get("video_url")
            start = video.get("start", 0)
            end = video.get("end", 0)
            target_start = video.get("target_start", 0)
            mode=video.get("mode", "cover")
            target_duration = video.get("target_duration", None)
            duration = video.get("duration", None)
            speed = video.get("speed", 1.0)

            if not video_url:
                logger.warning(f"Video at index {idx} is missing 'video_url', skipping.")
                continue

            draft_result = add_video_track(
                draft_folder=draft_folder,
                video_url=video_url,
                start=start,
                end=end,
                mode=mode,
                target_duration=target_duration,
                target_start=target_start,
                draft_id=draft_id,
                transform_y=transform_y,
                scale_x=scale_x,
                scale_y=scale_y,
                transform_x=transform_x,
                speed=speed,
                track_name=track_name,
                relative_index=relative_index,
                duration=duration,
                intro_animation=intro_animation,
                intro_animation_duration=intro_animation_duration,
                outro_animation=outro_animation,
                outro_animation_duration=outro_animation_duration,
                combo_animation=combo_animation,
                combo_animation_duration=combo_animation_duration,
                transition=transition,
                transition_duration=transition_duration,
                volume=volume,
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
                fade_in_duration=fade_in_duration,
                fade_out_duration=fade_out_duration,
                background_blur=background_blur
            )

            outputs.append({
                "video_url": video_url,
                "result": draft_result
            })

            # Update draft_id for subsequent videos
            draft_id = draft_result

        result["success"] = True
        result["output"] = outputs
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error occurred while processing batch videos: {e!s}", exc_info=True)
        result["error"] = f"Error occurred while processing batch videos: {e!s}."
        return jsonify(result)


@bp.route("/add_video_keyframe", methods=["POST"])
@api_endpoint_logger
def add_video_keyframe():
    data = request.get_json()

    draft_id = data.get("draft_id")
    track_name = data.get("track_name", "video_main")

    property_type = data.get("property_type", "alpha")
    time = data.get("time", 0.0)
    value = data.get("value", "1.0")

    property_types = data.get("property_types")
    times = data.get("times")
    values = data.get("values")

    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    try:
        draft_result = add_video_keyframe_impl(
            draft_id=draft_id,
            track_name=track_name,
            property_type=property_type,
            time=time,
            value=value,
            property_types=property_types,
            times=times,
            values=values
        )

        result["success"] = True
        result["output"] = draft_result
        return jsonify(result)

    except Exception as e:
        result["error"] = f"Error occurred while adding keyframe: {e!s}."
        return jsonify(result)


