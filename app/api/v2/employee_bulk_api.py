"""Real tenant employee bulk import/export endpoints."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_admin, require_admin_or_manager
from app.db.database import get_db_session
from app.services.employee_bulk_service import EmployeeBulkService

router = APIRouter(prefix="/employees", tags=["Employee Bulk I/O v2"])


def _company_id(claims: dict) -> uuid.UUID:
    try:
        return uuid.UUID(str(claims.get("company_id") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Valid company context is required.") from exc


@router.post("/bulk-import", summary="Validate or atomically import employees from CSV/XLSX")
async def bulk_import_employees(
    file: Annotated[UploadFile, File(...)],
    claims: Annotated[dict, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    dry_run: bool = Query(False),
    dry_run_form: bool | None = Form(None),
):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Employee import is limited to 10 MB.")
    actor_id = uuid.UUID(str(claims["sub"]))
    try:
        result = await EmployeeBulkService(db).import_employees(
            _company_id(claims), content, file.filename or "employees.xlsx",
            dry_run=dry_run or bool(dry_run_form), actor_id=actor_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "success": not result["errors"], "data": result,
        "message": "Dry-run validation completed." if result["dry_run"] else "Employee import processed.",
    }


@router.get("/bulk-export", summary="Export tenant employees as CSV or XLSX")
async def bulk_export_employees(
    claims: Annotated[dict, Depends(require_admin_or_manager)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    format: str = Query("xlsx", pattern="^(csv|xlsx)$"),
):
    content, filename, media_type = await EmployeeBulkService(db).export_employees(_company_id(claims), format)
    return Response(content=content, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Length": str(len(content)),
    })


__all__ = ["router"]
