"""Centralized document access control and RBAC rules."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from fastapi import status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.models.employee import Employee
from app.models.employee_document import EmployeeDocument
from app.models.document.company import CompanyDocument

logger = logging.getLogger(__name__)

ADMIN_ROLES = {"super_admin", "hr_admin", "executive"}


async def resolve_visible_employee_ids(claims: dict, session: AsyncSession) -> list[uuid.UUID] | None:
    """Resolve the list of employee IDs that the caller is authorized to view.
    
    Returns:
        None: The caller is authorized to view all employees within their tenant (super_admin, hr_admin, executive).
        list[UUID]: Specific list of employee IDs the caller can view.
    """
    role = (claims.get("role") or "").lower()
    if role in ADMIN_ROLES:
        return None

    user_id_raw = claims.get("sub")
    if not user_id_raw:
        return []
    user_id = uuid.UUID(str(user_id_raw))

    from app.repositories.employee_repository import EmployeeRepository
    emp_repo = EmployeeRepository(session)
    caller_emp = await emp_repo.get_by_user_id(user_id)
    if not caller_emp:
        return []

    if role == "employee":
        return [caller_emp.id]

    if role == "manager":
        # Bounded iterative traversal of reporting hierarchy with visited set (max depth 10)
        # Includes manager themselves + direct/indirect reports. No department/branch fallback.
        visited: set[uuid.UUID] = {caller_emp.id}
        current_level: set[uuid.UUID] = {caller_emp.id}
        depth = 0
        max_depth = 10

        while current_level and depth < max_depth:
            stmt = select(Employee.id).where(
                and_(
                    Employee.company_id == caller_emp.company_id,
                    Employee.is_deleted == False,
                    or_(
                        Employee.reporting_manager_id.in_(current_level),
                        Employee.manager_id.in_(current_level),
                    ),
                )
            )
            res = await session.execute(stmt)
            next_level = set(res.scalars().all()) - visited
            visited.update(next_level)
            current_level = next_level
            depth += 1

        return list(visited)

    return []


async def assert_can_access_employee_doc(
    claims: dict,
    doc: EmployeeDocument,
    session: AsyncSession,
) -> None:
    """Assert caller can access an employee document. Raises AppException 404 (or 403 on missing tenant)."""
    if doc.is_deleted:
        raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

    role = (claims.get("role") or "").lower()
    user_id_raw = claims.get("sub")
    if not user_id_raw:
        raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)
    user_id = uuid.UUID(str(user_id_raw))

    from app.repositories.employee_repository import EmployeeRepository
    emp_repo = EmployeeRepository(session)

    # 1. Tenant Isolation
    doc_emp = doc.employee or await emp_repo.get_by_id(doc.employee_id)
    if not doc_emp:
        raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

    if role != "super_admin":
        caller_company_id = claims.get("company_id")
        if not caller_company_id:
            raise AppException(message="Tenant context (company_id) is required.", status_code=status.HTTP_403_FORBIDDEN)
        if doc_emp.company_id != uuid.UUID(str(caller_company_id)):
            raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

    # 2. Admin / Executive access
    if role in ADMIN_ROLES:
        return

    # 3. Non-admin viewers
    viewer_emp = await emp_repo.get_by_user_id(user_id)
    if not viewer_emp:
        raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

    # HR_ONLY visibility is strictly prohibited for non-HR (owner and manager cannot see)
    if doc.visibility == "HR_ONLY":
        raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

    # Check owner access
    if doc.employee_id == viewer_emp.id:
        # Owner can view PRIVATE, MANAGER_ONLY, DEPARTMENT, PUBLIC
        return

    # Non-owner employee cannot view any other employee's documents
    if role == "employee":
        raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

    # Manager viewing someone else's document
    if role == "manager":
        allowed_ids = await resolve_visible_employee_ids(claims, session)
        if not allowed_ids or doc.employee_id not in allowed_ids:
            raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

        # Visibility checks for manager viewing a report's document:
        if doc.visibility == "PRIVATE":
            # PRIVATE is strictly owner + HR/admin
            raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

        if doc.visibility == "DEPARTMENT":
            if not (viewer_emp.department and doc_emp.department and viewer_emp.department == doc_emp.department):
                raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

        # MANAGER_ONLY and PUBLIC are allowed for hierarchical manager
        return

    raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)


async def assert_can_access_company_doc(
    claims: dict,
    doc: CompanyDocument,
    session: AsyncSession,
) -> None:
    """Assert caller can access a company document. Raises AppException 404 (or 403 on missing tenant)."""
    if doc.is_deleted:
        raise AppException(message="Company document not found.", status_code=status.HTTP_404_NOT_FOUND)

    role = (claims.get("role") or "").lower()
    user_id_raw = claims.get("sub")
    if not user_id_raw:
        raise AppException(message="Company document not found.", status_code=status.HTTP_404_NOT_FOUND)
    user_id = uuid.UUID(str(user_id_raw))

    # 1. Tenant Isolation
    if role != "super_admin":
        caller_company_id = claims.get("company_id")
        if not caller_company_id:
            raise AppException(message="Tenant context (company_id) is required.", status_code=status.HTTP_403_FORBIDDEN)
        caller_comp_uuid = uuid.UUID(str(caller_company_id))
        if doc.company_id and doc.company_id != caller_comp_uuid:
            raise AppException(message="Company document not found.", status_code=status.HTTP_404_NOT_FOUND)

    # 2. Admin / Executive access
    if role in ADMIN_ROLES:
        return

    # 3. Non-admin scoping
    from app.repositories.employee_repository import EmployeeRepository
    viewer_emp = await EmployeeRepository(session).get_by_user_id(user_id)

    # NEVER HR_ONLY or PRIVATE for normal viewers
    if doc.visibility in {"HR_ONLY", "PRIVATE"}:
        raise AppException(message="Company document not found.", status_code=status.HTTP_404_NOT_FOUND)

    # MANAGER_ONLY requires manager role
    if doc.visibility == "MANAGER_ONLY" and role != "manager":
        raise AppException(message="Company document not found.", status_code=status.HTTP_404_NOT_FOUND)

    # DEPARTMENT requires matching department
    if doc.visibility == "DEPARTMENT":
        if not viewer_emp or not viewer_emp.department or viewer_emp.department != doc.department:
            raise AppException(message="Company document not found.", status_code=status.HTTP_404_NOT_FOUND)

    # Branch scope check
    if doc.branch:
        if not viewer_emp or not viewer_emp.branch or viewer_emp.branch != doc.branch:
            raise AppException(message="Company document not found.", status_code=status.HTTP_404_NOT_FOUND)
