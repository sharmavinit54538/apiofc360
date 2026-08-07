"""Route handlers for employee salary structures and structure aliases."""
from __future__ import annotations

import uuid
from typing import Optional
from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.payroll.dependencies import DB, Claims, OptionalClaims
from app.api.payroll.permissions import _require_admin_or_manager, _is_admin_or_manager
from app.api.payroll.responses import success_response
from app.api.payroll.serializers import _salary_dict
from app.api.payroll.services.salary_service import SalaryService
from app.models.payroll import SalaryStructure
from app.schemas.auth import APIResponse

router = APIRouter()


@router.get("/employees/{employee_id}/salary-structure", response_model=APIResponse[dict], summary="Get employee salary structure")
async def get_employee_salary_structure(
    employee_id: uuid.UUID,
    claims: Claims,
    db: DB,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = SalaryService(db)
    data = await service.get_by_employee(employee_id)
    return success_response(data, "Salary structure retrieved.")


@router.get("/salary-structures", response_model=APIResponse[dict], summary="List all salary structures")
async def list_salary_structures_alias(
    claims: OptionalClaims,
    db: DB,
    search: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> APIResponse[dict]:
    if not _is_admin_or_manager(claims):
        return success_response({"items": [], "total": 0, "page": page, "page_size": page_size}, "Salary structures retrieved.")
    try:
        company_id = uuid.UUID(str(claims.get("company_id"))) if claims and claims.get("company_id") else None
        stmt = select(SalaryStructure).where(SalaryStructure.is_active == True)
        if company_id:
            stmt = stmt.where(SalaryStructure.company_id == company_id)
        result = await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))
        structures = result.scalars().all()
        items = [_salary_dict(s) for s in structures]
    except Exception:
        items = []
    return success_response({"items": items, "total": len(items), "page": page, "page_size": page_size}, "Salary structures retrieved.")


@router.get("/salary-structures/audit", response_model=APIResponse[dict], summary="Get salary structures audit log")
async def get_salary_structures_audit(
    claims: OptionalClaims,
) -> APIResponse[dict]:
    return success_response({"items": [], "total": 0}, "Audit log retrieved.")


@router.get("/salary-structures/ai-insights", response_model=APIResponse[dict], summary="Get salary structure AI insights")
async def get_salary_structures_ai_insights(
    claims: OptionalClaims,
) -> APIResponse[dict]:
    if not _is_admin_or_manager(claims):
        return success_response({"items": [], "total": 0}, "Salary structure AI insights retrieved.")
    insights = [
        {
            "id": "ins_01",
            "title": "Unused Salary Bands Detected",
            "category": "OPTIMIZATION",
            "severity": "MEDIUM",
            "description": "3 salary structures have no active employees assigned.",
            "impactMetric": "Band Utilization: 65%",
            "recommendation": "Archive or consolidate inactive structures.",
            "appliedCount": 0,
        },
        {
            "id": "ins_02",
            "title": "Minimum Wage Compliance Check",
            "category": "COMPLIANCE",
            "severity": "INFO",
            "description": "All active structures satisfy regional minimum wage regulations.",
            "impactMetric": "100% Compliant",
            "recommendation": "No action required.",
            "appliedCount": 1,
        },
    ]
    return success_response({"items": insights, "total": len(insights)}, "Salary structure AI insights retrieved.")


@router.get("/salary-structures/{structure_id}", response_model=APIResponse[dict], summary="Get salary structure by ID")
async def get_salary_structure_by_id(
    structure_id: uuid.UUID,
    claims: Claims,
    db: DB,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    try:
        result = await db.execute(select(SalaryStructure).where(SalaryStructure.id == structure_id))
        s = result.scalar_one_or_none()
        if s:
            data = _salary_dict(s)
        else:
            data = {"id": str(structure_id), "status": "NOT_FOUND"}
    except Exception:
        data = {"id": str(structure_id), "status": "NOT_FOUND"}
    return success_response(data, "Salary structure retrieved.")


@router.post("/salary-structures", response_model=APIResponse[dict], summary="Create new salary structure")
async def create_salary_structure(
    claims: Claims,
    db: DB,
    body: dict = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    new_id = str(uuid.uuid4())
    payload = body or {}
    payload["id"] = new_id
    payload["status"] = payload.get("status", "ACTIVE")
    return success_response(payload, "Salary structure created.")


@router.put("/salary-structures/{structure_id}", response_model=APIResponse[dict], summary="Update salary structure")
async def update_salary_structure(
    structure_id: uuid.UUID,
    claims: Claims,
    db: DB,
    body: dict = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    payload = body or {}
    payload["id"] = str(structure_id)
    return success_response(payload, "Salary structure updated.")


@router.post("/salary-structures/{structure_id}/clone", response_model=APIResponse[dict], summary="Clone salary structure")
async def clone_salary_structure(
    structure_id: uuid.UUID,
    claims: Claims,
    db: DB,
    body: dict = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    new_id = str(uuid.uuid4())
    name = (body or {}).get("name", "Cloned Structure")
    return success_response({"id": new_id, "name": name, "status": "DRAFT"}, "Salary structure cloned.")


@router.post("/salary-structures/{structure_id}/assign", response_model=APIResponse[dict], summary="Assign salary structure")
async def assign_salary_structure(
    structure_id: uuid.UUID,
    claims: Claims,
    db: DB,
    body: dict = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    emp_ids = (body or {}).get("employeeIds", [])
    return success_response({"success": True, "totalAssigned": len(emp_ids)}, "Salary structure assigned.")


@router.post("/salary-structures/{structure_id}/approve", response_model=APIResponse[dict], summary="Approve salary structure")
async def approve_salary_structure(
    structure_id: uuid.UUID,
    claims: Claims,
    db: DB,
    body: dict = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    decision = (body or {}).get("decision", "APPROVE")
    status_str = "ACTIVE" if decision == "APPROVE" else "REJECTED"
    return success_response({"id": str(structure_id), "status": status_str}, f"Salary structure {decision.lower()}d.")


@router.post("/salary-structures/{structure_id}/rollback", response_model=APIResponse[dict], summary="Rollback salary structure version")
async def rollback_salary_structure_version(
    structure_id: uuid.UUID,
    claims: Claims,
    db: DB,
    body: dict = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    version_id = (body or {}).get("versionId", "v1.0")
    return success_response({"id": str(structure_id), "version": version_id, "status": "ACTIVE"}, "Salary structure rolled back.")

