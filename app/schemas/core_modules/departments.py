"""Pydantic schemas for Departments Core Module.

Re-exports and unifies under the canonical Department schemas in app.schemas.department.
"""

from __future__ import annotations

from app.schemas.department import (
    AssignEmployeesRequest,
    AssignManagerRequest,
    BulkActionResponse,
    BulkAssignManagerRequest,
    BulkDeleteRequest,
    BulkStatusRequest,
    DepartmentAnalyticsResponse,
    DepartmentCreate,
    DepartmentHierarchyNode,
    DepartmentImportRequest,
    DepartmentListItem,
    DepartmentListResponse,
    DepartmentResponse,
    DepartmentStats,
    DepartmentSummary,
    DepartmentUpdate,
    TransferEmployeesRequest,
    UserBrief,
)

# Canonical aliases for backward compatibility with core module imports
DepartmentCreateRequest = DepartmentCreate
DepartmentUpdateRequest = DepartmentUpdate

__all__ = [
    "DepartmentCreateRequest",
    "DepartmentUpdateRequest",
    "DepartmentCreate",
    "DepartmentUpdate",
    "DepartmentResponse",
    "DepartmentListItem",
    "DepartmentListResponse",
    "DepartmentStats",
    "DepartmentSummary",
    "AssignEmployeesRequest",
    "AssignManagerRequest",
    "BulkDeleteRequest",
    "BulkStatusRequest",
    "BulkAssignManagerRequest",
    "TransferEmployeesRequest",
    "DepartmentHierarchyNode",
    "DepartmentAnalyticsResponse",
    "DepartmentImportRequest",
    "BulkActionResponse",
    "UserBrief",
]
