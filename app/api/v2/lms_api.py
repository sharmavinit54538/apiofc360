"""LMS course administration, employee progress, and certificate APIs."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v2.enterprise_dependencies import (
    Claims, Session, company_id, ok, require_admin, role, translate, user_id,
)
from app.models.employee import Employee
from app.models.lms import LMSCertificate, LMSEnrollment
from app.services.lms_service import LMSService

router = APIRouter(prefix="/lms", tags=["Learning Management v2"])


class CourseRequest(BaseModel):
    code: str
    title: str
    description: str | None = None
    target_roles: list[str] = Field(default_factory=list)
    target_departments: list[str] = Field(default_factory=list)
    mandatory_for_compliance: bool = False
    validity_months: int | None = Field(None, ge=1)


class ModuleRequest(BaseModel):
    title: str
    content_type: str
    sequence_number: int = Field(ge=1)
    content_url: str | None = None
    content_text: str | None = None
    duration_minutes: int = Field(0, ge=0)


class PublishRequest(BaseModel):
    due_at: datetime | None = None


class EnrollmentRequest(BaseModel):
    employee_id: uuid.UUID
    due_at: datetime | None = None


async def _current_employee(db, claims) -> Employee:
    employee = (await db.execute(select(Employee).where(
        Employee.user_id == user_id(claims), Employee.company_id == company_id(claims),
        Employee.is_deleted.is_(False),
    ))).scalar_one_or_none()
    if employee is None:
        raise LookupError("Employee profile not found for current user.")
    return employee


@router.post("/courses", status_code=201)
async def create_course(body: CourseRequest, claims: Claims, db: Session):
    require_admin(claims)
    try:
        course = await LMSService(db).create_course(company_id=company_id(claims), **body.model_dump())
        return ok({"id": str(course.id), "status": course.status, "mandatory_for_compliance": course.mandatory_for_compliance})
    except ValueError as exc:
        translate(exc)


@router.post("/courses/{course_id}/modules", status_code=201)
async def add_module(course_id: uuid.UUID, body: ModuleRequest, claims: Claims, db: Session):
    require_admin(claims)
    try:
        module = await LMSService(db).add_module(course_id, company_id=company_id(claims), **body.model_dump())
        return ok({"id": str(module.id), "sequence_number": module.sequence_number})
    except (ValueError, LookupError) as exc:
        translate(exc)


@router.post("/courses/{course_id}/publish")
async def publish_course(course_id: uuid.UUID, body: PublishRequest, claims: Claims, db: Session):
    require_admin(claims)
    try:
        rows = await LMSService(db).publish_and_assign(
            course_id, company_id=company_id(claims), actor_id=user_id(claims), due_at=body.due_at,
        )
        return ok({"assigned_count": len(rows), "enrollment_ids": [str(row.id) for row in rows]}, "Course published and targeted employees assigned")
    except (ValueError, LookupError) as exc:
        translate(exc)


@router.post("/courses/{course_id}/enrollments", status_code=201)
async def enroll_employee(course_id: uuid.UUID, body: EnrollmentRequest, claims: Claims, db: Session):
    require_admin(claims)
    try:
        row = await LMSService(db).enroll_employee(
            course_id, company_id=company_id(claims), actor_id=user_id(claims), **body.model_dump(),
        )
        return ok({"id": str(row.id), "status": row.status})
    except (ValueError, LookupError) as exc:
        translate(exc)


@router.post("/enrollments/{enrollment_id}/modules/{module_id}/complete")
async def complete_module(enrollment_id: uuid.UUID, module_id: uuid.UUID, claims: Claims, db: Session):
    try:
        employee = await _current_employee(db, claims)
        row = await LMSService(db).complete_module(
            enrollment_id, module_id, company_id=company_id(claims), employee_id=employee.id,
        )
        return ok({"id": str(row.id), "status": row.status, "progress_percentage": row.progress_percentage})
    except (ValueError, LookupError) as exc:
        translate(exc)


@router.get("/certificates/{certificate_id}/pdf")
async def download_certificate(certificate_id: uuid.UUID, claims: Claims, db: Session):
    try:
        certificate = (await db.execute(select(LMSCertificate).where(
            LMSCertificate.id == certificate_id, LMSCertificate.company_id == company_id(claims),
        ))).scalar_one_or_none()
        if certificate is None:
            raise LookupError("LMS certificate not found.")
        if role(claims) not in {"admin", "hr_admin", "super_admin", "it_admin", "manager"}:
            employee = await _current_employee(db, claims)
            if certificate.employee_id != employee.id:
                raise PermissionError("You may only download your own certificate.")
        content, filename = await LMSService(db).certificate_pdf(certificate_id, company_id=company_id(claims))
        return Response(content=content, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    except (ValueError, LookupError, PermissionError) as exc:
        translate(exc)


@router.get("/compliance/status")
async def compliance_training_status(claims: Claims, db: Session):
    require_admin(claims)
    return ok(await LMSService(db).mandatory_compliance_status(company_id=company_id(claims)))
