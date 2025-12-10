"""
COS (Tencent Cloud Object Storage) client utility for managing remote video files.
"""

import logging
import os
from typing import List, Optional
from urllib.parse import urlparse

from qcloud_cos import CosConfig, CosS3Client

logger = logging.getLogger(__name__)


class COSClient:
    """Wrapper for Tencent Cloud Object Storage operations."""

    def __init__(self):
        """Initialize COS client from configuration."""
        self.client: Optional[CosS3Client] = None
        self.bucket_name: Optional[str] = None
        self.region: Optional[str] = None

        # Try to initialize from config
        try:
            secret_id = os.getenv("COS_SECRET_ID")
            secret_key = os.getenv("COS_SECRET_KEY")
            region = os.getenv("COS_REGION", "ap-guangzhou")
            bucket_name = os.getenv("COS_BUCKET_NAME")

            if not secret_id or not secret_key or not bucket_name:
                logger.warning(
                    "Incomplete COS configuration. Required: access_key_id, access_key_secret, bucket_name. "
                    "COS operations will be disabled."
                )
                return

            config = CosConfig(
                Region=region,
                SecretId=secret_id,
                SecretKey=secret_key,
            )

            self.client = CosS3Client(config)
            self.bucket_name = bucket_name
            self.region = region

            logger.info(
                f"COS client initialized successfully for bucket: {bucket_name}, region: {region}"
            )

        except Exception as e:
            logger.error(f"Failed to initialize COS client: {e}")
            self.client = None

    def is_available(self) -> bool:
        """Check if COS client is properly configured and available."""
        return self.client is not None and self.bucket_name is not None

    def _parse_object_key_from_url(self, oss_url: str) -> Optional[str]:
        """
        Extract object key from OSS URL.

        Args:
            oss_url: Full URL to the object (e.g., https://bucket-name.cos.ap-guangzhou.myqcloud.com/path/to/file.mp4)

        Returns:
            Object key (path) or None if parsing fails
        """
        try:
            parsed = urlparse(oss_url)
            # Remove leading slash from path
            object_key = parsed.path.lstrip("/")
            if not object_key:
                logger.warning(f"Could not extract object key from URL: {oss_url}")
                return None
            return object_key
        except Exception as e:
            logger.error(f"Failed to parse object key from URL {oss_url}: {e}")
            return None

    def upload_file(
        self,
        local_file_path: str,
        object_key: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> Optional[str]:
        """
        Upload a file to COS.

        Args:
            local_file_path: Path to the local file to upload
            object_key: Object key (path) in COS. If None, uses the filename
            content_type: Content type of the file. If None, auto-detects based on extension

        Returns:
            CDN URL of the uploaded file, or None if upload fails
        """
        if not self.is_available():
            logger.warning("COS client not available, cannot upload file")
            return None

        if not os.path.exists(local_file_path):
            logger.error(f"Local file does not exist: {local_file_path}")
            return None

        try:
            # Generate object key if not provided
            if object_key is None:
                object_key = os.path.basename(local_file_path)

            # Auto-detect content type if not provided
            if content_type is None:
                ext = os.path.splitext(local_file_path)[1].lower()
                content_type_map = {
                    ".zip": "application/zip",
                    ".mp4": "video/mp4",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".png": "image/png",
                    ".json": "application/json",
                }
                content_type = content_type_map.get(ext, "application/octet-stream")

            logger.info(f"Uploading file to COS: {local_file_path} -> {object_key}")

            # Upload file
            with open(local_file_path, "rb") as fp:
                self.client.put_object(
                    Bucket=self.bucket_name,
                    Body=fp,
                    Key=object_key,
                    ContentType=content_type,
                )

            # Generate CDN URL
            cdn_domain = os.getenv("COS_CDN_DOMAIN")
            if cdn_domain:
                # Use CDN domain if configured
                cdn_url = f"https://{cdn_domain}/{object_key}"
            else:
                # Use default COS URL
                cdn_url = f"https://{self.bucket_name}.cos.{self.region}.myqcloud.com/{object_key}"

            logger.info(f"Successfully uploaded file to COS: {cdn_url}")
            return cdn_url

        except Exception as e:
            logger.error(f"Failed to upload file to COS ({local_file_path}): {e}")
            return None

    def delete_object_from_url(self, oss_url: str) -> bool:
        """
        Delete an object from COS using its full URL.

        Args:
            oss_url: Full URL to the object to delete

        Returns:
            True if deletion succeeded, False otherwise
        """
        if not self.is_available():
            logger.warning("COS client not available, cannot delete object")
            return False

        if not oss_url:
            logger.warning("Empty OSS URL provided")
            return False

        try:
            object_key = self._parse_object_key_from_url(oss_url)
            if not object_key:
                return False

            logger.info(
                f"Deleting object from COS: bucket={self.bucket_name}, key={object_key}"
            )

            self.client.delete_object(Bucket=self.bucket_name, Key=object_key)

            # COS returns 204 for successful deletion
            logger.info(f"Successfully deleted object: {object_key}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete object from COS (url={oss_url}): {e}")
            return False

    def delete_objects_batch(self, oss_urls: List[str]) -> dict:
        """
        Delete multiple objects from COS in batch.

        Args:
            oss_urls: List of full URLs to objects to delete

        Returns:
            Dict with 'success_count', 'failed_count', and 'errors' list
        """
        if not self.is_available():
            logger.warning("COS client not available, cannot delete objects")
            return {
                "success_count": 0,
                "failed_count": len(oss_urls),
                "errors": ["COS client not configured"],
            }

        if not oss_urls:
            return {"success_count": 0, "failed_count": 0, "errors": []}

        # Parse all URLs to get object keys
        objects_to_delete = []
        parse_errors = []

        for url in oss_urls:
            object_key = self._parse_object_key_from_url(url)
            if object_key:
                objects_to_delete.append({"Key": object_key})
            else:
                parse_errors.append(f"Failed to parse URL: {url}")

        if not objects_to_delete:
            logger.warning("No valid object keys found to delete")
            return {
                "success_count": 0,
                "failed_count": len(oss_urls),
                "errors": parse_errors,
            }

        try:
            logger.info(f"Deleting {len(objects_to_delete)} objects from COS in batch")

            response = self.client.delete_objects(
                Bucket=self.bucket_name,
                Delete={
                    "Object": objects_to_delete,
                    "Quiet": "false",  # Get detailed response
                },
            )

            # Parse response
            deleted = response.get("Deleted", [])
            errors = response.get("Error", [])

            success_count = len(deleted)
            failed_count = len(errors) + len(parse_errors)

            error_messages = parse_errors + [
                f"{err.get('Key', 'unknown')}: {err.get('Message', 'unknown error')}"
                for err in errors
            ]

            logger.info(
                f"Batch deletion completed: {success_count} succeeded, {failed_count} failed"
            )

            return {
                "success_count": success_count,
                "failed_count": failed_count,
                "errors": error_messages,
            }

        except Exception as e:
            logger.error(f"Failed to delete objects in batch: {e}")
            return {
                "success_count": 0,
                "failed_count": len(oss_urls),
                "errors": [str(e), *parse_errors],
            }


# Global COS client instance
_cos_client: Optional[COSClient] = None


def get_cos_client() -> COSClient:
    """Get or create the global COS client instance."""
    global _cos_client
    if _cos_client is None:
        _cos_client = COSClient()
    return _cos_client
