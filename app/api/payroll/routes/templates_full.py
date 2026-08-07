"""FastAPI Route Handlers for Enterprise Payroll Template Management System."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.payroll.dependencies import DB, Claims
from app.api.payroll.permissions import _require_admin_or_manager, _require_admin
from app.api.payroll.responses import success_response
from app.schemas.auth import APIResponse
from app.schemas.payroll_template import (
    PayrollTemplateSchema,
    PayrollTemplateCreateSchema,
    PayrollTemplateUpdateSchema,
    GenerateDocumentSchema,
    PreviewTemplateSchema,
)
from app.services.payroll_template_service import PayrollTemplateService

router = APIRouter()


def _tmpl_to_dict(t) -> dict:
    """Helper to convert PayrollTemplate model to dictionary."""
    return {
        "id": str(t.id),
        "company_id": str(t.company_id) if t.company_id else None,
        "template_name": t.template_name,
        "template_code": t.template_code,
        "category": t.category or "PAYSLIP",
        "description": t.description or "",
        "doc_format": t.doc_format or "PDF",
        "language": t.language or "EN",
        "status": t.status or "PUBLISHED",
        "version_number": t.version_number or 1,
        "is_default": t.is_default,
        "styling_theme": t.styling_theme or "MODERN_DARK",
        "html_content": t.html_content,
        "header_logo_url": t.header_logo_url or "",
        "footer_text": t.footer_text or "",
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


@router.get("/templates", response_model=APIResponse[dict], summary="List all payroll document templates")
@router.head("/templates")
async def list_payroll_templates(
    category_filter: Optional[str] = Query(None, alias="category"),
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    templates = await PayrollTemplateService.list_templates(db, category_filter=category_filter)
    items = [_tmpl_to_dict(t) for t in templates]
    return success_response({"items": items, "total": len(items)}, "Payroll templates retrieved successfully.")


@router.get("/templates/audit", response_model=APIResponse[List[dict]], summary="Get template audit log")
async def get_template_audit(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[List[dict]]:
    _require_admin_or_manager(claims)
    logs = await PayrollTemplateService.get_audit_logs(db)
    return success_response(logs, "Template audit log retrieved.")


@router.get("/templates/history", response_model=APIResponse[List[dict]], summary="Get template version history")
async def get_template_history(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[List[dict]]:
    _require_admin_or_manager(claims)
    logs = await PayrollTemplateService.get_audit_logs(db)
    return success_response(logs, "Template version history retrieved.")


@router.get("/templates/{template_id}", response_model=APIResponse[dict], summary="Get single template details")
async def get_template_details(
    template_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    tmpl = await PayrollTemplateService.get_template_by_id(db, template_id)
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found.")
    return success_response(_tmpl_to_dict(tmpl), "Template details retrieved.")


@router.post("/templates", status_code=201, response_model=APIResponse[dict], summary="Create new payroll template")
async def create_template(
    payload: PayrollTemplateCreateSchema,
    request: Request,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    actor_email = claims.get("email") if claims else "admin@aurix.ai"
    ip_address = request.client.host if request.client else "127.0.0.1"
    browser = request.headers.get("user-agent", "Dashboard Web")

    try:
        created = await PayrollTemplateService.create_template(
            db=db,
            data=payload.model_dump(),
            actor_email=actor_email,
            ip_address=ip_address,
            browser=browser
        )
        return success_response(_tmpl_to_dict(created), "Template created successfully.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/templates/{template_id}", response_model=APIResponse[dict], summary="Update payroll template")
@router.patch("/templates/{template_id}", response_model=APIResponse[dict], summary="Partial update payroll template")
async def update_template(
    template_id: uuid.UUID,
    payload: dict,
    request: Request,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    actor_email = claims.get("email") if claims else "admin@aurix.ai"
    ip_address = request.client.host if request.client else "127.0.0.1"
    browser = request.headers.get("user-agent", "Dashboard Web")

    updated = await PayrollTemplateService.update_template(
        db=db,
        template_id=template_id,
        payload=payload,
        actor_email=actor_email,
        ip_address=ip_address,
        browser=browser
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Template not found.")
    return success_response(_tmpl_to_dict(updated), "Template updated successfully.")


@router.post("/templates/{template_id}/duplicate", response_model=APIResponse[dict], summary="Duplicate template")
async def duplicate_template(
    template_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    cloned = await PayrollTemplateService.duplicate_template(db, template_id)
    if not cloned:
        raise HTTPException(status_code=404, detail="Template not found.")
    return success_response(_tmpl_to_dict(cloned), "Template duplicated successfully.")


@router.post("/templates/{template_id}/preview", response_model=APIResponse[dict], summary="Preview merged HTML template")
async def preview_template(
    template_id: uuid.UUID,
    payload: Optional[Dict[str, Any]] = None,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    tmpl = await PayrollTemplateService.get_template_by_id(db, template_id)
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found.")
    rendered_html = await PayrollTemplateService.render_merged_template(tmpl, payload or {})
    return success_response({"rendered_html": rendered_html, "template_code": tmpl.template_code}, "Template preview rendered.")


@router.post("/templates/{template_id}/publish", response_model=APIResponse[dict], summary="Publish template")
async def publish_template(
    template_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    tmpl = await PayrollTemplateService.get_template_by_id(db, template_id)
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found.")
    tmpl.status = "PUBLISHED"
    await db.commit()
    return success_response(_tmpl_to_dict(tmpl), "Template published successfully.")


@router.post("/templates/{template_id}/archive", response_model=APIResponse[dict], summary="Archive template")
async def archive_template(
    template_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    tmpl = await PayrollTemplateService.get_template_by_id(db, template_id)
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found.")
    tmpl.status = "ARCHIVED"
    await db.commit()
    return success_response(_tmpl_to_dict(tmpl), "Template archived successfully.")
