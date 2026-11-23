"""Interview Recording and Media Storage Service."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Optional, BinaryIO
from urllib.parse import urljoin

import boto3
from botocore.exceptions import ClientError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.interview_recording import (
    InterviewRecording,
    RecordingChunk,
    RecordingAccessLog,
    RecordingStatus,
    MediaType,
)
from app.models.ai_interview import AIInterviewSession

logger = logging.getLogger(__name__)


class S3StorageBackend:
    """S3-compatible storage backend for recordings."""

    def __init__(self) -> None:
        self._client = None
        self._bucket = getattr(settings, "S3_BUCKET", "ofc360-recordings")
        self._endpoint = getattr(settings, "S3_ENDPOINT_URL", None)
        self._region = getattr(settings, "S3_REGION", "us-east-1")
        self._access_key = getattr(settings, "S3_ACCESS_KEY", None)
        self._secret_key = getattr(settings, "S3_SECRET_KEY", None)
        self._public_url = getattr(settings, "S3_PUBLIC_URL", None)

    def _get_client(self):
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=self._endpoint,
                region_name=self._region,
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
            )
        return self._client

    def _ensure_bucket(self) -> None:
        """Ensure the bucket exists."""
        client = self._get_client()
        try:
            client.head_bucket(Bucket=self._bucket)
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                client.create_bucket(Bucket=self._bucket)
                logger.info("Created S3 bucket: %s", self._bucket)
            else:
                raise

    async def upload_file(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        metadata: dict = None,
    ) -> str:
        """Upload data to S3 and return the object URL."""
        self._ensure_bucket()
        client = self._get_client()
        
        extra_args = {"ContentType": "application/octet-stream"}
        if metadata:
            extra_args["Metadata"] = metadata
        
        try:
            await asyncio.to_thread(
                client.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=data,
                **extra_args,
            )
        except ClientError as e:
            logger.error("S3 upload failed: %s", e)
            raise
        
        if self._public_url:
            return urljoin(self._public_url.rstrip("/") + "/", key)
        return f"s3://{self._bucket}/{key}"

    async def upload_fileobj(
        self,
        key: str,
        fileobj: BinaryIO,
        content_type: str = "application/octet-stream",
        metadata: dict = None,
    ) -> str:
        """Upload a file object to S3."""
        self._ensure_bucket()
        client = self._get_client()
        
        extra_args = {"ContentType": content_type}
        if metadata:
            extra_args["Metadata"] = metadata
        
        try:
            await asyncio.to_thread(
                client.upload_fileobj,
                fileobj,
                self._bucket,
                key,
                ExtraArgs=extra_args,
            )
        except ClientError as e:
            logger.error("S3 upload_fileobj failed: %s", e)
            raise
        
        if self._public_url:
            return urljoin(self._public_url.rstrip("/") + "/", key)
        return f"s3://{self._bucket}/{key}"

    async def generate_presigned_url(
        self,
        key: str,
        expiration: int = 3600,
        method: str = "get_object",
    ) -> str:
        """Generate a presigned URL for accessing an object."""
        client = self._get_client()
        try:
            url = await asyncio.to_thread(
                client.generate_presigned_url,
                method,
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expiration,
            )
            return url
        except ClientError as e:
            logger.error("Presigned URL generation failed: %s", e)
            raise

    async def delete_object(self, key: str) -> bool:
        """Delete an object from S3."""
        client = self._get_client()
        try:
            await asyncio.to_thread(
                client.delete_object,
                Bucket=self._bucket,
                Key=key,
            )
            return True
        except ClientError as e:
            logger.error("S3 delete failed: %s", e)
            return False

    async def get_object_metadata(self, key: str) -> dict | None:
        """Get object metadata."""
        client = self._get_client()
        try:
            res = await asyncio.to_thread(
                client.head_object,
                Bucket=self._bucket,
                Key=key,
            )
            return {
                "size": res.get("ContentLength"),
                "content_type": res.get("ContentType"),
                "last_modified": res.get("LastModified"),
                "metadata": res.get("Metadata", {}),
            }
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return None
            raise


class RecordingService:
    """Service for managing interview recordings."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.storage = S3StorageBackend()

    async def start_recording(
        self,
        session_id: uuid.UUID,
        candidate_id: uuid.UUID,
        job_id: uuid.UUID,
        round_id: Optional[uuid.UUID] = None,
        media_type: str = "AUDIO",
        format: str = "webm",
        codec: Optional[str] = None,
        sample_rate: Optional[int] = None,
        channels: Optional[int] = None,
        bitrate_kbps: Optional[int] = None,
        resolution: Optional[str] = None,
        frame_rate: Optional[int] = None,
        consent_given: bool = False,
        consent_version: Optional[str] = None,
        retention_days: int = 90,
        company_id: Optional[uuid.UUID] = None,
    ) -> InterviewRecording:
        """Initialize a new recording session."""
        # Verify session exists
        stmt = select(AIInterviewSession).where(AIInterviewSession.id == session_id)
        res = await self.db.execute(stmt)
        session = res.scalar_one_or_none()
        
        if not session:
            raise ValueError("Interview session not found")
        
        if session.candidate_id != candidate_id:
            raise ValueError("Candidate mismatch")
        
        # Create recording record
        storage_key = f"recordings/{company_id or 'unknown'}/{session_id}/{uuid.uuid4()}.webm"
        
        recording = InterviewRecording(
            company_id=company_id or session.company_id,
            session_id=session_id,
            candidate_id=candidate_id,
            round_id=round_id,
            job_id=job_id,
            media_type=media_type,
            status=RecordingStatus.RECORDING,
            format="webm",
            codec=codec,
            storage_provider="s3",
            storage_bucket=getattr(settings, "S3_BUCKET", "ofc360-recordings"),
            storage_key=storage_key,
            sample_rate=sample_rate,
            channels=channels,
            bitrate_kbps=bitrate_kbps,
            resolution=resolution,
            frame_rate=frame_rate,
            recording_started_at=datetime.now(timezone.utc),
            consent_given=consent_given,
            consent_given_at=datetime.now(timezone.utc) if consent_given else None,
            consent_version=consent_version,
            retention_days=retention_days,
            expires_at=datetime.now(timezone.utc) + timedelta(days=retention_days),
            access_token=uuid.uuid4().hex,
            access_expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        
        self.db.add(recording)
        await self.db.commit()
        await self.db.refresh(recording)
        
        logger.info("Started recording %s for session %s", recording.id, session_id)
        return recording

    async def upload_chunk(
        self,
        recording_id: uuid.UUID,
        chunk_data: bytes,
        sequence_number: int,
        start_time_ms: int,
        end_time_ms: int,
        format: str = "webm",
        is_keyframe: bool = False,
    ) -> RecordingChunk:
        """Upload a recording chunk."""
        # Verify recording exists and is in RECORDING state
        stmt = select(InterviewRecording).where(InterviewRecording.id == recording_id)
        res = await self.db.execute(stmt)
        recording = res.scalar_one_or_none()
        
        if not recording:
            raise ValueError("Recording not found")
        
        if recording.status not in (RecordingStatus.RECORDING, RecordingStatus.PROCESSING):
            raise ValueError(f"Recording not in valid state for upload: {recording.status}")
        
        # Upload chunk to storage
        chunk_key = f"{recording.storage_key}.chunk.{sequence_number:06d}"
        storage_url = await self.storage.upload_file(
            chunk_key,
            chunk_data,
            content_type=f"video/{format}" if format in ("webm", "mp4") else f"audio/{format}",
            metadata={
                "recording_id": str(recording_id),
                "sequence": str(sequence_number),
                "start_ms": str(start_time_ms),
                "end_ms": str(end_time_ms),
            },
        )
        
        # Create chunk record
        chunk = RecordingChunk(
            recording_id=recording_id,
            sequence_number=sequence_number,
            start_time_seconds=start_time_ms,
            end_time_seconds=end_time_ms,
            duration_ms=end_time_ms - start_time_ms,
            storage_key=chunk_key,
            storage_url=storage_url,
            file_size_bytes=len(chunk_data),
            format=format,
            is_keyframe=is_keyframe,
            status="UPLOADED",
            uploaded_at=datetime.now(timezone.utc),
        )
        
        self.db.add(chunk)
        
        # Update recording file size
        recording.file_size_bytes += len(chunk_data)
        
        await self.db.commit()
        await self.db.refresh(chunk)
        
        logger.info("Uploaded chunk %d for recording %s", sequence_number, recording_id)
        return chunk

    async def finalize_recording(
        self,
        recording_id: uuid.UUID,
        total_duration_seconds: int,
        final_file_size: Optional[int] = None,
    ) -> InterviewRecording:
        """Finalize a recording after all chunks uploaded."""
        stmt = select(InterviewRecording).where(InterviewRecording.id == recording_id)
        res = await self.db.execute(stmt)
        recording = res.scalar_one_or_none()
        
        if not recording:
            raise ValueError("Recording not found")
        
        # Verify all chunks uploaded
        chunks_stmt = select(RecordingChunk).where(
            RecordingChunk.recording_id == recording_id
        ).order_by(RecordingChunk.sequence_number)
        chunks_res = await self.db.execute(chunks_stmt)
        chunks = chunks_res.scalars().all()
        
        if not chunks:
            raise ValueError("No chunks found for recording")
        
        # Check for gaps in sequence
        expected_seq = 0
        for chunk in chunks:
            if chunk.sequence_number != expected_seq:
                logger.warning("Chunk sequence gap detected in recording %s: expected %d, got %d", 
                              recording_id, expected_seq, chunk.sequence_number)
            expected_seq = chunk.sequence_number + 1
        
        # Combine chunks or verify final file
        if final_file_size:
            recording.file_size_bytes = final_file_size
        
        recording.duration_seconds = total_duration_seconds
        recording.recording_ended_at = datetime.now(timezone.utc)
        recording.status = RecordingStatus.PROCESSING
        recording.processing_started_at = datetime.now(timezone.utc)
        
        await self.db.commit()
        
        # Process recording (combine chunks, transcode, generate thumbnails, etc.)
        await self._process_recording(recording)
        
        await self.db.refresh(recording)
        return recording

    async def _process_recording(self, recording: InterviewRecording) -> None:
        """Process recording: combine chunks, transcode, generate thumbnails."""
        try:
            # For now, mark as completed
            # In production, this would:
            # 1. Download all chunks from S3
            # 2. Combine using ffmpeg
            # 3. Transcode to standard formats (mp4, webm)
            # 4. Generate thumbnails/previews
            # 5. Upload final files to S3
            # 6. Generate streaming manifests (HLS/DASH)
            # 7. Update recording with final storage keys
            
            recording.status = RecordingStatus.COMPLETED
            recording.processing_completed_at = datetime.now(timezone.utc)
            
            # Generate access token for authorized access
            recording.access_token = uuid.uuid4().hex
            recording.access_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
            
            # Generate signed URL for immediate access
            recording.storage_url = await self.storage.generate_presigned_url(
                recording.storage_key,
                expiration=3600,
            )
            
            await self.db.commit()
            logger.info("Recording %s processed and completed", recording.id)
            
        except Exception as exc:
            logger.error("Recording processing failed: %s", exc)
            recording.status = RecordingStatus.FAILED
            recording.error_message = str(exc)
            await self.db.commit()
            raise

    async def get_recording(self, recording_id: uuid.UUID) -> Optional[InterviewRecording]:
        """Get recording by ID."""
        stmt = select(InterviewRecording).where(InterviewRecording.id == recording_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_recordings_for_session(
        self,
        session_id: uuid.UUID,
        status: Optional[str] = None,
    ) -> list[InterviewRecording]:
        """Get all recordings for an interview session."""
        stmt = select(InterviewRecording).where(InterviewRecording.session_id == session_id)
        if status:
            stmt = stmt.where(InterviewRecording.status == status)
        stmt = stmt.order_by(InterviewRecording.created_at.desc())
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def get_recordings_for_candidate(
        self,
        candidate_id: uuid.UUID,
        company_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> list[InterviewRecording]:
        """Get recordings for a candidate."""
        stmt = select(InterviewRecording).where(InterviewRecording.candidate_id == candidate_id)
        if company_id:
            stmt = stmt.where(InterviewRecording.company_id == company_id)
        if status:
            stmt = stmt.where(InterviewRecording.status == status)
        stmt = stmt.order_by(InterviewRecording.created_at.desc())
        stmt = stmt.offset((page - 1) * limit).limit(limit)
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def authorize_access(
        self,
        recording_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        token: Optional[str] = None,
        action: str = "STREAM",
    ) -> tuple[bool, Optional[str]]:
        """Authorize access to a recording."""
        recording = await self.get_recording(recording_id)
        if not recording:
            return False, "Recording not found"
        
        if recording.status != RecordingStatus.COMPLETED:
            return False, f"Recording not ready: {recording.status}"
        
        # Check token if provided
        if token:
            if recording.access_token != token:
                return False, "Invalid access token"
            if recording.access_expires_at and recording.access_expires_at < datetime.now(timezone.utc):
                return False, "Access token expired"
        elif user_id:
            # Check if user has HR/admin access to this company
            # This would integrate with your RBAC system
            pass
        
        # Log access
        await self._log_access(
            recording_id=recording_id,
            accessed_by=user_id,
            action=action,
            success=True,
        )
        
        # Generate signed URL for access
        signed_url = await self.storage.generate_presigned_url(
            recording.storage_key,
            expiration=3600,
        )
        
        return True, signed_url

    async def _log_access(
        self,
        recording_id: uuid.UUID,
        accessed_by: Optional[uuid.UUID],
        action: str,
        success: bool = True,
        error_message: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> RecordingAccessLog:
        """Log recording access for audit."""
        log = RecordingAccessLog(
            recording_id=recording_id,
            accessed_by=accessed_by,
            action=action,
            success=success,
            error_message=error_message,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.db.add(log)
        await self.db.commit()
        return log

    async def get_recording_stream(
        self,
        recording_id: uuid.UUID,
        start_byte: int = 0,
        end_byte: Optional[int] = None,
    ) -> AsyncGenerator[bytes, None]:
        """Stream recording content for playback."""
        recording = await self.get_recording(recording_id)
        if not recording:
            raise ValueError("Recording not found")
        
        if recording.status != RecordingStatus.COMPLETED:
            raise ValueError(f"Recording not ready: {recording.status}")
        
        # Stream from S3
        client = recording.storage._get_client() if hasattr(recording.storage, '_get_client') else None
        
        # For now, use presigned URL and range requests
        # In production, implement proper range request handling
        url = await self.storage.generate_presigned_url(recording.storage_key)
        
        # Yield chunks from URL (simplified)
        # Real implementation would use range requests
        yield b""

    async def delete_recording(
        self,
        recording_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        gdpr_request: bool = False,
    ) -> bool:
        """Delete a recording (soft delete or GDPR hard delete)."""
        recording = await self.get_recording(recording_id)
        if not recording:
            return False
        
        if gdpr_request:
            recording.gdpr_deletion_requested = True
            recording.gdpr_deleted_at = datetime.now(timezone.utc)
            recording.status = RecordingStatus.DELETED
            
            # Delete from storage
            await self.storage.delete_object(recording.storage_key)
            
            # Delete chunks
            chunks_stmt = select(RecordingChunk).where(RecordingChunk.recording_id == recording_id)
            chunks_res = await self.db.execute(chunks_stmt)
            for chunk in chunks_res.scalars().all():
                await self.storage.delete_object(chunk.storage_key)
        else:
            recording.status = RecordingStatus.DELETED
        
        await self.db.commit()
        
        # Log access
        await self._log_access(
            recording_id=recording_id,
            accessed_by=user_id,
            action="DELETE",
            success=True,
        )
        
        return True

    async def generate_download_url(
        self,
        recording_id: uuid.UUID,
        expiration: int = 3600,
    ) -> Optional[str]:
        """Generate a download URL for a recording."""
        authorized, url = await self.authorize_access(recording_id, action="DOWNLOAD")
        if not authorized:
            return None
        return url

    async def get_recording_stats(self, company_id: Optional[uuid.UUID] = None) -> dict:
        """Get recording statistics."""
        from sqlalchemy import func
        
        stmt = select(
            InterviewRecording.status,
            func.count(InterviewRecording.id).label("count"),
            func.sum(InterviewRecording.file_size_bytes).label("total_size"),
            func.sum(InterviewRecording.duration_seconds).label("total_duration"),
        ).group_by(InterviewRecording.status)
        
        if company_id:
            stmt = stmt.where(InterviewRecording.company_id == company_id)
        
        res = await self.db.execute(stmt)
        stats = {}
        total_size = 0
        total_duration = 0
        for row in res:
            stats[row.status] = {
                "count": row.count,
                "size_bytes": row.total_size or 0,
                "duration_seconds": row.total_duration or 0,
            }
            total_size += row.total_size or 0
            total_duration += row.total_duration or 0
        
        stats["total"] = {
            "size_bytes": total_size,
            "duration_seconds": total_duration,
        }
        
        return stats