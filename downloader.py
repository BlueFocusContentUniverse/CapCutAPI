import os
import shutil
import time

import requests
from requests.exceptions import RequestException, Timeout


def download_file(url: str, local_filename, max_retries=3, timeout=180):
    # 检查是否是本地文件路径
    if os.path.exists(url) and os.path.isfile(url):
        # 是本地文件，直接复制
        directory = os.path.dirname(local_filename)

        # 创建目标目录（如果不存在）
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
            print(f"Created directory: {directory}")

        print(f"Copying local file: {url} to {local_filename}")
        start_time = time.time()

        # 复制文件
        shutil.copy2(url, local_filename)

        print(f"Copy completed in {time.time()-start_time:.2f} seconds")
        print(f"File saved as: {os.path.abspath(local_filename)}")
        return True

    # 原有的下载逻辑
    # Extract directory part
    directory = os.path.dirname(local_filename)

    retries = 0
    while retries < max_retries:
        try:
            if retries > 0:
                wait_time = 2**retries  # Exponential backoff strategy
                print(
                    f"Retrying in {wait_time} seconds... (Attempt {retries+1}/{max_retries})"
                )
                time.sleep(wait_time)

            print(f"Downloading file: {local_filename}")
            start_time = time.time()

            # Create directory (if it doesn't exist)
            if directory and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
                print(f"Created directory: {directory}")

            # Add headers
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }

            with requests.get(
                url, stream=True, timeout=timeout, headers=headers
            ) as response:
                response.raise_for_status()

                total_size = int(response.headers.get("content-length", 0))
                block_size = 1024

                with open(local_filename, "wb") as file:
                    bytes_written = 0
                    for chunk in response.iter_content(block_size):
                        if chunk:
                            file.write(chunk)
                            bytes_written += len(chunk)

                            if total_size > 0:
                                progress = bytes_written / total_size * 100
                                # For frequently updated progress, consider using logger.debug or more granular control to avoid large log files
                                # Or only output progress to console, not write to file
                                print(
                                    f"\r[PROGRESS] {progress:.2f}% ({bytes_written/1024:.2f}KB/{total_size/1024:.2f}KB)",
                                    end="",
                                )
                                # Avoid printing too much progress information in log files

                if total_size > 0:
                    # print() # Original newline
                    pass
                print(f"Download completed in {time.time()-start_time:.2f} seconds")
                print(f"File saved as: {os.path.abspath(local_filename)}")
                return True

        except Timeout:
            print(f"Download timed out after {timeout} seconds")
        except RequestException as e:
            print(f"Request failed: {e}")
        except Exception as e:
            print(f"Unexpected error during download: {e}")

        retries += 1

    print(f"Download failed after {max_retries} attempts for URL: {url}")
    return False
