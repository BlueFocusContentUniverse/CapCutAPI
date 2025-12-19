#!/usr/bin/env python3
import asyncio
import json
import logging
import os
import random
import re
import shutil
import string
import subprocess
import threading
import uuid
from typing import Dict, Literal, Optional, Tuple, Any

import pyJianYingDraft as draft
from celery import Celery

from downloader import download_file
from draft_cache import get_from_cache_with_version
from repositories.draft_archive_repository import get_postgres_archive_storage
from repositories.draft_repository import get_postgres_storage
from services.get_duration_impl import get_video_duration
from settings import IS_CAPCUT_ENV
from util.cos_client import get_cos_client
from util.helpers import is_windows_path, zip_draft

ARCHIVE_CALLBACK_URL = os.getenv("ARCHIVE_CALLBACK_URL")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL")
CELERY_APP_NAME = "draft_archive_notice"
CELERY_TASK_NAME = "tasks.archive_draft"
DRAFT_ARCHIVE_QUEUE = "draft_archive"

logger = logging.getLogger("uvicorn")

# --- Task 类型定义 ---
TaskStatus = Literal["initialized", "processing", "completed", "failed", "not_found"]

# --- Celery 单例实现 ---
_celery_app: Optional[Celery] = None
_celery_lock = threading.RLock()

def get_celery_app():
    """获取 draft_archive_notice 项目的 Celery 客户端（线程安全的延迟初始化）"""
    global _celery_app
    if _celery_app is None:
        with _celery_lock:
            if _celery_app is None:
                if not CELERY_BROKER_URL:
                    raise ValueError("CELERY_BROKER_URL environment variable is not set")
                _celery_app = Celery(
                    CELERY_APP_NAME,
                    broker=CELERY_BROKER_URL
                )
                logger.info(f"Initialized Celery client for draft_archive_notice: {CELERY_BROKER_URL}")
    return _celery_app

# --- 辅助工具函数 ---
def format_seconds(microseconds: int) -> str:
    """将微秒转换为格式化的秒数字符串

    Args:
        microseconds: 微秒数

    Returns:
        格式化的秒数字符串，例如 "25.50秒"
    """
    return f"{microseconds / 1e6:.2f}秒"

def _get_image_metadata(remote_url: str, timeout: int = 10) -> Tuple[int, int]:
    """获取远程媒体资源的宽高元数据"""
    try:
        command = [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "json",
                remote_url,
        ]
        result = subprocess.check_output(command, stderr=subprocess.STDOUT)
        result_str = result.decode("utf-8")
        json_start = result_str.find("{")
        if json_start == -1:
            raise ValueError("ffprobe did not return JSON output")

        info = json.loads(result_str[json_start:])
        streams = info.get("streams") or []
        if streams:
            stream = streams[0]
            width = int(stream.get("width", 0) or 0)
            height = int(stream.get("height", 0) or 0)
            return width, height
        return 0, 0
    except Exception as e:
        logger.warning(f"Failed to get photo metadata for {remote_url}: {e}")
        return 0, 0

