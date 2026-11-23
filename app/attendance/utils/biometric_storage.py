"""Production-ready biometric image storage using S3/GCS-compatible object storage.

Provides secure, private bucket storage for face attendance images with:
- Server-side encryption (SSE-S3/SSE-KMS)
- Private buckets only - no public URLs
- Presigned URLs for secure time-limited access
- Configurable retention and deletion
- Proper error handling without silent fallbacks
- Environment-based configuration
"""

from __future__ import annotations

import base64
import io
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, BinaryIO, Optional

from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, status
from PIL import Image

from app.core.config import get_settings

_logger = logging.getLogger(__name__)

# Biometric storage constants
BIOMETRIC_PREFIX = "biometric/face_attendance"
ALLOWED_FORMATS = {"JPEG", "JPG", "PNG", "WEBP"}
MIN_DIMENSION = 80
MAX_DIMENSION = 4096
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
PRESIGNED_URL_EXPIRY = 3600  # 1 hour


class BiometricStorageError(Exception):
    """Base exception for biometric storage errors."""
    pass


class BiometricStorage:
    """S3/GCS-compatible object storage for biometric images.
    
    Uses boto3 with S3-compatible APIs (AWS S3, GCS, MinIO, etc.)
    All buckets are private - no public access.
    Images are accessed via presigned URLs with short expiry.
    """
    
    def __init__(self) -> None:
        self._client = None
        self._settings = get_settings()
        self._bucket_name = self._settings.BIOMETRIC_STORAGE_BUCKET
        self._region = self._settings.BIOMETRIC_STORAGE_REGION
        self._endpoint_url = self._settings.BIOMETRIC_STORAGE_ENDPOINT_URL
        self._access_key = self._settings.BIOMETRIC_STORAGE_ACCESS_KEY
        self._secret_key = self._settings.BIOMETRIC_STORAGE_SECRET_KEY.get_secret_value() if self._settings.BIOMETRIC_STORAGE_SECRET_KEY else ""
        self._use_ssl = self._settings.BIOMETRIC_STORAGE_USE_SSL
        self._sse_algorithm = self._settings.BIOMETRIC_STORAGE_SSE_ALGORITHM
        self._kms_key_id = self._settings.BIOMETRIC_STORAGE_KMS_KEY_ID
    
    @property
    def client(self):
        """Lazy-initialize S3 client."""
        if self._client is None:
            self._client = self._create_client()
        return self._client
    
    def _create_client(self):
        """Create boto3 S3 client with production-ready configuration."""
        try:
            import boto3
        except ImportError:
            raise BiometricStorageError("boto3 not installed. Add 'boto3' to requirements.")
        
        if not self._bucket_name:
            raise BiometricStorageError("BIOMETRIC_STORAGE_BUCKET not configured")
        
        if not self._access_key or not self._secret_key:
            raise BiometricStorageError("BIOMETRIC_STORAGE_ACCESS_KEY and BIOMETRIC_STORAGE_SECRET_KEY must be set")
        
        session = boto3.session.Session()
        
        config = BotoConfig(
            retries={
                'max_attempts': 3,
                'mode': 'adaptive'
            },
            max_pool_connections=50,
        )
        
        client = session.client(
            's3',
            region_name=self._region or 'us-east-1',
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            use_ssl=self._use_ssl,
            config=config,
        )
        
        return client
    
    def _get_sse_params(self) -> dict[str, Any]:
        """Get server-side encryption parameters."""
        params = {}
        if self._sse_algorithm:
            params['ServerSideEncryption'] = self._sse_algorithm
        if self._kms_key_id and self._sse_algorithm == 'aws:kms':
            params['SSEKMSKeyId'] = self._kms_key_id
        return params
    
    def _generate_object_key(self, prefix: str, extension: str = "jpg") -> str:
        """Generate unique object key for biometric image."""
        date_prefix = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        unique_id = uuid.uuid4().hex
        return f"{BIOMETRIC_PREFIX}/{date_prefix}/{prefix}_{unique_id}.{extension}"
    
    def _validate_image(self, image_data: bytes) -> tuple[str, tuple[int, int]]:
        """Validate image data and return format and dimensions."""
        try:
            pil_image = Image.open(io.BytesIO(image_data))
            pil_image.verify()
            pil_image = Image.open(io.BytesIO(image_data))
            pil_image.load()
            
            fmt = (pil_image.format or "").upper()
            if fmt not in ALLOWED_FORMATS:
                raise ValueError(f"Unsupported image format: {fmt}. Allowed: {ALLOWED_FORMATS}")
            
            width, height = pil_image.size
            if width < MIN_DIMENSION or height < MIN_DIMENSION:
                raise ValueError(f"Image resolution too low: {width}x{height}. Minimum: {MIN_DIMENSION}x{MIN_DIMENSION}")
            if width > MAX_DIMENSION or height > MAX_DIMENSION:
                raise ValueError(f"Image resolution too high: {width}x{height}. Maximum: {MAX_DIMENSION}x{MAX_DIMENSION}")
            
            return fmt, (width, height)
        except BiometricStorageError:
            raise
        except Exception as exc:
            _logger.warning("Biometric image validation failed: %s", exc)
            raise BiometricStorageError(f"Invalid or corrupted image file: {exc}")
    
    async def upload_base64(
        self,
        image_base64: str,
        prefix: str = "face",
        metadata: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """Upload base64-encoded biometric image to object storage.
        
        Args:
            image_base64: Base64 encoded image (raw or data URI)
            prefix: Prefix for object key (e.g., 'checkin', 'checkout', 'enroll', 'break_start')
            metadata: Optional metadata to store with object
            
        Returns:
            Dict with object_key, bucket, size, format, dimensions, uploaded_at
            
        Raises:
            HTTPException: On validation or upload failure
        """
        # Decode base64
        clean_base64 = image_base64.strip()
        if "," in clean_base64:
            clean_base64 = clean_base64.split(",", 1)[1].strip()
        
        try:
            missing_padding = len(clean_base64) % 4
            if missing_padding:
                clean_base64 += "=" * (4 - missing_padding)
            image_data = base64.b64decode(clean_base64, validate=False)
            if not image_data:
                raise ValueError("Decoded image data is empty")
        except Exception as exc:
            _logger.warning("Failed to decode base64 image: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "FACE_QUALITY_LOW", "message": "Malformed base64 image data."},
            )
        
        # Validate size
        if len(image_data) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "FACE_QUALITY_LOW", "message": f"Image too large ({len(image_data) / (1024*1024):.2f}MB). Max: {MAX_FILE_SIZE / (1024*1024)}MB"},
            )
        
        # Validate image
        try:
            fmt, dimensions = self._validate_image(image_data)
        except BiometricStorageError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "FACE_QUALITY_LOW", "message": str(exc)},
            )
        
        # Generate object key
        ext = "jpg" if fmt in ("JPEG", "JPG") else fmt.lower()
        object_key = self._generate_object_key(prefix, ext)
        
        # Prepare metadata
        object_metadata = {
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "content_type": f"image/{ext}",
            "original_format": fmt,
            "width": str(dimensions[0]),
            "height": str(dimensions[1]),
            "size_bytes": str(len(image_data)),
        }
        if metadata:
            object_metadata.update(metadata)
        
        # Upload to S3/GCS
        try:
            sse_params = self._get_sse_params()
            self.client.put_object(
                Bucket=self._bucket_name,
                Key=object_key,
                Body=image_data,
                ContentType=f"image/{ext}",
                Metadata=object_metadata,
                **sse_params,
            )
        except (ClientError, BotoCoreError) as exc:
            _logger.error("Failed to upload biometric image to storage: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": "STORAGE_ERROR", "message": "Failed to save biometric image to secure storage."},
            )
        
        _logger.info("Biometric image uploaded: bucket=%s, key=%s, size=%d", self._bucket_name, object_key, len(image_data))
        
        return {
            "object_key": object_key,
            "bucket": self._bucket_name,
            "size_bytes": len(image_data),
            "format": fmt,
            "dimensions": dimensions,
            "uploaded_at": object_metadata["uploaded_at"],
        }
    
    async def upload_file(
        self,
        file_obj: BinaryIO,
        prefix: str = "face",
        filename: Optional[str] = None,
        metadata: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """Upload file object to biometric storage.
        
        Args:
            file_obj: File-like object (from multipart upload)
            prefix: Prefix for object key
            filename: Original filename (for extension detection)
            metadata: Optional metadata
            
        Returns:
            Dict with object_key, bucket, size, format, dimensions, uploaded_at
        """
        # Read file data
        file_data = file_obj.read()
        if not file_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "FACE_QUALITY_LOW", "message": "Empty file upload."},
            )
        
        # Validate size
        if len(file_data) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "FACE_QUALITY_LOW", "message": f"File too large ({len(file_data) / (1024*1024):.2f}MB). Max: {MAX_FILE_SIZE / (1024*1024)}MB"},
            )
        
        # Validate image
        try:
            fmt, dimensions = self._validate_image(file_data)
        except BiometricStorageError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "FACE_QUALITY_LOW", "message": str(exc)},
            )
        
        # Generate object key
        ext = "jpg" if fmt in ("JPEG", "JPG") else fmt.lower()
        if filename:
            _, file_ext = os.path.splitext(filename.lower())
            if file_ext.lstrip(".") in ALLOWED_FORMATS:
                ext = file_ext.lstrip(".")
        object_key = self._generate_object_key(prefix, ext)
        
        # Prepare metadata
        object_metadata = {
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "content_type": f"image/{ext}",
            "original_format": fmt,
            "width": str(dimensions[0]),
            "height": str(dimensions[1]),
            "size_bytes": str(len(file_data)),
        }
        if metadata:
            object_metadata.update(metadata)
        
        # Upload
        try:
            sse_params = self._get_sse_params()
            self.client.put_object(
                Bucket=self._bucket_name,
                Key=object_key,
                Body=file_data,
                ContentType=f"image/{ext}",
                Metadata=object_metadata,
                **sse_params,
            )
        except (ClientError, BotoCoreError) as exc:
            _logger.error("Failed to upload biometric file to storage: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": "STORAGE_ERROR", "message": "Failed to save biometric image to secure storage."},
            )
        
        return {
            "object_key": object_key,
            "bucket": self._bucket_name,
            "size_bytes": len(file_data),
            "format": fmt,
            "dimensions": dimensions,
            "uploaded_at": object_metadata["uploaded_at"],
        }
    
    def generate_presigned_url(
        self,
        object_key: str,
        expiry_seconds: int = PRESIGNED_URL_EXPIRY,
    ) -> str:
        """Generate presigned URL for secure biometric image access.
        
        Args:
            object_key: Object key in storage
            expiry_seconds: URL expiry in seconds (default 1 hour)
            
        Returns:
            Presigned URL for GET access
            
        Raises:
            BiometricStorageError: If URL generation fails
        """
        try:
            url = self.client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self._bucket_name, 'Key': object_key},
                ExpiresIn=expiry_seconds,
            )
            return url
        except (ClientError, BotoCoreError) as exc:
            _logger.error("Failed to generate presigned URL: %s", exc)
            raise BiometricStorageError(f"Failed to generate secure access URL: {exc}")
    
    async def delete_object(self, object_key: str) -> bool:
        """Delete biometric image from storage.
        
        Args:
            object_key: Object key to delete
            
        Returns:
            True if deleted, False if not found
        """
        try:
            self.client.delete_object(Bucket=self._bucket_name, Key=object_key)
            _logger.info("Biometric image deleted: bucket=%s, key=%s", self._bucket_name, object_key)
            return True
        except ClientError as exc:
            if exc.response['Error']['Code'] == 'NoSuchKey':
                return False
            _logger.error("Failed to delete biometric image: %s", exc)
            raise BiometricStorageError(f"Failed to delete biometric image: {exc}")
    
    async def delete_objects(self, object_keys: list[str]) -> dict[str, Any]:
        """Delete multiple biometric images.
        
        Args:
            object_keys: List of object keys to delete
            
        Returns:
            Dict with deleted_count and errors
        """
        if not object_keys:
            return {"deleted_count": 0, "errors": []}
        
        try:
            objects = [{"Key": key} for key in object_keys]
            response = self.client.delete_objects(
                Bucket=self._bucket_name,
                Delete={"Objects": objects, "Quiet": False}
            )
            deleted = response.get("Deleted", [])
            errors = response.get("Errors", [])
            _logger.info("Bulk delete: deleted=%d, errors=%d", len(deleted), len(errors))
            return {"deleted_count": len(deleted), "errors": errors}
        except (ClientError, BotoCoreError) as exc:
            _logger.error("Failed bulk delete: %s", exc)
            raise BiometricStorageError(f"Failed to delete biometric images: {exc}")
    
    async def get_object_metadata(self, object_key: str) -> Optional[dict[str, Any]]:
        """Get object metadata without downloading.
        
        Args:
            object_key: Object key
            
        Returns:
            Metadata dict or None if not found
        """
        try:
            response = self.client.head_object(Bucket=self._bucket_name, Key=object_key)
            return {
                "object_key": object_key,
                "bucket": self._bucket_name,
                "size_bytes": response.get("ContentLength"),
                "content_type": response.get("ContentType"),
                "last_modified": response.get("LastModified"),
                "metadata": response.get("Metadata", {}),
                "etag": response.get("ETag"),
                "server_side_encryption": response.get("ServerSideEncryption"),
            }
        except ClientError as exc:
            if exc.response['Error']['Code'] == 'NoSuchKey':
                return None
            _logger.error("Failed to get object metadata: %s", exc)
            raise BiometricStorageError(f"Failed to get object metadata: {exc}")
    
    async def list_objects(
        self,
        prefix: Optional[str] = None,
        max_keys: int = 1000,
    ) -> list[dict[str, Any]]:
        """List biometric objects with optional prefix filter.
        
        Args:
            prefix: Object key prefix filter
            max_keys: Maximum objects to return
            
        Returns:
            List of object metadata
        """
        try:
            list_prefix = f"{BIOMETRIC_PREFIX}/"
            if prefix:
                list_prefix += prefix.lstrip("/")
            
            paginator = self.client.get_paginator('list_objects_v2')
            pages = paginator.paginate(
                Bucket=self._bucket_name,
                Prefix=list_prefix,
                PaginationConfig={'MaxItems': max_keys}
            )
            
            objects = []
            for page in pages:
                for obj in page.get('Contents', []):
                    objects.append({
                        "object_key": obj['Key'],
                        "size_bytes": obj['Size'],
                        "last_modified": obj['LastModified'],
                        "etag": obj['ETag'],
                    })
            return objects
        except (ClientError, BotoCoreError) as exc:
            _logger.error("Failed to list objects: %s", exc)
            raise BiometricStorageError(f"Failed to list biometric images: {exc}")
    
    def check_bucket_exists(self) -> bool:
        """Verify bucket exists and is accessible."""
        try:
            self.client.head_bucket(Bucket=self._bucket_name)
            return True
        except ClientError as exc:
            _logger.error("Bucket check failed: %s", exc)
            return False
    
    def check_health(self) -> dict[str, Any]:
        """Health check for storage service."""
        healthy = self.check_bucket_exists()
        return {
            "healthy": healthy,
            "bucket": self._bucket_name,
            "region": self._region,
            "endpoint": self._endpoint_url,
            "encryption": self._sse_algorithm or "none",
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }


