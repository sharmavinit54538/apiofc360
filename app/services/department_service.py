"""Department service layer: all business logic, transactions, and structured logging."""

from __future__ import annotations

import logging
import math
import uuid
from typing import TYPE_CHECKING, Any

from fastapi import Depends, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ConflictException, DatabaseException
from app.db.database import get_db_session
from app.repositories.department_repository import DepartmentRepository
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
    DepartmentListItem,
    DepartmentListResponse,
    DepartmentResponse,
    DepartmentStats,
    DepartmentSummary,
    DepartmentUpdate,
    TransferEmployeesRequest,
    UserBrief,
)

if TYPE_CHECKING:
    from app.models.department import Department

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Department Code Generator (e.g. DEP0001, DEP0002)
# ---------------------------------------------------------------------------

async def generate_department_code(session: AsyncSession, company_id: uuid.UUID | None = None) -> str:
    from app.models.department import Department
    from sqlalchemy import select

    cid_filter = Department.company_id == company_id if company_id is not None else Department.company_id.is_(None)
    result = await session.execute(
        select(Department.department_code)
        .where(Department.department_code.like("DEP%"), cid_filter)
        .order_by(Department.department_code.desc())
        .limit(1)
    )
    last_code = result.scalar_one_or_none()
    if last_code:
        try:
            seq = int(last_code.replace("DEP", "")) + 1
        except ValueError:
            seq = 1
    else:
        seq = 1

    while True:
        code = f"DEP{seq:04d}"
        check = await session.execute(
            select(Department).where(Department.department_code == code, cid_filter)
        )
        if not check.scalar_one_or_none():
            return code
        seq += 1


