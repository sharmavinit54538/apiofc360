"""Document Management service layer coordinating secure uploads, template renders, and audits."""

from __future__ import annotations

import logging
import os
import uuid
import hashlib
from datetime import date, datetime, timezone
from typing import Any

from fastapi import Depends, UploadFile, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException, DatabaseException
from app.db.database import get_db_session
from app.models.employee_document import EmployeeDocument
from app.models.document import DocumentTemplate, DocumentCategory
from app.repositories.document_repository import DocumentRepository
from app.repositories.employee_repository import EmployeeRepository
from app.repositories.user_repository import UserRepository
from app.schemas.document import (
    CompanyDocumentCreate,
    CompanyDocumentResponse,
    EmployeeDocumentCreate,
    EmployeeDocumentResponse,
    EmployeeDocumentUpdate,
    SignatureResponse,
    TemplateCreate,
    TemplateResponse,
    VersionResponse,
)

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB limit
UPLOAD_DIR = "uploads/documents"

# Auto seed default categories on first access
DEFAULT_EMPLOYEE_CATEGORIES = [
    ("Resume", "RESUME"),
    ("Offer Letter", "OFFER_LETTER"),
    ("Appointment Letter", "APPT_LETTER"),
    ("Employment Contract", "CONTRACT"),
    ("Aadhaar", "AADHAAR"),
    ("PAN", "PAN"),
    ("Passport", "PASSPORT"),
    ("Driving License", "DL"),
    ("Voter ID", "VOTER_ID"),
    ("Educational Certificates", "EDU_CERT"),
    ("Experience Letter", "EXP_LETTER"),
    ("Salary Slip", "SALARY_SLIP"),
]

DEFAULT_COMPANY_CATEGORIES = [
    ("HR Policy", "HR_POLICY"),
    ("Leave Policy", "LEAVE_POLICY"),
    ("Payroll Policy", "PAYROLL_POLICY"),
    ("Code of Conduct", "CODE_OF_CONDUCT"),
    ("Employee Handbook", "HANDBOOK"),
    ("NDA", "NDA"),
]


