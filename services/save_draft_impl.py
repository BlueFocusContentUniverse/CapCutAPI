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
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Literal, Optional, Tuple

import pyJianYingDraft as draft
from downloader import download_file
from draft_cache import get_from_cache_with_version
from repositories.draft_archive_repository import get_postgres_archive_storage
from repositories.draft_repository import get_postgres_storage
from services.get_duration_impl import get_video_duration

# Import configuration
from settings import IS_CAPCUT_ENV
from util.cos_client import get_cos_client
from util.helpers import is_windows_path, zip_draft

ARCHIVE_CALLBACK_URL = os.getenv("ARCHIVE_CALLBACK_URL", "")
# db0 = notification/draft_archive, db1 = token
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL") or f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', '6379')}/{os.getenv('CELERY_REDIS_DB', '2')}"


# Celery 应用（延迟初始化，线程安全）
_celery_app = None
_celery_lock = threading.RLock()


def get_celery_app():
    """获取 Celery 应用（线程安全的单例）"""
    global _celery_app
    
    # 快速路径：无锁检查
    if _celery_app is not None:
        return _celery_app
    
    # 慢速路径：加锁初始化
    with _celery_lock:
        # Double-checked locking
        if _celery_app is None:
            try:
                from celery import Celery
                _celery_app = Celery(
                    "draft_archive",
                    broker=CELERY_BROKER_URL,
                    backend=CELERY_BROKER_URL
                )
                _celery_app.conf.update(
                    task_serializer="json",
                    accept_content=["json"],
                    result_serializer="json",
                )
                logger.info(f"Celery app initialized, broker: {CELERY_BROKER_URL[:50]}...")
            except Exception as e:
                logger.warning(f"Failed to initialize Celery app: {e}")
                return None
    
    return _celery_app


# --- Get your Logger instance ---
# The name here must match the logger name you configured in app.py
logger = logging.getLogger("uvicorn")


# ========== 辅助函数：时间格式化 ==========
def format_seconds(microseconds: int) -> str:
    """将微秒转换为格式化的秒数字符串

    Args:
        microseconds: 微秒数

    Returns:
        格式化的秒数字符串，例如 "25.50秒"
    """
    return f"{microseconds / 1e6:.2f}秒"


# Define task status enumeration type
TaskStatus = Literal["initialized", "processing", "completed", "failed", "not_found"]


def _get_image_metadata(remote_url: str) -> Tuple[int, int]:
    try:
        command = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
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


def build_asset_path(
    draft_folder: str, draft_id: str, asset_type: str, material_name: str
) -> str:
    """
    Build asset file path
    :param draft_folder: Draft folder path
    :param draft_id: Draft ID
    :param asset_type: Asset type (audio, image, video)
    :param material_name: Material name
    :return: Built path
    """
    if is_windows_path(draft_folder):
        if os.name == "nt":  # 'nt' for Windows
            draft_real_path = os.path.join(
                draft_folder, draft_id, "assets", asset_type, material_name
            )
        else:
            windows_drive, windows_path = re.match(
                r"([a-zA-Z]:)(.*)", draft_folder
            ).groups()
            parts = [p for p in windows_path.split("\\") if p]
            draft_real_path = os.path.join(
                windows_drive, *parts, draft_id, "assets", asset_type, material_name
            )
            draft_real_path = draft_real_path.replace("/", "\\")
    else:
        draft_real_path = os.path.join(
            draft_folder, draft_id, "assets", asset_type, material_name
        )
    return draft_real_path


