"""Pydantic v2 schemas for the Employee Hierarchy module."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class HierarchyNodeResponse(BaseModel):
    """Basic representation of an employee in a hierarchy tree node."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: str
    first_name: str
    last_name: str
    designation: str
    department: str
    profile_photo_url: str | None = None

    # Employment fields
    role: str
    status: str
    branch: str | None = None           # DB column: branch (create API se match)
    shift: str | None = None            # DB column: shift (create API se match)
    employment_type: str | None = None
    employment_status: str | None = None
    joining_date: date | None = None

    # Personal
    date_of_birth: date | None = None   # DB column: date_of_birth (dob)

    # Salary
    ctc: Decimal | None = None          # DB column: ctc

    # Reporting
    reporting_to: uuid.UUID | None = None          # reporting manager ka UUID (manager_id)
    reporting_manager_name: str | None = None      # computed: "First Last" of reporting manager


class HierarchyTreeResponse(HierarchyNodeResponse):
    """Nested tree node including direct reports."""

    children: list[HierarchyTreeResponse] = Field(default_factory=list)


class OrganizationChartNode(BaseModel):
    """Flat representation of a node optimized for React Flow rendering."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    parentId: str | None = None
    name: str
    designation: str
    department: str
    avatar: str | None = None
    status: str
    role: str | None = None
    branch: str | None = None           # branch (create API se match)
    shift: str | None = None            # shift (create API se match)
    manager: str | None = None          # reporting manager ka naam
    teamSize: int = 0


class AssignManagerRequest(BaseModel):
    """Request payload to assign a manager to an employee."""

    employee_id: uuid.UUID
    manager_id: uuid.UUID


class ChangeManagerRequest(BaseModel):
    """Request payload to transfer an employee's manager."""

    employee_id: uuid.UUID
    new_manager_id: uuid.UUID


class HierarchyAnalyticsResponse(BaseModel):
    """Hierarchy analytics metrics."""

    total_employees: int
    managers_count: int
    hierarchy_levels: int
    average_team_size: float
    largest_team: int
    employees_without_manager: int
    vacant_positions: int
    hierarchy_depth: int


class ReportingChainResponse(BaseModel):
    """Details about an employee's direct reporting surroundings and chain."""

    employee: HierarchyNodeResponse
    manager: HierarchyNodeResponse | None = None
    peers: list[HierarchyNodeResponse] = Field(default_factory=list)
    direct_reports: list[HierarchyNodeResponse] = Field(default_factory=list)
    reporting_chain: list[HierarchyNodeResponse] = Field(default_factory=list)
    organization_level: int


class ReportingPathResponse(BaseModel):
    """Visual top-down reporting path from the root down to the employee."""

    path: list[HierarchyNodeResponse]
    formatted_path: str


# Resolve forward references for recursive tree structure
HierarchyTreeResponse.model_rebuild()

