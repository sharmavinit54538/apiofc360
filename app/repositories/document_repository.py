"""Document Management repository layer: direct database operations."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.document import (
    DocumentCategory,
    CompanyDocument,
    DocumentTemplate,
    DocumentVersion,
    DocumentSignature,
    DocumentVerification,
    DocumentExpiryTracking,
    DocumentAuditLog,
)
from app.models.employee_document import EmployeeDocument
from app.models.employee import Employee
from app.models.user import User

logger = logging.getLogger(__name__)


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _emp_doc_active_filter(self):
        return EmployeeDocument.is_deleted == False  # noqa: E712

    def _company_doc_active_filter(self):
        return CompanyDocument.is_deleted == False  # noqa: E712

    # ------------------------------------------------------------------
    # Categories Operations
    # ------------------------------------------------------------------

    async def get_category_by_id(self, category_uuid: uuid.UUID) -> DocumentCategory | None:
        result = await self.session.execute(
            select(DocumentCategory).where(DocumentCategory.id == category_uuid)
        )
        return result.scalar_one_or_none()

    async def get_category_by_code(self, code: str) -> DocumentCategory | None:
        result = await self.session.execute(
            select(DocumentCategory).where(func.lower(DocumentCategory.code) == code.lower())
        )
        return result.scalar_one_or_none()

    async def create_category(self, **kwargs: Any) -> DocumentCategory:
        obj = DocumentCategory(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def list_categories(self, is_company: bool | None = None) -> list[DocumentCategory]:
        stmt = select(DocumentCategory)
        if is_company is not None:
            stmt = stmt.where(DocumentCategory.is_company == is_company)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Employee Document CRUD
    # ------------------------------------------------------------------

    async def create_employee_document(self, **kwargs: Any) -> EmployeeDocument:
        obj = EmployeeDocument(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_employee_document_by_id(self, doc_uuid: uuid.UUID) -> EmployeeDocument | None:
        result = await self.session.execute(
            select(EmployeeDocument)
            .where(and_(EmployeeDocument.id == doc_uuid, self._emp_doc_active_filter()))
            .options(
                selectinload(EmployeeDocument.category),
                selectinload(EmployeeDocument.employee),
                selectinload(EmployeeDocument.versions),
                selectinload(EmployeeDocument.signatures).selectinload(DocumentSignature.signer),
                selectinload(EmployeeDocument.verifications),
            )
        )
        return result.scalar_one_or_none()

    async def list_employee_documents(
        self,
        employee_id: uuid.UUID | None = None,
        category_id: uuid.UUID | None = None,
        status: str | None = None,
        visibility: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EmployeeDocument]:
        stmt = (
            select(EmployeeDocument)
            .where(self._emp_doc_active_filter())
            .options(
                selectinload(EmployeeDocument.category),
                selectinload(EmployeeDocument.employee),
            )
            .execution_options(bypass_tenant=True)
        )

        if employee_id:
            stmt = stmt.where(EmployeeDocument.employee_id == employee_id)
        if category_id:
            stmt = stmt.where(EmployeeDocument.category_id == category_id)
        if status:
            stmt = stmt.where(EmployeeDocument.status == status.upper())
        if visibility:
            stmt = stmt.where(EmployeeDocument.visibility == visibility.upper())
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    EmployeeDocument.title.ilike(pattern),
                    EmployeeDocument.description.ilike(pattern),
                    EmployeeDocument.tags.ilike(pattern),
                    EmployeeDocument.document_type.ilike(pattern),
                )
            )

        stmt = stmt.order_by(EmployeeDocument.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_employee_document(self, doc_uuid: uuid.UUID, **kwargs: Any) -> None:
        await self.session.execute(
            update(EmployeeDocument).where(EmployeeDocument.id == doc_uuid).values(**kwargs)
        )

    async def soft_delete_employee_document(self, doc_uuid: uuid.UUID) -> None:
        await self.session.execute(
            update(EmployeeDocument)
            .where(EmployeeDocument.id == doc_uuid)
            .values(is_deleted=True, deleted_at=func.now())
        )

    # ------------------------------------------------------------------
    # Company Document CRUD
    # ------------------------------------------------------------------

    async def create_company_document(self, **kwargs: Any) -> CompanyDocument:
        obj = CompanyDocument(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_company_document_by_id(self, doc_uuid: uuid.UUID) -> CompanyDocument | None:
        result = await self.session.execute(
            select(CompanyDocument)
            .where(and_(CompanyDocument.id == doc_uuid, self._company_doc_active_filter()))
            .options(
                selectinload(CompanyDocument.category),
                selectinload(CompanyDocument.versions),
            )
        )
        return result.scalar_one_or_none()

    async def list_company_documents(
        self,
        category_id: uuid.UUID | None = None,
        department: str | None = None,
        branch: str | None = None,
        visibility: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CompanyDocument]:
        stmt = select(CompanyDocument).where(self._company_doc_active_filter())

        if category_id:
            stmt = stmt.where(CompanyDocument.category_id == category_id)
        if department:
            stmt = stmt.where(CompanyDocument.department == department)
        if branch:
            stmt = stmt.where(CompanyDocument.branch == branch)
        if visibility:
            stmt = stmt.where(CompanyDocument.visibility == visibility.upper())
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    CompanyDocument.title.ilike(pattern),
                    CompanyDocument.description.ilike(pattern),
                )
            )

        stmt = stmt.order_by(CompanyDocument.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_company_document(self, doc_uuid: uuid.UUID, **kwargs: Any) -> None:
        await self.session.execute(
            update(CompanyDocument).where(CompanyDocument.id == doc_uuid).values(**kwargs)
        )

    async def soft_delete_company_document(self, doc_uuid: uuid.UUID) -> None:
        await self.session.execute(
            update(CompanyDocument)
            .where(CompanyDocument.id == doc_uuid)
            .values(is_deleted=True, deleted_at=func.now())
        )

    # ------------------------------------------------------------------
    # Document Templates CRUD
    # ------------------------------------------------------------------

    async def create_template(self, **kwargs: Any) -> DocumentTemplate:
        obj = DocumentTemplate(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_template_by_id(self, template_uuid: uuid.UUID) -> DocumentTemplate | None:
        result = await self.session.execute(
            select(DocumentTemplate).where(DocumentTemplate.id == template_uuid)
        )
        return result.scalar_one_or_none()

    async def list_templates(self) -> list[DocumentTemplate]:
        result = await self.session.execute(
            select(DocumentTemplate).order_by(DocumentTemplate.name.asc())
        )
        return list(result.scalars().all())

    async def update_template(self, template_uuid: uuid.UUID, **kwargs: Any) -> None:
        await self.session.execute(
            update(DocumentTemplate).where(DocumentTemplate.id == template_uuid).values(**kwargs)
        )

    async def delete_template(self, template_uuid: uuid.UUID) -> None:
        await self.session.execute(
            delete(DocumentTemplate).where(DocumentTemplate.id == template_uuid)
        )

    # ------------------------------------------------------------------
    # Versions & Signatures & Verifications
    # ------------------------------------------------------------------

    async def create_version(self, **kwargs: Any) -> DocumentVersion:
        obj = DocumentVersion(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def create_signature_request(self, **kwargs: Any) -> DocumentSignature:
        obj = DocumentSignature(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_signature_by_id(self, sig_uuid: uuid.UUID) -> DocumentSignature | None:
        result = await self.session.execute(
            select(DocumentSignature).where(DocumentSignature.id == sig_uuid)
        )
        return result.scalar_one_or_none()

    async def get_active_signature_request(self, doc_uuid: uuid.UUID) -> DocumentSignature | None:
        result = await self.session.execute(
            select(DocumentSignature).where(
                and_(
                    DocumentSignature.employee_doc_id == doc_uuid,
                    DocumentSignature.status == "PENDING",
                )
            )
        )
        return result.scalar_one_or_none()

    async def update_signature_status(self, sig_uuid: uuid.UUID, **kwargs: Any) -> None:
        await self.session.execute(
            update(DocumentSignature).where(DocumentSignature.id == sig_uuid).values(**kwargs)
        )

    async def create_verification(self, **kwargs: Any) -> DocumentVerification:
        obj = DocumentVerification(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    # ------------------------------------------------------------------
    # Expiry Tracking queries
    # ------------------------------------------------------------------

    async def get_expiring_documents(self, threshold_date: date) -> list[EmployeeDocument]:
        """Get documents expiring within the threshold date that are active."""
        stmt = (
            select(EmployeeDocument)
            .where(
                and_(
                    self._emp_doc_active_filter(),
                    EmployeeDocument.expiry_date != None,  # noqa: E711
                    EmployeeDocument.expiry_date >= date.today(),
                    EmployeeDocument.expiry_date <= threshold_date,
                )
            )
            .options(selectinload(EmployeeDocument.employee))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_expired_documents(self) -> list[EmployeeDocument]:
        """Get already expired documents."""
        stmt = (
            select(EmployeeDocument)
            .where(
                and_(
                    self._emp_doc_active_filter(),
                    EmployeeDocument.expiry_date != None,  # noqa: E711
                    EmployeeDocument.expiry_date < date.today(),
                )
            )
            .options(selectinload(EmployeeDocument.employee))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Audit Logs
    # ------------------------------------------------------------------

    async def create_audit_log(self, **kwargs: Any) -> DocumentAuditLog:
        obj = DocumentAuditLog(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj
