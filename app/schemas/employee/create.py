"""EmployeeCreate schema."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.schemas.employee.address import EmployeeAddressCreate
from app.schemas.employee.document import EmployeeDocumentCreate
from app.schemas.employee.education import EmployeeEducationCreate
from app.schemas.employee.experience import EmployeeExperienceCreate
from app.schemas.employee.skill import EmployeeSkillCreate
from app.schemas.employee.emergency import EmployeeEmergencyContactCreate
from app.schemas.employee.bank import EmployeeBankAccountCreate
from app.schemas.employee.validators import EmployeeValidatorsMixin
from app.schemas.employee.constants import ROLE_METADATA_KEYS


class EmployeeCreate(EmployeeValidatorsMixin, BaseModel):
    """Payload for admin creating a new employee record."""

    # Required — Basic
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    personal_email: EmailStr
    phone: str = Field(..., min_length=10, max_length=15)
    employee_id: str | None = Field(None)

    # Required — Employment
    department: str = Field(..., min_length=1, max_length=100)
    designation: str = Field(..., min_length=1, max_length=100)
    employment_type: str = Field("FULL_TIME", min_length=1, max_length=50)
    joining_date: date

    # Required — Basic (but nullable)
    profile_photo_url: str | None = Field(None, max_length=500)
    gender: str | None = Field(None)
    date_of_birth: date | None = Field(None)
    company_email: EmailStr | None = Field(None)
    alternate_phone: str | None = Field(None, max_length=15)
    blood_group: str | None = Field(None)
    marital_status: str | None = Field(None)

    # Required — Employment (but nullable)
    team: str | None = Field(None, max_length=100)
    reporting_manager_id: uuid.UUID | None = Field(None)
    branch: str | None = Field(None, max_length=100)
    work_location: str | None = Field(None, max_length=100)
    probation_period_months: int | None = Field(None, ge=0, le=36)
    shift: str | None = Field(None, max_length=50)
    employee_capacity: int | None = Field(100, ge=0, le=500)
    cost_center_id: str | None = Field(None, max_length=100)

    @model_validator(mode="before")
    @classmethod
    def handle_aliases(cls, data: any) -> any:
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

            if rm is not None and rm != "":
                data["reporting_manager_id"] = rm
            elif rm is None and ("reporting_manager_id" in data or "reporting_manager" in data or "manager_id" in data):
                data["reporting_manager_id"] = None
        return data

    # Required — Salary (but nullable)
    ctc: Decimal | None = Field(None, ge=0)
    basic_salary: Decimal | None = Field(None, ge=0)
    hra: Decimal | None = Field(None, ge=0)
    bonus: Decimal | None = Field(None, ge=0)
    pf: Decimal | None = Field(None, ge=0)
    esi: Decimal | None = Field(None, ge=0)
    professional_tax: Decimal | None = Field(None, ge=0)

    # Required — System
    role: str = Field("employee", max_length=50)
    leave_group: str | None = Field(None, max_length=100)

    # Role-specific metadata (JSONB)
    role_metadata: dict | None = Field(default_factory=dict)

    # Required — Nested relations (must be provided as lists, can be empty)
    addresses: list[EmployeeAddressCreate] = Field(default_factory=list)
    documents: list[EmployeeDocumentCreate] = Field(default_factory=list)
    education: list[EmployeeEducationCreate] = Field(default_factory=list)
    experience: list[EmployeeExperienceCreate] = Field(default_factory=list)
    skills: list[EmployeeSkillCreate] = Field(default_factory=list)
    emergency_contacts: list[EmployeeEmergencyContactCreate] = Field(default_factory=list)
    bank_accounts: list[EmployeeBankAccountCreate] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def clean_empty_nested_relations(cls, data: Any) -> Any:
        from typing import Any
        if isinstance(data, dict):
            # Convert empty string reporting_manager_id to None
            if "reporting_manager_id" in data and data["reporting_manager_id"] == "":
                data["reporting_manager_id"] = None
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

    @model_validator(mode="after")
    def validate_role_metadata_keys(self) -> "EmployeeCreate":
        """Validate that role_metadata keys are allowed for the given role."""
        if not self.role_metadata:
            return self
        allowed_keys = ROLE_METADATA_KEYS.get(self.role, set()) | {"skills", "profile_photo_url"}
        invalid_keys = set(self.role_metadata.keys()) - allowed_keys
        if invalid_keys:
            raise ValueError(
                f"Invalid role_metadata keys for role '{self.role}': {invalid_keys}. "
                f"Allowed: {allowed_keys or 'none'}"
            )
        return self

