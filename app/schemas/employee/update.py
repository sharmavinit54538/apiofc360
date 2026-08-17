"""EmployeeUpdate and EmployeeListItem schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Any

from app.schemas.employee.address import EmployeeAddressCreate
from app.schemas.employee.document import EmployeeDocumentCreate
from app.schemas.employee.education import EmployeeEducationCreate
from app.schemas.employee.experience import EmployeeExperienceCreate
from app.schemas.employee.skill import EmployeeSkillCreate
from app.schemas.employee.emergency import EmployeeEmergencyContactCreate
from app.schemas.employee.bank import EmployeeBankAccountCreate
from app.schemas.employee.validators import EmployeeValidatorsMixin


class EmployeeUpdate(EmployeeValidatorsMixin, BaseModel):
    """Partial update payload — all fields optional."""

    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    profile_photo_url: str | None = None
    gender: str | None = None
    date_of_birth: date | None = None
    personal_email: str | None = Field(None, max_length=255)
    company_email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=30)
    alternate_phone: str | None = None
    blood_group: str | None = None
    marital_status: str | None = None
    department: str | None = Field(None, max_length=100)
    designation: str | None = Field(None, max_length=100)
    joining_date: date | None = None
    team: str | None = Field(None, max_length=100)
    reporting_manager_id: uuid.UUID | None = None
    branch: str | None = None
    work_location: str | None = None
    employment_type: str | None = None
    employment_status: str | None = None
    probation_end_date: date | None = None
    shift: str | None = None
    employee_capacity: int | None = None
    cost_center_id: str | None = None
    ctc: Decimal | None = Field(None, ge=0)
    basic_salary: Decimal | None = Field(None, ge=0)
    hra: Decimal | None = Field(None, ge=0)
    bonus: Decimal | None = Field(None, ge=0)
    pf: Decimal | None = Field(None, ge=0)
    esi: Decimal | None = Field(None, ge=0)
    professional_tax: Decimal | None = Field(None, ge=0)
    role: str | None = None
    leave_group: str | None = None

    # Role-specific metadata (JSONB)
    role_metadata: dict | None = None

    addresses: list[EmployeeAddressCreate] | None = None
    documents: list[EmployeeDocumentCreate] | None = None
    education: list[EmployeeEducationCreate] | None = None
    experience: list[EmployeeExperienceCreate] | None = None
    skills: list[EmployeeSkillCreate] | None = None
    emergency_contacts: list[EmployeeEmergencyContactCreate] | None = None
    bank_accounts: list[EmployeeBankAccountCreate] | None = None

    @model_validator(mode="before")
    @classmethod
    def clean_payload(cls, data: Any) -> Any:
        if isinstance(data, dict):
            cc = data.get("cost_center_id") or data.get("cost_center") or data.get("cost_id") or data.get("costID") or data.get("costCenterId")
            if cc is not None:
                data["cost_center_id"] = str(cc)
            
            rm = (
                data.get("reporting_manager_id")
                or data.get("reportingManagerId")
                or data.get("reporting_manager")
                or data.get("reportingManager")
                or data.get("manager_id")
                or data.get("managerId")
            )
            if isinstance(rm, dict):
                rm = rm.get("reporting_manager_id") or rm.get("reportingManagerId") or rm.get("manager_id") or rm.get("managerId") or rm.get("user_id") or rm.get("userId") or rm.get("value") or rm.get("id")

            emp_dept_id = data.get("department_id") or data.get("departmentId")
            if rm is not None and emp_dept_id is not None and str(rm) == str(emp_dept_id):
                rm = None

            if rm is not None:
                if rm == "":
                    data["reporting_manager_id"] = None
                else:
                    data["reporting_manager_id"] = rm
            elif "reporting_manager_id" in data and data["reporting_manager_id"] == "":
                data["reporting_manager_id"] = None
            # Map alias keys to standard fields
            if "annual_ctc" in data and "ctc" not in data:
                data["ctc"] = data["annual_ctc"]
            if "annualCtc" in data and "ctc" not in data:
                data["ctc"] = data["annualCtc"]
            if "salary" in data and "ctc" not in data:
                data["ctc"] = data["salary"]
            if "basicSalary" in data and "basic_salary" not in data:
                data["basic_salary"] = data["basicSalary"]
            if "professionalTax" in data and "professional_tax" not in data:
                data["professional_tax"] = data["professionalTax"]

            # Clean salary fields
            salary_keys = ["ctc", "basic_salary", "hra", "bonus", "pf", "esi", "professional_tax"]
            for key in salary_keys:
                if key in data:
                    val = data[key]
                    if val == "" or val is None:
                        data[key] = None
                    elif isinstance(val, (int, float, str)):
                        try:
                            d_val = Decimal(str(val))
                            if d_val < 0:
                                pass
                        except Exception:
                            data[key] = None

            # If ctc is 0 or "0" in a partial update, avoid zeroing CTC when positive salary components exist or in partial profile updates
            if "ctc" in data and data["ctc"] in (0, "0", 0.0, Decimal("0")):
                has_positive_component = False
                for k in ["basic_salary", "hra", "bonus", "pf", "esi", "professional_tax"]:
                    if k in data and data[k] is not None:
                        try:
                            if Decimal(str(data[k])) > 0:
                                has_positive_component = True
                                break
                        except Exception:
                            pass
                has_all_zero_explicit_salaries = all(
                    data.get(k) in (0, "0", 0.0, Decimal("0")) for k in ["basic_salary", "hra", "bonus", "pf", "esi", "professional_tax"] if k in data
                ) and any(k in data for k in ["basic_salary", "hra", "bonus", "pf", "esi", "professional_tax"])

                if has_positive_component or (not has_all_zero_explicit_salaries and not any(k in data for k in ["basic_salary", "hra", "bonus", "pf", "esi", "professional_tax"])):
                    # Unset ctc so existing database CTC is preserved and used during merge validation
                    data.pop("ctc", None)

            # Clean skills
            if "skills" in data and isinstance(data["skills"], list):
                data["skills"] = [
                    sk for sk in data["skills"]
                    if isinstance(sk, dict) and (sk.get("skill_name") or sk.get("name") or sk.get("skill"))
                ]
            # Clean documents
            if "documents" in data and isinstance(data["documents"], list):
                data["documents"] = [
                    doc for doc in data["documents"]
                    if isinstance(doc, dict) and (doc.get("document_type") or doc.get("document_number"))
                ]
            # Clean addresses
            if "addresses" in data and isinstance(data["addresses"], list):
                data["addresses"] = [
                    addr for addr in data["addresses"]
                    if isinstance(addr, dict) and (
                        addr.get("address_line_1") or addr.get("address1") or addr.get("address_1") or addr.get("line1") or addr.get("street")
                    )
                ]
            # Clean education
            if "education" in data and isinstance(data["education"], list):
                data["education"] = [
                    edu for edu in data["education"]
                    if isinstance(edu, dict) and (edu.get("degree") or edu.get("institution"))
                ]
            # Clean experience
            if "experience" in data and isinstance(data["experience"], list):
                data["experience"] = [
                    exp for exp in data["experience"]
                    if isinstance(exp, dict) and (exp.get("company_name") or exp.get("designation") or exp.get("job_title"))
                ]
            # Clean bank accounts
            if "bank_accounts" in data and isinstance(data["bank_accounts"], list):
                data["bank_accounts"] = [
                    ba for ba in data["bank_accounts"]
                    if isinstance(ba, dict) and (ba.get("bank_name") or ba.get("account_number"))
                ]
            # Clean emergency contacts
            if "emergency_contacts" in data and isinstance(data["emergency_contacts"], list):
                data["emergency_contacts"] = [
                    ec for ec in data["emergency_contacts"]
                    if isinstance(ec, dict) and (ec.get("emergency_contact_name") or ec.get("emergency_contact_phone") or ec.get("name") or ec.get("contact_name") or ec.get("contact_phone"))
                ]
        return data


class EmployeeListItem(BaseModel):
    """Lightweight employee representation for paginated lists."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: str
    first_name: str
    last_name: str
    profile_photo_url: str | None = None
    company_email: str | None = None
    personal_email: str
    phone: str
    department: str
    designation: str
    employment_type: str
    shift: str | None = None
    employee_capacity: int | None = 100
    cost_center_id: str | None = None
    reporting_manager_id: uuid.UUID | None = None
    reporting_manager_name: str | None = None
    status: str
    joining_date: date
    created_at: datetime
    activation_token: str | None = None
    activation_url: str | None = None
    activation_token_expires_at: datetime | None = None
    full_name: str | None = None
    email: str | None = None
    job_title: str | None = None
    role: str | None = None
    ctc: Decimal | None = None
    annual_ctc: Decimal | None = None
    annualCtc: Decimal | None = None
    salary: Decimal | None = None
    basic_salary: Decimal | None = None
    basicSalary: Decimal | None = None
    hra: Decimal | None = None
    bonus: Decimal | None = None
    pf: Decimal | None = None
    esi: Decimal | None = None
    professional_tax: Decimal | None = None
    professionalTax: Decimal | None = None

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

        def get_val(key: str, alt_keys: list[str] | None = None) -> Any:
            keys = [key] + (alt_keys or [])
            for k in keys:
                if hasattr(data, k):
                    v = getattr(data, k)
                    if v is not None:
                        return v
                elif isinstance(data, dict) and k in data:
                    v = data[k]
                    if v is not None:
                        return v
            return None

        basic_in = get_val("basic_salary", ["basicSalary"])
        hra_in = get_val("hra")
        bonus_in = get_val("bonus")
        pf_in = get_val("pf")
        esi_in = get_val("esi")
        pt_in = get_val("professional_tax", ["professionalTax"])

        sal_val = get_val("ctc", ["annual_ctc", "annualCtc", "salary"])
        if sal_val in (0, Decimal("0"), 0.0, "0", None):
            try:
                b_dec = Decimal(str(basic_in)) if basic_in is not None else Decimal("0")
                h_dec = Decimal(str(hra_in)) if hra_in is not None else Decimal("0")
                bon_dec = Decimal(str(bonus_in)) if bonus_in is not None else Decimal("0")
                if b_dec > 0 or h_dec > 0 or bon_dec > 0:
                    sal_val = b_dec + h_dec + bon_dec
            except Exception:
                pass
        if sal_val is None:
            sal_val = get_val("ctc")

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
                data.job_title = getattr(data, "designation", None) or getattr(data, "job_title", None)
                data.role = getattr(data, "role", None) or "EMPLOYEE"
                data.ctc = sal_val
                data.salary = sal_val
                data.annual_ctc = sal_val
                data.annualCtc = sal_val
                data.basic_salary = basic_in
                data.basicSalary = basic_in
                data.hra = hra_in
                data.bonus = bonus_in
                data.pf = pf_in
                data.esi = esi_in
                data.professional_tax = pt_in
                data.professionalTax = pt_in
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
            data["job_title"] = data.get("designation") or data.get("job_title")
            data["role"] = data.get("role") or "EMPLOYEE"
            data["ctc"] = sal_val
            data["salary"] = sal_val
            data["annual_ctc"] = sal_val
            data["annualCtc"] = sal_val
            data["basic_salary"] = basic_in
            data["basicSalary"] = basic_in
            data["hra"] = hra_in
            data["bonus"] = bonus_in
            data["pf"] = pf_in
            data["esi"] = esi_in
            data["professional_tax"] = pt_in
            data["professionalTax"] = pt_in
        return data
    role_metadata: dict | None = None
    verification_status: str | None = None
    is_active: bool = True
    deactivated_at: datetime | None = None
    deactivated_by: uuid.UUID | None = None
    deactivation_reason: str | None = None
