"""Pydantic v2 schemas for the Department Management module."""

from __future__ import annotations

from datetime import datetime
import uuid

from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEPARTMENT_STATUS_VALUES = {"ACTIVE", "INACTIVE", "HIRING", "GROWING"}


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str


class DepartmentCreate(BaseModel):
    department_name: str = Field(..., min_length=1, max_length=100, examples=["Human Resources"])
    description: str = Field(..., min_length=1, max_length=1000, examples=["Handles recruitment and employee relations"])
    manager_id: uuid.UUID | None = Field(None, description="Department Head (Manager user ID)")
    managerId: uuid.UUID | None = None
    reporting_manager_id: uuid.UUID | None = None
    reportingManagerId: uuid.UUID | None = None
    reporting_manager: Any | None = None
    reportingManager: Any | None = None
    head_id: uuid.UUID | None = None
    headId: uuid.UUID | None = None
    department_head_id: uuid.UUID | None = None
    departmentHeadId: uuid.UUID | None = None
    parent_department_id: uuid.UUID | None = Field(None, description="Parent Department UUID")
    branch_id: uuid.UUID | None = Field(None, description="Branch UUID")
    location: str = Field(..., min_length=1, max_length=100, examples=["Headquarters, Floor 4"])
    cost_center: str | None = Field(None, max_length=50, examples=["CC-HR-101"])
    cost_id: str | None = Field(None, max_length=50)
    costID: str | None = Field(None, max_length=50)
    cost_center_id: str | None = Field(None, max_length=50)
    costCenterId: str | None = Field(None, max_length=50)
    cost_code: str | None = Field(None, max_length=50)
    costCode: str | None = Field(None, max_length=50)
    costId: str | None = Field(None, max_length=50)
    budget: float | None = Field(0.0, description="Annual Budget (USD)")
    extension_number: str | None = Field(None, max_length=50, description="Phone Extension")
    employee_capacity: int | None = Field(100, ge=0, description="Department Employee Capacity")
    status: str = Field("ACTIVE", description="ACTIVE or INACTIVE")

    @model_validator(mode="before")
    @classmethod
    def handle_aliases(cls, data: any) -> any:
        if isinstance(data, dict):
            if "extensionNumber" in data and "extension_number" not in data:
                data["extension_number"] = data["extensionNumber"]
            cc = (
                data.get("cost_center")
                or data.get("cost_id")
                or data.get("costID")
                or data.get("cost_center_id")
                or data.get("costCenterId")
                or data.get("cost_code")
                or data.get("costCode")
                or data.get("costId")
            )
            if cc is not None:
                cc_str = str(cc).strip()
                data["cost_center"] = cc_str
                data["cost_id"] = cc_str
                data["costID"] = cc_str
                data["cost_center_id"] = cc_str
                data["costCenterId"] = cc_str
                data["cost_code"] = cc_str
                data["costCode"] = cc_str
                data["costId"] = cc_str

            mgr = (
                data.get("manager_id")
                or data.get("managerId")
                or data.get("reporting_manager_id")
                or data.get("reportingManagerId")
                or data.get("reporting_manager")
                or data.get("reportingManager")
                or data.get("head_id")
                or data.get("headId")
                or data.get("department_head_id")
                or data.get("departmentHeadId")
            )
            if isinstance(mgr, dict):
                mgr = mgr.get("manager_id") or mgr.get("managerId") or mgr.get("reporting_manager_id") or mgr.get("reportingManagerId") or mgr.get("user_id") or mgr.get("userId") or mgr.get("value") or mgr.get("id")

            dept_self_id = data.get("id") or data.get("department_id") or data.get("departmentId")
            if mgr is not None and dept_self_id is not None and str(mgr) == str(dept_self_id):
                mgr = None

            if mgr is not None and mgr != "":
                data["manager_id"] = mgr
                data["managerId"] = mgr
                data["reporting_manager_id"] = mgr
                data["reportingManagerId"] = mgr
            elif mgr is None and ("manager_id" in data or "reporting_manager_id" in data or "reporting_manager" in data):
                data["manager_id"] = None
                data["reporting_manager_id"] = None

            if "employeeCapacity" in data and "employee_capacity" not in data:
                data["employee_capacity"] = data["employeeCapacity"]
            elif "capacity" in data and "employee_capacity" not in data:
                data["employee_capacity"] = data["capacity"]
        return data

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        v = v.upper()
        if v not in DEPARTMENT_STATUS_VALUES:
            raise ValueError("status must be ACTIVE, INACTIVE, HIRING, or GROWING")
        return v


