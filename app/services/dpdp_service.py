"""Application services for DPDP consent, export, retention and erasure."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.attendance.models.attendance import Attendance
from app.models.audit_log import AuditLog
from app.models.dpdp_compliance import (
    ConsentPurposeCode,
    ConsentStatus,
    DataConsentLedger,
    DataRetentionPolicy,
    DataSubjectRequest,
    DataSubjectRequestStatus,
    DataSubjectRequestType,
)
from app.models.employee import Employee
from app.models.employee_address import EmployeeAddress
from app.models.employee_bank_account import EmployeeBankAccount
from app.models.employee_document import EmployeeDocument
from app.models.employee_education import EmployeeEducation
from app.models.employee_emergency_contact import EmployeeEmergencyContact
from app.models.employee_experience import EmployeeExperience
from app.models.employee_skill import EmployeeSkill
from app.models.leave import LeaveRequest
from app.models.payroll import Payslip
from app.models.user import User


DEFAULT_STATUTORY_RETENTION_DAYS = 2920  # eight years
STATUTORY_RETENTION_ENTITY_TYPES = ("PAYROLL", "TAX", "STATUTORY_PAYROLL")


class DPDPNotFoundError(LookupError):
    """A resource does not exist inside the caller's tenant."""


class DPDPService:
    """Tenant-scoped DPDP operations.

    Every lookup includes ``company_id`` explicitly and bypasses the ambient
    loader tenant filter.  This makes cross-tenant isolation independent of
    context-variable state and ensures an unknown *or foreign* id has the same
    not-found behavior.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    # ------------------------------------------------------------------
    # Lookup and serialization helpers
    # ------------------------------------------------------------------
    async def get_employee(
        self,
        employee_id: uuid.UUID,
        company_id: uuid.UUID,
        *,
        with_personal_relations: bool = False,
    ) -> Employee:
        stmt = select(Employee).where(
            Employee.id == employee_id,
            Employee.company_id == company_id,
            Employee.is_deleted.is_(False),
        )
        if with_personal_relations:
            stmt = stmt.options(
                selectinload(Employee.addresses),
                selectinload(Employee.documents),
                selectinload(Employee.education),
                selectinload(Employee.experience),
                selectinload(Employee.skills),
                selectinload(Employee.emergency_contacts),
                selectinload(Employee.bank_accounts),
            )
        result = await self.session.execute(stmt.execution_options(bypass_tenant=True))
        employee = result.scalar_one_or_none()
        if employee is None:
            raise DPDPNotFoundError("Employee not found")
        return employee

    async def get_employee_for_user(
        self, user_id: uuid.UUID, company_id: uuid.UUID
    ) -> Employee:
        result = await self.session.execute(
            select(Employee)
            .where(
                Employee.user_id == user_id,
                Employee.company_id == company_id,
                Employee.is_deleted.is_(False),
            )
            .execution_options(bypass_tenant=True)
        )
        employee = result.scalar_one_or_none()
        if employee is None:
            raise DPDPNotFoundError("Employee profile not found")
        return employee

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, (datetime, date, time)):
            return value.isoformat()
        if isinstance(value, uuid.UUID):
            return str(value)
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, dict):
            return {str(key): DPDPService._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [DPDPService._json_safe(item) for item in value]
        if isinstance(value, bytes):
            # Binary biometric/document payloads are not inlined into JSON.
            return f"<{len(value)} binary bytes>"
        return value

    @classmethod
    def _model_dict(cls, instance: Any, *, exclude: Iterable[str] = ()) -> dict[str, Any]:
        from sqlalchemy import inspect

        excluded = set(exclude)
        values: dict[str, Any] = {}
        for attribute in inspect(instance).mapper.column_attrs:
            name = attribute.key
            if name in excluded or name.endswith("_blind_idx"):
                continue
            values[name] = cls._json_safe(getattr(instance, name))
        return values

    @staticmethod
    def _enum_text(value: Any) -> str:
        return value.value if isinstance(value, Enum) else str(value)

    @classmethod
    def _request_summary(cls, request: DataSubjectRequest) -> dict[str, Any]:
        execution_summary: Any = request.execution_summary
        if isinstance(execution_summary, str):
            try:
                execution_summary = json.loads(execution_summary)
            except json.JSONDecodeError:
                pass
        return {
            "id": str(request.id),
            "employee_id": str(request.employee_id),
            "company_id": str(request.company_id) if request.company_id else None,
            "request_type": cls._enum_text(request.request_type),
            "status": cls._enum_text(request.status),
            "reviewed_by": str(request.reviewed_by) if request.reviewed_by else None,
            "execution_summary": execution_summary,
            "requested_at": request.requested_at.isoformat() if request.requested_at else None,
            "reviewed_at": request.reviewed_at.isoformat() if request.reviewed_at else None,
            "executed_at": request.executed_at.isoformat() if request.executed_at else None,
            "created_at": request.created_at.isoformat() if request.created_at else None,
            "updated_at": request.updated_at.isoformat() if request.updated_at else None,
        }

    # ------------------------------------------------------------------
    # Consent ledger
    # ------------------------------------------------------------------
    async def record_consent(
        self,
        *,
        employee_id: uuid.UUID,
        company_id: uuid.UUID,
        user_id: uuid.UUID | None,
        purpose_code: str | ConsentPurposeCode,
        policy_version: str,
        consent_status: str | ConsentStatus = ConsentStatus.GRANTED,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> DataConsentLedger:
        employee = await self.get_employee(employee_id, company_id)
        purpose = purpose_code.value if isinstance(purpose_code, ConsentPurposeCode) else str(purpose_code).upper()
        status_value = consent_status.value if isinstance(consent_status, ConsentStatus) else str(consent_status).upper()
        if purpose not in {item.value for item in ConsentPurposeCode}:
            raise ValueError("Unsupported consent purpose_code")
        if status_value not in {item.value for item in ConsentStatus}:
            raise ValueError("Unsupported consent_status")
        if not policy_version or not policy_version.strip():
            raise ValueError("policy_version is required")

        now = datetime.now(timezone.utc)
        entry = DataConsentLedger(
            company_id=company_id,
            employee_id=employee.id,
            user_id=user_id or employee.user_id,
            purpose_code=purpose,
            policy_version=policy_version.strip(),
            consent_status=status_value,
            ip_address=ip_address,
            user_agent=user_agent[:512] if user_agent else None,
            granted_at=now if status_value == ConsentStatus.GRANTED.value else None,
            withdrawn_at=now if status_value == ConsentStatus.WITHDRAWN.value else None,
        )
        self.session.add(entry)
        await self.session.flush()
        await self.session.commit()
        await self.session.refresh(entry)
        return entry

    async def list_consents(
        self, *, employee_id: uuid.UUID, company_id: uuid.UUID
    ) -> list[DataConsentLedger]:
        # Resolve first so a foreign employee id cannot be used as an oracle.
        await self.get_employee(employee_id, company_id)
        result = await self.session.execute(
            select(DataConsentLedger)
            .where(
                DataConsentLedger.employee_id == employee_id,
                DataConsentLedger.company_id == company_id,
            )
            .order_by(DataConsentLedger.created_at.desc(), DataConsentLedger.id.desc())
            .execution_options(bypass_tenant=True)
        )
        return list(result.scalars().all())

    async def list_consents_for_user(
        self, *, user_id: uuid.UUID, company_id: uuid.UUID
    ) -> list[DataConsentLedger]:
        employee = await self.get_employee_for_user(user_id, company_id)
        return await self.list_consents(employee_id=employee.id, company_id=company_id)

    # ------------------------------------------------------------------
    # Retention policy and statutory hold
    # ------------------------------------------------------------------
    async def get_retention_policy(
        self, company_id: uuid.UUID, entity_type: str = "PAYROLL"
    ) -> DataRetentionPolicy:
        normalized = entity_type.strip().upper()
        result = await self.session.execute(
            select(DataRetentionPolicy)
            .where(
                DataRetentionPolicy.company_id == company_id,
                DataRetentionPolicy.entity_type == normalized,
            )
            .execution_options(bypass_tenant=True)
        )
        policy = result.scalar_one_or_none()
        if policy is not None:
            return policy
        return DataRetentionPolicy(
            company_id=company_id,
            entity_type=normalized,
            retention_days=DEFAULT_STATUTORY_RETENTION_DAYS,
            auto_anonymise_after_exit=True,
        )

    async def set_retention_policy(
        self,
        *,
        company_id: uuid.UUID,
        entity_type: str,
        retention_days: int = DEFAULT_STATUTORY_RETENTION_DAYS,
        auto_anonymise_after_exit: bool = True,
    ) -> DataRetentionPolicy:
        if retention_days < 0:
            raise ValueError("retention_days cannot be negative")
        normalized = entity_type.strip().upper()
        if not normalized:
            raise ValueError("entity_type is required")
        result = await self.session.execute(
            select(DataRetentionPolicy)
            .where(
                DataRetentionPolicy.company_id == company_id,
                DataRetentionPolicy.entity_type == normalized,
            )
            .execution_options(bypass_tenant=True)
        )
        policy = result.scalar_one_or_none()
        if policy is None:
            policy = DataRetentionPolicy(company_id=company_id, entity_type=normalized)
            self.session.add(policy)
        policy.retention_days = retention_days
        policy.auto_anonymise_after_exit = auto_anonymise_after_exit
        await self.session.flush()
        await self.session.commit()
        await self.session.refresh(policy)
        return policy

    async def _payslips(
        self, employee_id: uuid.UUID, company_id: uuid.UUID
    ) -> list[Payslip]:
        result = await self.session.execute(
            select(Payslip)
            .where(Payslip.employee_id == employee_id, Payslip.company_id == company_id)
            .order_by(Payslip.created_at.desc())
            .execution_options(bypass_tenant=True)
        )
        return list(result.scalars().all())

    @staticmethod
    def _aware(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    def _within_retention(
        self,
        payslips: Iterable[Payslip],
        retention_days: int,
        *,
        now: datetime | None = None,
    ) -> list[Payslip]:
        current = self._aware(now) or datetime.now(timezone.utc)
        held: list[Payslip] = []
        for payslip in payslips:
            reference = self._aware(payslip.created_at)
            if reference is None:
                try:
                    reference = datetime(
                        payslip.period_year,
                        payslip.period_month,
                        1,
                        tzinfo=timezone.utc,
                    )
                except (TypeError, ValueError):
                    # An invalid historical period must not accidentally weaken
                    # the statutory hold. Treat it as retained.
                    held.append(payslip)
                    continue
            if reference + timedelta(days=retention_days) > current:
                held.append(payslip)
        return held

    async def statutory_hold_check(
        self,
        *,
        employee_id: uuid.UUID,
        company_id: uuid.UUID,
        now: datetime | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        payslips = await self._payslips(employee_id, company_id)
        policy = await self.get_retention_policy(company_id, "PAYROLL")
        held = self._within_retention(payslips, policy.retention_days, now=now)
        details = {
            "statutory_record_count": len(payslips),
            "held_record_count": len(held),
            "retention_days": policy.retention_days,
            "reason": "STATUTORY_PAYROLL_TAX_RETENTION" if held else None,
        }
        return bool(held), details

    # ------------------------------------------------------------------
    # Data export
    # ------------------------------------------------------------------
    async def build_data_export(
        self, *, employee_id: uuid.UUID, company_id: uuid.UUID
    ) -> dict[str, Any]:
        employee = await self.get_employee(
            employee_id, company_id, with_personal_relations=True
        )
        attendance_result = await self.session.execute(
            select(Attendance)
            .where(Attendance.employee_id == employee_id, Attendance.company_id == company_id)
            .order_by(Attendance.date.desc())
            .execution_options(bypass_tenant=True)
        )
        leave_result = await self.session.execute(
            select(LeaveRequest)
            .where(LeaveRequest.employee_id == employee_id)
            .order_by(LeaveRequest.created_at.desc())
            .execution_options(bypass_tenant=True)
        )
        payslips = await self._payslips(employee_id, company_id)
        attendance = list(attendance_result.scalars().all())
        leave = list(leave_result.scalars().all())

        operational_columns = {
            "activation_token",
            "activation_token_expires_at",
            "invited_by",
            "created_by",
            "deactivated_by",
        }
        personal = self._model_dict(employee, exclude=operational_columns)
        personal["addresses"] = [self._model_dict(item) for item in employee.addresses]
        personal["documents"] = [self._model_dict(item) for item in employee.documents]
        personal["education"] = [self._model_dict(item) for item in employee.education]
        personal["experience"] = [self._model_dict(item) for item in employee.experience]
        personal["skills"] = [self._model_dict(item) for item in employee.skills]
        personal["emergency_contacts"] = [self._model_dict(item) for item in employee.emergency_contacts]
        personal["bank_accounts"] = [self._model_dict(item) for item in employee.bank_accounts]

        generated_at = datetime.now(timezone.utc)
        return {
            "manifest": {
                "format_version": "1.0",
                "employee_id": str(employee.id),
                "company_id": str(company_id),
                "generated_at": generated_at.isoformat(),
                "attendance_records": len(attendance),
                "leave_records": len(leave),
                "payslip_records": len(payslips),
            },
            "personal": personal,
            "attendance": [self._model_dict(item) for item in attendance],
            "leave": [self._model_dict(item) for item in leave],
            "payslips": [self._model_dict(item) for item in payslips],
        }

    async def export_employee_data(
        self,
        *,
        employee_id: uuid.UUID,
        company_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> dict[str, Any]:
        payload = await self.build_data_export(employee_id=employee_id, company_id=company_id)
        now = datetime.now(timezone.utc)
        request = DataSubjectRequest(
            company_id=company_id,
            employee_id=employee_id,
            request_type=DataSubjectRequestType.EXPORT.value,
            status=DataSubjectRequestStatus.EXECUTED.value,
            reviewed_by=actor_id,
            reviewed_at=now,
            executed_at=now,
            execution_summary=json.dumps(
                {
                    "attendance_records": payload["manifest"]["attendance_records"],
                    "leave_records": payload["manifest"]["leave_records"],
                    "payslip_records": payload["manifest"]["payslip_records"],
                },
                separators=(",", ":"),
            ),
        )
        self.session.add(request)
        await self.session.flush()
        payload["manifest"]["data_subject_request_id"] = str(request.id)
        await self.session.commit()
        return payload

    @staticmethod
    def export_as_json(payload: dict[str, Any]) -> bytes:
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")

    @staticmethod
    def export_as_zip(payload: dict[str, Any]) -> bytes:
        """Build an in-memory ZIP without writing personal data to disk."""

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for section in ("manifest", "personal", "attendance", "leave", "payslips"):
                archive.writestr(
                    f"{section}.json",
                    json.dumps(payload[section], ensure_ascii=False, indent=2, sort_keys=True),
                )
            # A single complete document is convenient for data-portability
            # tools while the per-section files support targeted imports.
            archive.writestr(
                "dpdp-export.json",
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            )
        return buffer.getvalue()

    # ------------------------------------------------------------------
    # Erasure requests and anonymisation
    # ------------------------------------------------------------------
    async def create_erasure_request(
        self, *, employee_id: uuid.UUID, company_id: uuid.UUID
    ) -> DataSubjectRequest:
        await self.get_employee(employee_id, company_id)
        request = DataSubjectRequest(
            company_id=company_id,
            employee_id=employee_id,
            request_type=DataSubjectRequestType.ERASURE.value,
            status=DataSubjectRequestStatus.PENDING.value,
        )
        self.session.add(request)
        await self.session.flush()
        await self.session.commit()
        await self.session.refresh(request)
        return request

    async def get_data_subject_request(
        self, request_id: uuid.UUID, company_id: uuid.UUID
    ) -> DataSubjectRequest:
        result = await self.session.execute(
            select(DataSubjectRequest)
            .where(
                DataSubjectRequest.id == request_id,
                DataSubjectRequest.company_id == company_id,
            )
            .execution_options(bypass_tenant=True)
        )
        request = result.scalar_one_or_none()
        if request is None:
            raise DPDPNotFoundError("Data subject request not found")
        return request

    async def _anonymise_non_statutory_data(
        self, employee: Employee, *, preserve_statutory_identity: bool
    ) -> dict[str, int]:
        company_id = employee.company_id
        employee_id = employee.id
        token = employee_id.hex
        counts = {"bank_accounts": 0, "attendance_records": 0, "leave_records": 0}

        # Keep employee_id and employment/payslip linkage intact for statutory
        # reconciliation. Direct contact and biometric identifiers are erased.
        employee.first_name = "Erased"
        employee.last_name = f"Employee-{token[:8]}"
        employee.personal_email = f"erased_{token}@erased.invalid"
        employee.company_email = None
        employee.phone = f"erased_{token[:8]}"
        employee.alternate_phone = None
        employee.profile_photo_url = None
        employee.date_of_birth = None
        employee.gender = None
        employee.blood_group = None
        employee.marital_status = None
        employee.middle_name = None
        employee.father_name = None
        employee.mother_name = None
        employee.spouse_name = None
        employee.face_embedding = None
        employee.is_face_enrolled = False
        employee.face_enrolled_at = None
        employee.is_active = False
        employee.status = "ANONYMISED"

        employee.aadhaar_number = None
        employee.passport_number = None
        employee.voter_id = None
        employee.driving_license = None
        employee.upi_id = None
        if not preserve_statutory_identity:
            employee.pan_number = None
            employee.uan_number = None
            employee.pf_number = None
            employee.esi_number = None
            employee.esic_number = None
        employee.refresh_pii_blind_indexes()

        bank_result = await self.session.execute(
            select(EmployeeBankAccount)
            .where(EmployeeBankAccount.employee_id == employee_id)
            .execution_options(bypass_tenant=True)
        )
        for account in bank_result.scalars().all():
            account.account_holder_name = "Erased Employee"
            account.account_number = f"ERASED-{account.id.hex[:20]}"
            account.ifsc_code = "ERASED00000"
            account.bank_name = "ERASED"
            counts["bank_accounts"] += 1

        attendance_result = await self.session.execute(
            select(Attendance)
            .where(Attendance.employee_id == employee_id, Attendance.company_id == company_id)
            .execution_options(bypass_tenant=True)
        )
        for record in attendance_result.scalars().all():
            # Preserve worked-time facts needed by payroll but erase biometrics,
            # precise location, network and device identifiers.
            record.face_image_url = None
            record.captured_face_url = None
            record.checkout_image_url = None
            record.latitude = None
            record.longitude = None
            record.location_accuracy = None
            record.device_info = None
            record.ip_address = None
            record.notes = None
            counts["attendance_records"] += 1

        leave_result = await self.session.execute(
            select(LeaveRequest)
            .where(LeaveRequest.employee_id == employee_id)
            .execution_options(bypass_tenant=True)
        )
        for record in leave_result.scalars().all():
            record.reason = "[ERASED]"
            record.rejection_reason = None
            counts["leave_records"] += 1

        # These relations have no statutory ledger totals. Delete them rather
        # than retaining reversible pseudonyms or document URLs.
        for model in (
            EmployeeAddress,
            EmployeeDocument,
            EmployeeEducation,
            EmployeeExperience,
            EmployeeSkill,
            EmployeeEmergencyContact,
        ):
            result = await self.session.execute(
                delete(model)
                .where(model.employee_id == employee_id)
                .execution_options(bypass_tenant=True)
            )
            counts[model.__tablename__] = max(0, getattr(result, "rowcount", 0) or 0)

        if employee.user_id:
            user_result = await self.session.execute(
                select(User)
                .where(User.id == employee.user_id, User.company_id == company_id)
                .execution_options(bypass_tenant=True)
            )
            user = user_result.scalar_one_or_none()
            if user is not None:
                user.name = "Erased Employee"
                user.email = f"erased_{token}@erased.invalid"
                user.phone = token[-10:]
                user.is_active = False
                user.is_deleted = True
                user.account_status = "DEACTIVATED"
                user.token_version = (user.token_version or 0) + 1

        self.session.add(employee)
        return counts

    async def execute_erasure_request(
        self,
        *,
        request_id: uuid.UUID,
        company_id: uuid.UUID,
        reviewer_id: uuid.UUID,
        now: datetime | None = None,
    ) -> DataSubjectRequest:
        request = await self.get_data_subject_request(request_id, company_id)
        if request.request_type != DataSubjectRequestType.ERASURE.value:
            raise ValueError("Only ERASURE requests can be executed by this endpoint")
        if request.status == DataSubjectRequestStatus.EXECUTED.value:
            return request
        if request.status == DataSubjectRequestStatus.REJECTED_STATUTORY_HOLD.value:
            return request

        employee = await self.get_employee(request.employee_id, company_id)
        payslips = await self._payslips(employee.id, company_id)
        held, hold_details = await self.statutory_hold_check(
            employee_id=employee.id, company_id=company_id, now=now
        )
        current = self._aware(now) or datetime.now(timezone.utc)
        request.reviewed_by = reviewer_id
        request.reviewed_at = current

        if held:
            request.status = DataSubjectRequestStatus.REJECTED_STATUTORY_HOLD.value
            request.execution_summary = json.dumps(hold_details, separators=(",", ":"))
            self.session.add(request)
            await self.session.commit()
            return request

        counts = await self._anonymise_non_statutory_data(
            employee, preserve_statutory_identity=bool(payslips)
        )
        def amount(value: Any) -> Decimal:
            return Decimal(str(value)) if value is not None else Decimal("0")

        statutory_totals = {
            "payslip_records_preserved": len(payslips),
            "gross_earnings_preserved": str(sum((amount(item.gross_earnings) for item in payslips), Decimal("0"))),
            "net_pay_preserved": str(sum((amount(item.net_pay) for item in payslips), Decimal("0"))),
            "employee_pf_preserved": str(sum((amount(item.employee_pf) for item in payslips), Decimal("0"))),
        }
        request.status = DataSubjectRequestStatus.EXECUTED.value
        request.executed_at = current
        request.execution_summary = json.dumps(
            {**counts, **statutory_totals}, separators=(",", ":"), sort_keys=True
        )
        self.session.add(request)
        self.session.add(
            AuditLog(
                company_id=company_id,
                user_id=reviewer_id,
                actor_id=str(reviewer_id),
                action="DPDP_ERASURE_EXECUTED",
                entity_type="DataSubjectRequest",
                entity_id=str(request.id),
                details="Non-statutory personal data erased; statutory payroll ledger totals preserved.",
            )
        )
        await self.session.commit()
        return request


# Alternative spelling used by some integrations.
DpdpService = DPDPService


__all__ = [
    "DEFAULT_STATUTORY_RETENTION_DAYS",
    "DPDPNotFoundError",
    "DPDPService",
    "DpdpService",
]