class DepartmentService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        department_repository: DepartmentRepository,
    ) -> None:
        self.session = session
        self.repo = department_repository

    async def _to_brief(self, user_model: Any | None) -> UserBrief | None:
        if not user_model:
            return None
        return UserBrief(id=user_model.id, name=user_model.name, email=user_model.email)

    async def _to_response(self, dept: Department) -> DepartmentResponse:
        parent_name = None
        reporting_manager_id = dept.manager_id
        if reporting_manager_id and str(reporting_manager_id) == str(dept.id):
            reporting_manager_id = None
        reporting_manager_name = None

        if dept.manager_user:
            reporting_manager_name = dept.manager_user.name
        elif dept.manager_id:
            from app.models.user import User
            from sqlalchemy import select
            user_stmt = select(User).where(User.id == dept.manager_id)
            if dept.company_id is not None:
                user_stmt = user_stmt.where(User.company_id == dept.company_id)
            res = await self.session.execute(user_stmt)
            m_user = res.scalar_one_or_none()
            if m_user:
                reporting_manager_name = m_user.name

        if dept.parent_department_id:
            parent = await self.repo.get_by_id(dept.parent_department_id, company_id=dept.company_id)
            if parent:
                parent_name = parent.department_name
                if not reporting_manager_id:
                    reporting_manager_id = parent.manager_id
                    if parent.manager_user:
                        reporting_manager_name = parent.manager_user.name
                    elif parent.manager_id:
                        from app.models.user import User
                        from sqlalchemy import select
                        user_stmt = select(User).where(User.id == parent.manager_id)
                        if dept.company_id is not None:
                            user_stmt = user_stmt.where(User.company_id == dept.company_id)
                        res = await self.session.execute(user_stmt)
                        p_user = res.scalar_one_or_none()
                        if p_user:
                            reporting_manager_name = p_user.name

        return DepartmentResponse(
            id=dept.id,
            company_id=dept.company_id,
            department_code=dept.department_code,
            department_name=dept.department_name,
            description=dept.description,
            manager_id=dept.manager_id,
            head_id=dept.manager_id,
            head_name=reporting_manager_name,
            parent_department_id=dept.parent_department_id,
            branch_id=dept.branch_id,
            location=dept.location,
            cost_center=dept.cost_center,
            budget=float(dept.budget) if dept.budget is not None else 0.0,
            extension_number=dept.extension_number,
            employee_capacity=getattr(dept, "employee_capacity", 100) or 100,
            employeeCapacity=getattr(dept, "employee_capacity", 100) or 100,
            status=dept.status,
            created_by=dept.created_by,
            created_at=dept.created_at,
            updated_at=dept.updated_at,
            manager_details=await self._to_brief(dept.manager_user),
            created_by_details=await self._to_brief(dept.creator),
            parent_department_name=parent_name,
            reporting_manager_id=reporting_manager_id,
            reporting_manager_name=reporting_manager_name,
        )

    # ------------------------------------------------------------------
    # CRUD Operations
    # ------------------------------------------------------------------

    async def create_department(
        self, user_id: uuid.UUID, payload: DepartmentCreate, company_id: uuid.UUID | None = None
    ) -> DepartmentResponse:
        logger.info("create_department | user_id=%s | name=%s | company_id=%s", user_id, payload.department_name, company_id)
        try:
            # Uniqueness check (including soft-deleted ones)
            existing = await self.repo.get_by_name_all(payload.department_name, company_id=company_id)
            if existing and not existing.is_deleted:
                raise ConflictException(
                    message="A department with this name already exists.",
                    errors=[{"field": "department_name", "message": "Name already in use."}],
                )

            # Check custom department_code uniqueness if provided
            custom_code = (
                payload.department_code
                or getattr(payload, "code", None)
            )
            code_to_use = str(custom_code).strip().upper() if custom_code and str(custom_code).strip() else None
            if code_to_use:
                existing_code = await self.repo.get_by_code_all(code_to_use, company_id=company_id)
                if existing_code and not existing_code.is_deleted:
                    raise ConflictException(
                        message="A department with this code already exists.",
                        errors=[{"field": "department_code", "message": "Code already in use."}],
                    )

            # Parent check
            if payload.parent_department_id:
                parent = await self.repo.get_by_id_raw(payload.parent_department_id, company_id=company_id)
                if not parent:
                    raise AppException(message="Parent department not found.", status_code=status.HTTP_400_BAD_REQUEST)

            # Manager Head check
            resolved_manager_user_id = None
            if payload.manager_id:
                manager = await self.repo.get_manager_by_user_id(payload.manager_id, company_id=company_id)
                if not manager:
                    raise AppException(
                        message="Department Head must be a valid User with MANAGER role.",
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )
                resolved_manager_user_id = manager.id

            if existing and existing.is_deleted:
                # Reactivate and reuse the soft-deleted department
                logger.info("create_department | Reactivating soft-deleted department ID=%s", existing.id)
            cost_center_val = (
                payload.cost_center
                or getattr(payload, "cost_id", None)
                or getattr(payload, "costID", None)
                or getattr(payload, "cost_center_id", None)
                or getattr(payload, "costCenterId", None)
                or getattr(payload, "cost_code", None)
                or getattr(payload, "costCode", None)
                or getattr(payload, "costId", None)
            )
            cost_center_str = cost_center_val.strip() if cost_center_val else None

            if existing:
                dept = existing
                dept.is_deleted = False
                dept.deleted_at = None
                dept.company_id = company_id
                dept.normalized_name = payload.department_name.strip().upper()
                if code_to_use:
                    dept.department_code = code_to_use
                    dept.normalized_code = code_to_use
                dept.description = payload.description.strip() if payload.description else ""
                dept.manager_id = resolved_manager_user_id
                dept.parent_department_id = payload.parent_department_id
                dept.branch_id = payload.branch_id
                dept.location = payload.location.strip()
                dept.cost_center = cost_center_str
                dept.budget = payload.budget
                dept.extension_number = payload.extension_number.strip() if payload.extension_number else None
                dept.employee_capacity = payload.employee_capacity if payload.employee_capacity is not None else 100
                dept.status = payload.status
                await self.session.commit()
            else:
                dept = None
                if code_to_use:
                    dept_kwargs = {
                        "department_code": code_to_use,
                        "normalized_code": code_to_use,
                        "normalized_name": payload.department_name.strip().upper(),
                        "department_name": payload.department_name.strip(),
                        "description": payload.description.strip() if payload.description else "",
                        "manager_id": resolved_manager_user_id,
                        "parent_department_id": payload.parent_department_id,
                        "branch_id": payload.branch_id,
                        "location": payload.location.strip(),
                        "cost_center": cost_center_str or f"CC-{code_to_use}",
                        "budget": payload.budget,
                        "extension_number": payload.extension_number.strip() if payload.extension_number else None,
                        "employee_capacity": payload.employee_capacity if payload.employee_capacity is not None else 100,
                        "status": payload.status,
                        "created_by": user_id,
                        "company_id": company_id,
                    }
                    dept = await self.repo.create_department(**dept_kwargs)
                    await self.session.commit()
                else:
                    for attempt in range(3):
                        code = await generate_department_code(self.session, company_id=company_id)
                        dept_kwargs = {
                            "department_code": code,
                            "normalized_code": code.strip().upper(),
                            "normalized_name": payload.department_name.strip().upper(),
                            "department_name": payload.department_name.strip(),
                            "description": payload.description.strip() if payload.description else "",
                            "manager_id": resolved_manager_user_id,
                            "parent_department_id": payload.parent_department_id,
                            "branch_id": payload.branch_id,
                            "location": payload.location.strip(),
                            "cost_center": cost_center_str or f"CC-{code.replace('DEP', '')}",
                            "budget": payload.budget,
                            "extension_number": payload.extension_number.strip() if payload.extension_number else None,
                            "employee_capacity": payload.employee_capacity if payload.employee_capacity is not None else 100,
                            "status": payload.status,
                            "created_by": user_id,
                            "company_id": company_id,
                        }
                        try:
                            dept = await self.repo.create_department(**dept_kwargs)
                            await self.session.commit()
                            break
                        except IntegrityError:
                            await self.session.rollback()
                            dept = None
                            if attempt == 2:
                                raise ConflictException("Could not generate a unique department code, please retry.")

            # Re-fetch with loaded relations
            full_dept = await self.repo.get_by_id(dept.id, company_id=company_id)
            return await self._to_response(full_dept)

        except (AppException, ConflictException):
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("create_department: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def list_departments(
        self,
        status_filter: str | None = None,
        search: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        parent_id: uuid.UUID | None = None,
        page: int = 1,
        limit: int = 20,
        company_id: uuid.UUID | None = None,
    ) -> DepartmentListResponse:
        try:
            offset = (page - 1) * limit
            departments = await self.repo.list_departments(
                company_id=company_id,
                status=status_filter,
                search=search,
                parent_id=parent_id,
                sort_by=sort_by,
                sort_order=sort_order,
                limit=limit,
                offset=offset,
            )
            total = await self.repo.count_departments(
                company_id=company_id,
                status=status_filter,
                search=search,
                parent_id=parent_id,
            )

            items = []
            for d in departments:
                emp_count = await self.repo.get_employee_count(d.id)
                manager_name = d.manager_user.name if d.manager_user else None
                
                parent_department_name = None
                reporting_manager_id = None
                reporting_manager_name = None
                
                if d.parent_department:
                    parent_department_name = d.parent_department.department_name
                    reporting_manager_id = d.parent_department.manager_id
                    if reporting_manager_id:
                        from app.models.user import User
                        from sqlalchemy import select
                        user_stmt = select(User).where(User.id == reporting_manager_id)
                        res = await self.session.execute(user_stmt)
                        parent_user = res.scalar_one_or_none()
                        if parent_user:
                            reporting_manager_name = parent_user.name

                items.append(
                    DepartmentListItem(
                        id=d.id,
                        department_code=d.department_code,
                        department_name=d.department_name,
                        location=d.location,
                        status=d.status,
                        created_at=d.created_at,
                        employee_count=emp_count,
                        manager_name=manager_name,
                        manager_id=d.manager_id,
                        parent_department_id=d.parent_department_id,
                        parent_department_name=parent_department_name,
                        description=d.description,
                        budget=float(d.budget) if d.budget is not None else 0.0,
                        cost_center=d.cost_center,
                        extension_number=d.extension_number,
                        employee_capacity=getattr(d, "employee_capacity", 100) or 100,
                        employeeCapacity=getattr(d, "employee_capacity", 100) or 100,
                        reporting_manager_id=reporting_manager_id,
                        reporting_manager_name=reporting_manager_name,
                    )
                )

            pages = math.ceil(total / limit) if limit > 0 else 0
            return DepartmentListResponse(items=items, total=total, page=page, limit=limit, pages=pages)
        except SQLAlchemyError as exc:
            logger.exception("list_departments: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_department(self, department_uuid: uuid.UUID, company_id: uuid.UUID | None = None) -> DepartmentResponse:
        try:
            dept = await self.repo.get_by_id(department_uuid, company_id=company_id)
            if not dept:
                raise AppException(message="Department not found.", status_code=status.HTTP_404_NOT_FOUND)
            return await self._to_response(dept)
        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("get_department: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def update_department(
        self, user_id: uuid.UUID, department_uuid: uuid.UUID, payload: DepartmentUpdate, company_id: uuid.UUID | None = None
    ) -> DepartmentResponse:
        logger.info("update_department | user_id=%s | dept_id=%s | company_id=%s", user_id, department_uuid, company_id)
        try:
            dept = await self.repo.get_by_id_raw(department_uuid, company_id=company_id)
            if not dept:
                raise AppException(message="Department not found.", status_code=status.HTTP_404_NOT_FOUND)

            update_data = payload.model_dump(exclude_unset=True)
            if not update_data:
                raise AppException(message="No fields provided to update.", status_code=status.HTTP_400_BAD_REQUEST)

            cc_alias = (
                update_data.get("cost_center")
                or update_data.get("cost_id")
                or update_data.get("costID")
                or update_data.get("cost_center_id")
                or update_data.get("costCenterId")
                or update_data.get("cost_code")
                or update_data.get("costCode")
                or update_data.get("costId")
            )
            if cc_alias is not None:
                update_data["cost_center"] = str(cc_alias).strip() if str(cc_alias).strip() else None

            mgr_alias = (
                update_data.get("manager_id")
                or update_data.get("managerId")
                or update_data.get("reporting_manager_id")
                or update_data.get("reportingManagerId")
                or update_data.get("reporting_manager")
                or update_data.get("reportingManager")
                or update_data.get("head_id")
                or update_data.get("headId")
                or update_data.get("department_head_id")
                or update_data.get("departmentHeadId")
            )
            if isinstance(mgr_alias, dict):
                mgr_alias = mgr_alias.get("id") or mgr_alias.get("user_id") or mgr_alias.get("value")
            if mgr_alias is not None and mgr_alias != "":
                update_data["manager_id"] = mgr_alias

            for alias_key in ("cost_id", "costID", "cost_center_id", "costCenterId", "cost_code", "costCode", "costId",
                              "managerId", "reporting_manager_id", "reportingManagerId", "reporting_manager", "reportingManager",
                              "head_id", "headId", "department_head_id", "departmentHeadId"):
                update_data.pop(alias_key, None)

            for field in ["department_name", "description", "location", "cost_center", "extension_number", "employee_capacity"]:
                if field in update_data and isinstance(update_data[field], str):
                    update_data[field] = update_data[field].strip()
                    if field in ("cost_center", "extension_number") and not update_data[field]:
                        update_data[field] = None

            if "department_name" in update_data:
                existing = await self.repo.get_by_name_all(update_data["department_name"], company_id=company_id)
                if existing and existing.id != department_uuid:
                    if existing.is_deleted:
                        raise ConflictException(
                            message="A department with this name already exists (archived).",
                            errors=[{"field": "department_name", "message": "Name is archived. Please reactivate it or use a different name."}],
                        )
                    else:
                        raise ConflictException(
                            message="A department with this name already exists.",
                            errors=[{"field": "department_name", "message": "Name already in use."}],
                        )

            if "department_code" in update_data and update_data["department_code"]:
                code_str = update_data["department_code"].strip().upper()
                existing_code = await self.repo.get_by_code_all(code_str, company_id=company_id)
                if existing_code and existing_code.id != department_uuid and not existing_code.is_deleted:
                    raise ConflictException(
                        message="A department with this code already exists.",
                        errors=[{"field": "department_code", "message": "Code already in use."}],
                    )
                update_data["department_code"] = code_str

            if "parent_department_id" in update_data:
                if update_data["parent_department_id"] is not None:
                    if update_data["parent_department_id"] == department_uuid:
                        raise AppException(
                            message="A department cannot be its own parent.",
                            status_code=status.HTTP_400_BAD_REQUEST,
                        )
                    parent = await self.repo.get_by_id_raw(update_data["parent_department_id"], company_id=company_id)
                    if not parent:
                        raise AppException(message="Parent department not found.", status_code=status.HTTP_400_BAD_REQUEST)

                    # Prevent circular hierarchy
                    ancestor_ids = await self.repo.get_department_ancestor_ids(update_data["parent_department_id"], company_id=company_id)
                    if department_uuid in ancestor_ids:
                        raise AppException(
                            message="Circular department hierarchy detected. A department cannot be a child of its own sub-department.",
                            status_code=status.HTTP_400_BAD_REQUEST,
                        )

            if "manager_id" in update_data and update_data["manager_id"] is not None:
                manager = await self.repo.get_manager_by_user_id(update_data["manager_id"], company_id=company_id)
                if not manager:
                    raise AppException(
                        message="Department Head must be a valid User with MANAGER role.",
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )
                update_data["manager_id"] = manager.id

            await self.repo.update_department(department_uuid, company_id=company_id, **update_data)
            await self.session.commit()

            full_dept = await self.repo.get_by_id(department_uuid, company_id=company_id)
            return await self._to_response(full_dept)

        except (AppException, ConflictException):
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("update_department: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def delete_department(self, user_id: uuid.UUID, department_uuid: uuid.UUID, company_id: uuid.UUID | None = None) -> None:
        logger.info("delete_department | user_id=%s | dept_id=%s | company_id=%s", user_id, department_uuid, company_id)
        try:
            dept = await self.repo.get_by_id_raw(department_uuid, company_id=company_id)
            if not dept:
                raise AppException(message="Department not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Delete Guard: check if employees are assigned
            emp_count = await self.repo.get_employee_count(department_uuid)
            if emp_count > 0:
                raise AppException(
                    message="Cannot delete department because there are employees assigned to it.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            await self.repo.soft_delete(department_uuid, company_id=company_id)
            await self.session.commit()
            logger.info("delete_department: success | dept_id=%s", department_uuid)

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("delete_department: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Assign Manager & Employees
    # ------------------------------------------------------------------

    async def assign_manager(
        self, user_id: uuid.UUID, department_uuid: uuid.UUID, payload: AssignManagerRequest, company_id: uuid.UUID | None = None
    ) -> None:
        logger.info("assign_manager | user_id=%s | dept_id=%s | company_id=%s", user_id, department_uuid, company_id)
        try:
            dept = await self.repo.get_by_id_raw(department_uuid, company_id=company_id)
            if not dept:
                raise AppException(message="Department not found.", status_code=status.HTTP_404_NOT_FOUND)

            manager = await self.repo.get_manager_by_user_id(payload.manager_user_id, company_id=company_id)
            if not manager:
                raise AppException(
                    message="Department Head must be a valid User with MANAGER role.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            await self.repo.assign_manager(department_uuid, manager.id, company_id=company_id)
            await self.session.commit()

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("assign_manager: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def remove_manager(self, user_id: uuid.UUID, department_uuid: uuid.UUID, company_id: uuid.UUID | None = None) -> None:
        logger.info("remove_manager | user_id=%s | dept_id=%s | company_id=%s", user_id, department_uuid, company_id)
        try:
            dept = await self.repo.get_by_id_raw(department_uuid, company_id=company_id)
            if not dept:
                raise AppException(message="Department not found.", status_code=status.HTTP_404_NOT_FOUND)

            await self.repo.remove_manager(department_uuid, company_id=company_id)
            await self.session.commit()

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("remove_manager: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def assign_employees(
        self, user_id: uuid.UUID, department_uuid: uuid.UUID, payload: AssignEmployeesRequest, company_id: uuid.UUID | None = None
    ) -> None:
        logger.info("assign_employees | user_id=%s | dept_id=%s | company_id=%s", user_id, department_uuid, company_id)
        try:
            dept = await self.repo.get_by_id_raw(department_uuid, company_id=company_id)
            if not dept:
                raise AppException(message="Department not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Assign all employee records to this department
            await self.repo.assign_employees(department_uuid, payload.employee_ids, company_id=company_id)
            await self.session.commit()

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("assign_employees: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def remove_employee(
        self, user_id: uuid.UUID, department_uuid: uuid.UUID, employee_id: uuid.UUID, company_id: uuid.UUID | None = None
    ) -> None:
        logger.info("remove_employee | user_id=%s | dept_id=%s | emp_id=%s | company_id=%s", user_id, department_uuid, employee_id, company_id)
        try:
            dept = await self.repo.get_by_id_raw(department_uuid, company_id=company_id)
            if not dept:
                raise AppException(message="Department not found.", status_code=status.HTTP_404_NOT_FOUND)

            await self.repo.remove_employee_from_department(employee_id, company_id=company_id)
            await self.session.commit()

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("remove_employee: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_department_employees(self, department_uuid: uuid.UUID, company_id: uuid.UUID | None = None) -> list[Any]:
        try:
            dept = await self.repo.get_by_id_raw(department_uuid, company_id=company_id)
            if not dept:
                raise AppException(message="Department not found.", status_code=status.HTTP_404_NOT_FOUND)

            employees = await self.repo.get_department_employees(department_uuid, company_id=company_id)
            # return custom briefs or response objects
            return employees
        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("get_department_employees: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_department_stats(self, department_uuid: uuid.UUID, company_id: uuid.UUID | None = None) -> DepartmentStats:
        try:
            dept = await self.repo.get_by_id_raw(department_uuid, company_id=company_id)
            if not dept:
                raise AppException(message="Department not found.", status_code=status.HTTP_404_NOT_FOUND)

            active_cnt = await self.repo.get_employee_count(department_uuid, active_only=True)
            inactive_cnt = await self.repo.get_inactive_employee_count(department_uuid)
            total_cnt = active_cnt + inactive_cnt
            subs_cnt = await self.repo.get_sub_departments_count(department_uuid, company_id=company_id)

            return DepartmentStats(
                department_id=department_uuid,
                department_name=dept.department_name,
                active_employee_count=active_cnt,
                inactive_employee_count=inactive_cnt,
                total_employee_count=total_cnt,
                sub_departments_count=subs_cnt,
            )
        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("get_department_stats: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_departments_summary(self, company_id: uuid.UUID | None = None) -> dict[str, Any]:
        try:
            return await self.repo.get_departments_summary(company_id=company_id)
        except SQLAlchemyError as exc:
            logger.exception("get_departments_summary: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Hierarchy & Tree Views
    # ------------------------------------------------------------------

    async def get_department_hierarchy(self, company_id: uuid.UUID | None = None) -> list[DepartmentHierarchyNode]:
        """Build and return a hierarchical tree of departments for the company."""
        try:
            departments = await self.repo.get_all_active_departments(company_id=company_id)

            nodes_by_id: dict[uuid.UUID, DepartmentHierarchyNode] = {}
            for dept in departments:
                emp_count = await self.repo.get_employee_count(dept.id, company_id=company_id)
                mgr_name = dept.manager_user.name if dept.manager_user else None
                node = DepartmentHierarchyNode(
                    id=dept.id,
                    department_code=dept.department_code,
                    department_name=dept.department_name,
                    description=dept.description,
                    parent_department_id=dept.parent_department_id,
                    manager_id=dept.manager_id,
                    manager_name=mgr_name,
                    head_id=dept.manager_id,
                    head_name=mgr_name,
                    employee_count=emp_count,
                    headcount=emp_count,
                    budget=float(dept.budget) if dept.budget is not None else 0.0,
                    status=dept.status or "ACTIVE",
                    location=dept.location or "Main Office",
                    children=[],
                )
                nodes_by_id[dept.id] = node

            roots: list[DepartmentHierarchyNode] = []
            for node in nodes_by_id.values():
                if node.parent_department_id and node.parent_department_id in nodes_by_id:
                    nodes_by_id[node.parent_department_id].children.append(node)
                else:
                    roots.append(node)

            return roots
        except SQLAlchemyError as exc:
            logger.exception("get_department_hierarchy: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_department_subtree_hierarchy(self, department_uuid: uuid.UUID, company_id: uuid.UUID | None = None) -> DepartmentHierarchyNode:
        """Return the subtree hierarchy rooted at the specified department."""
        dept = await self.repo.get_by_id(department_uuid, company_id=company_id)
        if not dept:
            raise AppException(message="Department not found.", status_code=status.HTTP_404_NOT_FOUND)

        all_roots = await self.get_department_hierarchy(company_id=company_id)

        # Search for node in all_roots
        def find_node(nodes: list[DepartmentHierarchyNode]) -> DepartmentHierarchyNode | None:
            for n in nodes:
                if n.id == department_uuid:
                    return n
                sub = find_node(n.children)
                if sub:
                    return sub
            return None

        found = find_node(all_roots)
        if not found:
            emp_count = await self.repo.get_employee_count(dept.id, company_id=company_id)
            mgr_name = dept.manager_user.name if dept.manager_user else None
            return DepartmentHierarchyNode(
                id=dept.id,
                department_code=dept.department_code,
                department_name=dept.department_name,
                description=dept.description,
                parent_department_id=dept.parent_department_id,
                manager_id=dept.manager_id,
                manager_name=mgr_name,
                head_id=dept.manager_id,
                head_name=mgr_name,
                employee_count=emp_count,
                headcount=emp_count,
                budget=float(dept.budget) if dept.budget is not None else 0.0,
                status=dept.status or "ACTIVE",
                location=dept.location or "Main Office",
                children=[],
            )
        return found

    # ------------------------------------------------------------------
    # Analytics & Metrics
    # ------------------------------------------------------------------

    async def get_department_analytics(self, company_id: uuid.UUID | None = None) -> DepartmentAnalyticsResponse:
        """Compile department analytics including capacity utilization, budget allocation, and team sizes."""
        try:
            summary = await self.repo.get_departments_summary(company_id=company_id)
            departments = await self.repo.get_all_active_departments(company_id=company_id)

            total_budget = 0.0
            total_capacity = 0
            depts_without_mgr = 0
            breakdown: list[dict[str, Any]] = []

            for d in departments:
                emp_count = await self.repo.get_employee_count(d.id, company_id=company_id)
                cap = getattr(d, "employee_capacity", 100) or 100
                b = float(d.budget) if d.budget is not None else 0.0
                total_budget += b
                total_capacity += cap
                if not d.manager_id:
                    depts_without_mgr += 1

                util_pct = round((emp_count / cap) * 100, 1) if cap > 0 else 0.0
                breakdown.append({
                    "id": str(d.id),
                    "code": d.department_code,
                    "name": d.department_name,
                    "status": d.status,
                    "employee_count": emp_count,
                    "capacity": cap,
                    "capacity_utilization_pct": util_pct,
                    "budget": b,
                    "manager_name": d.manager_user.name if d.manager_user else None,
                })

            total_hc = summary.get("total_employees", 0)
            cap_util = round((total_hc / total_capacity) * 100, 1) if total_capacity > 0 else 0.0

            return DepartmentAnalyticsResponse(
                total_departments=summary.get("total_departments", 0),
                active_departments=summary.get("active_departments", 0),
                inactive_departments=summary.get("inactive_departments", 0),
                hiring_departments=summary.get("hiring_departments", 0),
                total_headcount=total_hc,
                total_budget=round(total_budget, 2),
                departments_without_manager=depts_without_mgr,
                capacity_utilization_pct=cap_util,
                average_team_size=summary.get("avg_team_size", 0.0),
                open_positions=summary.get("open_positions", 0),
                department_breakdown=breakdown,
            )
        except SQLAlchemyError as exc:
            logger.exception("get_department_analytics: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Bulk Operations
    # ------------------------------------------------------------------

    async def bulk_delete_departments(
        self, user_id: uuid.UUID, department_ids: list[uuid.UUID], company_id: uuid.UUID | None = None
    ) -> BulkActionResponse:
        """Soft delete multiple departments, blocking any that have active employees assigned."""
        success_ids: list[uuid.UUID] = []
        errors: list[dict[str, Any]] = []

        for dept_id in department_ids:
            dept = await self.repo.get_by_id_raw(dept_id, company_id=company_id)
            if not dept or dept.is_deleted:
                errors.append({"id": str(dept_id), "message": "Department not found or already deleted."})
                continue

            emp_cnt = await self.repo.get_employee_count(dept_id, company_id=company_id)
            if emp_cnt > 0:
                errors.append({
                    "id": str(dept_id),
                    "name": dept.department_name,
                    "message": f"Cannot delete department with {emp_cnt} active employees assigned. Transfer them first."
                })
                continue

            await self.repo.soft_delete(dept_id, company_id=company_id)
            success_ids.append(dept_id)

        await self.session.commit()
        return BulkActionResponse(affected_count=len(success_ids), success_ids=success_ids, errors=errors if errors else None)

    async def bulk_update_status(
        self, user_id: uuid.UUID, department_ids: list[uuid.UUID], status: str, company_id: uuid.UUID | None = None
    ) -> BulkActionResponse:
        """Bulk update status for departments."""
        status_norm = status.strip().upper()
        affected = await self.repo.bulk_update_status(department_ids, status_norm, company_id=company_id)
        await self.session.commit()
        return BulkActionResponse(affected_count=affected, success_ids=department_ids, errors=None)

    async def bulk_assign_manager(
        self, user_id: uuid.UUID, department_ids: list[uuid.UUID], manager_user_id: uuid.UUID | None, company_id: uuid.UUID | None = None
    ) -> BulkActionResponse:
        """Bulk assign manager to multiple departments."""
        resolved_mgr_id = None
        if manager_user_id:
            manager = await self.repo.get_manager_by_user_id(manager_user_id, company_id=company_id)
            if not manager:
                raise AppException(
                    message="Department Head must be a valid User with MANAGER role.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            resolved_mgr_id = manager.id

        affected = await self.repo.bulk_assign_manager(department_ids, resolved_mgr_id, company_id=company_id)
        await self.session.commit()
        return BulkActionResponse(affected_count=affected, success_ids=department_ids, errors=None)

    async def transfer_employees(
        self,
        user_id: uuid.UUID,
        source_dept_id: uuid.UUID,
        target_dept_id: uuid.UUID,
        employee_ids: list[uuid.UUID] | None = None,
        company_id: uuid.UUID | None = None,
    ) -> BulkActionResponse:
        """Transfer employees from source to target department."""
        if source_dept_id == target_dept_id:
            raise AppException(message="Source and target departments cannot be identical.", status_code=status.HTTP_400_BAD_REQUEST)

        source = await self.repo.get_by_id_raw(source_dept_id, company_id=company_id)
        if not source or source.is_deleted:
            raise AppException(message="Source department not found.", status_code=status.HTTP_404_NOT_FOUND)

        target = await self.repo.get_by_id_raw(target_dept_id, company_id=company_id)
        if not target or target.is_deleted:
            raise AppException(message="Target department not found.", status_code=status.HTTP_404_NOT_FOUND)

        affected = await self.repo.transfer_employees(
            source_dept_id=source_dept_id,
            target_dept_id=target_dept_id,
            target_dept_name=target.department_name,
            employee_ids=employee_ids,
            company_id=company_id,
        )
        await self.session.commit()
        return BulkActionResponse(affected_count=affected, success_ids=[target_dept_id], errors=None)

    # ------------------------------------------------------------------
    # Import / Export
    # ------------------------------------------------------------------

    async def export_departments(self, company_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
        """Export all departments with detailed attributes."""
        departments = await self.repo.get_all_active_departments(company_id=company_id)
        records: list[dict[str, Any]] = []
        for d in departments:
            emp_cnt = await self.repo.get_employee_count(d.id, company_id=company_id)
            records.append({
                "id": str(d.id),
                "department_code": d.department_code,
                "department_name": d.department_name,
                "description": d.description or "",
                "status": d.status,
                "location": d.location,
                "cost_center": d.cost_center,
                "budget": float(d.budget) if d.budget is not None else 0.0,
                "extension_number": d.extension_number or "",
                "employee_capacity": getattr(d, "employee_capacity", 100) or 100,
                "employee_count": emp_cnt,
                "manager_name": d.manager_user.name if d.manager_user else None,
                "parent_department_name": d.parent_department.department_name if d.parent_department else None,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            })
        return records

    async def export_departments_csv(self, company_id: uuid.UUID | None = None) -> str:
        """Export departments as CSV formatted string."""
        import csv
        import io

        records = await self.export_departments(company_id=company_id)
        output = io.StringIO()
        fieldnames = [
            "id", "department_code", "department_name", "status", "location",
            "cost_center", "budget", "extension_number", "employee_capacity",
            "employee_count", "manager_name", "parent_department_name", "created_at"
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in records:
            writer.writerow(r)
        return output.getvalue()

    async def import_departments(
        self, user_id: uuid.UUID, items: list[DepartmentCreate], company_id: uuid.UUID | None = None
    ) -> BulkActionResponse:
        """Bulk import department records with conflict and error resilience."""
        success_ids: list[uuid.UUID] = []
        errors: list[dict[str, Any]] = []

        for item in items:
            try:
                dept_resp = await self.create_department(user_id=user_id, payload=item, company_id=company_id)
                success_ids.append(dept_resp.id)
            except Exception as exc:
                errors.append({
                    "department_name": item.department_name,
                    "code": item.department_code,
                    "error": str(exc),
                })

        return BulkActionResponse(affected_count=len(success_ids), success_ids=success_ids, errors=errors if errors else None)


async def get_department_service(
    session: AsyncSession = Depends(get_db_session),
) -> DepartmentService:
    return DepartmentService(
        session=session,
        department_repository=DepartmentRepository(session),
    )