def save_draft_background(
    draft_id: str,
    draft_folder: Optional[str],
    archive_id: str,
    draft_version: Optional[int] = None,
    archive_name: Optional[str] = None,
):
    """Background save draft to OSS

    Args:
        draft_id: Draft ID
        draft_folder: Draft folder path (optional)
        archive_id: Archive ID for tracking progress
        draft_version: Specific version to retrieve (optional). If None, uses current version.
        archive_name: Optional custom archive name (optional). If provided, will be used instead of draft_id in asset paths and folder names.
    """
    archive_storage = get_postgres_archive_storage()

    try:
        # Get draft information based on version parameter
        if draft_version is not None:
            # Retrieve specific version from PostgreSQL
            from repositories.draft_repository import get_postgres_storage

            pg_storage = get_postgres_storage()
            script = pg_storage.get_draft_version(draft_id, draft_version)
            if script is None:
                error_msg = f"Draft {draft_id} version {draft_version} does not exist in storage"
                archive_storage.update_archive(
                    archive_id,
                    progress=0.0,
                    downloaded_files=0,
                    total_files=0,
                    message=error_msg,
                    draft_version=draft_version,
                )
                logger.error(f"{error_msg}, archive {archive_id} failed.")
                return
            # Use the specified version
            actual_version = draft_version
            logger.info(
                f"Successfully retrieved draft {draft_id} version {draft_version} from storage."
            )
        else:
            # Get current version draft information from cache (Redis first, fallback to PostgreSQL)
            cache_result = get_from_cache_with_version(draft_id)
            if cache_result is None:
                error_msg = f"Draft {draft_id} does not exist in cache (Redis or PostgreSQL)"
                archive_storage.update_archive(
                    archive_id,
                    progress=0.0,
                    downloaded_files=0,
                    total_files=0,
                    message=error_msg,
                    draft_version=0,  # 0 表示草稿不存在，无法获取版本号
                )
                logger.error(f"{error_msg}, archive {archive_id} failed.")
                return
            script, actual_version = cache_result
            
            # Update archive with draft version info
            archive_storage.update_archive(
                archive_id,
                progress=0.0,
                downloaded_files=0,
                total_files=0,
                draft_version=actual_version,
            )
            logger.info(
                f"Successfully retrieved draft {draft_id} version {actual_version} from cache."
            )

        # Determine the folder name to use: archive_name if provided, else draft_id
        if archive_name:
            random_suffix = "".join(
                random.choices(string.ascii_lowercase + string.digits, k=2)
            )
            folder_name = f"{archive_name}_{random_suffix}"
        else:
            folder_name = draft_id
        logger.info(
            f"Using folder name: {folder_name} (archive_name: {archive_name}, draft_id: {draft_id})"
        )

        # Delete possibly existing folder
        if os.path.exists(folder_name):
            logger.warning(
                f"Deleting existing draft folder (current working directory): {folder_name}"
            )
            shutil.rmtree(folder_name)

        logger.info(f"Starting to save draft: {draft_id}")
        # Save draft to draft_archive directory
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)
        draft_archive_dir = os.path.join(project_root, "draft_archive")

        # Ensure draft_archive directory exists
        os.makedirs(draft_archive_dir, exist_ok=True)

        # Copy template directories to draft_archive if they don't exist
        # This is needed because Draft_folder expects templates in the same directory tree
        template_src_dir = os.path.join(
            current_dir, "template" if IS_CAPCUT_ENV else "template_jianying"
        )
        template_dst_dir = os.path.join(
            draft_archive_dir, "template" if IS_CAPCUT_ENV else "template_jianying"
        )
        if not os.path.exists(template_dst_dir):
            logger.info(
                f"Copying template directory to draft_archive: {template_src_dir} -> {template_dst_dir}"
            )
            shutil.copytree(template_src_dir, template_dst_dir)

        # Delete possibly existing folder in draft_archive
        draft_path_in_archive = os.path.join(draft_archive_dir, folder_name)
        if os.path.exists(draft_path_in_archive):
            logger.warning(
                f"Deleting existing draft folder in draft_archive: {draft_path_in_archive}"
            )
            shutil.rmtree(draft_path_in_archive)

        draft_folder_for_duplicate = draft.DraftFolder(draft_archive_dir)
        # Choose different template directory based on configuration
        template_dir = "template" if IS_CAPCUT_ENV else "template_jianying"
        draft_folder_for_duplicate.duplicate_as_template(template_dir, folder_name)

        # Update archive status
        archive_storage.update_archive(archive_id, progress=5.0)
        logger.info(f"Archive {archive_id} progress 5%: Updating media file metadata.")

        # update_media_metadata(script, archive_id)

        download_tasks = []

        audios = script.materials.audios
        if audios:
            for audio in audios:
                remote_url = audio.remote_url
                material_name = audio.material_name
                # Use helper function to build path
                if draft_folder:
                    audio.replace_path = build_asset_path(
                        draft_folder, folder_name, "audio", material_name
                    )
                if not remote_url:
                    logger.warning(
                        f"Audio file {material_name} has no remote_url, skipping download."
                    )
                    continue

                # Add audio download task
                download_tasks.append(
                    {
                        "type": "audio",
                        "func": download_file,
                        "args": (
                            remote_url,
                            os.path.join(
                                draft_archive_dir,
                                f"{folder_name}/assets/audio/{material_name}",
                            ),
                        ),
                        "material": audio,
                    }
                )

        # Collect video and image download tasks
        videos = script.materials.videos
        if videos:
            for video in videos:
                remote_url = video.remote_url
                material_name = video.material_name

                if video.material_type == "photo":
                    # Use helper function to build path
                    if draft_folder:
                        video.replace_path = build_asset_path(
                            draft_folder, folder_name, "image", material_name
                        )
                    if not remote_url:
                        logger.warning(
                            f"Image file {material_name} has no remote_url, skipping download."
                        )
                        continue

                    # Add image download task
                    download_tasks.append(
                        {
                            "type": "image",
                            "func": download_file,
                            "args": (
                                remote_url,
                                os.path.join(
                                    draft_archive_dir,
                                    f"{folder_name}/assets/image/{material_name}",
                                ),
                            ),
                            "material": video,
                        }
                    )

                elif video.material_type == "video":
                    # Use helper function to build path
                    if draft_folder:
                        video.replace_path = build_asset_path(
                            draft_folder, folder_name, "video", material_name
                        )
                    if not remote_url:
                        logger.warning(
                            f"Video file {material_name} has no remote_url, skipping download."
                        )
                        continue

                    # Add video download task
                    download_tasks.append(
                        {
                            "type": "video",
                            "func": download_file,
                            "args": (
                                remote_url,
                                os.path.join(
                                    draft_archive_dir,
                                    f"{folder_name}/assets/video/{material_name}",
                                ),
                            ),
                            "material": video,
                        }
                    )

        archive_storage.update_archive(
            archive_id, progress=10.0, total_files=len(download_tasks)
        )
        logger.info(
            f"Archive {archive_id} progress 10%: Collected {len(download_tasks)} download tasks in total."
        )

        # Execute all download tasks concurrently
        downloaded_paths = []
        completed_files = 0
        if download_tasks:
            logger.info(
                f"Starting concurrent download of {len(download_tasks)} files..."
            )

            # Use thread pool for concurrent downloads, maximum concurrency of 16
            with ThreadPoolExecutor(max_workers=16) as executor:
                # Submit all download tasks
                future_to_task = {
                    executor.submit(task["func"], *task["args"]): task
                    for task in download_tasks
                }

                # Wait for all tasks to complete
                for future in as_completed(future_to_task):
                    task = future_to_task[future]
                    try:
                        local_path = future.result()
                        downloaded_paths.append(local_path)

                        # Update archive status - only update completed files count
                        completed_files += 1
                        total = len(download_tasks)
                        # Download part accounts for 60% of the total progress
                        download_progress = 10 + int((completed_files / total) * 60)
                        archive_storage.update_archive(
                            archive_id,
                            downloaded_files=completed_files,
                            progress=float(download_progress),
                        )

                        logger.info(
                            f"Archive {archive_id}: Successfully downloaded {task['type']} file, progress {download_progress}."
                        )
                    except Exception as e:
                        logger.error(
                            f"Archive {archive_id}: Download {task['type']} file failed: {e!s}",
                            exc_info=True,
                        )
                        # Continue processing other files, don't interrupt the entire process

            logger.info(
                f"Archive {archive_id}: Concurrent download completed, downloaded {len(downloaded_paths)} files in total."
            )

        # Update archive status - Start saving draft information
        archive_storage.update_archive(archive_id, progress=70.0)
        logger.info(f"Archive {archive_id} progress 70%: Saving draft information.")

        script.dump(os.path.join(draft_archive_dir, f"{folder_name}/draft_info.json"))
        logger.info(
            f"Draft information has been saved to {os.path.join(draft_archive_dir, folder_name)}/draft_info.json."
        )

        draft_url = ""

        # Update archive status - Start compressing draft
        archive_storage.update_archive(archive_id, progress=80.0)
        logger.info(f"Archive {archive_id} progress 80%: Compressing draft files.")

        # Compress the entire draft directory
        draft_dir_path = os.path.join(draft_archive_dir, folder_name)
        zip_path = zip_draft(folder_name, draft_dir_path)
        logger.info(
            f"Draft directory {draft_dir_path} has been compressed to {zip_path}."
        )

        # Update archive status - Start uploading to OSS
        archive_storage.update_archive(archive_id, progress=90.0)
        logger.info(f"Archive {archive_id} progress 90%: Uploading to cloud storage.")

        # Upload to COS and get CDN URL
        cos_client = get_cos_client()
        if not cos_client.is_available():
            logger.error("COS client not available, cannot upload draft")
            raise Exception("Cloud storage service is not available")

        # Generate object key with draft_id and version for better organization
        object_key = (
            f"draft_archives/{draft_id}/v{actual_version}/{os.path.basename(zip_path)}"
        )
        draft_url = cos_client.upload_file(zip_path, object_key=object_key)

        if not draft_url:
            logger.error(f"Failed to upload draft {draft_id} to COS")
            raise Exception("Failed to upload draft to cloud storage")

        logger.info(f"Draft archive has been uploaded to COS, CDN URL: {draft_url}")

        # Clean up temporary files
        try:
            # Remove draft folder using draft_folder_for_duplicate.remove()
            draft_folder_for_duplicate.remove(folder_name)
            logger.info(
                f"Cleaned up temporary draft folder: {os.path.join(draft_archive_dir, folder_name)}"
            )
        except FileNotFoundError:
            # Folder might already be removed or doesn't exist
            logger.warning(
                f"Draft folder {folder_name} not found for cleanup, may already be removed"
            )
        except Exception as e:
            logger.error(f"Failed to remove draft folder {folder_name}: {e}")

        # Clean up zip file after successful upload
        if os.path.exists(zip_path):
            os.remove(zip_path)
            logger.info(f"Cleaned up temporary zip file: {zip_path}")

        # Update archive status - Completed
        archive_storage.update_archive(
            archive_id,
            progress=100.0,
            download_url=draft_url,
            message="Draft creation completed successfully",
        )
        logger.info(f"Archive {archive_id} completed, draft URL: {draft_url}")
        return draft_url

    except Exception as e:
        # Update archive status - Failed
        error_msg = f"Failed to save draft: {e!s}"
        archive_storage.update_archive(archive_id, message=error_msg)
        logger.error(
            f"Saving draft {draft_id} archive {archive_id} failed: {e!s}", exc_info=True
        )
        return ""


def save_draft_impl(
    draft_id: str,
    draft_folder: Optional[str] = None,
    draft_version: Optional[int] = None,
    user_id: Optional[str] = None,
    user_name: Optional[str] = None,
    archive_name: Optional[str] = None,
) -> Dict[str, str]:
    """Start a background task to save the draft (via Celery worker or local thread)"""
    logger.info(
        f"Received save draft request: draft_id={draft_id}, draft_folder={draft_folder}, draft_version={draft_version}, archive_name={archive_name}"
    )
    try:
        archive_storage = get_postgres_archive_storage()

        # Check if archive already exists for this draft_id and draft_version
        existing_archive = archive_storage.get_archive_by_draft(draft_id, draft_version)

        if existing_archive and existing_archive.get("download_url"):
            # Archive already exists and has a download URL, return it immediately
            logger.info(
                f"Archive already exists for draft {draft_id} version {draft_version}, returning existing URL"
            )
            return {
                "success": True,
                "draft_url": existing_archive["download_url"],
                "archive_id": existing_archive["archive_id"],
                "message": "Draft archive already exists",
            }

        # 获取草稿数据
        if draft_version is not None:
            pg_storage = get_postgres_storage()
            script = pg_storage.get_draft_version(draft_id, draft_version)
            actual_version = draft_version
        else:
            cache_result = get_from_cache_with_version(draft_id)
            if cache_result is None:
                logger.error(f"Draft {draft_id} not found in cache or storage")
                return {"success": False, "error": f"Draft {draft_id} not found"}
            script, actual_version = cache_result

        # Create or get archive_id
        if existing_archive:
            # Archive exists but no download_url yet (possibly failed or in progress)
            archive_id = existing_archive["archive_id"]
            logger.info(
                f"Using existing archive {archive_id} for draft {draft_id} version {draft_version}"
            )
        else:
            # Create new archive record
            try:
                archive_id = archive_storage.create_archive(
                    draft_id=draft_id,
                    draft_version=actual_version,
                    user_id=user_id,
                    user_name=user_name,
                    archive_name=archive_name,
                )
                if not archive_id:
                    raise Exception("Failed to create draft archive record")
                logger.info(
                    f"Created new archive {archive_id} for draft {draft_id} version {actual_version} with archive_name={archive_name}"
                )
            except Exception as e:
                # 如果创建失败（可能是并发创建导致的重复键错误），尝试获取已存在的记录
                if "duplicate key" in str(e).lower() or "unique constraint" in str(e).lower():
                    logger.warning(f"Archive creation failed due to duplicate key, attempting to retrieve existing archive: {e}")
                    existing_archive = archive_storage.get_archive_by_draft(draft_id, actual_version)
                    if existing_archive:
                        archive_id = existing_archive["archive_id"]
                        logger.info(
                            f"Retrieved existing archive {archive_id} for draft {draft_id} version {actual_version}"
                        )
                    else:
                        raise Exception(f"Failed to create archive and could not retrieve existing one: {e}") from e
                else:
                    raise

        # 使用 Celery 归档，任务执行结果通过回调接口异步通知
        return _invoke_celery_archive(
            draft_id=draft_id,
            draft_folder=draft_folder,
            archive_id=archive_id,
            draft_version=actual_version,
            archive_name=archive_name,
            script=script,
        )

    except Exception as e:
        logger.error(
            f"Failed to start save draft task {draft_id}: {e!s}", exc_info=True
        )
        return {"success": False, "error": str(e)}


