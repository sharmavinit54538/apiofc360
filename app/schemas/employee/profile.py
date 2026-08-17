"""EmployeeResponse and profile detail schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from typing import Any
from pydantic import BaseModel, ConfigDict, model_validator

from app.schemas.employee.address import EmployeeAddressResponse
from app.schemas.employee.document import EmployeeDocumentResponse
from app.schemas.employee.education import EmployeeEducationResponse
from app.schemas.employee.experience import EmployeeExperienceResponse
from app.schemas.employee.skill import EmployeeSkillResponse
from app.schemas.employee.asset import EmployeeAssetResponse
from app.schemas.employee.emergency import EmployeeEmergencyContactResponse
from app.schemas.employee.bank import EmployeeBankAccountResponse
from app.schemas.employee.onboarding import EmployeeLeavePolicyResponse, EmployeeOnboardingStepResponse
from app.schemas.employee.update import EmployeeListItem


class EmployeeResponse(BaseModel):
    """Full employee profile returned by GET /employees/{id}."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID | None
    employee_id: str
    first_name: str
    last_name: str
    profile_photo_url: str | None
    gender: str | None
    date_of_birth: date | None
    personal_email: str
    company_email: str | None
    phone: str
    alternate_phone: str | None
    blood_group: str | None
    marital_status: str | None
    department: str
    designation: str
    team: str | None
    reporting_manager_id: uuid.UUID | None
    branch: str | None
    work_location: str | None
    employment_type: str
    employment_status: str
    joining_date: date
    probation_end_date: date | None
    shift: str | None
    employee_capacity: int | None = 100
    cost_center_id: str | None = None
    cost_center: str | None = None
    cost_id: str | None = None
    costID: str | None = None
    costCenterId: str | None = None
    ctc: Decimal | None
    basic_salary: Decimal | None
    hra: Decimal | None
    bonus: Decimal | None
    pf: Decimal | None
    esi: Decimal | None
    professional_tax: Decimal | None
    salary: Decimal | None = None
    annual_ctc: Decimal | None = None
    role: str
    leave_group: str | None
    status: str
    is_deleted: bool
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    reporting_manager_id: uuid.UUID | None = None
    reporting_manager_name: str | None = None
    activation_token: str | None = None
    activation_url: str | None = None
    activation_token_expires_at: datetime | None = None
    email_sent: bool | None = True
    email: str | None = None
    full_name: str | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_cost_id(cls, data: Any) -> Any:
        from app.core.config import settings

        cc_val = None
        if hasattr(data, "cost_center_id") and getattr(data, "cost_center_id") is not None:
            cc_val = getattr(data, "cost_center_id")
        elif hasattr(data, "cost_center") and getattr(data, "cost_center") is not None:
            cc_val = getattr(data, "cost_center")
        elif hasattr(data, "cost_id") and getattr(data, "cost_id") is not None:
            cc_val = getattr(data, "cost_id")
        elif hasattr(data, "costID") and getattr(data, "costID") is not None:
            cc_val = getattr(data, "costID")
        elif hasattr(data, "costCenterId") and getattr(data, "costCenterId") is not None:
            cc_val = getattr(data, "costCenterId")
        elif isinstance(data, dict):
            cc_val = data.get("cost_center_id") or data.get("cost_center") or data.get("cost_id") or data.get("costID") or data.get("costCenterId")

        act_token = None
        if hasattr(data, "activation_token") and getattr(data, "activation_token") is not None:
            act_token = getattr(data, "activation_token")
        elif isinstance(data, dict):
            act_token = data.get("activation_token") or data.get("activationToken") or data.get("invite_token") or data.get("inviteToken") or data.get("token")

        act_url = f"{settings.FRONTEND_BASE_URL}/onboarding?token={act_token}" if act_token else None

        mgr_id = None
        if hasattr(data, "reporting_manager_id") and getattr(data, "reporting_manager_id") is not None:
            mgr_id = getattr(data, "reporting_manager_id")
        elif hasattr(data, "manager_id") and getattr(data, "manager_id") is not None:
            mgr_id = getattr(data, "manager_id")
        elif isinstance(data, dict):
            mgr_id = (
                data.get("reporting_manager_id")
                or data.get("reportingManagerId")
                or data.get("reporting_manager")
                or data.get("reportingManager")
                or data.get("manager_id")
                or data.get("managerId")
            )

        if isinstance(mgr_id, dict):
            mgr_id = mgr_id.get("reporting_manager_id") or mgr_id.get("reportingManagerId") or mgr_id.get("manager_id") or mgr_id.get("managerId") or mgr_id.get("user_id") or mgr_id.get("userId") or mgr_id.get("value") or mgr_id.get("id")

        emp_dept_id = getattr(data, "department_id", None) if hasattr(data, "department_id") else (data.get("department_id") if isinstance(data, dict) else None)
        if mgr_id is not None and emp_dept_id is not None and str(mgr_id) == str(emp_dept_id):
            mgr_id = None

        mgr_name = None
        if hasattr(data, "reporting_manager_name") and getattr(data, "reporting_manager_name") is not None:
            mgr_name = getattr(data, "reporting_manager_name")
        elif hasattr(data, "__dict__"):
            d = data.__dict__
            rm = d.get("reporting_manager") or d.get("reporting_manager_user") or d.get("manager_user")
            if isinstance(rm, str):
                mgr_name = rm
            elif rm is not None:
                fn = getattr(rm, "first_name", "") or ""
                ln = getattr(rm, "last_name", "") or ""
                if fn or ln:
                    mgr_name = f"{fn} {ln}".strip()
                elif hasattr(rm, "name"):
                    mgr_name = getattr(rm, "name", None)
        elif isinstance(data, dict):
            mgr_name = data.get("reporting_manager_name") or data.get("reportingManagerName") or data.get("manager_name") or data.get("managerName")

        if hasattr(data, "__dict__") or not isinstance(data, dict):
            try:
                data.cost_center_id = cc_val
                data.cost_center = cc_val
                data.cost_id = cc_val
                data.costID = cc_val
                data.costCenterId = cc_val
                data.activation_token = act_token
                data.activationToken = act_token
                data.invite_token = act_token
                data.inviteToken = act_token
                data.token = act_token
                data.activation_url = act_url
                data.activationUrl = act_url
                data.invite_link = act_url
                data.inviteLink = act_url
                data.invite_url = act_url
                data.inviteUrl = act_url
                data.onboarding_url = act_url
                data.onboardingUrl = act_url
                data.onboarding_link = act_url
                data.onboardingLink = act_url
                data.reporting_manager_id = mgr_id
                data.reportingManagerId = mgr_id
                data.reporting_manager_name = mgr_name
                data.reportingManagerName = mgr_name
                data.reporting_manager = mgr_name or (str(mgr_id) if mgr_id else None)
                data.reportingManager = mgr_name or (str(mgr_id) if mgr_id else None)
                fn = getattr(data, "first_name", "") or ""
                ln = getattr(data, "last_name", "") or ""
                data.full_name = f"{fn} {ln}".strip() or getattr(data, "company_email", None) or getattr(data, "personal_email", None)
                data.email = getattr(data, "company_email", None) or getattr(data, "personal_email", None)
                sal_ctc = getattr(data, "ctc", None) or getattr(data, "salary", None) or getattr(data, "annual_ctc", None)
                data.ctc = sal_ctc
                data.salary = sal_ctc
                data.annual_ctc = sal_ctc
            except AttributeError:
                pass
        if isinstance(data, dict) or not hasattr(data, "__dict__"):
            data["cost_center_id"] = cc_val
            data["cost_center"] = cc_val
            data["cost_id"] = cc_val
            data["costID"] = cc_val
            data["costCenterId"] = cc_val
            data["activation_token"] = act_token
            data["activationToken"] = act_token
            data["invite_token"] = act_token
            data["inviteToken"] = act_token
            data["token"] = act_token
            data["activation_url"] = act_url
            data["activationUrl"] = act_url
            data["invite_link"] = act_url
            data["inviteLink"] = act_url
            data["invite_url"] = act_url
            data["inviteUrl"] = act_url
            data["onboarding_url"] = act_url
            data["onboardingUrl"] = act_url
            data["onboarding_link"] = act_url
            data["onboardingLink"] = act_url
            data["reporting_manager_id"] = mgr_id
            data["reportingManagerId"] = mgr_id
            data["reporting_manager_name"] = mgr_name
            data["reportingManagerName"] = mgr_name
            data["reporting_manager"] = mgr_name or (str(mgr_id) if mgr_id else None)
            data["reportingManager"] = mgr_name or (str(mgr_id) if mgr_id else None)
            fn = data.get("first_name", "") or ""
            ln = data.get("last_name", "") or ""
            data["full_name"] = f"{fn} {ln}".strip() or data.get("company_email") or data.get("personal_email")
            data["email"] = data.get("company_email") or data.get("personal_email")
            sal_ctc = data.get("ctc") or data.get("salary") or data.get("annual_ctc")
            data["ctc"] = sal_ctc
            data["salary"] = sal_ctc
            data["annual_ctc"] = sal_ctc
        return data

    # Relations
    addresses: list[EmployeeAddressResponse] = []
    documents: list[EmployeeDocumentResponse] = []
    education: list[EmployeeEducationResponse] = []
    experience: list[EmployeeExperienceResponse] = []
    skills: list[EmployeeSkillResponse] = []
    assets: list[EmployeeAssetResponse] = []
    emergency_contacts: list[EmployeeEmergencyContactResponse] = []
    bank_accounts: list[EmployeeBankAccountResponse] = []
    leave_policies: list[EmployeeLeavePolicyResponse] = []
    onboarding_steps: list[EmployeeOnboardingStepResponse] = []


class EmployeeListResponse(BaseModel):
    """Paginated list of employees."""
    items: list[EmployeeListItem]
    total: int
    page: int
    limit: int
    pages: int
    total_pages: int
    has_next: bool
    has_previous: bool
