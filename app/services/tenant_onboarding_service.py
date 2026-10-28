"""Validation for real tenant legal-entity, branch and hierarchy mappings."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Branch, LegalEntity
from app.models.department import Department
from app.models.employee import Employee


class TenantMappingError(ValueError):
    """Raised when an organization assignment crosses tenant/branch boundaries."""


async def validate_branch_department_manager(
    session: AsyncSession,
    *,
    company_id: uuid.UUID,
    branch_id: uuid.UUID | None = None,
    legal_entity_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    manager_employee_id: uuid.UUID | None = None,
    employee_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Validate and return the effective legal entity for an assignment.

    A branch is authoritative for its legal entity.  Departments and managers
    must belong to the same tenant, and a department explicitly mapped to a
    different branch cannot be used.  Manager branch membership is enforced
    whenever that manager has an explicit branch assignment.
    """
    branch: Branch | None = None
    if branch_id is not None:
        branch = await session.get(Branch, branch_id)
        if branch is None or branch.company_id != company_id or not branch.is_active:
            raise TenantMappingError("Branch not found in the current tenant or is inactive.")
        if legal_entity_id is not None and branch.legal_entity_id != legal_entity_id:
            raise TenantMappingError("Employee legal entity does not match the branch legal entity.")
        legal_entity_id = branch.legal_entity_id

    if legal_entity_id is not None:
        legal_entity = await session.get(LegalEntity, legal_entity_id)
        if legal_entity is None or legal_entity.company_id != company_id or not legal_entity.is_active:
            raise TenantMappingError("Legal entity not found in the current tenant or is inactive.")

    if department_id is not None:
        department = await session.get(Department, department_id)
        if department is None or department.company_id != company_id or department.is_deleted:
            raise TenantMappingError("Department not found in the current tenant.")
        if branch_id is not None and department.branch_id != branch_id:
            raise TenantMappingError("Department is not mapped to the employee branch.")

    if manager_employee_id is not None:
        if employee_id is not None and manager_employee_id == employee_id:
            raise TenantMappingError("An employee cannot be their own reporting manager.")
        manager = await session.get(Employee, manager_employee_id)
        if manager is None or manager.company_id != company_id or manager.is_deleted:
            raise TenantMappingError("Reporting manager not found in the current tenant.")
        if branch_id is not None and manager.branch_id is not None and manager.branch_id != branch_id:
            raise TenantMappingError("Reporting manager belongs to a different branch.")
    return legal_entity_id


async def validate_employee_assignment(session: AsyncSession, employee: Employee) -> None:
    """Validate an ORM employee before insert/update."""
    if employee.company_id is None:
        raise TenantMappingError("Employee tenant is required for organization mapping.")
    manager_id = employee.reporting_manager_id or employee.manager_id
    effective_entity = await validate_branch_department_manager(
        session,
        company_id=employee.company_id,
        branch_id=employee.branch_id,
        legal_entity_id=employee.legal_entity_id,
        department_id=employee.department_id,
        manager_employee_id=manager_id,
        employee_id=employee.id,
    )
    employee.legal_entity_id = effective_entity


async def validate_branch_manager(session: AsyncSession, branch: Branch) -> None:
    """Ensure a branch manager is a tenant employee mapped to that branch."""
    if branch.branch_manager_id is None:
        return
    manager = await session.get(Employee, branch.branch_manager_id)
    if manager is None or manager.company_id != branch.company_id or manager.is_deleted:
        raise TenantMappingError("Branch manager not found in the current tenant.")
    if manager.branch_id is not None and manager.branch_id != branch.id:
        raise TenantMappingError("Branch manager belongs to a different branch.")


class TenantOnboardingService:
    """Namespace for callers that prefer service-style mapping validation."""

    validate_employee_assignment = staticmethod(validate_employee_assignment)
    validate_branch_manager = staticmethod(validate_branch_manager)
    validate_branch_department_manager = staticmethod(validate_branch_department_manager)


__all__ = [
    "TenantMappingError",
    "TenantOnboardingService",
    "validate_branch_department_manager",
    "validate_employee_assignment",
    "validate_branch_manager",
]