# Celery 任务名称
CELERY_TASK_NAME = "tasks.archive_draft"


def _invoke_celery_archive(
    draft_id: str,
    draft_folder: Optional[str],
    archive_id: str,
    draft_version: int,
    archive_name: Optional[str],
    script,
) -> Dict[str, str]:
    """通过 Celery 执行草稿打包
    
    Celery 没有 payload 大小限制（消息通过 Redis 传递），
    但为了性能考虑，建议 draft_content 不要太大
    """
    # 生成文件夹名称
    if archive_name:
        folder_name = f"{archive_name}_{uuid.uuid4().hex[:4]}"
    else:
        folder_name = draft_id

    # 准备任务参数
    draft_content = json.loads(script.dumps())
    
    # 构建 callback_url: 优先 ARCHIVE_CALLBACK_URL，其次 API_BASE_URL
    api_base = ARCHIVE_CALLBACK_URL or os.getenv("API_BASE_URL", f"http://localhost:{os.getenv('PORT', '9000')}")
    callback_url = f"{api_base.rstrip('/')}/api/draft_archives/callback" if not ARCHIVE_CALLBACK_URL else ARCHIVE_CALLBACK_URL
    
    task_kwargs = {
        "archive_id": archive_id,
        "draft_id": draft_id,
        "draft_version": draft_version,
        "draft_content": draft_content,
        "folder_name": folder_name,
        "callback_url": callback_url
    }

    try:
        celery_app = get_celery_app()
        if celery_app is None:
            raise Exception(
                "Celery app not available. Check CELERY_BROKER_URL configuration."
            )

        # 任务执行结果通过 callback_url 异步回调通知
        result = celery_app.send_task(
            CELERY_TASK_NAME,
            kwargs=task_kwargs,
            queue="draft_archive"
        )
        
        logger.info(
            f"Successfully sent Celery task for archive {archive_id}, draft {draft_id}, task_id={result.id}"
        )
        return {
            "success": True,
            "archive_id": archive_id,
            "message": "Draft archiving started via Celery",
            "task_id": result.id
        }

    except Exception as e:
        logger.error(f"Failed to send Celery task for archive {archive_id}: {e!s}")
        # 回退到本地线程
        return _fallback_to_local_thread(
            draft_id, draft_folder, archive_id, draft_version, archive_name
        )


