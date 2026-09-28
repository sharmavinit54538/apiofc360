"""Document Management repository layer: direct database operations."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta
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
        stmt = stmt.order_by(DocumentCategory.name.asc())
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

    async def get_employee_document_by_id(
        self,
        doc_uuid: uuid.UUID,
        company_id: uuid.UUID | None = None,
    ) -> EmployeeDocument | None:
        stmt = (
            select(EmployeeDocument)
            .where(and_(EmployeeDocument.id == doc_uuid, self._emp_doc_active_filter()))
            .options(
                selectinload(EmployeeDocument.category),
                selectinload(EmployeeDocument.employee),
                selectinload(EmployeeDocument.uploader),
                selectinload(EmployeeDocument.versions),
                selectinload(EmployeeDocument.signatures).selectinload(DocumentSignature.signer),
                selectinload(EmployeeDocument.verifications),
            )
        )
        if company_id is not None:
            stmt = stmt.join(Employee, EmployeeDocument.employee_id == Employee.id).where(Employee.company_id == company_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_employee_documents(
        self,
        company_id: uuid.UUID | None = None,
        employee_id: uuid.UUID | None = None,
        employee_ids: list[uuid.UUID] | None = None,
        category_id: uuid.UUID | None = None,
        status: str | None = None,
        visibility: str | None = None,
        search: str | None = None,
        limit: int = 20,
        offset: int = 0,
        sort_by: str = "created_at",
        order: str = "desc",
        is_super_admin: bool = False,
    ) -> tuple[list[EmployeeDocument], int]:
        # Handle empty employee_ids filter (e.g. employee without permissions)
        if employee_ids is not None and len(employee_ids) == 0:
            return [], 0

        stmt = select(EmployeeDocument).where(self._emp_doc_active_filter())
        count_stmt = select(func.count(EmployeeDocument.id)).where(self._emp_doc_active_filter())

        # Always join Employee when company_id or search on employee fields is present
        need_employee_join = company_id is not None or bool(search)
        if need_employee_join:
            stmt = stmt.join(Employee, EmployeeDocument.employee_id == Employee.id)
            count_stmt = count_stmt.join(Employee, EmployeeDocument.employee_id == Employee.id)

        if company_id is not None:
            stmt = stmt.where(Employee.company_id == company_id)
            count_stmt = count_stmt.where(Employee.company_id == company_id)
        elif is_super_admin:
            stmt = stmt.execution_options(bypass_tenant=True)
            count_stmt = count_stmt.execution_options(bypass_tenant=True)

        if employee_id:
            stmt = stmt.where(EmployeeDocument.employee_id == employee_id)
            count_stmt = count_stmt.where(EmployeeDocument.employee_id == employee_id)

        if employee_ids is not None:
            stmt = stmt.where(EmployeeDocument.employee_id.in_(employee_ids))
            count_stmt = count_stmt.where(EmployeeDocument.employee_id.in_(employee_ids))

        if category_id:
            stmt = stmt.where(EmployeeDocument.category_id == category_id)
            count_stmt = count_stmt.where(EmployeeDocument.category_id == category_id)

        if status:
            stmt = stmt.where(EmployeeDocument.status == status.upper())
            count_stmt = count_stmt.where(EmployeeDocument.status == status.upper())

        if visibility:
            stmt = stmt.where(EmployeeDocument.visibility == visibility.upper())
            count_stmt = count_stmt.where(EmployeeDocument.visibility == visibility.upper())

        if search:
            # Escape % and _ for safe ILIKE
            escaped_search = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped_search}%"
            search_cond = or_(
                EmployeeDocument.title.ilike(pattern, escape="\\"),
                EmployeeDocument.description.ilike(pattern, escape="\\"),
                EmployeeDocument.tags.ilike(pattern, escape="\\"),
                EmployeeDocument.document_type.ilike(pattern, escape="\\"),
                EmployeeDocument.file_name.ilike(pattern, escape="\\"),
                Employee.first_name.ilike(pattern, escape="\\"),
                Employee.last_name.ilike(pattern, escape="\\"),
                Employee.employee_id.ilike(pattern, escape="\\"),
            )
            stmt = stmt.where(search_cond)
            count_stmt = count_stmt.where(search_cond)

        # Get total count
        count_res = await self.session.execute(count_stmt)
        total = count_res.scalar() or 0

        # Eager load relationships to prevent N+1 queries
        stmt = stmt.options(
            selectinload(EmployeeDocument.category),
            selectinload(EmployeeDocument.employee),
            selectinload(EmployeeDocument.uploader),
            selectinload(EmployeeDocument.signatures).selectinload(DocumentSignature.signer),
            selectinload(EmployeeDocument.verifications),
        )

        # Sorting
        sort_map = {
            "created_at": EmployeeDocument.created_at,
            "expiry_date": EmployeeDocument.expiry_date,
            "title": EmployeeDocument.title,
            "status": EmployeeDocument.status,
            "updated_at": EmployeeDocument.updated_at,
        }
        sort_col = sort_map.get(sort_by.lower(), EmployeeDocument.created_at)
        if order.lower() == "asc":
            stmt = stmt.order_by(sort_col.asc())
        else:
            stmt = stmt.order_by(sort_col.desc())

        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        records = list(result.scalars().all())
        return records, total

    async def update_employee_document(
        self,
        doc_uuid: uuid.UUID,
        company_id: uuid.UUID | None = None,
        **kwargs: Any,
    ) -> None:
        if company_id is not None:
            doc = await self.get_employee_document_by_id(doc_uuid, company_id=company_id)
            if not doc:
                return
        await self.session.execute(
            update(EmployeeDocument).where(EmployeeDocument.id == doc_uuid).values(**kwargs)
        )

    async def soft_delete_employee_document(
        self,
        doc_uuid: uuid.UUID,
        company_id: uuid.UUID | None = None,
    ) -> None:
        if company_id is not None:
            doc = await self.get_employee_document_by_id(doc_uuid, company_id=company_id)
            if not doc:
                return
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

    async def get_company_document_by_id(
        self,
        doc_uuid: uuid.UUID,
        company_id: uuid.UUID | None = None,
    ) -> CompanyDocument | None:
        stmt = (
            select(CompanyDocument)
            .where(and_(CompanyDocument.id == doc_uuid, self._company_doc_active_filter()))
            .options(
                selectinload(CompanyDocument.category),
                selectinload(CompanyDocument.uploader),
                selectinload(CompanyDocument.versions),
            )
        )
        if company_id is not None:
            stmt = stmt.where(CompanyDocument.company_id == company_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_company_documents(
        self,
        company_id: uuid.UUID | None = None,
        category_id: uuid.UUID | None = None,
        department: str | None = None,
        branch: str | None = None,
        visibility: str | None = None,
        search: str | None = None,
        limit: int = 20,
        offset: int = 0,
        caller_role: str | None = None,
        viewer_dept: str | None = None,
        viewer_branch: str | None = None,
        is_admin: bool = False,
    ) -> tuple[list[CompanyDocument], int]:
        stmt = select(CompanyDocument).where(self._company_doc_active_filter())
        count_stmt = select(func.count(CompanyDocument.id)).where(self._company_doc_active_filter())

        if company_id is not None:
            stmt = stmt.where(CompanyDocument.company_id == company_id)
            count_stmt = count_stmt.where(CompanyDocument.company_id == company_id)

        # Server-side visibility scoping for non-admin viewers
        if not is_admin:
            hidden_for_all = and_(
                CompanyDocument.visibility != "HR_ONLY",
                CompanyDocument.visibility != "PRIVATE",
            )
            stmt = stmt.where(hidden_for_all)
            count_stmt = count_stmt.where(hidden_for_all)

            if caller_role != "manager":
                stmt = stmt.where(CompanyDocument.visibility != "MANAGER_ONLY")
                count_stmt = count_stmt.where(CompanyDocument.visibility != "MANAGER_ONLY")

            # Scope by PUBLIC or (DEPARTMENT and match)
            if viewer_dept:
                dept_cond = or_(
                    CompanyDocument.visibility == "PUBLIC",
                    and_(
                        CompanyDocument.visibility == "DEPARTMENT",
                        CompanyDocument.department == viewer_dept,
                    ),
                    CompanyDocument.visibility == "MANAGER_ONLY" if caller_role == "manager" else False,
                )
            else:
                dept_cond = or_(
                    CompanyDocument.visibility == "PUBLIC",
                    CompanyDocument.visibility == "MANAGER_ONLY" if caller_role == "manager" else False,
                )
            stmt = stmt.where(dept_cond)
            count_stmt = count_stmt.where(dept_cond)

            # Scope by Branch
            if viewer_branch:
                branch_cond = or_(
                    CompanyDocument.branch == None,  # noqa: E711
                    CompanyDocument.branch == viewer_branch,
                )
            else:
                branch_cond = CompanyDocument.branch == None  # noqa: E711
            stmt = stmt.where(branch_cond)
            count_stmt = count_stmt.where(branch_cond)

        # Client-supplied filters only narrow down
        if category_id:
            stmt = stmt.where(CompanyDocument.category_id == category_id)
            count_stmt = count_stmt.where(CompanyDocument.category_id == category_id)
        if department:
            stmt = stmt.where(CompanyDocument.department == department)
            count_stmt = count_stmt.where(CompanyDocument.department == department)
        if branch:
            stmt = stmt.where(CompanyDocument.branch == branch)
            count_stmt = count_stmt.where(CompanyDocument.branch == branch)
        if visibility:
            stmt = stmt.where(CompanyDocument.visibility == visibility.upper())
            count_stmt = count_stmt.where(CompanyDocument.visibility == visibility.upper())
        if search:
            escaped_search = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped_search}%"
            search_cond = or_(
                CompanyDocument.title.ilike(pattern, escape="\\"),
                CompanyDocument.description.ilike(pattern, escape="\\"),
                CompanyDocument.file_name.ilike(pattern, escape="\\"),
            )
            stmt = stmt.where(search_cond)
            count_stmt = count_stmt.where(search_cond)

        # Count total
        count_res = await self.session.execute(count_stmt)
        total = count_res.scalar() or 0

        # Eager load relations
        stmt = stmt.options(
            selectinload(CompanyDocument.category),
            selectinload(CompanyDocument.uploader),
            selectinload(CompanyDocument.versions),
        )

        stmt = stmt.order_by(CompanyDocument.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        records = list(result.scalars().all())
        return records, total

    async def update_company_document(
        self,
        doc_uuid: uuid.UUID,
        company_id: uuid.UUID | None = None,
        **kwargs: Any,
    ) -> None:
        stmt = update(CompanyDocument).where(CompanyDocument.id == doc_uuid)
        if company_id is not None:
            stmt = stmt.where(CompanyDocument.company_id == company_id)
        await self.session.execute(stmt.values(**kwargs))

    async def soft_delete_company_document(
        self,
        doc_uuid: uuid.UUID,
        company_id: uuid.UUID | None = None,
    ) -> None:
        stmt = update(CompanyDocument).where(CompanyDocument.id == doc_uuid)
        if company_id is not None:
            stmt = stmt.where(CompanyDocument.company_id == company_id)
        await self.session.execute(stmt.values(is_deleted=True, deleted_at=func.now()))

    # ------------------------------------------------------------------
    # Document Templates CRUD
    # ------------------------------------------------------------------

    async def create_template(self, **kwargs: Any) -> DocumentTemplate:
        obj = DocumentTemplate(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_template_by_id(
        self,
        template_uuid: uuid.UUID,
        company_id: uuid.UUID | None = None,
    ) -> DocumentTemplate | None:
        stmt = select(DocumentTemplate).where(DocumentTemplate.id == template_uuid)
        if company_id is not None:
            stmt = stmt.where(
                or_(
                    DocumentTemplate.company_id == None,  # noqa: E711
                    DocumentTemplate.company_id == company_id,
                )
            )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_templates(self, company_id: uuid.UUID | None = None) -> list[DocumentTemplate]:
        stmt = select(DocumentTemplate)
        if company_id is not None:
            stmt = stmt.where(
                or_(
                    DocumentTemplate.company_id == None,  # noqa: E711
                    DocumentTemplate.company_id == company_id,
                )
            )
        stmt = stmt.order_by(DocumentTemplate.name.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_template(
        self,
        template_uuid: uuid.UUID,
        company_id: uuid.UUID | None = None,
        **kwargs: Any,
    ) -> None:
        stmt = update(DocumentTemplate).where(DocumentTemplate.id == template_uuid)
        if company_id is not None:
            stmt = stmt.where(
                or_(
                    DocumentTemplate.company_id == None,  # noqa: E711
                    DocumentTemplate.company_id == company_id,
                )
            )
        await self.session.execute(stmt.values(**kwargs))

    async def delete_template(
        self,
        template_uuid: uuid.UUID,
        company_id: uuid.UUID | None = None,
    ) -> None:
        stmt = delete(DocumentTemplate).where(DocumentTemplate.id == template_uuid)
        if company_id is not None:
            stmt = stmt.where(
                or_(
                    DocumentTemplate.company_id == None,  # noqa: E711
                    DocumentTemplate.company_id == company_id,
                )
            )
        await self.session.execute(stmt)

    # ------------------------------------------------------------------
    # Versions & Signatures & Verifications
    # ------------------------------------------------------------------

    async def create_version(self, **kwargs: Any) -> DocumentVersion:
        obj = DocumentVersion(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_versions_by_employee_doc_id(self, doc_uuid: uuid.UUID) -> list[DocumentVersion]:
        stmt = (
            select(DocumentVersion)
            .where(DocumentVersion.employee_doc_id == doc_uuid)
            .order_by(DocumentVersion.version_number.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_version_by_number(self, doc_uuid: uuid.UUID, version_number: int) -> DocumentVersion | None:
        stmt = (
            select(DocumentVersion)
            .where(
                and_(
                    DocumentVersion.employee_doc_id == doc_uuid,
                    DocumentVersion.version_number == version_number,
                )
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

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

    async def get_active_signature_request(
        self,
        doc_uuid: uuid.UUID,
        signer_user_id: uuid.UUID | None = None,
    ) -> DocumentSignature | None:
        stmt = (
            select(DocumentSignature)
            .where(
                and_(
                    DocumentSignature.employee_doc_id == doc_uuid,
                    DocumentSignature.status == "PENDING",
                )
            )
        )
        if signer_user_id is not None:
            stmt = stmt.where(DocumentSignature.signer_user_id == signer_user_id)
        stmt = stmt.order_by(DocumentSignature.created_at.desc()).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_pending_signature_request(
        self,
        doc_uuid: uuid.UUID,
        signer_user_id: uuid.UUID,
    ) -> DocumentSignature | None:
        stmt = (
            select(DocumentSignature)
            .where(
                and_(
                    DocumentSignature.employee_doc_id == doc_uuid,
                    DocumentSignature.signer_user_id == signer_user_id,
                    DocumentSignature.status == "PENDING",
                )
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
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

    async def get_latest_verification(self, doc_uuid: uuid.UUID) -> DocumentVerification | None:
        stmt = (
            select(DocumentVerification)
            .where(DocumentVerification.employee_doc_id == doc_uuid)
            .order_by(DocumentVerification.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Expiry Tracking queries
    # ------------------------------------------------------------------

    async def get_expiring_documents(
        self,
        threshold_date: date,
        company_id: uuid.UUID | None = None,
        employee_ids: list[uuid.UUID] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[EmployeeDocument], int]:
        """Get documents expiring within the threshold date that are active, non-rejected."""
        if employee_ids is not None and len(employee_ids) == 0:
            return [], 0

        cond = and_(
            self._emp_doc_active_filter(),
            EmployeeDocument.status != "REJECTED",
            EmployeeDocument.expiry_date != None,  # noqa: E711
            EmployeeDocument.expiry_date >= date.today(),
            EmployeeDocument.expiry_date <= threshold_date,
        )
        stmt = select(EmployeeDocument).where(cond)
        count_stmt = select(func.count(EmployeeDocument.id)).where(cond)

        if company_id is not None:
            stmt = stmt.join(Employee, EmployeeDocument.employee_id == Employee.id).where(Employee.company_id == company_id)
            count_stmt = count_stmt.join(Employee, EmployeeDocument.employee_id == Employee.id).where(Employee.company_id == company_id)

        if employee_ids is not None:
            stmt = stmt.where(EmployeeDocument.employee_id.in_(employee_ids))
            count_stmt = count_stmt.where(EmployeeDocument.employee_id.in_(employee_ids))

        count_res = await self.session.execute(count_stmt)
        total = count_res.scalar() or 0

        stmt = stmt.options(
            selectinload(EmployeeDocument.employee),
            selectinload(EmployeeDocument.category),
            selectinload(EmployeeDocument.uploader),
            selectinload(EmployeeDocument.signatures).selectinload(DocumentSignature.signer),
            selectinload(EmployeeDocument.verifications),
        )
        stmt = stmt.order_by(EmployeeDocument.expiry_date.asc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def get_expired_documents(
        self,
        company_id: uuid.UUID | None = None,
        employee_ids: list[uuid.UUID] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[EmployeeDocument], int]:
        """Get already expired documents that are active and not rejected."""
        if employee_ids is not None and len(employee_ids) == 0:
            return [], 0

        cond = and_(
            self._emp_doc_active_filter(),
            EmployeeDocument.status != "REJECTED",
            EmployeeDocument.expiry_date != None,  # noqa: E711
            EmployeeDocument.expiry_date < date.today(),
        )
        stmt = select(EmployeeDocument).where(cond)
        count_stmt = select(func.count(EmployeeDocument.id)).where(cond)

        if company_id is not None:
            stmt = stmt.join(Employee, EmployeeDocument.employee_id == Employee.id).where(Employee.company_id == company_id)
            count_stmt = count_stmt.join(Employee, EmployeeDocument.employee_id == Employee.id).where(Employee.company_id == company_id)

        if employee_ids is not None:
            stmt = stmt.where(EmployeeDocument.employee_id.in_(employee_ids))
            count_stmt = count_stmt.where(EmployeeDocument.employee_id.in_(employee_ids))

        count_res = await self.session.execute(count_stmt)
        total = count_res.scalar() or 0

        stmt = stmt.options(
            selectinload(EmployeeDocument.employee),
            selectinload(EmployeeDocument.category),
            selectinload(EmployeeDocument.uploader),
            selectinload(EmployeeDocument.signatures).selectinload(DocumentSignature.signer),
            selectinload(EmployeeDocument.verifications),
        )
        stmt = stmt.order_by(EmployeeDocument.expiry_date.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    # ------------------------------------------------------------------
    # Summary Metrics Aggregation
    # ------------------------------------------------------------------

    async def get_summary(
        self,
        company_id: uuid.UUID | None = None,
        employee_ids: list[uuid.UUID] | None = None,
    ) -> dict[str, int]:
        """Get real aggregate counts for documents in one single query."""
        if employee_ids is not None and len(employee_ids) == 0:
            return {
                "total_documents": 0,
                "verified_documents": 0,
                "pending_verification": 0,
                "rejected_documents": 0,
                "requires_signature": 0,
                "expiring_soon": 0,
                "expiring_90_days": 0,
                "expired_documents": 0,
            }

        today = date.today()
        in_30 = today + timedelta(days=30)
        in_90 = today + timedelta(days=90)

        base_stmt = (
            select(
                func.count(EmployeeDocument.id).label("total_documents"),
                func.count(EmployeeDocument.id).filter(
                    and_(EmployeeDocument.status == "VERIFIED", EmployeeDocument.is_verified == True)  # noqa: E712
                ).label("verified_documents"),
                func.count(EmployeeDocument.id).filter(
                    EmployeeDocument.status == "PENDING"
                ).label("pending_verification"),
                func.count(EmployeeDocument.id).filter(
                    EmployeeDocument.status == "REJECTED"
                ).label("rejected_documents"),
                func.count(EmployeeDocument.id).filter(
                    EmployeeDocument.status == "REQUIRES_SIGNATURE"
                ).label("requires_signature"),
                func.count(EmployeeDocument.id).filter(
                    and_(
                        EmployeeDocument.status != "REJECTED",
                        EmployeeDocument.expiry_date != None,  # noqa: E711
                        EmployeeDocument.expiry_date >= today,
                        EmployeeDocument.expiry_date <= in_30,
                    )
                ).label("expiring_soon"),
                func.count(EmployeeDocument.id).filter(
                    and_(
                        EmployeeDocument.status != "REJECTED",
                        EmployeeDocument.expiry_date != None,  # noqa: E711
                        EmployeeDocument.expiry_date >= today,
                        EmployeeDocument.expiry_date <= in_90,
                    )
                ).label("expiring_90_days"),
                func.count(EmployeeDocument.id).filter(
                    and_(
                        EmployeeDocument.status != "REJECTED",
                        EmployeeDocument.expiry_date != None,  # noqa: E711
                        EmployeeDocument.expiry_date < today,
                    )
                ).label("expired_documents"),
            )
            .where(self._emp_doc_active_filter())
        )

        if company_id is not None:
            base_stmt = base_stmt.join(Employee, EmployeeDocument.employee_id == Employee.id).where(Employee.company_id == company_id)

        if employee_ids is not None:
            base_stmt = base_stmt.where(EmployeeDocument.employee_id.in_(employee_ids))

        res = await self.session.execute(base_stmt)
        row = res.one()
        return {
            "total_documents": row.total_documents or 0,
            "verified_documents": row.verified_documents or 0,
            "pending_verification": row.pending_verification or 0,
            "rejected_documents": row.rejected_documents or 0,
            "requires_signature": row.requires_signature or 0,
            "expiring_soon": row.expiring_soon or 0,
            "expiring_90_days": row.expiring_90_days or 0,
            "expired_documents": row.expired_documents or 0,
        }

    # ------------------------------------------------------------------
    # Audit Logs
    # ------------------------------------------------------------------

    async def create_audit_log(self, **kwargs: Any) -> DocumentAuditLog:
        obj = DocumentAuditLog(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_audit_logs_for_document(self, target_id: uuid.UUID) -> list[DocumentAuditLog]:
        stmt = (
            select(DocumentAuditLog)
            .where(DocumentAuditLog.target_id == target_id)
            .order_by(DocumentAuditLog.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
