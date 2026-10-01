"""Document Management service layer coordinating secure uploads, template renders, and audits."""

from __future__ import annotations

import html
import io
import logging
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, UploadFile, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException, DatabaseException
from app.db.database import get_db_session
from app.models.employee_document import EmployeeDocument
from app.models.document import (
    CompanyDocument,
    DocumentCategory,
    DocumentTemplate,
    DocumentVersion,
    DocumentSignature,
    DocumentVerification,
    DocumentAuditLog,
)
from app.repositories.document_repository import DocumentRepository
from app.repositories.employee_repository import EmployeeRepository
from app.repositories.user_repository import UserRepository
from app.schemas.document import (
    AuditLogResponse,
    CompanyDocumentCreate,
    CompanyDocumentResponse,
    CompanyDocumentUpdate,
    EmployeeDocumentCreate,
    EmployeeDocumentResponse,
    EmployeeDocumentUpdate,
    SignatureResponse,
    TemplateCreate,
    TemplateResponse,
    VersionResponse,
    VERIFICATION_ACTION_VALUES,
)
from app.services.document_access import (
    assert_can_access_company_doc,
    assert_can_access_employee_doc,
    resolve_visible_employee_ids,
)
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)


class DocumentService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        repo: DocumentRepository,
        employee_repo: EmployeeRepository,
        user_repo: UserRepository,
        storage_service: StorageService | None = None,
    ) -> None:
        self.session = session
        self.repo = repo
        self.employee_repo = employee_repo
        self.user_repo = user_repo
        self.storage = storage_service or StorageService()

    # ------------------------------------------------------------------
    # Status & Verification Consistency Helper (Rule 2.2)
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_status(
        doc: EmployeeDocument,
        status_val: str,
        actor_user_id: uuid.UUID | None = None,
    ) -> None:
        """Enforces status and is_verified consistency across all transition points."""
        status_upper = status_val.upper()
        if status_upper == "VERIFIED":
            doc.status = "VERIFIED"
            doc.is_verified = True
            doc.verified_by = actor_user_id
            doc.verified_at = datetime.now(timezone.utc)
        elif status_upper == "REJECTED":
            doc.status = "REJECTED"
            doc.is_verified = False
            doc.verified_by = actor_user_id
            doc.verified_at = datetime.now(timezone.utc)
        elif status_upper in {"PENDING", "REQUIRES_SIGNATURE"}:
            doc.status = status_upper
            doc.is_verified = False
            doc.verified_by = None
            doc.verified_at = None
        else:
            doc.status = status_upper
            doc.is_verified = False

    # ------------------------------------------------------------------
    # Enrichment Helpers for API Responses (Rule 2.1)
    # ------------------------------------------------------------------

    def _enrich_employee_doc(self, doc: EmployeeDocument) -> EmployeeDocumentResponse:
        last_review = None
        if doc.verifications:
            sorted_v = sorted(doc.verifications, key=lambda x: x.created_at or datetime.min, reverse=True)
            if sorted_v:
                latest_v = sorted_v[0]
                last_review = {
                    "action": latest_v.action,
                    "comments": latest_v.comments,
                    "reviewer_user_id": str(latest_v.verifier_user_id) if latest_v.verifier_user_id else None,
                    "created_at": latest_v.created_at.isoformat() if latest_v.created_at else None,
                }

        sig_status = None
        if doc.signatures:
            sorted_s = sorted(doc.signatures, key=lambda x: getattr(x, "created_at", None) or datetime.min, reverse=True)
            if sorted_s:
                sig_status = sorted_s[0].status

        emp_name = None
        emp_code = None
        if doc.employee:
            emp_name = f"{doc.employee.first_name} {doc.employee.last_name}".strip()
            emp_code = doc.employee.employee_id

        cat_name = doc.category.name if doc.category else None
        cat_code = doc.category.code if doc.category else None
        uploader_name = doc.uploader.name if doc.uploader else None

        return EmployeeDocumentResponse(
            id=doc.id,
            employee_id=doc.employee_id,
            category_id=doc.category_id,
            uploaded_by=doc.uploaded_by,
            title=doc.title,
            description=doc.description,
            file_name=doc.file_name,
            file_size=doc.file_size,
            issue_date=doc.issue_date,
            expiry_date=doc.expiry_date,
            version=doc.version,
            status=doc.status,
            visibility=doc.visibility,
            tags=doc.tags,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
            is_verified=doc.is_verified,
            verified_by=doc.verified_by,
            verified_at=doc.verified_at,
            file_url=f"/documents/employees/{doc.id}/download",
            document_type=doc.document_type,
            employee_name=emp_name,
            employee_code=emp_code,
            category_name=cat_name,
            category_code=cat_code,
            last_review=last_review,
            signature_status=sig_status,
            uploaded_by_name=uploader_name,
            document_hash=doc.document_hash,
        )

    def _enrich_company_doc(self, doc: CompanyDocument) -> CompanyDocumentResponse:
        cat_name = doc.category.name if doc.category else None
        cat_code = doc.category.code if doc.category else None
        uploader_name = doc.uploader.name if doc.uploader else None

        return CompanyDocumentResponse(
            id=doc.id,
            category_id=doc.category_id,
            uploaded_by=doc.uploaded_by,
            title=doc.title,
            description=doc.description,
            file_name=doc.file_name,
            file_size=doc.file_size,
            department=doc.department,
            branch=doc.branch,
            visibility=doc.visibility,
            status=doc.status,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
            file_url=f"/documents/company/{doc.id}/download",
            category_name=cat_name,
            category_code=cat_code,
            uploaded_by_name=uploader_name,
            version=len(doc.versions) if getattr(doc, "versions", None) else 1,
        )

    # ------------------------------------------------------------------
    # Employee Document CRUD
    # ------------------------------------------------------------------

    async def upload_employee_document(
        self,
        uploader_id: uuid.UUID,
        payload: EmployeeDocumentCreate,
        file: UploadFile,
        company_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        auto_verify: bool = False,
    ) -> EmployeeDocumentResponse:
        logger.info("upload_employee_document | employee=%s | title=%s", payload.employee_id, payload.title)

        # 1. Validate employee exists and matches company
        emp = await self.employee_repo.get_by_id(payload.employee_id)
        if not emp:
            raise AppException(message="Employee profile not found.", status_code=status.HTTP_404_NOT_FOUND)
        if company_id is not None and emp.company_id != company_id:
            raise AppException(message="Employee profile not found in your company.", status_code=status.HTTP_404_NOT_FOUND)

        # 2. Validate category exists and is NOT a company-only category
        cat = await self.repo.get_category_by_id(payload.category_id)
        if not cat:
            raise AppException(message="Document category not found.", status_code=status.HTTP_404_NOT_FOUND)
        if cat.is_company:
            raise AppException(message="Cannot use a company document category for an employee document.", status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)

        # 3. Stream file and compute hash
        saved_info = await self.storage.save_file(file)
        saved_file_path = saved_info["file_path"]

        try:
            # 4. Check for duplicate upload (Rule 3.7)
            existing_docs, _ = await self.repo.list_employee_documents(
                company_id=company_id,
                employee_id=payload.employee_id,
                category_id=payload.category_id,
                limit=10,
            )
            for ed in existing_docs:
                if ed.document_hash and ed.document_hash == saved_info["document_hash"]:
                    self.storage.delete_file(saved_file_path)
                    raise AppException(
                        message="An identical document for this category already exists.",
                        status_code=status.HTTP_409_CONFLICT,
                    )

            # 5. Determine initial status (Rule 2.2: Force PENDING unless auto_verify=True)
            initial_status = "PENDING"
            is_verified = False
            verified_by = None
            verified_at = None

            if auto_verify:
                initial_status = "VERIFIED"
                is_verified = True
                verified_by = uploader_id
                verified_at = datetime.now(timezone.utc)

            doc_kwargs = payload.model_dump()
            doc_kwargs.update({
                "uploaded_by": uploader_id,
                "file_path": saved_file_path,
                "file_name": saved_info["original_filename"],
                "file_size": saved_info["file_size"],
                "document_hash": saved_info["document_hash"],
                "version": 1,
                "status": initial_status,
                "is_verified": is_verified,
                "verified_by": verified_by,
                "verified_at": verified_at,
            })

            doc = await self.repo.create_employee_document(**doc_kwargs)

            # 6. Add version row
            await self.repo.create_version(
                employee_doc_id=doc.id,
                version_number=1,
                file_path=saved_file_path,
                document_hash=saved_info["document_hash"],
                uploaded_by=uploader_id,
            )

            # 7. Audit log
            await self.repo.create_audit_log(
                company_id=company_id,
                user_id=uploader_id,
                action="UPLOAD",
                target_type="EMPLOYEE_DOC",
                target_id=doc.id,
                details=f"Uploaded version 1 of document: {payload.title}",
                ip_address=ip_address,
            )

            if auto_verify:
                await self.repo.create_verification(
                    employee_doc_id=doc.id,
                    verifier_user_id=uploader_id,
                    action="APPROVED",
                    comments="Auto-verified upon upload by administrator.",
                )

            await self.session.commit()
            full_doc = await self.repo.get_employee_document_by_id(doc.id, company_id=company_id)
            return self._enrich_employee_doc(full_doc)

        except Exception:
            await self.session.rollback()
            self.storage.delete_file(saved_file_path)
            raise

    async def get_employee_document(
        self,
        user_id: uuid.UUID,
        doc_uuid: uuid.UUID,
        claims: dict,
        company_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        action: str = "VIEW",
    ) -> EmployeeDocumentResponse:
        """Fetch document with permission verification BEFORE audit logging (Rule 1.6)."""
        doc = await self.repo.get_employee_document_by_id(doc_uuid, company_id=company_id)
        if not doc:
            raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

        try:
            await assert_can_access_employee_doc(claims, doc, self.session)
        except AppException as exc:
            # Unauthorized access attempt: log ACCESS_DENIED and return 404
            try:
                await self.repo.create_audit_log(
                    company_id=company_id,
                    user_id=user_id,
                    action="ACCESS_DENIED",
                    target_type="EMPLOYEE_DOC",
                    target_id=doc_uuid,
                    details=f"Unauthorized access attempt by role '{claims.get('role')}': {exc.message}",
                    ip_address=ip_address,
                )
                await self.session.commit()
            except Exception:
                await self.session.rollback()
            raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

        # Audit successful VIEW or DOWNLOAD
        await self.repo.create_audit_log(
            company_id=company_id,
            user_id=user_id,
            action=action.upper(),
            target_type="EMPLOYEE_DOC",
            target_id=doc_uuid,
            details=f"{action.capitalize()} document: {doc.title}",
            ip_address=ip_address,
        )
        await self.session.commit()

        return self._enrich_employee_doc(doc)

    async def update_employee_document(
        self,
        uploader_id: uuid.UUID,
        doc_uuid: uuid.UUID,
        payload: EmployeeDocumentUpdate,
        claims: dict,
        file: UploadFile | None = None,
        company_id: uuid.UUID | None = None,
        ip_address: str | None = None,
    ) -> EmployeeDocumentResponse:
        logger.info("update_employee_document | doc_id=%s", doc_uuid)
        doc = await self.repo.get_employee_document_by_id(doc_uuid, company_id=company_id)
        if not doc:
            raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

        await assert_can_access_employee_doc(claims, doc, self.session)

        # Employee self-service checks (Rule 2.7)
        role = (claims.get("role") or "").lower()
        if role == "employee":
            # Employees may re-upload ONLY documents that are REJECTED or RE_UPLOAD_REQUESTED
            latest_v = await self.repo.get_latest_verification(doc_uuid)
            is_reupload_allowed = doc.status == "REJECTED" or (latest_v and latest_v.action == "RE_UPLOAD_REQUESTED")
            if not is_reupload_allowed or not file:
                raise AppException(
                    message="Employees can only re-upload files for documents that are rejected or have re-upload requested.",
                    status_code=status.HTTP_403_FORBIDDEN,
                )
            if payload.status is not None or payload.visibility is not None:
                raise AppException(message="Employees cannot change document status or visibility.", status_code=status.HTTP_403_FORBIDDEN)

        # Use exclude_unset=True so None values explicitly provided are not ignored (Rule 2.2)
        update_data = payload.model_dump(exclude_unset=True)

        # Generic PUT may only set PENDING or REQUIRES_SIGNATURE (Rule 2.2)
        if "status" in update_data and update_data["status"] is not None:
            st = update_data["status"].upper()
            if st in {"VERIFIED", "REJECTED"}:
                raise AppException(
                    message="Status transitions to VERIFIED or REJECTED must use dedicated /verify or /reject endpoints.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            self._apply_status(doc, st, uploader_id)
            update_data["status"] = doc.status
            update_data["is_verified"] = doc.is_verified
            update_data["verified_by"] = doc.verified_by
            update_data["verified_at"] = doc.verified_at

        new_saved_path = None
        try:
            if file:
                saved_info = await self.storage.save_file(file)
                new_saved_path = saved_info["file_path"]
                new_version = doc.version + 1

                # Changed file must reset status to PENDING and is_verified to False (Rule 2.2)
                self._apply_status(doc, "PENDING", uploader_id)

                update_data.update({
                    "file_path": new_saved_path,
                    "file_name": saved_info["original_filename"],
                    "file_size": saved_info["file_size"],
                    "document_hash": saved_info["document_hash"],
                    "version": new_version,
                    "status": "PENDING",
                    "is_verified": False,
                    "verified_by": None,
                    "verified_at": None,
                })

                await self.repo.create_version(
                    employee_doc_id=doc_uuid,
                    version_number=new_version,
                    file_path=new_saved_path,
                    document_hash=saved_info["document_hash"],
                    uploaded_by=uploader_id,
                )
                audit_msg = f"Updated document fields & uploaded version {new_version}."
            else:
                audit_msg = "Updated document metadata."

            await self.repo.update_employee_document(doc_uuid, company_id=company_id, **update_data)

            await self.repo.create_audit_log(
                company_id=company_id,
                user_id=uploader_id,
                action="UPDATE",
                target_type="EMPLOYEE_DOC",
                target_id=doc_uuid,
                details=audit_msg,
                ip_address=ip_address,
            )

            await self.session.commit()
            updated = await self.repo.get_employee_document_by_id(doc_uuid, company_id=company_id)
            return self._enrich_employee_doc(updated)

        except Exception:
            await self.session.rollback()
            if new_saved_path:
                self.storage.delete_file(new_saved_path)
            raise

    async def delete_employee_document(
        self,
        uploader_id: uuid.UUID,
        doc_uuid: uuid.UUID,
        claims: dict,
        company_id: uuid.UUID | None = None,
        ip_address: str | None = None,
    ) -> None:
        doc = await self.repo.get_employee_document_by_id(doc_uuid, company_id=company_id)
        if not doc:
            raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

        await assert_can_access_employee_doc(claims, doc, self.session)

        # Employees cannot delete verified documents (Rule 2.7)
        role = (claims.get("role") or "").lower()
        if role == "employee" and doc.is_verified:
            raise AppException(message="Cannot delete a verified document.", status_code=status.HTTP_403_FORBIDDEN)

        try:
            await self.repo.soft_delete_employee_document(doc_uuid, company_id=company_id)

            await self.repo.create_audit_log(
                company_id=company_id,
                user_id=uploader_id,
                action="DELETE",
                target_type="EMPLOYEE_DOC",
                target_id=doc_uuid,
                details=f"Soft deleted document: {doc.title}",
                ip_address=ip_address,
            )

            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

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
    ) -> tuple[list[EmployeeDocumentResponse], int]:
        docs, total = await self.repo.list_employee_documents(
            company_id=company_id,
            employee_id=employee_id,
            employee_ids=employee_ids,
            category_id=category_id,
            status=status,
            visibility=visibility,
            search=search,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            order=order,
            is_super_admin=is_super_admin,
        )
        return [self._enrich_employee_doc(d) for d in docs], total

    # ------------------------------------------------------------------
    # Company Document CRUD
    # ------------------------------------------------------------------

    async def upload_company_document(
        self,
        uploader_id: uuid.UUID,
        payload: CompanyDocumentCreate,
        file: UploadFile,
        company_id: uuid.UUID | None = None,
        ip_address: str | None = None,
    ) -> CompanyDocumentResponse:
        # Validate category exists and is a company category
        cat = await self.repo.get_category_by_id(payload.category_id)
        if not cat:
            raise AppException(message="Document category not found.", status_code=status.HTTP_404_NOT_FOUND)
        if not cat.is_company:
            raise AppException(message="Selected category is not a company document category.", status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)

        saved_info = await self.storage.save_file(file)
        saved_file_path = saved_info["file_path"]

        try:
            doc_kwargs = payload.model_dump()
            doc_kwargs.update({
                "company_id": company_id,
                "uploaded_by": uploader_id,
                "file_path": saved_file_path,
                "file_name": saved_info["original_filename"],
                "file_size": saved_info["file_size"],
                "visibility": payload.visibility.upper(),
                "status": "PUBLISHED",
            })

            doc = await self.repo.create_company_document(**doc_kwargs)

            await self.repo.create_version(
                company_doc_id=doc.id,
                version_number=1,
                file_path=saved_file_path,
                document_hash=saved_info["document_hash"],
                uploaded_by=uploader_id,
            )

            await self.repo.create_audit_log(
                company_id=company_id,
                user_id=uploader_id,
                action="UPLOAD",
                target_type="COMPANY_DOC",
                target_id=doc.id,
                details=f"Uploaded company document: {payload.title}",
                ip_address=ip_address,
            )

            await self.session.commit()
            full_doc = await self.repo.get_company_document_by_id(doc.id, company_id=company_id)
            return self._enrich_company_doc(full_doc)

        except Exception:
            await self.session.rollback()
            self.storage.delete_file(saved_file_path)
            raise

    async def get_company_document(
        self,
        user_id: uuid.UUID,
        doc_uuid: uuid.UUID,
        claims: dict,
        company_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        action: str = "VIEW",
    ) -> CompanyDocumentResponse:
        doc = await self.repo.get_company_document_by_id(doc_uuid, company_id=company_id)
        if not doc:
            raise AppException(message="Company document not found.", status_code=status.HTTP_404_NOT_FOUND)

        try:
            await assert_can_access_company_doc(claims, doc, self.session)
        except AppException as exc:
            try:
                await self.repo.create_audit_log(
                    company_id=company_id,
                    user_id=user_id,
                    action="ACCESS_DENIED",
                    target_type="COMPANY_DOC",
                    target_id=doc_uuid,
                    details=f"Unauthorized company document access attempt: {exc.message}",
                    ip_address=ip_address,
                )
                await self.session.commit()
            except Exception:
                await self.session.rollback()
            raise AppException(message="Company document not found.", status_code=status.HTTP_404_NOT_FOUND)

        await self.repo.create_audit_log(
            company_id=company_id,
            user_id=user_id,
            action=action.upper(),
            target_type="COMPANY_DOC",
            target_id=doc_uuid,
            details=f"{action.capitalize()} company document: {doc.title}",
            ip_address=ip_address,
        )
        await self.session.commit()

        return self._enrich_company_doc(doc)

    async def update_company_document(
        self,
        uploader_id: uuid.UUID,
        doc_uuid: uuid.UUID,
        payload: CompanyDocumentUpdate,
        file: UploadFile | None = None,
        company_id: uuid.UUID | None = None,
        ip_address: str | None = None,
    ) -> CompanyDocumentResponse:
        doc = await self.repo.get_company_document_by_id(doc_uuid, company_id=company_id)
        if not doc:
            raise AppException(message="Company document not found.", status_code=status.HTTP_404_NOT_FOUND)

        update_data = payload.model_dump(exclude_unset=True)
        new_saved_path = None

        try:
            if file:
                saved_info = await self.storage.save_file(file)
                new_saved_path = saved_info["file_path"]

                # Get existing versions count
                ver_num = len(doc.versions or []) + 1
                update_data.update({
                    "file_path": new_saved_path,
                    "file_name": saved_info["original_filename"],
                    "file_size": saved_info["file_size"],
                })

                await self.repo.create_version(
                    company_doc_id=doc_uuid,
                    version_number=ver_num,
                    file_path=new_saved_path,
                    document_hash=saved_info["document_hash"],
                    uploaded_by=uploader_id,
                )
                audit_msg = f"Updated company document metadata and uploaded version {ver_num}."
            else:
                audit_msg = "Updated company document metadata."

            await self.repo.update_company_document(doc_uuid, company_id=company_id, **update_data)

            await self.repo.create_audit_log(
                company_id=company_id,
                user_id=uploader_id,
                action="UPDATE",
                target_type="COMPANY_DOC",
                target_id=doc_uuid,
                details=audit_msg,
                ip_address=ip_address,
            )

            await self.session.commit()
            updated = await self.repo.get_company_document_by_id(doc_uuid, company_id=company_id)
            return self._enrich_company_doc(updated)

        except Exception:
            await self.session.rollback()
            if new_saved_path:
                self.storage.delete_file(new_saved_path)
            raise

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
    ) -> tuple[list[CompanyDocumentResponse], int]:
        docs, total = await self.repo.list_company_documents(
            company_id=company_id,
            category_id=category_id,
            department=department,
            branch=branch,
            visibility=visibility,
            search=search,
            limit=limit,
            offset=offset,
            caller_role=caller_role,
            viewer_dept=viewer_dept,
            viewer_branch=viewer_branch,
            is_admin=is_admin,
        )
        return [self._enrich_company_doc(d) for d in docs], total

    async def delete_company_document(
        self,
        uploader_id: uuid.UUID,
        doc_uuid: uuid.UUID,
        company_id: uuid.UUID | None = None,
        ip_address: str | None = None,
    ) -> None:
        doc = await self.repo.get_company_document_by_id(doc_uuid, company_id=company_id)
        if not doc:
            raise AppException(message="Company document not found.", status_code=status.HTTP_404_NOT_FOUND)

        try:
            await self.repo.soft_delete_company_document(doc_uuid, company_id=company_id)

            await self.repo.create_audit_log(
                company_id=company_id,
                user_id=uploader_id,
                action="DELETE",
                target_type="COMPANY_DOC",
                target_id=doc_uuid,
                details=f"Soft deleted company document: {doc.title}",
                ip_address=ip_address,
            )

            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    # ------------------------------------------------------------------
    # Document Templates
    # ------------------------------------------------------------------

    async def create_template(
        self,
        user_id: uuid.UUID,
        payload: TemplateCreate,
        company_id: uuid.UUID | None = None,
    ) -> TemplateResponse:
        try:
            template = await self.repo.create_template(
                company_id=company_id,
                name=payload.name,
                description=payload.description,
                template_body=payload.template_body,
                created_by=user_id,
            )
            await self.session.commit()
            return TemplateResponse.model_validate(template)
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("create_template: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def list_templates(self, company_id: uuid.UUID | None = None) -> list[TemplateResponse]:
        templates = await self.repo.list_templates(company_id=company_id)
        return [TemplateResponse.model_validate(t) for t in templates]

    async def generate_document_from_template(
        self,
        template_uuid: uuid.UUID,
        employee_uuid: uuid.UUID,
        caller_claims: dict,
        extra_fields: dict[str, str] | None = None,
        save_as_document: bool = False,
    ) -> dict[str, Any]:
        """Inject dynamic placeholders and optionally generate and vault a PDF (Rule 3.7)."""
        template = await self.repo.get_template_by_id(template_uuid)
        if not template:
            raise AppException(message="Template not found.", status_code=status.HTTP_404_NOT_FOUND)

        emp = await self.employee_repo.get_by_id(employee_uuid)
        if not emp:
            raise AppException(message="Employee profile not found.", status_code=status.HTTP_404_NOT_FOUND)

        # Tenant isolation
        caller_role = (caller_claims.get("role") or "").lower()
        if caller_role != "super_admin":
            caller_comp = caller_claims.get("company_id")
            if not caller_comp or emp.company_id != uuid.UUID(str(caller_comp)):
                raise AppException(message="Employee profile not found.", status_code=status.HTTP_404_NOT_FOUND)

        # Safe placeholder dictionary
        # Salary is strictly injected ONLY if caller is Admin/HR and {{salary}} is in template (Rule 3.7)
        salary_str = "0.00"
        if caller_role in {"super_admin", "hr_admin", "it_admin", "executive"}:
            raw_salary = getattr(emp, "basic_salary", None) or getattr(emp, "ctc", None)
            if raw_salary is not None:
                salary_str = f"{raw_salary:.2f}"

        # Fetch manager name safely
        manager_name = ""
        mgr_id = getattr(emp, "reporting_manager_id", None) or getattr(emp, "manager_id", None)
        if mgr_id:
            mgr = await self.employee_repo.get_by_id(mgr_id)
            if mgr:
                manager_name = f"{mgr.first_name} {mgr.last_name}".strip()

        # Company name
        company_name = ""
        if emp.company_id:
            from app.models.company import Company
            comp_res = await self.session.execute(select(Company).where(Company.id == emp.company_id))
            comp_obj = comp_res.scalar_one_or_none()
            if comp_obj:
                company_name = comp_obj.name or ""

        replacements: dict[str, str] = {
            "{{employee_name}}": f"{emp.first_name or ''} {emp.last_name or ''}".strip(),
            "{{employee_id}}": str(emp.employee_id or ""),
            "{{department}}": str(emp.department or "General"),
            "{{designation}}": str(emp.designation or "Staff"),
            "{{joining_date}}": str(emp.joining_date or ""),
            "{{salary}}": salary_str,
            "{{company_name}}": company_name,
            "{{today}}": date.today().isoformat(),
            "{{manager_name}}": manager_name,
            "{{location}}": str(emp.work_location or emp.branch or ""),
        }

        # Extra dynamic fields with HTML escaping (Rule 3.7)
        if extra_fields:
            for k, v in extra_fields.items():
                clean_k = k if k.startswith("{{") else f"{{{{{k}}}}}"
                replacements[clean_k] = html.escape(str(v or ""))

        body = template.template_body
        for placeholder, value in replacements.items():
            body = body.replace(placeholder, value)

        result: dict[str, Any] = {
            "template_name": template.name,
            "content": body,
            "saved_document_id": None,
        }

        # If requested, render to PDF and save to vault as EmployeeDocument (Rule 3.7)
        if save_as_document:
            pdf_bytes = self._render_text_to_pdf(template.name, body)
            from app.services.storage_service import DOCUMENTS_DIR_ABSOLUTE
            unique_filename = f"vault_{uuid.uuid4().hex}.pdf"
            save_path = os.path.join(DOCUMENTS_DIR_ABSOLUTE, unique_filename)

            hasher = hashlib.sha256(pdf_bytes)
            with open(save_path, "wb") as f:
                f.write(pdf_bytes)

            uploader_id = uuid.UUID(str(caller_claims["sub"]))

            # Find or fallback category
            cat = await self.repo.get_category_by_code("CONTRACT") or await self.repo.get_category_by_code("OFFER_LETTER")
            cat_id = cat.id if cat else None

            emp_doc = await self.repo.create_employee_document(
                employee_id=emp.id,
                category_id=cat_id,
                uploaded_by=uploader_id,
                title=f"{template.name} - {emp.first_name} {emp.last_name}",
                description=f"Generated from template: {template.name}",
                file_path=save_path,
                file_name=f"{template.name.replace(' ', '_')}.pdf",
                file_size=len(pdf_bytes),
                document_hash=hasher.hexdigest(),
                version=1,
                status="PENDING",
                visibility="PRIVATE",
                is_verified=False,
            )

            await self.repo.create_version(
                employee_doc_id=emp_doc.id,
                version_number=1,
                file_path=save_path,
                document_hash=hasher.hexdigest(),
                uploaded_by=uploader_id,
            )

            await self.repo.create_audit_log(
                company_id=emp.company_id,
                user_id=uploader_id,
                action="TEMPLATE_GENERATED",
                target_type="EMPLOYEE_DOC",
                target_id=emp_doc.id,
                details=f"Generated and saved document from template '{template.name}' to Vault.",
            )

            await self.session.commit()
            result["saved_document_id"] = str(emp_doc.id)

        return result

    @staticmethod
    def _render_text_to_pdf(title: str, text_content: str) -> bytes:
        """Render plain text / template output to a clean PDF using reportlab."""
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=54, rightMargin=54, topMargin=54, bottomMargin=54)
        styles = getSampleStyleSheet()

        title_style = styles["Heading1"]
        body_style = styles["Normal"]

        story = [
            Paragraph(title, title_style),
            Spacer(1, 18),
        ]

        # Split content into paragraphs
        for line in text_content.split("\n"):
            clean_line = line.strip()
            if clean_line:
                story.append(Paragraph(clean_line, body_style))
                story.append(Spacer(1, 8))
            else:
                story.append(Spacer(1, 12))

        doc.build(story)
        buf.seek(0)
        return buf.read()

    # ------------------------------------------------------------------
    # Digital Signatures (Rule 1.8)
    # ------------------------------------------------------------------

    async def request_signature(
        self,
        user_id: uuid.UUID,
        doc_uuid: uuid.UUID,
        signer_user_id: uuid.UUID,
        company_id: uuid.UUID | None = None,
    ) -> SignatureResponse:
        logger.info("request_signature | doc=%s | signer=%s", doc_uuid, signer_user_id)
        doc = await self.repo.get_employee_document_by_id(doc_uuid, company_id=company_id)
        if not doc or doc.is_deleted:
            raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

        # Verify signer user exists and belongs to same company
        signer = await self.user_repo.get_by_id(signer_user_id)
        if not signer or signer.is_deleted:
            raise AppException(message="Signer user account not found.", status_code=status.HTTP_404_NOT_FOUND)
        if company_id is not None and signer.company_id != company_id:
            raise AppException(message="Signer does not belong to the same company.", status_code=status.HTTP_403_FORBIDDEN)

        # Block duplicate PENDING requests for the same (doc, signer) -> 409 Conflict
        existing_sig = await self.repo.get_pending_signature_request(doc_uuid, signer_user_id)
        if existing_sig:
            raise AppException(
                message="A pending signature request already exists for this signer on this document.",
                status_code=status.HTTP_409_CONFLICT,
            )

        # Record document hash at request time to detect subsequent tampering
        doc_hash = doc.document_hash
        if not doc_hash and doc.file_path and os.path.exists(doc.file_path):
            with open(doc.file_path, "rb") as f:
                doc_hash = hashlib.sha256(f.read()).hexdigest()

        try:
            sig = await self.repo.create_signature_request(
                employee_doc_id=doc_uuid,
                signer_user_id=signer_user_id,
                status="PENDING",
                document_hash=doc_hash,
            )

            # Transition document status to REQUIRES_SIGNATURE
            self._apply_status(doc, "REQUIRES_SIGNATURE", user_id)
            await self.repo.update_employee_document(doc_uuid, status="REQUIRES_SIGNATURE", is_verified=False)

            await self.repo.create_audit_log(
                company_id=company_id,
                user_id=user_id,
                action="SIGNATURE_REQUESTED",
                target_type="EMPLOYEE_DOC",
                target_id=doc_uuid,
                details=f"Requested signature from user: {signer.name}",
            )

            await self.session.commit()
            return SignatureResponse.model_validate(sig)

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("request_signature: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def sign_document(
        self,
        signer_id: uuid.UUID,
        doc_uuid: uuid.UUID,
        device_info: str | None = None,
        ip_address: str | None = None,
    ) -> SignatureResponse:
        logger.info("sign_document | doc=%s | signer=%s", doc_uuid, signer_id)
        doc = await self.repo.get_employee_document_by_id(doc_uuid)
        if not doc or doc.is_deleted:
            raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

        sig = await self.repo.get_active_signature_request(doc_uuid, signer_user_id=signer_id)
        if not sig:
            raise AppException(
                message="No pending signature request found for you on this document.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # Anti-tampering check: verify file's current hash matches the hash recorded when requested
        if doc.file_path and os.path.exists(doc.file_path):
            with open(doc.file_path, "rb") as f:
                current_hash = hashlib.sha256(f.read()).hexdigest()
            if sig.document_hash and current_hash != sig.document_hash:
                raise AppException(
                    message="Document content has been modified since signature request was created. Signing rejected.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

        try:
            await self.repo.update_signature_status(
                sig.id,
                status="SIGNED",
                signed_at=datetime.now(timezone.utc),
                ip_address=ip_address,
                device_info=device_info,
            )

            # Rule 1.8 & 2.2: Set status to VERIFIED only if doc was previously verified, otherwise PENDING
            next_status = "VERIFIED" if doc.is_verified else "PENDING"
            self._apply_status(doc, next_status, signer_id)
            await self.repo.update_employee_document(
                doc_uuid,
                status=doc.status,
                is_verified=doc.is_verified,
            )

            await self.repo.create_audit_log(
                company_id=getattr(doc.employee, "company_id", None) if doc.employee else None,
                user_id=signer_id,
                action="SIGN",
                target_type="EMPLOYEE_DOC",
                target_id=doc_uuid,
                details="Digitally signed document.",
                ip_address=ip_address,
            )

            await self.session.commit()
            updated_sig = await self.repo.get_signature_by_id(sig.id)
            return SignatureResponse.model_validate(updated_sig)

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("sign_document: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Document Verifications & Re-upload Request (Rule 2.6)
    # ------------------------------------------------------------------

    async def verify_document(
        self,
        verifier_id: uuid.UUID,
        doc_uuid: uuid.UUID,
        action: str,
        comments: str | None = None,
        company_id: uuid.UUID | None = None,
        ip_address: str | None = None,
    ) -> EmployeeDocumentResponse:
        logger.info("verify_document | doc=%s | action=%s", doc_uuid, action)
        action_upper = action.upper()
        if action_upper not in VERIFICATION_ACTION_VALUES:
            raise AppException(
                message=f"Invalid action '{action}'. Must be one of: {', '.join(VERIFICATION_ACTION_VALUES)}",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        if action_upper in {"REJECTED", "RE_UPLOAD_REQUESTED"} and not (comments and comments.strip()):
            raise AppException(message="Comments are strictly required when rejecting or requesting re-upload.", status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)

        doc = await self.repo.get_employee_document_by_id(doc_uuid, company_id=company_id)
        if not doc or doc.is_deleted:
            raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

        try:
            # Map action explicitly (Rule 2.2 & 2.6)
            if action_upper == "APPROVED":
                self._apply_status(doc, "VERIFIED", verifier_id)
            elif action_upper == "REJECTED":
                self._apply_status(doc, "REJECTED", verifier_id)
            elif action_upper == "RE_UPLOAD_REQUESTED":
                self._apply_status(doc, "PENDING", verifier_id)

            await self.repo.update_employee_document(
                doc_uuid,
                company_id=company_id,
                status=doc.status,
                is_verified=doc.is_verified,
                verified_by=doc.verified_by,
                verified_at=doc.verified_at,
            )

            await self.repo.create_verification(
                employee_doc_id=doc_uuid,
                verifier_user_id=verifier_id,
                action=action_upper,
                comments=comments.strip() if comments else None,
            )

            await self.repo.create_audit_log(
                company_id=company_id,
                user_id=verifier_id,
                action="VERIFY" if action_upper == "APPROVED" else action_upper,
                target_type="EMPLOYEE_DOC",
                target_id=doc_uuid,
                details=f"Verification decision: {action_upper}. Remarks: {comments}",
                ip_address=ip_address,
            )

            await self.session.commit()
            updated = await self.repo.get_employee_document_by_id(doc_uuid, company_id=company_id)
            return self._enrich_employee_doc(updated)

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("verify_document: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Version & History Retrieval (Rule 2.8)
    # ------------------------------------------------------------------

    async def list_document_versions(
        self,
        doc_uuid: uuid.UUID,
        claims: dict,
        company_id: uuid.UUID | None = None,
    ) -> list[VersionResponse]:
        doc = await self.repo.get_employee_document_by_id(doc_uuid, company_id=company_id)
        if not doc or doc.is_deleted:
            raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

        await assert_can_access_employee_doc(claims, doc, self.session)
        versions = await self.repo.get_versions_by_employee_doc_id(doc_uuid)

        responses = []
        for v in versions:
            responses.append(
                VersionResponse(
                    id=v.id,
                    version_number=v.version_number,
                    uploaded_by=v.uploaded_by,
                    created_at=v.created_at,
                    download_url=f"/documents/employees/{doc_uuid}/versions/{v.version_number}/download",
                    document_hash=getattr(v, "document_hash", None),
                )
            )
        return responses

    async def get_document_version_file(
        self,
        doc_uuid: uuid.UUID,
        version_number: int,
        claims: dict,
        company_id: uuid.UUID | None = None,
    ) -> tuple[str, str]:
        doc = await self.repo.get_employee_document_by_id(doc_uuid, company_id=company_id)
        if not doc or doc.is_deleted:
            raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

        await assert_can_access_employee_doc(claims, doc, self.session)
        ver = await self.repo.get_version_by_number(doc_uuid, version_number)
        if not ver:
            raise AppException(message=f"Version {version_number} not found for this document.", status_code=status.HTTP_404_NOT_FOUND)

        safe_path = self.storage.verify_safe_path(ver.file_path)
        if not os.path.exists(safe_path):
            raise AppException(message="File missing from storage.", status_code=status.HTTP_404_NOT_FOUND)

        filename = f"v{version_number}_{doc.file_name or 'document.pdf'}"
        return safe_path, filename

    async def list_document_history(
        self,
        doc_uuid: uuid.UUID,
        claims: dict,
        company_id: uuid.UUID | None = None,
    ) -> list[AuditLogResponse]:
        doc = await self.repo.get_employee_document_by_id(doc_uuid, company_id=company_id)
        if not doc or doc.is_deleted:
            raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

        await assert_can_access_employee_doc(claims, doc, self.session)
        logs = await self.repo.get_audit_logs_for_document(doc_uuid)
        return [AuditLogResponse.model_validate(l) for l in logs]

    # ------------------------------------------------------------------
    # Expiry Tracking queries (Rule 2.4 & 3.6)
    # ------------------------------------------------------------------

    async def list_expiring_documents(
        self,
        company_id: uuid.UUID | None = None,
        employee_ids: list[uuid.UUID] | None = None,
        days: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[EmployeeDocumentResponse], int]:
        warning_days = days or getattr(settings, "DOCUMENT_EXPIRY_WARNING_DAYS", 30)
        threshold_date = date.today() + timedelta(days=warning_days)
        docs, total = await self.repo.get_expiring_documents(
            threshold_date,
            company_id=company_id,
            employee_ids=employee_ids,
            limit=limit,
            offset=offset,
        )
        return [self._enrich_employee_doc(d) for d in docs], total

    async def list_expired_documents(
        self,
        company_id: uuid.UUID | None = None,
        employee_ids: list[uuid.UUID] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[EmployeeDocumentResponse], int]:
        docs, total = await self.repo.get_expired_documents(
            company_id=company_id,
            employee_ids=employee_ids,
            limit=limit,
            offset=offset,
        )
        return [self._enrich_employee_doc(d) for d in docs], total

    # ------------------------------------------------------------------
    # Summary Metrics (Rule 2.4)
    # ------------------------------------------------------------------

    async def get_summary(
        self,
        company_id: uuid.UUID | None = None,
        employee_ids: list[uuid.UUID] | None = None,
    ) -> dict[str, int]:
        return await self.repo.get_summary(company_id=company_id, employee_ids=employee_ids)


async def get_document_service(
    session: AsyncSession = Depends(get_db_session),
) -> DocumentService:
    return DocumentService(
        session=session,
        repo=DocumentRepository(session),
        employee_repo=EmployeeRepository(session),
        user_repo=UserRepository(session),
    )