def _fallback_to_local_thread(
    draft_id: str,
    draft_folder: Optional[str],
    archive_id: str,
    draft_version: int,
    archive_name: Optional[str],
) -> Dict[str, str]:
    """回退到本地线程处理草稿打包"""
    logger.warning(f"Falling back to local thread for archive {archive_id}")
    thread = threading.Thread(
        target=save_draft_background,
        args=(draft_id, draft_folder, archive_id, draft_version, archive_name),
        daemon=True,
    )
    thread.start()
    return {
        "success": True,
        "archive_id": archive_id,
        "message": "Draft archiving started in background (local thread)",
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
                logger.warning(
                    f"Warning: Audio file {material_name} has no remote_url, skipped."
                )
                continue

            try:
                video_command = [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=codec_type",
                    "-of",
                    "json",
                    remote_url,
                ]
                video_result = subprocess.check_output(
                    video_command, stderr=subprocess.STDOUT
                )
                video_result_str = video_result.decode("utf-8")
                # Find JSON start position (first '{')
                video_json_start = video_result_str.find("{")
                if video_json_start != -1:
                    video_json_str = video_result_str[video_json_start:]
                    video_info = json.loads(video_json_str)
                    if "streams" in video_info and len(video_info["streams"]) > 0:
                        logger.warning(
                            f"Warning: Audio file {material_name} contains video tracks, skipped its metadata update."
                        )
                        continue
            except Exception as e:
                logger.error(
                    f"Error occurred while checking if audio {material_name} contains video streams: {e!s}",
                    exc_info=True,
                )

            # Get audio duration and set it
            try:
                duration_result = get_video_duration(remote_url)
                if duration_result["success"]:
                    # Convert seconds to microseconds
                    audio.duration = int(duration_result["output"] * 1000000)
                    logger.info(
                        f"Successfully obtained audio {material_name} duration: {duration_result['output']:.2f} seconds ({audio.duration} microseconds)."
                    )

                    # Update timerange for all segments using this audio material
                    for track_name, track in script.tracks.items():
                        if track.track_type == draft.TrackType.audio:
                            for segment in track.segments:
                                if (
                                    isinstance(segment, draft.AudioSegment)
                                    and segment.material_id == audio.material_id
                                ):
                                    # Get current settings
                                    current_target = segment.target_timerange
                                    current_source = segment.source_timerange
                                    speed = segment.speed.speed

                                    # If the end time of source_timerange exceeds the new audio duration, adjust it
                                    if (
                                        current_source.end > audio.duration
                                        or current_source.end <= 0
                                    ):
                                        # Adjust source_timerange to fit the new audio duration
                                        new_source_duration = (
                                            audio.duration - current_source.start
                                        )
                                        if new_source_duration <= 0:
                                            logger.warning(
                                                f"Warning: Audio segment {segment.segment_id} start time {current_source.start} exceeds audio duration {audio.duration}, will skip this segment."
                                            )
                                            continue

                                        # Update source_timerange
                                        segment.source_timerange = draft.Timerange(
                                            current_source.start, new_source_duration
                                        )

                                        # Update target_timerange based on new source_timerange and speed
                                        new_target_duration = int(
                                            new_source_duration / speed
                                        )
                                        segment.target_timerange = draft.Timerange(
                                            current_target.start, new_target_duration
                                        )

                                        logger.info(
                                            f"Adjusted audio segment {segment.segment_id} timerange to fit the new audio duration."
                                        )
                else:
                    logger.warning(
                        f"Warning: Unable to get audio {material_name} duration: {duration_result['error']}."
                    )
            except Exception as e:
                logger.error(
                    f"Error occurred while getting audio {material_name} duration: {e!s}",
                    exc_info=True,
                )

    # Process video and image file metadata
    videos = script.materials.videos
    if not videos:
        logger.info("No video or image files found in the draft.")
    else:
        for video in videos:
            remote_url = video.remote_url
            material_name = video.material_name
            if not remote_url:
                logger.warning(
                    f"Warning: Media file {material_name} has no remote_url, skipped."
                )
                continue

            if video.material_type == "photo":
                try:
                    width, height = _get_image_metadata(remote_url)
                    video.width = width or 1920
                    video.height = height or 1080
                    logger.info(
                        f"Successfully set image {material_name} dimensions: {video.width}x{video.height}."
                    )
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
                        "-v",
                        "error",
                        "-select_streams",
                        "v:0",  # Select the first video stream
                        "-show_entries",
                        "stream=width,height,duration",
                        "-show_entries",
                        "format=duration",
                        "-of",
                        "json",
                        remote_url,
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
                            logger.info(
                                f"Successfully set video {material_name} dimensions: {video.width}x{video.height}."
                            )

                            # Set duration
                            # Prefer stream duration, if not available use format duration
                            duration = stream.get("duration") or info["format"].get(
                                "duration", "0"
                            )
                            video.duration = int(
                                float(duration) * 1000000
                            )  # Convert to microseconds
                            logger.info(
                                f"Successfully obtained video {material_name} duration: {float(duration):.2f} seconds ({video.duration} microseconds)."
                            )

                            # Update timerange for all segments using this video material
                            for track_name, track in script.tracks.items():
                                if track.track_type == draft.TrackType.video:
                                    for segment in track.segments:
                                        if (
                                            isinstance(segment, draft.VideoSegment)
                                            and segment.material_id == video.material_id
                                        ):
                                            # Get current settings
                                            current_target = segment.target_timerange
                                            current_source = segment.source_timerange
                                            speed = segment.speed.speed

                                            # If the end time of source_timerange exceeds the new video duration, adjust it
                                            if (
                                                current_source.end > video.duration
                                                or current_source.end <= 0
                                            ):
                                                # Adjust source_timerange to fit the new video duration
                                                new_source_duration = (
                                                    video.duration
                                                    - current_source.start
                                                )

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
                                                segment.source_timerange = (
                                                    draft.Timerange(
                                                        current_source.start,
                                                        new_source_duration,
                                                    )
                                                )

                                                # Update target_timerange based on new source_timerange and speed
                                                new_target_duration = int(
                                                    new_source_duration / speed
                                                )
                                                segment.target_timerange = (
                                                    draft.Timerange(
                                                        current_target.start,
                                                        new_target_duration,
                                                    )
                                                )

                                                logger.info(
                                                    f"Adjusted video segment {segment.segment_id} timerange to fit the new video duration."
                                                )
                        else:
                            logger.warning(
                                f"Warning: Unable to get video {material_name} stream information."
                            )
                            # Set default values
                            video.width = 1920
                            video.height = 1080
                    else:
                        logger.warning(
                            "Warning: Could not find JSON data in ffprobe output."
                        )
                        # Set default values
                        video.width = 1920
                        video.height = 1080
                except Exception as e:
                    logger.error(
                        f"Error occurred while getting video {material_name} information: {e!s}, using default values 1920x1080.",
                        exc_info=True,
                    )
                    # Set default values
                    video.width = 1920
                    video.height = 1080

                    # Try to get duration separately
                    try:
                        duration_result = get_video_duration(remote_url)
                        if duration_result["success"]:
                            # Convert seconds to microseconds
                            video.duration = int(duration_result["output"] * 1000000)
                            logger.info(
                                f"Successfully obtained video {material_name} duration: {duration_result['output']:.2f} seconds ({video.duration} microseconds)."
                            )
                        else:
                            logger.warning(
                                f"Warning: Unable to get video {material_name} duration: {duration_result['error']}."
                            )
                    except Exception as e2:
                        logger.error(
                            f"Error occurred while getting video {material_name} duration: {e2!s}.",
                            exc_info=True,
                        )

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
                    logger.warning(
                        f"Time range conflict between segments {track.segments[min(i, j)].segment_id} and {track.segments[later_index].segment_id} in track {track_name}, deleting the later segment"
                    )
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
            logger.info(
                f"Processing {len(track.pending_keyframes)} pending keyframes in track {track_name}..."
            )
            track.process_pending_keyframes()
            logger.info(f"Pending keyframes in track {track_name} have been processed.")


def query_script_impl(draft_id: str, force_update: bool = False):
    """
    Query draft script object, with option to force refresh media metadata

    :param draft_id: Draft ID
    :param force_update: Whether to force refresh media metadata, default is True
    :return: Script object
    """
    # Get draft information from cache (memory first, then PostgreSQL)
    script, version = get_from_cache_with_version(draft_id)
    if script is None:
        logger.warning(
            f"Draft {draft_id} does not exist in cache (memory or PostgreSQL)."
        )
        return None

    logger.info(f"Retrieved draft {draft_id} version {version} from cache.")

    # If force_update is True, force refresh media metadata
    if force_update:
        logger.info(f"Force refreshing media metadata for draft {draft_id}.")
        update_media_metadata(script)

    # Return script object
    return script