class DepartmentUpdate(BaseModel):
    department_name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, min_length=1, max_length=1000)
    manager_id: uuid.UUID | None = None
    managerId: uuid.UUID | None = None
    reporting_manager_id: uuid.UUID | None = None
    reportingManagerId: uuid.UUID | None = None
    reporting_manager: Any | None = None
    reportingManager: Any | None = None
    head_id: uuid.UUID | None = None
    headId: uuid.UUID | None = None
    department_head_id: uuid.UUID | None = None
    departmentHeadId: uuid.UUID | None = None
    parent_department_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    location: str | None = Field(None, min_length=1, max_length=100)
    cost_center: str | None = Field(None, max_length=50)
    cost_id: str | None = Field(None, max_length=50)
    costID: str | None = Field(None, max_length=50)
    cost_center_id: str | None = Field(None, max_length=50)
    costCenterId: str | None = Field(None, max_length=50)
    cost_code: str | None = Field(None, max_length=50)
    costCode: str | None = Field(None, max_length=50)
    costId: str | None = Field(None, max_length=50)
    budget: float | None = Field(None, description="Annual Budget (USD)")
    extension_number: str | None = Field(None, max_length=50, description="Phone Extension")
    employee_capacity: int | None = Field(None, ge=0, description="Department Employee Capacity")
    status: str | None = None

    @model_validator(mode="before")
    @classmethod
    def handle_aliases(cls, data: any) -> any:
        if isinstance(data, dict):
            if "extensionNumber" in data and "extension_number" not in data:
                data["extension_number"] = data["extensionNumber"]
            cc = (
                data.get("cost_center")
                or data.get("cost_id")
                or data.get("costID")
                or data.get("cost_center_id")
                or data.get("costCenterId")
                or data.get("cost_code")
                or data.get("costCode")
                or data.get("costId")
            )
            if cc is not None:
                cc_str = str(cc).strip()
                data["cost_center"] = cc_str
                data["cost_id"] = cc_str
                data["costID"] = cc_str
                data["cost_center_id"] = cc_str
                data["costCenterId"] = cc_str
                data["cost_code"] = cc_str
                data["costCode"] = cc_str
                data["costId"] = cc_str

            mgr = (
                data.get("manager_id")
                or data.get("managerId")
                or data.get("reporting_manager_id")
                or data.get("reportingManagerId")
                or data.get("reporting_manager")
                or data.get("reportingManager")
                or data.get("head_id")
                or data.get("headId")
                or data.get("department_head_id")
                or data.get("departmentHeadId")
            )
            if isinstance(mgr, dict):
                mgr = mgr.get("manager_id") or mgr.get("managerId") or mgr.get("reporting_manager_id") or mgr.get("reportingManagerId") or mgr.get("user_id") or mgr.get("userId") or mgr.get("value") or mgr.get("id")

            dept_self_id = data.get("id") or data.get("department_id") or data.get("departmentId")
            if mgr is not None and dept_self_id is not None and str(mgr) == str(dept_self_id):
                mgr = None

            if mgr is not None and mgr != "":
                data["manager_id"] = mgr
                data["managerId"] = mgr
                data["reporting_manager_id"] = mgr
                data["reportingManagerId"] = mgr
            elif mgr is None and ("manager_id" in data or "reporting_manager_id" in data or "reporting_manager" in data):
                data["manager_id"] = None
                data["reporting_manager_id"] = None

            if "employeeCapacity" in data and "employee_capacity" not in data:
                data["employee_capacity"] = data["employeeCapacity"]
            elif "capacity" in data and "employee_capacity" not in data:
                data["employee_capacity"] = data["capacity"]
        return data

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.upper()
        if v not in DEPARTMENT_STATUS_VALUES:
            raise ValueError("status must be ACTIVE, INACTIVE, HIRING, or GROWING")
        return v


class DepartmentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    department_code: str
    department_name: str
    description: str | None = None
    manager_id: uuid.UUID | None = None
    manager_name: str | None = None
    reporting_manager_id: uuid.UUID | None = None
    reporting_manager_name: str | None = None
    parent_department_id: uuid.UUID | None = None
    parent_department_name: str | None = None
    location: str
    cost_center: str | None = None
    budget: float | None = 0.0
    extension_number: str | None = None
    employee_capacity: int | None = 100
    employee_count: int = 0
    status: str
    created_at: datetime

    @model_validator(mode="before")
    @classmethod
    def populate_cost_id(cls, data: any) -> any:
        # Cost Center
        dept_code = getattr(data, "department_code", None) if hasattr(data, "department_code") else (data.get("department_code") if isinstance(data, dict) else None)
        default_cc = f"CC-{dept_code.replace('DEP', '')}" if dept_code else "CC-101"

        cc_val = None
        if hasattr(data, "cost_center") and getattr(data, "cost_center") is not None:
            cc_val = getattr(data, "cost_center")
        elif hasattr(data, "cost_id") and getattr(data, "cost_id") is not None:
            cc_val = getattr(data, "cost_id")
        elif hasattr(data, "costID") and getattr(data, "costID") is not None:
            cc_val = getattr(data, "costID")
        elif hasattr(data, "cost_center_id") and getattr(data, "cost_center_id") is not None:
            cc_val = getattr(data, "cost_center_id")
        elif hasattr(data, "costCenterId") and getattr(data, "costCenterId") is not None:
            cc_val = getattr(data, "costCenterId")
        elif isinstance(data, dict):
            cc_val = (
                data.get("cost_center")
                or data.get("cost_id")
                or data.get("costID")
                or data.get("cost_center_id")
                or data.get("costCenterId")
                or data.get("cost_code")
                or data.get("costCode")
                or data.get("costId")
            )

        cc_val = cc_val or default_cc

        # Reporting Manager / Manager Aliases
        mgr_id = None
        if hasattr(data, "manager_id") and getattr(data, "manager_id") is not None:
            mgr_id = getattr(data, "manager_id")
        elif hasattr(data, "reporting_manager_id") and getattr(data, "reporting_manager_id") is not None:
            mgr_id = getattr(data, "reporting_manager_id")
        elif isinstance(data, dict):
            mgr_id = (
                data.get("manager_id")
                or data.get("managerId")
                or data.get("reporting_manager_id")
                or data.get("reportingManagerId")
                or data.get("reporting_manager")
                or data.get("reportingManager")
            )

        if isinstance(mgr_id, dict):
            mgr_id = mgr_id.get("manager_id") or mgr_id.get("managerId") or mgr_id.get("reporting_manager_id") or mgr_id.get("reportingManagerId") or mgr_id.get("user_id") or mgr_id.get("userId") or mgr_id.get("value") or mgr_id.get("id")

        dept_self_id = getattr(data, "id", None) if hasattr(data, "id") else (data.get("id") if isinstance(data, dict) else None)
        if mgr_id is not None and dept_self_id is not None and str(mgr_id) == str(dept_self_id):
            mgr_id = None

        mgr_name = None
        if hasattr(data, "manager_name") and getattr(data, "manager_name") is not None:
            mgr_name = getattr(data, "manager_name")
        elif hasattr(data, "reporting_manager_name") and getattr(data, "reporting_manager_name") is not None:
            mgr_name = getattr(data, "reporting_manager_name")
        elif hasattr(data, "manager_user") and getattr(data, "manager_user") is not None:
            m_user = getattr(data, "manager_user")
            mgr_name = getattr(m_user, "name", None)
        elif isinstance(data, dict):
            mgr_name = data.get("manager_name") or data.get("managerName") or data.get("reporting_manager_name") or data.get("reportingManagerName")

        # Extension Number
        ext_val = None
        if hasattr(data, "extension_number"):
            ext_val = getattr(data, "extension_number")
        elif hasattr(data, "extensionNumber"):
            ext_val = getattr(data, "extensionNumber")
        elif isinstance(data, dict):
            ext_val = data.get("extension_number") or data.get("extensionNumber")

        # Employee Capacity
        cap_val = 100
        if hasattr(data, "employee_capacity") and getattr(data, "employee_capacity") is not None:
            cap_val = getattr(data, "employee_capacity")
        elif isinstance(data, dict):
            cap_val = data.get("employee_capacity") or data.get("employeeCapacity") or 100

        if hasattr(data, "__dict__") or not isinstance(data, dict):
            try:
                data.cost_center = cc_val
                data.manager_id = mgr_id
                data.reporting_manager_id = mgr_id
                data.manager_name = mgr_name
                data.reporting_manager_name = mgr_name
                data.extension_number = ext_val
                data.employee_capacity = cap_val
            except AttributeError:
                pass
        if isinstance(data, dict) or not hasattr(data, "__dict__"):
            data["cost_center"] = cc_val
            data["manager_id"] = mgr_id
            data["reporting_manager_id"] = mgr_id
            data["manager_name"] = mgr_name
            data["reporting_manager_name"] = mgr_name
            data["extension_number"] = ext_val
            data["employee_capacity"] = cap_val

        return data



class DepartmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    department_code: str
    department_name: str
    description: str
    manager_id: uuid.UUID | None = None
    manager_name: str | None = None
    reporting_manager_id: uuid.UUID | None = None
    reporting_manager_name: str | None = None
    parent_department_id: uuid.UUID | None = None
    parent_department_name: str | None = None
    branch_id: uuid.UUID | None = None
    location: str
    cost_center: str | None = None
    budget: float | None = 0.0
    extension_number: str | None = None
    employee_capacity: int | None = 100
    status: str
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def populate_cost_id(cls, data: any) -> any:
        # Cost Center
        dept_code = getattr(data, "department_code", None) if hasattr(data, "department_code") else (data.get("department_code") if isinstance(data, dict) else None)
        default_cc = f"CC-{dept_code.replace('DEP', '')}" if dept_code else "CC-101"

        cc_val = None
        if hasattr(data, "cost_center") and getattr(data, "cost_center") is not None:
            cc_val = getattr(data, "cost_center")
        elif hasattr(data, "cost_id") and getattr(data, "cost_id") is not None:
            cc_val = getattr(data, "cost_id")
        elif hasattr(data, "costID") and getattr(data, "costID") is not None:
            cc_val = getattr(data, "costID")
        elif hasattr(data, "cost_center_id") and getattr(data, "cost_center_id") is not None:
            cc_val = getattr(data, "cost_center_id")
        elif hasattr(data, "costCenterId") and getattr(data, "costCenterId") is not None:
            cc_val = getattr(data, "costCenterId")
        elif isinstance(data, dict):
            cc_val = (
                data.get("cost_center")
                or data.get("cost_id")
                or data.get("costID")
                or data.get("cost_center_id")
                or data.get("costCenterId")
                or data.get("cost_code")
                or data.get("costCode")
                or data.get("costId")
            )

        cc_val = cc_val or default_cc
            
        if hasattr(data, "__dict__") or not isinstance(data, dict):
            try:
                data.cost_center = cc_val
                data.cost_id = cc_val
                data.costID = cc_val
                data.cost_center_id = cc_val
                data.costCenterId = cc_val
            except AttributeError:
                pass
        if isinstance(data, dict) or not hasattr(data, "__dict__"):
            data["cost_center"] = cc_val
            data["cost_id"] = cc_val
            data["costID"] = cc_val
            data["cost_center_id"] = cc_val
            data["costCenterId"] = cc_val

        # Reporting Manager / Manager Aliases
        mgr_id = None
        if hasattr(data, "manager_id") and getattr(data, "manager_id") is not None:
            mgr_id = getattr(data, "manager_id")
        elif hasattr(data, "reporting_manager_id") and getattr(data, "reporting_manager_id") is not None:
            mgr_id = getattr(data, "reporting_manager_id")
        elif isinstance(data, dict):
            mgr_id = (
                data.get("manager_id")
                or data.get("managerId")
                or data.get("reporting_manager_id")
                or data.get("reportingManagerId")
                or data.get("reporting_manager")
                or data.get("reportingManager")
            )

        if isinstance(mgr_id, dict):
            mgr_id = mgr_id.get("manager_id") or mgr_id.get("managerId") or mgr_id.get("reporting_manager_id") or mgr_id.get("reportingManagerId") or mgr_id.get("user_id") or mgr_id.get("userId") or mgr_id.get("value") or mgr_id.get("id")

        dept_self_id = getattr(data, "id", None) if hasattr(data, "id") else (data.get("id") if isinstance(data, dict) else None)
        if mgr_id is not None and dept_self_id is not None and str(mgr_id) == str(dept_self_id):
            mgr_id = None

        mgr_name = None
        if hasattr(data, "manager_name") and getattr(data, "manager_name") is not None:
            mgr_name = getattr(data, "manager_name")
        elif hasattr(data, "reporting_manager_name") and getattr(data, "reporting_manager_name") is not None:
            mgr_name = getattr(data, "reporting_manager_name")
        elif hasattr(data, "manager_user") and getattr(data, "manager_user") is not None:
            m_user = getattr(data, "manager_user")
            mgr_name = getattr(m_user, "name", None)
        elif isinstance(data, dict):
            mgr_name = data.get("manager_name") or data.get("managerName") or data.get("reporting_manager_name") or data.get("reportingManagerName")

        if hasattr(data, "__dict__") or not isinstance(data, dict):
            try:
                data.manager_id = mgr_id
                data.managerId = mgr_id
                data.reporting_manager_id = mgr_id
                data.reportingManagerId = mgr_id
                data.manager_name = mgr_name
                data.managerName = mgr_name
                data.reporting_manager_name = mgr_name
                data.reportingManagerName = mgr_name
                data.reporting_manager = mgr_name or (str(mgr_id) if mgr_id else None)
                data.reportingManager = mgr_name or (str(mgr_id) if mgr_id else None)
            except AttributeError:
                pass
        if isinstance(data, dict) or not hasattr(data, "__dict__"):
            data["manager_id"] = mgr_id
            data["managerId"] = mgr_id
            data["reporting_manager_id"] = mgr_id
            data["reportingManagerId"] = mgr_id
            data["manager_name"] = mgr_name
            data["managerName"] = mgr_name
            data["reporting_manager_name"] = mgr_name
            data["reportingManagerName"] = mgr_name
            data["reporting_manager"] = mgr_name or (str(mgr_id) if mgr_id else None)
            data["reportingManager"] = mgr_name or (str(mgr_id) if mgr_id else None)

        # Extension Number
        ext_val = None
        if hasattr(data, "extension_number"):
            ext_val = getattr(data, "extension_number")
        elif isinstance(data, dict):
            ext_val = data.get("extension_number")
        elif hasattr(data, "extensionNumber"):
            ext_val = getattr(data, "extensionNumber")
        elif isinstance(data, dict):
            ext_val = data.get("extensionNumber")

        if hasattr(data, "__dict__") or not isinstance(data, dict):
            try:
                data.extension_number = ext_val
                data.extensionNumber = ext_val
            except AttributeError:
                pass
        if isinstance(data, dict) or not hasattr(data, "__dict__"):
            data["extension_number"] = ext_val
            data["extensionNumber"] = ext_val

        # Department ID
        id_val = None
        if hasattr(data, "id"):
            id_val = getattr(data, "id")
        elif isinstance(data, dict):
            id_val = data.get("id")
            
        if hasattr(data, "__dict__") or not isinstance(data, dict):
            try:
                data.department_id = id_val
                data.departmentId = id_val
            except AttributeError:
                pass
        if isinstance(data, dict) or not hasattr(data, "__dict__"):
            data["department_id"] = id_val
            data["departmentId"] = id_val

        # Parent ID
        p_val = None
        if hasattr(data, "parent_department_id"):
            p_val = getattr(data, "parent_department_id")
        elif isinstance(data, dict):
            p_val = data.get("parent_department_id")
            
        if hasattr(data, "__dict__") or not isinstance(data, dict):
            try:
                data.parent_id = p_val
                data.parentId = p_val
            except AttributeError:
                pass
        if isinstance(data, dict) or not hasattr(data, "__dict__"):
            data["parent_id"] = p_val
            data["parentId"] = p_val
            
        return data

    # Extra features info
    manager_details: UserBrief | None = None
    created_by_details: UserBrief | None = None
    parent_department_name: str | None = None
    reporting_manager_id: uuid.UUID | None = None
    reporting_manager_name: str | None = None


class DepartmentListResponse(BaseModel):
    items: list[DepartmentListItem]
    total: int
    page: int
    limit: int
    pages: int


class DepartmentStats(BaseModel):
    department_id: uuid.UUID
    department_name: str
    active_employee_count: int
    inactive_employee_count: int
    total_employee_count: int
    sub_departments_count: int


class AssignEmployeesRequest(BaseModel):
    employee_ids: list[uuid.UUID] = Field(..., min_length=1, description="List of Employee UUIDs (not user IDs)")


class AssignManagerRequest(BaseModel):
    manager_user_id: uuid.UUID = Field(..., description="The User ID of the Manager to assign as Head of Department")