class DocumentService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        repo: DocumentRepository,
        employee_repo: EmployeeRepository,
        user_repo: UserRepository,
    ) -> None:
        self.session = session
        self.repo = repo
        self.employee_repo = employee_repo
        self.user_repo = user_repo
        
        # Ensure uploads folder exists
        os.makedirs(UPLOAD_DIR, exist_ok=True)

    async def seed_categories_if_needed(self) -> None:
        try:
            existing = await self.repo.list_categories()
            if not existing:
                for name, code in DEFAULT_EMPLOYEE_CATEGORIES:
                    await self.repo.create_category(name=name, code=code, is_company=False)
                for name, code in DEFAULT_COMPANY_CATEGORIES:
                    await self.repo.create_category(name=name, code=code, is_company=True)
                await self.session.commit()
        except Exception as exc:
            logger.error("seed_categories_if_needed failed: %s", exc)

    # ------------------------------------------------------------------
    # File Helper
    # ------------------------------------------------------------------

    async def _save_uploaded_file(self, file: UploadFile) -> tuple[str, str, int]:
        filename = file.filename or "doc.pdf"
        _, ext = os.path.splitext(filename.lower())
        if ext not in ALLOWED_EXTENSIONS:
            raise AppException(
                message="Invalid file extension. Only PDF, DOC, DOCX, JPG, JPEG, and PNG are allowed.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # File size verification
        file_data = await file.read()
        file_size = len(file_data)
        await file.seek(0)

        if file_size > MAX_FILE_SIZE_BYTES:
            raise AppException(
                message="File size exceeds maximum limit of 10 MB.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Generate secure hash name
        unique_filename = f"{uuid.uuid4().hex}{ext}"
        save_path = os.path.join(UPLOAD_DIR, unique_filename)
        
        with open(save_path, "wb") as f:
            f.write(file_data)

        return save_path, filename, file_size

    # ------------------------------------------------------------------
    # Employee Document CRUD
    # ------------------------------------------------------------------

    async def upload_employee_document(
        self,
        uploader_id: uuid.UUID,
        payload: EmployeeDocumentCreate,
        file: UploadFile,
        ip_address: str | None = None,
    ) -> EmployeeDocumentResponse:
        logger.info("upload_employee_document | employee=%s | title=%s", payload.employee_id, payload.title)
        try:
            await self.seed_categories_if_needed()
            
            # Check employee exists
            emp = await self.employee_repo.get_by_id(payload.employee_id)
            if not emp:
                raise AppException(message="Employee profile not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Check category exists
            cat = await self.repo.get_category_by_id(payload.category_id)
            if not cat:
                raise AppException(message="Document category not found.", status_code=status.HTTP_404_NOT_FOUND)

            save_path, filename, file_size = await self._save_uploaded_file(file)

            doc_kwargs = payload.model_dump()
            doc_kwargs.update({
                "uploaded_by": uploader_id,
                "file_path": save_path,
                "file_name": filename,
                "file_size": file_size,
                "version": 1,
            })

            doc = await self.repo.create_employee_document(**doc_kwargs)

            # Add to versions table
            await self.repo.create_version(
                employee_doc_id=doc.id,
                version_number=1,
                file_path=save_path,
                uploaded_by=uploader_id,
            )

            # Write Audit log
            await self.repo.create_audit_log(
                user_id=uploader_id,
                action="UPLOAD",
                target_type="EMPLOYEE_DOC",
                target_id=doc.id,
                details=f"Uploaded version 1 of document: {payload.title}",
                ip_address=ip_address,
            )

            await self.session.commit()
            full_doc = await self.repo.get_employee_document_by_id(doc.id)
            return EmployeeDocumentResponse.model_validate(full_doc)

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("upload_employee_document: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_employee_document(
        self,
        user_id: uuid.UUID,
        doc_uuid: uuid.UUID,
        ip_address: str | None = None,
    ) -> EmployeeDocumentResponse:
        try:
            doc = await self.repo.get_employee_document_by_id(doc_uuid)
            if not doc:
                raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Audit view action
            await self.repo.create_audit_log(
                user_id=user_id,
                action="VIEW",
                target_type="EMPLOYEE_DOC",
                target_id=doc_uuid,
                details=f"Viewed document: {doc.title}",
                ip_address=ip_address,
            )
            await self.session.commit()

            return EmployeeDocumentResponse.model_validate(doc)
        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("get_employee_document: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def update_employee_document(
        self,
        uploader_id: uuid.UUID,
        doc_uuid: uuid.UUID,
        payload: EmployeeDocumentUpdate,
        file: UploadFile | None = None,
        ip_address: str | None = None,
    ) -> EmployeeDocumentResponse:
        logger.info("update_employee_document | doc_id=%s", doc_uuid)
        try:
            doc = await self.repo.get_employee_document_by_id(doc_uuid)
            if not doc:
                raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

            update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
            
            # Revisions file upload versioning
            if file:
                save_path, filename, file_size = await self._save_uploaded_file(file)
                new_version = doc.version + 1
                update_data.update({
                    "file_path": save_path,
                    "file_name": filename,
                    "file_size": file_size,
                    "version": new_version,
                })
                # Add version log
                await self.repo.create_version(
                    employee_doc_id=doc_uuid,
                    version_number=new_version,
                    file_path=save_path,
                    uploaded_by=uploader_id,
                )
                audit_msg = f"Updated document fields & uploaded version {new_version}."
            else:
                audit_msg = "Updated document details metadata."

            await self.repo.update_employee_document(doc_uuid, **update_data)

            # Write Audit log
            await self.repo.create_audit_log(
                user_id=uploader_id,
                action="UPDATE",
                target_type="EMPLOYEE_DOC",
                target_id=doc_uuid,
                details=audit_msg,
                ip_address=ip_address,
            )

            await self.session.commit()
            updated = await self.repo.get_employee_document_by_id(doc_uuid)
            return EmployeeDocumentResponse.model_validate(updated)

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("update_employee_document: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def delete_employee_document(
        self,
        uploader_id: uuid.UUID,
        doc_uuid: uuid.UUID,
        ip_address: str | None = None,
    ) -> None:
        try:
            doc = await self.repo.get_employee_document_by_id(doc_uuid)
            if not doc:
                raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

            await self.repo.soft_delete_employee_document(doc_uuid)

            # Write Audit log
            await self.repo.create_audit_log(
                user_id=uploader_id,
                action="DELETE",
                target_type="EMPLOYEE_DOC",
                target_id=doc_uuid,
                details=f"Soft deleted document: {doc.title}",
                ip_address=ip_address,
            )

            await self.session.commit()
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("delete_employee_document: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def list_employee_documents(
        self,
        employee_id: uuid.UUID | None = None,
        category_id: uuid.UUID | None = None,
        status: str | None = None,
        visibility: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EmployeeDocumentResponse]:
        try:
            await self.seed_categories_if_needed()
            docs = await self.repo.list_employee_documents(
                employee_id=employee_id,
                category_id=category_id,
                status=status,
                visibility=visibility,
                search=search,
                limit=limit,
                offset=offset,
            )
            return [EmployeeDocumentResponse.model_validate(d) for d in docs]
        except SQLAlchemyError as exc:
            logger.exception("list_employee_documents: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Company Document CRUD
    # ------------------------------------------------------------------

    async def upload_company_document(
        self,
        uploader_id: uuid.UUID,
        payload: CompanyDocumentCreate,
        file: UploadFile,
        ip_address: str | None = None,
    ) -> CompanyDocumentResponse:
        try:
            await self.seed_categories_if_needed()
            
            # Check category exists
            cat = await self.repo.get_category_by_id(payload.category_id)
            if not cat:
                raise AppException(message="Document category not found.", status_code=status.HTTP_440_NOT_FOUND if hasattr(status, "HTTP_440_NOT_FOUND") else status.HTTP_404_NOT_FOUND)

            save_path, filename, file_size = await self._save_uploaded_file(file)

            doc_kwargs = payload.model_dump()
            doc_kwargs.update({
                "uploaded_by": uploader_id,
                "file_path": save_path,
                "file_name": filename,
                "file_size": file_size,
                "visibility": payload.visibility.upper(),
                "status": "PUBLISHED",
            })

            doc = await self.repo.create_company_document(**doc_kwargs)

            # Add to versions table
            await self.repo.create_version(
                company_doc_id=doc.id,
                version_number=1,
                file_path=save_path,
                uploaded_by=uploader_id,
            )

            # Write Audit log
            await self.repo.create_audit_log(
                user_id=uploader_id,
                action="UPLOAD",
                target_type="COMPANY_DOC",
                target_id=doc.id,
                details=f"Uploaded company document: {payload.title}",
                ip_address=ip_address,
            )

            await self.session.commit()
            full_doc = await self.repo.get_company_document_by_id(doc.id)
            return CompanyDocumentResponse.model_validate(full_doc)

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("upload_company_document: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_company_document(
        self,
        user_id: uuid.UUID,
        doc_uuid: uuid.UUID,
        ip_address: str | None = None,
    ) -> CompanyDocumentResponse:
        try:
            doc = await self.repo.get_company_document_by_id(doc_uuid)
            if not doc:
                raise AppException(message="Company document not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Audit view action
            await self.repo.create_audit_log(
                user_id=user_id,
                action="VIEW",
                target_type="COMPANY_DOC",
                target_id=doc_uuid,
                details=f"Viewed company document: {doc.title}",
                ip_address=ip_address,
            )
            await self.session.commit()

            return CompanyDocumentResponse.model_validate(doc)
        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("get_company_document: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def list_company_documents(
        self,
        category_id: uuid.UUID | None = None,
        department: str | None = None,
        branch: str | None = None,
        visibility: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CompanyDocumentResponse]:
        try:
            await self.seed_categories_if_needed()
            docs = await self.repo.list_company_documents(
                category_id=category_id,
                department=department,
                branch=branch,
                visibility=visibility,
                search=search,
                limit=limit,
                offset=offset,
            )
            return [CompanyDocumentResponse.model_validate(d) for d in docs]
        except SQLAlchemyError as exc:
            logger.exception("list_company_documents: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def delete_company_document(
        self,
        uploader_id: uuid.UUID,
        doc_uuid: uuid.UUID,
        ip_address: str | None = None,
    ) -> None:
        try:
            doc = await self.repo.get_company_document_by_id(doc_uuid)
            if not doc:
                raise AppException(message="Company document not found.", status_code=status.HTTP_404_NOT_FOUND)

            await self.repo.soft_delete_company_document(doc_uuid)

            # Write Audit log
            await self.repo.create_audit_log(
                user_id=uploader_id,
                action="DELETE",
                target_type="COMPANY_DOC",
                target_id=doc_uuid,
                details=f"Soft deleted company document: {doc.title}",
                ip_address=ip_address,
            )

            await self.session.commit()
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("delete_company_document: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Document Templates Placeholder generation
    # ------------------------------------------------------------------

    async def create_template(self, user_id: uuid.UUID, payload: TemplateCreate) -> TemplateResponse:
        try:
            template = await self.repo.create_template(
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

    async def list_templates(self) -> list[TemplateResponse]:
        try:
            templates = await self.repo.list_templates()
            return [TemplateResponse.model_validate(t) for t in templates]
        except SQLAlchemyError as exc:
            logger.exception("list_templates: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def generate_document_from_template(
        self,
        template_uuid: uuid.UUID,
        employee_uuid: uuid.UUID,
    ) -> str:
        """Inject placeholders dynamically like {{employee_name}}, {{employee_id}}, {{designation}} etc."""
        try:
            template = await self.repo.get_template_by_id(template_uuid)
            if not template:
                raise AppException(message="Template not found.", status_code=status.HTTP_404_NOT_FOUND)

            emp = await self.employee_repo.get_by_id(employee_uuid)
            if not emp:
                raise AppException(message="Employee profile not found.", status_code=status.HTTP_404_NOT_FOUND)

            body = template.template_body
            replacements = {
                "{{employee_name}}": f"{emp.first_name} {emp.last_name}",
                "{{employee_id}}": emp.employee_id,
                "{{department}}": emp.department or "General",
                "{{designation}}": emp.designation or "Staff",
                "{{joining_date}}": str(emp.joining_date) if emp.joining_date else "",
                "{{salary}}": str(emp.salary) if hasattr(emp, "salary") else "0.00",
            }

            for placeholder, value in replacements.items():
                body = body.replace(placeholder, value)

            return body

        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("generate_document_from_template: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Digital Signatures
    # ------------------------------------------------------------------

    async def request_signature(self, user_id: uuid.UUID, doc_uuid: uuid.UUID, signer_user_id: uuid.UUID) -> SignatureResponse:
        logger.info("request_signature | doc=%s | signer=%s", doc_uuid, signer_user_id)
        try:
            doc = await self.repo.get_employee_document_by_id(doc_uuid)
            if not doc:
                raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Check signer user profile exists
            signer = await self.user_repo.get_by_id(signer_user_id)
            if not signer:
                raise AppException(message="Signer user account not found.", status_code=status.HTTP_404_NOT_FOUND)

            sig = await self.repo.create_signature_request(
                employee_doc_id=doc_uuid,
                signer_user_id=signer_user_id,
                status="PENDING",
            )

            # Transition document status to REQUIRES_SIGNATURE
            await self.repo.update_employee_document(doc_uuid, status="REQUIRES_SIGNATURE")

            # Audit signature request
            await self.repo.create_audit_log(
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
        try:
            sig = await self.repo.get_active_signature_request(doc_uuid)
            if not sig or sig.signer_user_id != signer_id:
                raise AppException(message="No pending signature request found for you on this document.", status_code=status.HTTP_404_NOT_FOUND)

            await self.repo.update_signature_status(
                sig.id,
                status="SIGNED",
                signed_at=datetime.now(timezone.utc),
                ip_address=ip_address,
                device_info=device_info,
            )

            # Update document status back to PENDING or VERIFIED
            await self.repo.update_employee_document(doc_uuid, status="PENDING")

            # Audit signature complete
            await self.repo.create_audit_log(
                user_id=signer_id,
                action="SIGN",
                target_type="EMPLOYEE_DOC",
                target_id=doc_uuid,
                details="Digitally signed document.",
                ip_address=ip_address,
            )

            await self.session.commit()
            updated = await self.repo.get_signature_by_id(sig.id)
            return SignatureResponse.model_validate(updated)

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("sign_document: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Document Verifications
    # ------------------------------------------------------------------

    async def verify_document(
        self,
        verifier_id: uuid.UUID,
        doc_uuid: uuid.UUID,
        action: str,
        comments: str | None = None,
        ip_address: str | None = None,
    ) -> EmployeeDocumentResponse:
        logger.info("verify_document | doc=%s | action=%s", doc_uuid, action)
        try:
            doc = await self.repo.get_employee_document_by_id(doc_uuid)
            if not doc:
                raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Update employee_documents status
            mapped_status = "VERIFIED" if action == "APPROVED" else "REJECTED"
            await self.repo.update_employee_document(
                doc_uuid,
                status=mapped_status,
                is_verified=(action == "APPROVED"),
                verified_by=verifier_id,
                verified_at=datetime.now(timezone.utc),
            )

            # Create Verification audit entry
            await self.repo.create_verification(
                employee_doc_id=doc_uuid,
                verifier_user_id=verifier_id,
                action=action,
                comments=comments,
            )

            # Create Audit log
            await self.repo.create_audit_log(
                user_id=verifier_id,
                action="VERIFY",
                target_type="EMPLOYEE_DOC",
                target_id=doc_uuid,
                details=f"Verification decision: {action}. Remarks: {comments}",
                ip_address=ip_address,
            )

            await self.session.commit()
            updated = await self.repo.get_employee_document_by_id(doc_uuid)
            return EmployeeDocumentResponse.model_validate(updated)

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("verify_document: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Expiry Tracking lists
    # ------------------------------------------------------------------

    async def list_expiring_documents(self) -> list[EmployeeDocumentResponse]:
        try:
            # Threshold default: 90 days
            limit_date = date.today() + timedelta(days=90)
            docs = await self.repo.get_expiring_documents(limit_date)
            return [EmployeeDocumentResponse.model_validate(d) for d in docs]
        except SQLAlchemyError as exc:
            logger.exception("list_expiring_documents: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def list_expired_documents(self) -> list[EmployeeDocumentResponse]:
        try:
            docs = await self.repo.get_expired_documents()
            return [EmployeeDocumentResponse.model_validate(d) for d in docs]
        except SQLAlchemyError as exc:
            logger.exception("list_expired_documents: db error", exc_info=exc)
            raise DatabaseException() from exc


async def get_document_service(
    session: AsyncSession = Depends(get_db_session),
) -> DocumentService:
    return DocumentService(
        session=session,
        repo=DocumentRepository(session),
        employee_repo=EmployeeRepository(session),
        user_repo=UserRepository(session),
    )