# --- 草稿归档逻辑 ---
async def save_draft_impl(
    draft_id: str,
    draft_folder: str,  
    draft_version: Optional[int] = None,
    user_id: Optional[str] = None,
    user_name: Optional[str] = None,
    archive_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    发起草稿归档请求（委托给 draft_archive_notice 项目处理）
    """
    logger.info(f"Received save draft request: draft_id={draft_id}, draft_folder={draft_folder}, draft_version={draft_version}, archive_name={archive_name}")
    
    try:
        if not draft_folder:
            raise ValueError("draft_folder 是必传参数，用于设置草稿素材的 replace_path")
        
        archive_storage = get_postgres_archive_storage()

        # 1. 检查归档是否已存在且已有下载地址
        existing_archive = await archive_storage.get_archive_by_draft(draft_id, draft_version)

        if existing_archive and existing_archive.get("download_url"):
            logger.info(f"Archive already exists for draft {draft_id} version {draft_version}, returning existing URL")
            return {
                "success": True,
                "draft_url": existing_archive["download_url"],
                "archive_id": existing_archive["archive_id"],
                "message": "Draft archive already exists"
            }

        # 2. 获取草稿内容与实际版本
        if draft_version is not None:
            pg_storage = get_postgres_storage()
            script = await pg_storage.get_draft_version(draft_id, draft_version)
            if script is None:
                raise Exception(f"Draft {draft_id} version {draft_version} does not exist in storage")
            actual_version = draft_version
        else:
            result = await get_from_cache_with_version(draft_id)
            if result is None:
                raise Exception(f"Draft {draft_id} does not exist in cache (redis or PostgreSQL)")
            script, actual_version = result
        
        logger.info(f"Successfully retrieved draft {draft_id} version {actual_version}")

        # 3. 创建或获取 archive_id
        if existing_archive:
            archive_id = existing_archive["archive_id"]
            logger.info(f"Using existing archive {archive_id} for draft {draft_id} version {actual_version}")
        else:
            try:
                archive_id = await archive_storage.create_archive(
                    draft_id=draft_id,
                    draft_version=actual_version,
                    user_id=user_id,
                    user_name=user_name,
                    archive_name=archive_name,
                )
                if not archive_id:
                    raise Exception("Failed to create draft archive record")
                logger.info(f"Created new archive {archive_id} for draft {draft_id} version {actual_version}")
            except Exception as e:
                # 并发创建冲突处理：尝试重新获取已存在的记录
                if "duplicate key" in str(e).lower() or "unique constraint" in str(e).lower():
                    logger.warning(f"Archive creation failed due to duplicate key, attempting to retrieve: {e}")
                    existing_archive = await archive_storage.get_archive_by_draft(draft_id, actual_version)
                    if existing_archive:
                        archive_id = existing_archive["archive_id"]
                    else:
                        raise Exception(f"Failed to create archive and could not retrieve existing one: {e}") from e
                else:
                    raise

        # 4. 调用 Celery 归档任务
        return _invoke_celery_archive(
            draft_id=draft_id,
            draft_folder=draft_folder,
            archive_id=archive_id,
            draft_version=actual_version,
            archive_name=archive_name,
            script=script,
        )

    except Exception as e:
        logger.error(f"Failed to start save draft task {draft_id}: {e!s}", exc_info=True)
        return {"success": False, "error": str(e)}

def _invoke_celery_archive(
    draft_id: str,
    draft_folder: str,
    archive_id: str,
    draft_version: int,
    archive_name: Optional[str],
    script: Any,
) -> Dict[str, Any]:
    """
    通过 Celery 异步执行草稿打包。
    """
    # 1. 生成唯一的文件夹名称
    suffix = uuid.uuid4().hex[:4]
    folder_name = f"{archive_name}_{suffix}" if archive_name else f"{draft_id}_{suffix}"

    # 2. 序列化草稿内容
    draft_content = json.loads(script.dumps())
    
    task_payload = {
        "archive_id": archive_id,
        "draft_id": draft_id,
        "draft_version": draft_version,
        "draft_content": draft_content,
        "folder_name": folder_name,
        "draft_folder": draft_folder,
        "is_capcut": IS_CAPCUT_ENV,
        "callback_url": ARCHIVE_CALLBACK_URL
    }

    try:
        celery_app = get_celery_app()
        
        # 3. 发送任务：开启 1 次自动重试
        result = celery_app.send_task(
            CELERY_TASK_NAME,
            kwargs=task_payload,
            queue=DRAFT_ARCHIVE_QUEUE,
            retry=True,
            retry_policy={
                'max_retries': 1,      # 重试 1 次
                'interval_start': 0.5, # 间隔 0.5s
            }
        )
        
        logger.info(f"Task dispatched: archive_id={archive_id}, task_id={result.id}")
        return {
            "success": True,
            "archive_id": archive_id,
            "task_id": result.id,
            "message": "Archiving process initiated via Celery"
        }

    except Exception as e:
        logger.error(f"Failed to send Celery task for archive {archive_id}: {e!s}", exc_info=True)
        return {
            "success": False, 
            "error": f"Task queue unavailable: {str(e)}"
        }

def update_media_metadata(script, task_id=None):
    """
    Update metadata for all media files in the script (duration, width/height, etc.)

    :param script: Draft script object
    :param task_id: Optional task ID for updating task status
    :return: None
    """
    # Process audio file metadata
    audios = script.materials.audios
    if not audios:
        logger.info("No audio files found in the draft.")
    else:
        for audio in audios:
            remote_url = audio.remote_url
            material_name = audio.material_name
            if not remote_url:
                logger.warning(f"Warning: Audio file {material_name} has no remote_url, skipped.")
                continue

            try:
                video_command = [
                    "ffprobe",
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=codec_type",
                    "-of", "json",
                    remote_url
                ]
                video_result = subprocess.check_output(video_command, stderr=subprocess.STDOUT)
                video_result_str = video_result.decode("utf-8")
                # Find JSON start position (first '{')
                video_json_start = video_result_str.find("{")
                if video_json_start != -1:
                    video_json_str = video_result_str[video_json_start:]
                    video_info = json.loads(video_json_str)
                    if "streams" in video_info and len(video_info["streams"]) > 0:
                        logger.warning(f"Warning: Audio file {material_name} contains video tracks, skipped its metadata update.")
                        continue
            except Exception as e:
                logger.error(f"Error occurred while checking if audio {material_name} contains video streams: {e!s}", exc_info=True)

            # Get audio duration and set it
            try:
                duration_result = get_video_duration(remote_url)
                if duration_result["success"]:
                    # Convert seconds to microseconds
                    audio.duration = int(duration_result["output"] * 1000000)
                    logger.info(f"Successfully obtained audio {material_name} duration: {duration_result['output']:.2f} seconds ({audio.duration} microseconds).")

                    # Update timerange for all segments using this audio material
                    for track_name, track in script.tracks.items():
                        if track.track_type == draft.TrackType.audio:
                            for segment in track.segments:
                                if isinstance(segment, draft.AudioSegment) and segment.material_id == audio.material_id:
                                    # Get current settings
                                    current_target = segment.target_timerange
                                    current_source = segment.source_timerange
                                    speed = segment.speed.speed

                                    # If the end time of source_timerange exceeds the new audio duration, adjust it
                                    if current_source.end > audio.duration or current_source.end <= 0:
                                        # Adjust source_timerange to fit the new audio duration
                                        new_source_duration = audio.duration - current_source.start
                                        if new_source_duration <= 0:
                                            logger.warning(f"Warning: Audio segment {segment.segment_id} start time {current_source.start} exceeds audio duration {audio.duration}, will skip this segment.")
                                            continue

                                        # Update source_timerange
                                        segment.source_timerange = draft.Timerange(current_source.start, new_source_duration)

                                        # Update target_timerange based on new source_timerange and speed
                                        new_target_duration = int(new_source_duration / speed)
                                        segment.target_timerange = draft.Timerange(current_target.start, new_target_duration)

                                        logger.info(f"Adjusted audio segment {segment.segment_id} timerange to fit the new audio duration.")
                else:
                    logger.warning(f"Warning: Unable to get audio {material_name} duration: {duration_result['error']}.")
            except Exception as e:
                logger.error(f"Error occurred while getting audio {material_name} duration: {e!s}", exc_info=True)

    # Process video and image file metadata
    videos = script.materials.videos
    if not videos:
        logger.info("No video or image files found in the draft.")
    else:
        for video in videos:
            remote_url = video.remote_url
            material_name = video.material_name
            if not remote_url:
                logger.warning(f"Warning: Media file {material_name} has no remote_url, skipped.")
                continue

            if video.material_type == "photo":
                try:
                    width, height = _get_image_metadata(remote_url)
                    video.width = width or 1920
                    video.height = height or 1080
                    logger.info(f"Successfully set image {material_name} dimensions: {video.width}x{video.height}.")
                except Exception as e:
                    logger.error(
                        f"Failed to set image {material_name} dimensions using ffprobe: {e!s}, using default values 1920x1080.",
                        exc_info=True,
                    )
                    video.width = 1920
                    video.height = 1080

            elif video.material_type == "video":
                # Get video duration and width/height information
                try:
                    # Use ffprobe to get video information
                    command = [
                        "ffprobe",
                        "-v", "error",
                        "-select_streams", "v:0",  # Select the first video stream
                        "-show_entries", "stream=width,height,duration",
                        "-show_entries", "format=duration",
                        "-of", "json",
                        remote_url
                    ]
                    result = subprocess.check_output(command, stderr=subprocess.STDOUT)
                    result_str = result.decode("utf-8")
                    # Find JSON start position (first '{')
                    json_start = result_str.find("{")
                    if json_start != -1:
                        json_str = result_str[json_start:]
                        info = json.loads(json_str)

                        if "streams" in info and len(info["streams"]) > 0:
                            stream = info["streams"][0]
                            # Set width and height
                            video.width = int(stream.get("width", 0))
                            video.height = int(stream.get("height", 0))
                            logger.info(f"Successfully set video {material_name} dimensions: {video.width}x{video.height}.")

                            # Set duration
                            # Prefer stream duration, if not available use format duration
                            duration = stream.get("duration") or info["format"].get("duration", "0")
                            video.duration = int(float(duration) * 1000000)  # Convert to microseconds
                            logger.info(f"Successfully obtained video {material_name} duration: {float(duration):.2f} seconds ({video.duration} microseconds).")

                            # Update timerange for all segments using this video material
                            for track_name, track in script.tracks.items():
                                if track.track_type == draft.TrackType.video:
                                    for segment in track.segments:
                                        if isinstance(segment, draft.VideoSegment) and segment.material_id == video.material_id:
                                            # Get current settings
                                            current_target = segment.target_timerange
                                            current_source = segment.source_timerange
                                            speed = segment.speed.speed

                                            # If the end time of source_timerange exceeds the new video duration, adjust it
                                            if current_source.end > video.duration or current_source.end <= 0:
                                                # Adjust source_timerange to fit the new video duration
                                                new_source_duration = video.duration - current_source.start

                                                # ========== 新增：防止start超出视频时长导致黑屏 ==========
                                                if new_source_duration <= 0:
                                                    logger.error(
                                                        f"❌ 严重错误：视频片段 {segment.segment_id} 的 start={format_seconds(current_source.start)} "
                                                        f"超出或等于视频总时长 {format_seconds(video.duration)}，无法生成有效片段。\n"
                                                        f"详细信息：\n"
                                                        f"  - 素材URL: {video.remote_url}\n"
                                                        f"  - start参数: {format_seconds(current_source.start)}\n"
                                                        f"  - 视频总时长: {format_seconds(video.duration)}\n"
                                                        f"  - 计算出的素材时长: {format_seconds(new_source_duration)}（无效）\n"
                                                        f"建议检查调用参数：start应小于{format_seconds(video.duration)}"
                                                    )
                                                    # 跳过此片段，避免黑屏
                                                    continue

                                                # Update source_timerange
                                                segment.source_timerange = draft.Timerange(current_source.start, new_source_duration)

                                                # Update target_timerange based on new source_timerange and speed
                                                new_target_duration = int(new_source_duration / speed)
                                                segment.target_timerange = draft.Timerange(current_target.start, new_target_duration)

                                                logger.info(f"Adjusted video segment {segment.segment_id} timerange to fit the new video duration.")
                        else:
                            logger.warning(f"Warning: Unable to get video {material_name} stream information.")
                            # Set default values
                            video.width = 1920
                            video.height = 1080
                    else:
                        logger.warning("Warning: Could not find JSON data in ffprobe output.")
                        # Set default values
                        video.width = 1920
                        video.height = 1080
                except Exception as e:
                    logger.error(f"Error occurred while getting video {material_name} information: {e!s}, using default values 1920x1080.", exc_info=True)
                    # Set default values
                    video.width = 1920
                    video.height = 1080

                    # Try to get duration separately
                    try:
                        duration_result = get_video_duration(remote_url)
                        if duration_result["success"]:
                            # Convert seconds to microseconds
                            video.duration = int(duration_result["output"] * 1000000)
                            logger.info(f"Successfully obtained video {material_name} duration: {duration_result['output']:.2f} seconds ({video.duration} microseconds).")
                        else:
                            logger.warning(f"Warning: Unable to get video {material_name} duration: {duration_result['error']}.")
                    except Exception as e2:
                        logger.error(f"Error occurred while getting video {material_name} duration: {e2!s}.", exc_info=True)

    # After updating all segments' timerange, check if there are time range conflicts in each track, and delete the later segment in case of conflict
    logger.info("Checking track segment time range conflicts...")
    for track_name, track in script.tracks.items():
        # Use a set to record segment indices that need to be deleted
        to_remove = set()

        # Check for conflicts between all segments
        for i in range(len(track.segments)):
            # Skip if current segment is already marked for deletion
            if i in to_remove:
                continue

            for j in range(len(track.segments)):
                # Skip self-comparison and segments already marked for deletion
                if i == j or j in to_remove:
                    continue

                # Check if there is a conflict
                if track.segments[i].overlaps(track.segments[j]):
                    # Always keep the segment with the smaller index (added first)
                    later_index = max(i, j)
                    logger.warning(f"Time range conflict between segments {track.segments[min(i, j)].segment_id} and {track.segments[later_index].segment_id} in track {track_name}, deleting the later segment")
                    to_remove.add(later_index)

        # Delete marked segments from back to front to avoid index change issues
        for index in sorted(to_remove, reverse=True):
            track.segments.pop(index)

    # After updating all segments' timerange, recalculate the total duration of the script
    max_duration = 0
    for track_name, track in script.tracks.items():
        for segment in track.segments:
            max_duration = max(max_duration, segment.end)
    script.duration = max_duration
    logger.info(f"Updated script total duration to: {script.duration} microseconds.")

    # Process all pending keyframes in tracks
    logger.info("Processing pending keyframes...")
    for track_name, track in script.tracks.items():
        if hasattr(track, "pending_keyframes") and track.pending_keyframes:
            logger.info(f"Processing {len(track.pending_keyframes)} pending keyframes in track {track_name}...")
            track.process_pending_keyframes()
            logger.info(f"Pending keyframes in track {track_name} have been processed.")


async def query_script_impl(draft_id: str, force_update: bool = False):
    """
    Query draft script object, with option to force refresh media metadata

    :param draft_id: Draft ID
    :param force_update: Whether to force refresh media metadata, default is True
    :return: Script object
    """
    # Get draft information from cache (memory first, then PostgreSQL)
    result = await get_from_cache_with_version(draft_id)
    if result is None:
        logger.warning(f"Draft {draft_id} does not exist in cache (memory or PostgreSQL).")
        return None
    
    script, version = result

    logger.info(f"Retrieved draft {draft_id} version {version} from cache.")

    # If force_update is True, force refresh media metadata
    if force_update:
        logger.info(f"Force refreshing media metadata for draft {draft_id}.")
        update_media_metadata(script)

    # Return script object
    return script
