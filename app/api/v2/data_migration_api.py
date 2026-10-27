"""E5 legacy data migration validation/commit/rollback APIs."""
from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_admin
from app.db.database import get_db_session
from app.models.data_migration import DataMigrationBatch
from app.schemas.auth import APIResponse
from app.services.data_migration_service import DataMigrationService

router = APIRouter(prefix="/migrations", tags=["E5 Data Migration v2"])


class MigrationRowsPayload(BaseModel):
    migration_type: str
    rows: list[dict[str, Any]] = Field(min_length=1)
    source_filename: str | None = None


class RollbackPayload(BaseModel):
    reason: str | None = Field(None, max_length=1000)


def _company_id(claims: dict) -> uuid.UUID:
    try:
        return uuid.UUID(str(claims.get("company_id") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Valid company context is required.") from exc


def _batch_dict(batch: DataMigrationBatch, include_payload: bool = False) -> dict[str, Any]:
    result = {
        "id": str(batch.id), "migration_type": batch.migration_type,
        "source_filename": batch.source_filename, "file_hash": batch.file_hash,
        "status": batch.status, "total_rows": batch.total_rows, "valid_rows": batch.valid_rows,
        "error_rows": batch.error_rows, "validation_errors": batch.validation_errors_json or [],
        "committed_at": batch.committed_at.isoformat() if batch.committed_at else None,
        "rolled_back_at": batch.rolled_back_at.isoformat() if batch.rolled_back_at else None,
        "rollback_reason": batch.rollback_reason,
    }
    if include_payload:
        result["payload"] = batch.payload_json
    return result


async def _validate_upload(file: UploadFile, migration_type: str, claims: dict, db: AsyncSession):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Migration file is empty.")
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Migration file is limited to 25 MB.")
    try:
        batch = await DataMigrationService(db).validate_file(
            company_id=_company_id(claims), migration_type=migration_type,
            file_bytes=content, filename=file.filename or "migration.xlsx",
            actor_id=uuid.UUID(claims["sub"]),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return APIResponse(success=not batch.validation_errors_json, message="Migration validation completed.", data=_batch_dict(batch), errors=None)


@router.post("/validate", response_model=APIResponse[dict[str, Any]])
async def validate_migration(
    file: Annotated[UploadFile, File(...)], migration_type: Annotated[str, Form(...)],
    claims: Annotated[dict, Depends(require_admin)], db: Annotated[AsyncSession, Depends(get_db_session)],
):
    return await _validate_upload(file, migration_type, claims, db)


@router.post("/validate-json", response_model=APIResponse[dict[str, Any]])
async def validate_migration_rows(
    payload: MigrationRowsPayload, claims: Annotated[dict, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    try:
        batch = await DataMigrationService(db).validate_payload(
            company_id=_company_id(claims), migration_type=payload.migration_type,
            rows=payload.rows, source_filename=payload.source_filename, actor_id=uuid.UUID(claims["sub"]),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return APIResponse(success=not batch.validation_errors_json, message="Migration validation completed.", data=_batch_dict(batch), errors=None)


@router.post("/{migration_type}/validate", response_model=APIResponse[dict[str, Any]])
async def validate_typed_migration(
    migration_type: str, file: Annotated[UploadFile, File(...)],
    claims: Annotated[dict, Depends(require_admin)], db: Annotated[AsyncSession, Depends(get_db_session)],
):
    return await _validate_upload(file, migration_type, claims, db)


@router.get("", response_model=APIResponse[list[dict[str, Any]]])
async def list_migrations(
    claims: Annotated[dict, Depends(require_admin)], db: Annotated[AsyncSession, Depends(get_db_session)],
):
    batches = (await db.execute(select(DataMigrationBatch).where(
        DataMigrationBatch.company_id == _company_id(claims)
    ).order_by(DataMigrationBatch.created_at.desc()).limit(100))).scalars().all()
    return APIResponse(success=True, message="Migration batches retrieved.", data=[_batch_dict(batch) for batch in batches], errors=None)


@router.get("/{batch_id}", response_model=APIResponse[dict[str, Any]])
async def get_migration(
    batch_id: uuid.UUID, claims: Annotated[dict, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    try:
        batch = await DataMigrationService(db).get_batch(batch_id, company_id=_company_id(claims))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return APIResponse(success=True, message="Migration batch retrieved.", data=_batch_dict(batch), errors=None)


@router.post("/{batch_id}/commit", response_model=APIResponse[dict[str, Any]])
async def commit_migration(
    batch_id: uuid.UUID, claims: Annotated[dict, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    try:
        batch = await DataMigrationService(db).commit_batch(batch_id, company_id=_company_id(claims))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return APIResponse(success=True, message="Migration batch committed atomically.", data=_batch_dict(batch), errors=None)


@router.post("/{batch_id}/rollback", response_model=APIResponse[dict[str, Any]])
async def rollback_migration(
    batch_id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    payload: RollbackPayload | None = None,
):
    try:
        batch = await DataMigrationService(db).rollback_batch(
            batch_id, company_id=_company_id(claims), reason=payload.reason if payload else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return APIResponse(success=True, message="Migration batch rolled back from snapshots.", data=_batch_dict(batch), errors=None)


__all__ = ["router"]
