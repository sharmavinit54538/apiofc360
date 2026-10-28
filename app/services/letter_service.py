"""Canonical HR letter substitution, PDF rendering and employee-vault storage."""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Branch, Company, LegalEntity
from app.models.document import DocumentAuditLog, DocumentTemplate, DocumentVersion
from app.models.employee import Employee
from app.models.employee_document import EmployeeDocument
from app.models.exit import EmployeeExit
from app.services.document_service import DocumentService
from app.services.storage_service import DOCUMENTS_DIR_ABSOLUTE

LETTER_TYPES = {
    "OFFER": "Offer Letter", "OFFER_LETTER": "Offer Letter",
    "APPOINTMENT": "Appointment Letter", "APPOINTMENT_LETTER": "Appointment Letter",
    "CONFIRMATION": "Confirmation Letter", "CONFIRMATION_LETTER": "Confirmation Letter",
    "INCREMENT": "Increment Letter", "INCREMENT_LETTER": "Increment Letter",
    "TRANSFER": "Transfer Letter", "TRANSFER_LETTER": "Transfer Letter",
    "RELIEVING": "Relieving Letter", "RELIEVING_LETTER": "Relieving Letter",
    "EXPERIENCE": "Experience Letter", "EXPERIENCE_LETTER": "Experience Letter",
    "WARNING": "Warning Letter", "WARNING_LETTER": "Warning Letter",
}
CANONICAL_LETTER_NAMES = tuple(dict.fromkeys(LETTER_TYPES.values()))
_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