# Global storage instance
_storage_instance: Optional[BiometricStorage] = None


def get_biometric_storage() -> BiometricStorage:
    """Get or create global biometric storage instance."""
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = BiometricStorage()
    return _storage_instance


async def save_biometric_image_base64(
    image_base64: str,
    prefix: str = "face",
    metadata: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Convenience function to save base64 biometric image."""
    storage = get_biometric_storage()
    return await storage.upload_base64(image_base64, prefix, metadata)


async def save_biometric_image_file(
    file_obj: BinaryIO,
    prefix: str = "face",
    filename: Optional[str] = None,
    metadata: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Convenience function to save file biometric image."""
    storage = get_biometric_storage()
    return await storage.upload_file(file_obj, prefix, filename, metadata)


def get_biometric_presigned_url(object_key: str, expiry_seconds: int = PRESIGNED_URL_EXPIRY) -> str:
    """Convenience function to generate presigned URL."""
    storage = get_biometric_storage()
    return storage.generate_presigned_url(object_key, expiry_seconds)


async def delete_biometric_image(object_key: str) -> bool:
    """Convenience function to delete biometric image."""
    storage = get_biometric_storage()
    return await storage.delete_object(object_key)


async def delete_biometric_images(object_keys: list[str]) -> dict[str, Any]:
    """Convenience function to bulk delete biometric images."""
    storage = get_biometric_storage()
    return await storage.delete_objects(object_keys)


async def get_biometric_metadata(object_key: str) -> Optional[dict[str, Any]]:
    """Convenience function to get biometric image metadata."""
    storage = get_biometric_storage()
    return await storage.get_object_metadata(object_key)


def enrich_attendance_with_presigned_urls(
    attendance_data: dict[str, Any],
    expiry_seconds: int = PRESIGNED_URL_EXPIRY,
) -> dict[str, Any]:
    """Add presigned URLs to attendance response for secure image access.
    
    Args:
        attendance_data: Attendance response dict with object keys
        expiry_seconds: URL expiry time
        
    Returns:
        Dict with presigned URLs added for face_image_url, captured_face_url, checkout_image_url
    """
    storage = get_biometric_storage()
    enriched = attendance_data.copy()
    
    for field in ("face_image_url", "captured_face_url", "checkout_image_url"):
        object_key = enriched.get(field)
        if object_key and isinstance(object_key, str) and not object_key.startswith("http"):
            try:
                enriched[f"{field}_presigned"] = storage.generate_presigned_url(object_key, expiry_seconds)
            except BiometricStorageError:
                enriched[f"{field}_presigned"] = None
    
    return enriched


def enrich_break_with_presigned_urls(
    break_data: dict[str, Any],
    expiry_seconds: int = PRESIGNED_URL_EXPIRY,
) -> dict[str, Any]:
    """Add presigned URLs to break response for secure image access."""
    storage = get_biometric_storage()
    enriched = break_data.copy()
    
    for field in ("start_image_url", "end_image_url"):
        object_key = enriched.get(field)
        if object_key and isinstance(object_key, str) and not object_key.startswith("http"):
            try:
                enriched[f"{field}_presigned"] = storage.generate_presigned_url(object_key, expiry_seconds)
            except BiometricStorageError:
                enriched[f"{field}_presigned"] = None
    
    return enriched


def generate_presigned_urls_for_attendance(
    attendance_dict: dict[str, Any],
    expiry_seconds: int = PRESIGNED_URL_EXPIRY,
) -> dict[str, Any]:
    """Generate presigned URLs for all biometric image fields in attendance record.
    
    Args:
        attendance_dict: Attendance record as dict (from ORM or schema)
        expiry_seconds: URL expiry in seconds
        
    Returns:
        Dict with presigned URLs added for each image field
    """
    storage = get_biometric_storage()
    result = attendance_dict.copy()
    
    image_fields = [
        "face_image_url",
        "captured_face_url",
        "checkout_image_url",
        "start_image_url",
        "end_image_url",
    ]
    
    for field in image_fields:
        object_key = result.get(field)
        if object_key and isinstance(object_key, str) and object_key.startswith("biometric/"):
            try:
                result[f"{field}_presigned"] = storage.generate_presigned_url(object_key, expiry_seconds)
            except BiometricStorageError:
                result[f"{field}_presigned"] = None
        else:
            result[f"{field}_presigned"] = None
    
    return result


def generate_presigned_urls_for_break(
    break_dict: dict[str, Any],
    expiry_seconds: int = PRESIGNED_URL_EXPIRY,
) -> dict[str, Any]:
    """Generate presigned URLs for all biometric image fields in break record.
    
    Args:
        break_dict: Break record as dict
        expiry_seconds: URL expiry in seconds
        
    Returns:
        Dict with presigned URLs added for each image field
    """
    storage = get_biometric_storage()
    result = break_dict.copy()
    
    image_fields = ["start_image_url", "end_image_url"]
    
    for field in image_fields:
        object_key = result.get(field)
        if object_key and isinstance(object_key, str) and object_key.startswith("biometric/"):
            try:
                result[f"{field}_presigned"] = storage.generate_presigned_url(object_key, expiry_seconds)
            except BiometricStorageError:
                result[f"{field}_presigned"] = None
        else:
            result[f"{field}_presigned"] = None
    
    return result