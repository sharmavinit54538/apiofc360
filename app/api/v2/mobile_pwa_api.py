"""Mobile PWA APIs for secure field workforce workflows."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.employee import Employee
from app.models.hr_workflow import HRWorkflowStepInstance
from app.models.leave import LeaveRequest
from app.models.payroll import Payslip
from app.services.hr_workflow_service import HRWorkflowService
from app.services.leave_service import LeaveService
from app.services.mobile_pwa_service import MobilePWAService
from app.services.payroll.payslip_service import PayslipService

router = APIRouter(prefix="/pwa", tags=["Mobile PWA v2"])
Claims = Annotated[dict, Depends(get_current_user_claims)]
Session = Annotated[AsyncSession, Depends(get_db_session)]


def _uid(claims: dict) -> uuid.UUID:
    return uuid.UUID(str(claims["sub"]))


def _company(claims: dict) -> uuid.UUID:
    if not claims.get("company_id"):
        raise HTTPException(status_code=403, detail="Tenant claim is required")
    return uuid.UUID(str(claims["company_id"]))


def _role(claims: dict) -> str:
    value = claims.get("role") or claims.get("user_role") or "employee"
    if isinstance(value, dict):
        value = value.get("name", "employee")
    return str(getattr(value, "value", value)).lower()


async def _employee(db: AsyncSession, claims: dict) -> Employee:
    employee = (await db.execute(select(Employee).where(
        Employee.user_id == _uid(claims), Employee.company_id == _company(claims), Employee.is_deleted.is_(False),
    ))).scalar_one_or_none()
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee profile not found")
    return employee


class PushSubscriptionRequest(BaseModel):
    provider: str = "WEBPUSH"
    endpoint_or_token: str | None = None
    endpoint: str | None = None
    token: str | None = None
    keys: dict[str, Any] | None = None
    device_id: str | None = None


class MobileAttendanceRequest(BaseModel):
    image_base64: str = Field(min_length=1)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float | None = Field(None, ge=0)
    notes: str | None = Field(None, max_length=500)
    device_info: str | None = Field(None, max_length=255)
    client_captured_at: datetime | None = None


class ApprovalDecisionRequest(BaseModel):
    decision: str
    notes: str | None = None
    rejection_reason: str | None = None


@router.post("/push-subscriptions", status_code=201)
async def subscribe_push(
    body: PushSubscriptionRequest, request: Request, claims: Claims, db: Session,
    user_agent: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    endpoint = body.endpoint_or_token or body.endpoint or body.token
    if not endpoint:
        raise HTTPException(status_code=422, detail="endpoint_or_token, endpoint, or token is required")
    try:
        subscription = await MobilePWAService(db).subscribe_push(
            user_id=_uid(claims), company_id=_company(claims), provider=body.provider,
            endpoint_or_token=endpoint, keys=body.keys, device_id=body.device_id, user_agent=user_agent,
        )
        return {"success": True, "data": {"id": str(subscription.id), "provider": subscription.provider, "active": subscription.is_active}}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _mark_attendance(
    operation: str, body: MobileAttendanceRequest, key: str, request: Request, claims: dict, db: AsyncSession,
) -> dict[str, Any]:
    try:
        result = await MobilePWAService(db).mark_attendance(
            user_id=_uid(claims), company_id=_company(claims), operation=operation,
            idempotency_key=key, image_base64=body.image_base64,
            latitude=body.latitude, longitude=body.longitude, accuracy=body.accuracy,
            notes=body.notes, device_info=body.device_info,
            ip_address=request.client.host if request.client else None,
            client_captured_at=body.client_captured_at.isoformat() if body.client_captured_at else None,
        )
        return {"success": True, "data": result, "message": "Attendance replayed without duplicate punch." if result["idempotent_replay"] else "Face and geofence verified attendance recorded."}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/attendance/check-in")
async def mobile_check_in(
    body: MobileAttendanceRequest, request: Request, claims: Claims, db: Session,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
) -> dict[str, Any]:
    return await _mark_attendance("CHECK_IN", body, idempotency_key, request, claims, db)


@router.post("/attendance/check-out")
async def mobile_check_out(
    body: MobileAttendanceRequest, request: Request, claims: Claims, db: Session,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
) -> dict[str, Any]:
    return await _mark_attendance("CHECK_OUT", body, idempotency_key, request, claims, db)


@router.get("/approvals")
async def mobile_approval_cards(claims: Claims, db: Session) -> dict[str, Any]:
    cards: list[dict[str, Any]] = []
    steps = (await db.execute(
        select(HRWorkflowStepInstance)
        .options(selectinload(HRWorkflowStepInstance.instance))
        .where(HRWorkflowStepInstance.assigned_to_user_id == _uid(claims), HRWorkflowStepInstance.status == "PENDING")
        .order_by(HRWorkflowStepInstance.step_order)
    )).scalars().all()
    cards.extend({
        "type": "WORKFLOW", "id": str(step.id), "title": step.step_name,
        "context_id": str(step.instance.context_id), "status": step.status,
    } for step in steps)

    employee = (await db.execute(select(Employee).where(Employee.user_id == _uid(claims)))).scalar_one_or_none()
    leave_stmt = select(LeaveRequest).join(Employee, Employee.id == LeaveRequest.employee_id).where(
        Employee.company_id == _company(claims), LeaveRequest.status == "PENDING",
    )
    if _role(claims) == "manager":
        if employee is None:
            leave_stmt = leave_stmt.where(False)
        else:
            leave_stmt = leave_stmt.where(or_(Employee.manager_id == employee.id, Employee.reporting_manager_id == employee.id))
    elif _role(claims) not in {"admin", "hr_admin", "super_admin"}:
        leave_stmt = leave_stmt.where(False)
    leaves = (await db.execute(leave_stmt.order_by(LeaveRequest.created_at))).scalars().all()
    cards.extend({
        "type": "LEAVE", "id": str(leave.id), "title": f"{leave.leave_type} approval",
        "context_id": str(leave.id), "start_date": leave.start_date.isoformat(),
        "end_date": leave.end_date.isoformat(), "status": leave.status,
    } for leave in leaves)
    return {"success": True, "data": cards}


@router.post("/approvals/leave/{leave_id}")
async def mobile_leave_approval(leave_id: uuid.UUID, body: ApprovalDecisionRequest, claims: Claims, db: Session) -> dict[str, Any]:
    decision = body.decision.upper()
    if decision not in {"APPROVED", "REJECTED"}:
        raise HTTPException(status_code=400, detail="Decision must be APPROVED or REJECTED")
    leave = await LeaveService(db).review_leave(
        leave_id, decision, _uid(claims), _role(claims), _company(claims),
        rejection_reason=body.rejection_reason or body.notes,
    )
    return {"success": True, "data": {"id": str(leave.id), "status": leave.status}}


@router.post("/approvals/{step_id}")
async def mobile_workflow_approval(step_id: uuid.UUID, body: ApprovalDecisionRequest, claims: Claims, db: Session) -> dict[str, Any]:
    step = await db.get(HRWorkflowStepInstance, step_id)
    if step is None or step.assigned_to_user_id != _uid(claims):
        raise HTTPException(status_code=404, detail="Approval card not found")
    if step.status != "PENDING":
        raise HTTPException(status_code=409, detail="Approval card is no longer pending")
    decision = body.decision.upper()
    changed = await HRWorkflowService(db).evaluate_step_decision(
        step_id, decision, notes=body.notes, user_id=_uid(claims),
    )
    if not changed:
        raise HTTPException(status_code=404, detail="Approval card not found")
    return {"success": True, "data": {"id": str(step_id), "status": decision}}


@router.post("/documents/camera", status_code=201)
async def camera_document_upload(
    claims: Claims, db: Session,
    document_type: Annotated[str, Form()], file: Annotated[UploadFile, File()],
    captured_at: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    employee = await _employee(db, claims)
    content = await file.read(10 * 1024 * 1024 + 1)
    try:
        document = await MobilePWAService(db).save_camera_document(
            employee_id=employee.id, user_id=_uid(claims), document_type=document_type,
            file_name=file.filename or "camera-document", content_type=file.content_type or "",
            content=content, captured_at=captured_at,
        )
        return {"success": True, "data": {"id": str(document.id), "status": document.status, "sha256": document.document_hash}}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/payslips")
async def mobile_payslips(claims: Claims, db: Session) -> dict[str, Any]:
    employee = await _employee(db, claims)
    payslips = (await db.execute(select(Payslip).where(
        Payslip.employee_id == employee.id, Payslip.company_id == _company(claims),
    ).order_by(Payslip.period_year.desc(), Payslip.period_month.desc()))).scalars().all()
    return {"success": True, "data": [{
        "run_id": str(p.payroll_run_id), "period_month": p.period_month, "period_year": p.period_year,
        "payslip_number": p.payslip_number, "net_pay": float(p.net_pay), "payment_status": p.payment_status,
        "pdf_url": f"/api/v2/pwa/payslips/{p.payroll_run_id}/pdf",
    } for p in payslips]}


@router.get("/payslips/{run_id}")
async def mobile_payslip_detail(run_id: uuid.UUID, claims: Claims, db: Session) -> dict[str, Any]:
    employee = await _employee(db, claims)
    detail = await PayslipService.get_payslip_detail(db, run_id, employee.id)
    if detail.get("company_id") and uuid.UUID(str(detail["company_id"])) != _company(claims):
        raise HTTPException(status_code=404, detail="Payslip not found")
    return {"success": True, "data": detail}


@router.get("/payslips/{run_id}/pdf")
async def mobile_payslip_pdf(run_id: uuid.UUID, claims: Claims, db: Session) -> Response:
    employee = await _employee(db, claims)
    payslip = (await db.execute(select(Payslip).where(
        Payslip.payroll_run_id == run_id, Payslip.employee_id == employee.id,
        Payslip.company_id == _company(claims),
    ))).scalar_one_or_none()
    if payslip is None:
        raise HTTPException(status_code=404, detail="Payslip not found")
    content, filename = await PayslipService.get_payslip_file(db, run_id, employee.id)
    payslip.download_count = (payslip.download_count or 0) + 1
    await db.commit()
    return Response(content=content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{filename}"'})
