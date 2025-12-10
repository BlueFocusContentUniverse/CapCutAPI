"""
Helper utility functions for CapCut API.
Includes color conversion, path handling, hashing, timing, and draft URL generation.
"""

import asyncio
import functools
import hashlib
import json
import os
import re
import shutil
import time

from settings.local import DRAFT_DOMAIN, IS_CAPCUT_ENV, PREVIEW_ROUTER


def hex_to_rgb(hex_color: str) -> tuple:
    """Convert hexadecimal color code to RGB tuple (range 0.0-1.0)"""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(
            [c * 2 for c in hex_color]
        )  # Handle shorthand form (e.g. #fff)
    try:
        r = int(hex_color[0:2], 16) / 255.0
        g = int(hex_color[2:4], 16) / 255.0
        b = int(hex_color[4:6], 16) / 255.0
        return (r, g, b)
    except ValueError:
        raise ValueError(f"Invalid hexadecimal color code: {hex_color}")


def is_windows_path(path):
    """Detect if the path is Windows style"""
    # Check if it starts with a drive letter (e.g. C:\) or contains Windows style separators
    return re.match(r"^[a-zA-Z]:\\|\\\\", path) is not None


def zip_draft(draft_id, draft_dir):
    """
    Compress a draft directory into a zip file.

    Args:
        draft_id: The draft identifier (used for zip filename)
        draft_dir: The directory path containing the draft to compress

    Returns:
        Path to the created zip file
    """
    current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Compress folder
    zip_dir = os.path.join(current_dir, "tmp/zip")
    os.makedirs(zip_dir, exist_ok=True)
    zip_path = os.path.join(zip_dir, f"{draft_id}.zip")
    shutil.make_archive(os.path.join(zip_dir, draft_id), "zip", draft_dir)
    return zip_path


def url_to_hash(url, length=16):
    """
    Convert URL to a fixed-length hash string (without extension)

    Parameters:
    - url: Original URL string
    - length: Length of the hash string (maximum 64, default 16)

    Returns:
    - Hash string (e.g.: 3a7f9e7d9a1b4e2d)
    """
    # Ensure URL is bytes type
    url_bytes = url.encode("utf-8")

    # Use SHA-256 to generate hash (secure and highly unique)
    hash_object = hashlib.sha256(url_bytes)

    # Truncate to specified length of hexadecimal string
    return hash_object.hexdigest()[:length]


def timing_decorator(func_name):
    """Decorator: Used to monitor function execution time"""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            print(f"[{func_name}] Starting execution...")
            try:
                result = func(*args, **kwargs)
                end_time = time.time()
                duration = end_time - start_time
                print(
                    f"[{func_name}] Execution completed, time taken: {duration:.3f} seconds"
                )
                return result
            except Exception as e:
                end_time = time.time()
                duration = end_time - start_time
                print(
                    f"[{func_name}] Execution failed, time taken: {duration:.3f} seconds, error: {e}"
                )
                raise

        return wrapper

    return decorator


def generate_draft_url(draft_id):
    return f"{DRAFT_DOMAIN}{PREVIEW_ROUTER}?draft_id={draft_id}&is_capcut={1 if IS_CAPCUT_ENV else 0}"


async def get_ffprobe_info(
    media_path: str, select_streams: str = "v:0", show_entries: list = None
) -> dict:
    """
    Run ffprobe to get media information asynchronously.

    Args:
        media_path: Path to the media file or URL
        select_streams: Stream selection specifier (default: "v:0" for first video stream)
        show_entries: List of entries to show (default: entries for video info)

    Returns:
        Parsed JSON output from ffprobe
    """
    if show_entries is None:
        show_entries = [
            "stream=width,height,duration,codec_type",
            "format=duration,format_name",
        ]

    args = ["-v", "error", "-select_streams", select_streams, "-of", "json", media_path]

    for entry in show_entries:
        args.extend(["-show_entries", entry])

    try:
        process = await asyncio.create_subprocess_exec(
            "ffprobe",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise ValueError(f"ffprobe failed with error: {stderr.decode('utf-8')}")

        result_str = stdout.decode("utf-8")
        # 查找JSON开始位置（第一个'{'）
        json_start = result_str.find("{")
        if json_start != -1:
            json_str = result_str[json_start:]
            return json.loads(json_str)
        else:
            raise ValueError(f"无法在输出中找到JSON数据: {result_str}")
    except Exception as e:
        raise ValueError(f"处理文件 {media_path} 时出错: {e}") from e


def get_extension_from_format(format_name: str, default: str) -> str:
    """
    Get file extension from ffprobe format name.
    """
    if not format_name:
        return default

    format_name = format_name.lower()

    # Common video formats
    if "mp4" in format_name:
        return ".mp4"
    if "mov" in format_name:
        return ".mov"
    if "avi" in format_name:
        return ".avi"
    if "webm" in format_name:
        return ".webm"
    if "mkv" in format_name or "matroska" in format_name:
        return ".mkv"

    # Common audio formats
    if "mp3" in format_name:
        return ".mp3"
    if "wav" in format_name:
        return ".wav"
    if "aac" in format_name:
        return ".aac"
    if "m4a" in format_name:
        return ".m4a"
    if "flac" in format_name:
        return ".flac"
    if "ogg" in format_name:
        return ".ogg"

    # Common image formats
    if "png" in format_name:
        return ".png"
    if "jpeg" in format_name or "jpg" in format_name:
        return ".jpg"
    if "gif" in format_name:
        return ".gif"
    if "webp" in format_name:
        return ".webp"

    # Fallback: use the first format name as extension if it looks like one
    first = format_name.split(",")[0].strip()
    if first and len(first) < 5:
        return f".{first}"

    return default