class LetterService:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def substitute(template_body: str, fields: dict[str, Any]) -> str:
        values = {key: "" if value is None else str(value) for key, value in fields.items()}
        return _PLACEHOLDER.sub(lambda match: values.get(match.group(1), match.group(0)), template_body)

    @staticmethod
    def render_pdf(title: str, content: str) -> bytes:
        return DocumentService._render_text_to_pdf(title, content)

    async def employee_fields(self, employee: Employee, extra_fields: dict[str, Any] | None = None) -> dict[str, Any]:
        company = await self.session.get(Company, employee.company_id) if employee.company_id else None
        manager = None
        manager_id = employee.reporting_manager_id or employee.manager_id
        if manager_id:
            manager = await self.session.get(Employee, manager_id)
        latest_exit = (await self.session.execute(select(EmployeeExit).where(
            EmployeeExit.employee_id == employee.id
        ).order_by(EmployeeExit.created_at.desc()).limit(1))).scalar_one_or_none()
        salary = getattr(employee, "basic_salary", None) or getattr(employee, "ctc", None) or 0
        location = employee.work_location or employee.branch or ""
        if employee.branch_id:
            branch = await self.session.get(Branch, employee.branch_id)
            if branch:
                location = branch.name
                if employee.legal_entity_id:
                    legal_entity = await self.session.get(LegalEntity, employee.legal_entity_id)
                    if legal_entity:
                        company_name = legal_entity.name
                    else:
                        company_name = company.name if company else ""
                else:
                    company_name = company.name if company else ""
            else:
                company_name = company.name if company else ""
        else:
            company_name = company.name if company else ""
        fields: dict[str, Any] = {
            "employee_name": f"{employee.first_name or ''} {employee.last_name or ''}".strip(),
            "employee_id": employee.employee_id, "company_name": company_name,
            "department": employee.department or "", "designation": employee.designation or "",
            "joining_date": employee.joining_date.isoformat() if employee.joining_date else "",
            "last_working_day": latest_exit.last_working_date.isoformat() if latest_exit and latest_exit.last_working_date else "",
            "salary": f"{salary:.2f}", "previous_salary": f"{salary:.2f}", "revised_salary": f"{salary:.2f}",
            "manager_name": f"{manager.first_name} {manager.last_name}".strip() if manager else "",
            "location": location, "previous_location": location, "new_location": location,
            "previous_department": employee.department or "", "new_department": employee.department or "",
            "new_designation": employee.designation or "", "today": date.today().isoformat(),
            "confirmation_date": date.today().isoformat(), "effective_date": date.today().isoformat(),
            "incident_date": date.today().isoformat(), "warning_reason": "the issue documented in the HR review",
            "corrective_action": "Complete the corrective plan agreed with your reporting manager and HR.",
            "handbook_version": "1.0",
        }
        fields.update(extra_fields or {})
        return fields

    async def render_letter(
        self, letter_type: str, employee_id: uuid.UUID,
        *, company_id: uuid.UUID | None = None, fields: dict[str, Any] | None = None,
        render_pdf: bool = True,
    ) -> dict[str, Any]:
        key = re.sub(r"[^A-Z0-9]+", "_", letter_type.upper()).strip("_")
        template_name = LETTER_TYPES.get(key)
        if template_name is None:
            raise ValueError(f"Unsupported letter type. Choose one of: {', '.join(sorted(set(LETTER_TYPES)))}")
        employee = await self.session.get(Employee, employee_id)
        if employee is None or employee.is_deleted or (company_id is not None and employee.company_id != company_id):
            raise ValueError("Employee not found in the current tenant.")
        template = (await self.session.execute(select(DocumentTemplate).where(
            DocumentTemplate.name == template_name
        ).limit(1))).scalar_one_or_none()
        if template is None:
            raise ValueError(f"Canonical template '{template_name}' is not seeded.")
        merged_fields = await self.employee_fields(employee, fields)
        content = self.substitute(template.template_body, merged_fields)
        company = await self.session.get(Company, employee.company_id) if employee.company_id else None
        branding = None
        if company is not None:
            from app.services.whitelabel_service import WhiteLabelService
            branding = WhiteLabelService.branding_for(company)
        return {
            "letter_type": key, "template_name": template.name, "employee_id": str(employee.id),
            "content": content, "fields": merged_fields,
            "pdf_bytes": DocumentService._render_text_to_pdf(template.name, content, branding=branding) if render_pdf else None,
        }

    async def save_employee_pdf(
        self, *, employee: Employee, title: str, document_type: str, pdf_bytes: bytes,
        actor_id: uuid.UUID | None, description: str | None = None, commit: bool = False,
    ) -> EmployeeDocument:
        if not pdf_bytes.startswith(b"%PDF"):
            raise ValueError("Rendered document is not a valid PDF.")
        os.makedirs(DOCUMENTS_DIR_ABSOLUTE, exist_ok=True)
        unique_name = f"letter_{uuid.uuid4().hex}.pdf"
        path = os.path.join(DOCUMENTS_DIR_ABSOLUTE, unique_name)
        digest = hashlib.sha256(pdf_bytes).hexdigest()
        with open(path, "wb") as handle:
            handle.write(pdf_bytes)
        uploader_id = actor_id or employee.user_id
        doc = EmployeeDocument(
            employee_id=employee.id, uploaded_by=uploader_id, title=title[:150],
            description=description, document_type=document_type[:100], file_path=path,
            document_url=None, file_name=f"{re.sub(r'[^A-Za-z0-9]+', '_', title).strip('_')}.pdf"[:255],
            file_size=len(pdf_bytes), document_hash=digest, version=1,
            status="PENDING", visibility="PRIVATE", is_verified=False,
        )
        self.session.add(doc)
        try:
            await self.session.flush()
            doc.document_url = f"/api/documents/{doc.id}/download"
            if uploader_id is not None:
                self.session.add(DocumentVersion(
                    employee_doc_id=doc.id, version_number=1, file_path=path,
                    document_hash=digest, uploaded_by=uploader_id,
                ))
                self.session.add(DocumentAuditLog(
                    company_id=employee.company_id, user_id=uploader_id, action="TEMPLATE_GENERATED",
                    target_type="EMPLOYEE_DOC", target_id=doc.id,
                    details=f"Generated PDF letter/document: {title}",
                ))
            await self.session.flush()
            if commit:
                await self.session.commit()
            return doc
        except Exception:
            await self.session.rollback()
            try:
                os.remove(path)
            except OSError:
                pass
            raise

    async def generate_letter(
        self, letter_type: str, employee_id: uuid.UUID, *, company_id: uuid.UUID | None = None,
        fields: dict[str, Any] | None = None, actor_id: uuid.UUID | None = None,
        save: bool = True, commit: bool = True,
    ) -> dict[str, Any]:
        rendered = await self.render_letter(letter_type, employee_id, company_id=company_id, fields=fields)
        rendered.update({"document_id": None, "document_hash": hashlib.sha256(rendered["pdf_bytes"]).hexdigest()})
        if save:
            employee = await self.session.get(Employee, employee_id)
            doc = await self.save_employee_pdf(
                employee=employee, title=rendered["template_name"], document_type=rendered["letter_type"],
                pdf_bytes=rendered["pdf_bytes"], actor_id=actor_id,
                description=f"Generated from canonical template {rendered['template_name']}", commit=commit,
            )
            rendered["document_id"] = str(doc.id)
        return rendered


__all__ = ["LetterService", "LETTER_TYPES", "CANONICAL_LETTER_NAMES"]
