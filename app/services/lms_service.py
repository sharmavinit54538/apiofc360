"""Learning assignments, completion tracking, and real PDF certificates."""
from __future__ import annotations

import calendar
import hashlib
import hmac
import io
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.employee import Employee
from app.models.lms import LMSCertificate, LMSCourse, LMSEnrollment, LMSModule, LMSModuleProgress


def _now() -> datetime:
    return datetime.now(UTC)


def _add_months(value: datetime, months: int) -> datetime:
    month_index = value.year * 12 + value.month - 1 + months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    return value.replace(year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1]))


class LMSService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _course(self, course_id: uuid.UUID, company_id: uuid.UUID) -> LMSCourse:
        course = (await self.session.execute(select(LMSCourse).options(selectinload(LMSCourse.modules)).where(
            LMSCourse.id == course_id, LMSCourse.company_id == company_id,
        ).execution_options(populate_existing=True))).scalar_one_or_none()
        if course is None:
            raise LookupError("LMS course not found.")
        return course

    async def _employee(self, employee_id: uuid.UUID, company_id: uuid.UUID) -> Employee:
        employee = (await self.session.execute(select(Employee).where(
            Employee.id == employee_id, Employee.company_id == company_id,
            Employee.is_deleted.is_(False), Employee.status == "ACTIVE",
        ))).scalar_one_or_none()
        if employee is None:
            raise LookupError("Active employee not found in this tenant.")
        return employee

    async def create_course(
        self, *, company_id: uuid.UUID, code: str, title: str,
        description: str | None = None, target_roles: list[str] | None = None,
        target_departments: list[str] | None = None,
        mandatory_for_compliance: bool = False, validity_months: int | None = None,
    ) -> LMSCourse:
        if validity_months is not None and validity_months < 1:
            raise ValueError("Certificate validity must be at least one month.")
        course = LMSCourse(
            id=uuid.uuid4(), company_id=company_id, code=code.strip().upper(), title=title.strip(),
            description=description, target_roles=[value.upper() for value in (target_roles or [])],
            target_departments=target_departments or [], mandatory_for_compliance=mandatory_for_compliance,
            validity_months=validity_months,
        )
        self.session.add(course)
        await self.session.commit()
        return course

    async def add_module(
        self, course_id: uuid.UUID, *, company_id: uuid.UUID, title: str,
        content_type: str, sequence_number: int, content_url: str | None = None,
        content_text: str | None = None, duration_minutes: int = 0,
    ) -> LMSModule:
        course = await self._course(course_id, company_id)
        if course.status != "DRAFT":
            raise ValueError("Modules can only be added to a draft course.")
        content_type = content_type.upper()
        if content_type not in {"VIDEO", "PDF", "TEXT", "LINK", "SCORM"}:
            raise ValueError("Unsupported LMS module content type.")
        if not content_url and not content_text:
            raise ValueError("Module content URL or text is required.")
        if sequence_number < 1 or duration_minutes < 0:
            raise ValueError("Invalid module sequence or duration.")
        module = LMSModule(
            id=uuid.uuid4(), company_id=company_id, course_id=course_id, title=title.strip(),
            content_type=content_type, content_url=content_url, content_text=content_text,
            sequence_number=sequence_number, duration_minutes=duration_minutes,
        )
        self.session.add(module)
        await self.session.commit()
        return module

    async def publish_and_assign(
        self, course_id: uuid.UUID, *, company_id: uuid.UUID,
        actor_id: uuid.UUID, due_at: datetime | None = None,
    ) -> list[LMSEnrollment]:
        course = await self._course(course_id, company_id)
        if not course.modules:
            raise ValueError("A course requires at least one module before publication.")
        if course.mandatory_for_compliance and due_at is None:
            raise ValueError("Mandatory compliance training requires a completion due date.")
        course.status = "PUBLISHED"
        stmt = select(Employee).where(
            Employee.company_id == company_id, Employee.is_deleted.is_(False), Employee.status == "ACTIVE",
        )
        if course.target_departments:
            stmt = stmt.where(Employee.department.in_(course.target_departments))
        employees = (await self.session.execute(stmt)).scalars().all()
        roles = set(course.target_roles or [])
        enrollments = []
        for employee in employees:
            if roles and (employee.role or "").upper() not in roles:
                continue
            enrollment = (await self.session.execute(select(LMSEnrollment).where(
                LMSEnrollment.course_id == course.id, LMSEnrollment.employee_id == employee.id,
            ))).scalar_one_or_none()
            if enrollment is None:
                enrollment = LMSEnrollment(
                    id=uuid.uuid4(), company_id=company_id, course_id=course.id, employee_id=employee.id,
                    assigned_by=actor_id, assignment_reason="COMPLIANCE" if course.mandatory_for_compliance else "AUTO_TARGET",
                    is_mandatory=course.mandatory_for_compliance, due_at=due_at,
                )
                self.session.add(enrollment)
                await self.session.flush()
                for module in course.modules:
                    self.session.add(LMSModuleProgress(
                        id=uuid.uuid4(), company_id=company_id,
                        enrollment_id=enrollment.id, module_id=module.id,
                    ))
            enrollments.append(enrollment)
        await self.session.commit()
        return enrollments

    async def enroll_employee(
        self, course_id: uuid.UUID, *, company_id: uuid.UUID,
        employee_id: uuid.UUID, actor_id: uuid.UUID, due_at: datetime | None = None,
    ) -> LMSEnrollment:
        course = await self._course(course_id, company_id)
        if course.status != "PUBLISHED":
            raise ValueError("Course is not published.")
        await self._employee(employee_id, company_id)
        existing = (await self.session.execute(select(LMSEnrollment).where(
            LMSEnrollment.course_id == course_id, LMSEnrollment.employee_id == employee_id,
        ))).scalar_one_or_none()
        if existing:
            return existing
        enrollment = LMSEnrollment(
            id=uuid.uuid4(), company_id=company_id, course_id=course_id, employee_id=employee_id,
            assigned_by=actor_id, is_mandatory=course.mandatory_for_compliance, due_at=due_at,
        )
        self.session.add(enrollment)
        await self.session.flush()
        for module in course.modules:
            self.session.add(LMSModuleProgress(
                id=uuid.uuid4(), company_id=company_id, enrollment_id=enrollment.id, module_id=module.id,
            ))
        await self.session.commit()
        return enrollment

    async def complete_module(
        self, enrollment_id: uuid.UUID, module_id: uuid.UUID, *,
        company_id: uuid.UUID, employee_id: uuid.UUID,
    ) -> LMSEnrollment:
        enrollment = (await self.session.execute(select(LMSEnrollment).options(
            selectinload(LMSEnrollment.module_progress),
        ).where(
            LMSEnrollment.id == enrollment_id, LMSEnrollment.company_id == company_id,
        ))).scalar_one_or_none()
        if enrollment is None or enrollment.employee_id != employee_id:
            raise LookupError("LMS enrollment not found for this employee.")
        course = await self._course(enrollment.course_id, company_id)
        if not any(module.id == module_id for module in course.modules):
            raise LookupError("Module does not belong to this course.")
        progress = next((item for item in enrollment.module_progress if item.module_id == module_id), None)
        if progress is None:
            raise LookupError("Module progress not found.")
        if progress.status != "COMPLETED":
            progress.status = "COMPLETED"
            progress.completed_at = _now()
        completed = sum(item.status == "COMPLETED" for item in enrollment.module_progress)
        enrollment.progress_percentage = round(completed * 100 / len(course.modules))
        enrollment.status = "COMPLETED" if completed == len(course.modules) else "IN_PROGRESS"
        if enrollment.status == "COMPLETED":
            enrollment.completed_at = enrollment.completed_at or _now()
            await self._issue_certificate(enrollment, course)
        await self.session.commit()
        return enrollment

    async def _issue_certificate(self, enrollment: LMSEnrollment, course: LMSCourse) -> LMSCertificate:
        existing = (await self.session.execute(select(LMSCertificate).where(
            LMSCertificate.enrollment_id == enrollment.id,
        ))).scalar_one_or_none()
        if existing:
            return existing
        issued_at = enrollment.completed_at or _now()
        number = f"OFC-LMS-{uuid.uuid4().hex[:16].upper()}"
        payload = f"{number}|{enrollment.company_id}|{enrollment.employee_id}|{course.id}|{issued_at.isoformat()}"
        digest = hmac.new(settings.SECRET_KEY.get_secret_value().encode(), payload.encode(), hashlib.sha256).hexdigest()
        certificate = LMSCertificate(
            id=uuid.uuid4(), company_id=enrollment.company_id, enrollment_id=enrollment.id,
            employee_id=enrollment.employee_id, certificate_number=number,
            verification_hash=digest, issued_at=issued_at,
            valid_until=_add_months(issued_at, course.validity_months) if course.validity_months else None,
        )
        self.session.add(certificate)
        await self.session.flush()
        return certificate

    async def certificate_pdf(self, certificate_id: uuid.UUID, *, company_id: uuid.UUID) -> tuple[bytes, str]:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.pdfgen import canvas
        certificate = (await self.session.execute(select(LMSCertificate).where(
            LMSCertificate.id == certificate_id, LMSCertificate.company_id == company_id,
        ))).scalar_one_or_none()
        if certificate is None:
            raise LookupError("LMS certificate not found.")
        enrollment = (await self.session.execute(select(LMSEnrollment).where(
            LMSEnrollment.id == certificate.enrollment_id, LMSEnrollment.company_id == company_id,
        ))).scalar_one()
        course = await self._course(enrollment.course_id, company_id)
        employee = await self._employee(certificate.employee_id, company_id)
        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=landscape(A4))
        width, height = landscape(A4)
        pdf.setTitle(f"Certificate {certificate.certificate_number}")
        pdf.setFont("Helvetica-Bold", 28)
        pdf.drawCentredString(width / 2, height - 110, "Certificate of Completion")
        pdf.setFont("Helvetica", 14)
        pdf.drawCentredString(width / 2, height - 155, "This certifies that")
        pdf.setFont("Helvetica-Bold", 22)
        pdf.drawCentredString(width / 2, height - 200, f"{employee.first_name} {employee.last_name}")
        pdf.setFont("Helvetica", 14)
        pdf.drawCentredString(width / 2, height - 240, f"has successfully completed {course.title}")
        pdf.setFont("Helvetica", 11)
        pdf.drawCentredString(width / 2, 100, f"Certificate: {certificate.certificate_number}")
        pdf.drawCentredString(width / 2, 82, f"Issued: {certificate.issued_at.date().isoformat()}")
        pdf.drawCentredString(width / 2, 64, f"Verification: {certificate.verification_hash[:24]}")
        pdf.showPage()
        pdf.save()
        return buffer.getvalue(), f"{certificate.certificate_number}.pdf"

    async def mandatory_compliance_status(self, *, company_id: uuid.UUID) -> dict:
        rows = (await self.session.execute(select(LMSEnrollment).where(
            LMSEnrollment.company_id == company_id, LMSEnrollment.is_mandatory.is_(True),
        ))).scalars().all()
        now = _now()
        overdue = [row for row in rows if row.status != "COMPLETED" and row.due_at and row.due_at.astimezone(UTC) < now]
        return {
            "assigned": len(rows), "completed": sum(row.status == "COMPLETED" for row in rows),
            "overdue": len(overdue), "overdue_enrollment_ids": [str(row.id) for row in overdue],
        }
