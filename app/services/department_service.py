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
    DepartmentCreate,
    DepartmentListResponse,
    DepartmentResponse,
    DepartmentUpdate,
    DepartmentStats,
    DepartmentListItem,
    UserBrief,
)

if TYPE_CHECKING:
    from app.models.department import Department

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Department Code Generator (e.g. DEP0001, DEP0002)
# ---------------------------------------------------------------------------

async def generate_department_code(session: AsyncSession) -> str:
    from app.models.department import Department
    from sqlalchemy import select
    result = await session.execute(
        select(Department.department_code)
        .where(Department.department_code.like("DEP%"))
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
            select(Department).where(Department.department_code == code)
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
            res = await self.session.execute(user_stmt)
            m_user = res.scalar_one_or_none()
            if m_user:
                reporting_manager_name = m_user.name

        if dept.parent_department_id:
            parent = await self.repo.get_by_id_raw(dept.parent_department_id)
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
                        res = await self.session.execute(user_stmt)
                        p_user = res.scalar_one_or_none()
                        if p_user:
                            reporting_manager_name = p_user.name

        return DepartmentResponse(
            id=dept.id,
            department_code=dept.department_code,
            department_name=dept.department_name,
            description=dept.description,
            manager_id=dept.manager_id,
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

    async def create_department(self, user_id: uuid.UUID, payload: DepartmentCreate) -> DepartmentResponse:
        logger.info("create_department | user_id=%s | name=%s", user_id, payload.department_name)
        try:
            # Uniqueness check (including soft-deleted ones)
            existing = await self.repo.get_by_name_all(payload.department_name)
            if existing and not existing.is_deleted:
                raise ConflictException(
                    message="A department with this name already exists.",
                    errors=[{"field": "department_name", "message": "Name already in use."}],
                )

            # Parent check
            if payload.parent_department_id:
                parent = await self.repo.get_by_id_raw(payload.parent_department_id)
                if not parent:
                    raise AppException(message="Parent department not found.", status_code=status.HTTP_400_BAD_REQUEST)

            # Manager Head check
            resolved_manager_user_id = None
            if payload.manager_id:
                manager = await self.repo.get_manager_by_user_id(payload.manager_id)
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
                dept.description = payload.description.strip()
                dept.manager_id = resolved_manager_user_id
                dept.parent_department_id = payload.parent_department_id
                dept.branch_id = payload.branch_id
                dept.location = payload.location.strip()
                dept.cost_center = cost_center_str
                dept.budget = payload.budget
                dept.extension_number = payload.extension_number.strip() if payload.extension_number else None
                dept.employee_capacity = payload.employee_capacity if payload.employee_capacity is not None else 100
                dept.status = payload.status
            else:
                code = await generate_department_code(self.session)
                dept_kwargs = {
                    "department_code": code,
                    "department_name": payload.department_name.strip(),
                    "description": payload.description.strip(),
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
                }
                dept = await self.repo.create_department(**dept_kwargs)

            await self.session.commit()

            # Re-fetch with loaded relations
            full_dept = await self.repo.get_by_id(dept.id)
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
        page: int = 1,
        limit: int = 20,
    ) -> DepartmentListResponse:
        try:
            offset = (page - 1) * limit
            departments = await self.repo.list_departments(
                status=status_filter,
                search=search,
                sort_by=sort_by,
                sort_order=sort_order,
                limit=limit,
                offset=offset,
            )
            total = await self.repo.count_departments(
                status=status_filter,
                search=search,
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

    async def get_department(self, department_uuid: uuid.UUID) -> DepartmentResponse:
        try:
            dept = await self.repo.get_by_id(department_uuid)
            if not dept:
                raise AppException(message="Department not found.", status_code=status.HTTP_404_NOT_FOUND)
            return await self._to_response(dept)
        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("get_department: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def update_department(
        self, user_id: uuid.UUID, department_uuid: uuid.UUID, payload: DepartmentUpdate
    ) -> DepartmentResponse:
        logger.info("update_department | user_id=%s | dept_id=%s", user_id, department_uuid)
        try:
            dept = await self.repo.get_by_id_raw(department_uuid)
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
                existing = await self.repo.get_by_name_all(update_data["department_name"])
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

            if "parent_department_id" in update_data:
                if update_data["parent_department_id"] == department_uuid:
                    raise AppException(
                        message="A department cannot be its own parent.",
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )
                parent = await self.repo.get_by_id_raw(update_data["parent_department_id"])
                if not parent:
                    raise AppException(message="Parent department not found.", status_code=status.HTTP_400_BAD_REQUEST)

            if "manager_id" in update_data and update_data["manager_id"] is not None:
                manager = await self.repo.get_manager_by_user_id(update_data["manager_id"])
                if not manager:
                    raise AppException(
                        message="Department Head must be a valid User with MANAGER role.",
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )
                update_data["manager_id"] = manager.id

            await self.repo.update_department(department_uuid, **update_data)
            await self.session.commit()

            full_dept = await self.repo.get_by_id(department_uuid)
            return await self._to_response(full_dept)

        except (AppException, ConflictException):
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("update_department: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def delete_department(self, user_id: uuid.UUID, department_uuid: uuid.UUID) -> None:
        logger.info("delete_department | user_id=%s | dept_id=%s", user_id, department_uuid)
        try:
            dept = await self.repo.get_by_id_raw(department_uuid)
            if not dept:
                raise AppException(message="Department not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Delete Guard: check if employees are assigned
            emp_count = await self.repo.get_employee_count(department_uuid)
            if emp_count > 0:
                raise AppException(
                    message="Cannot delete department because there are employees assigned to it.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            await self.repo.soft_delete(department_uuid)
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

    async def assign_manager(self, user_id: uuid.UUID, department_uuid: uuid.UUID, payload: AssignManagerRequest) -> None:
        logger.info("assign_manager | user_id=%s | dept_id=%s", user_id, department_uuid)
        try:
            dept = await self.repo.get_by_id_raw(department_uuid)
            if not dept:
                raise AppException(message="Department not found.", status_code=status.HTTP_404_NOT_FOUND)

            manager = await self.repo.get_manager_by_user_id(payload.manager_user_id)
            if not manager:
                raise AppException(
                    message="Department Head must be a valid User with MANAGER role.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            await self.repo.assign_manager(department_uuid, manager.id)
            await self.session.commit()

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("assign_manager: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def remove_manager(self, user_id: uuid.UUID, department_uuid: uuid.UUID) -> None:
        logger.info("remove_manager | user_id=%s | dept_id=%s", user_id, department_uuid)
        try:
            dept = await self.repo.get_by_id_raw(department_uuid)
            if not dept:
                raise AppException(message="Department not found.", status_code=status.HTTP_404_NOT_FOUND)

            await self.repo.remove_manager(department_uuid)
            await self.session.commit()

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("remove_manager: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def assign_employees(self, user_id: uuid.UUID, department_uuid: uuid.UUID, payload: AssignEmployeesRequest) -> None:
        logger.info("assign_employees | user_id=%s | dept_id=%s", user_id, department_uuid)
        try:
            dept = await self.repo.get_by_id_raw(department_uuid)
            if not dept:
                raise AppException(message="Department not found.", status_code=status.HTTP_440_NOT_FOUND if hasattr(status, "HTTP_440_NOT_FOUND") else status.HTTP_404_NOT_FOUND)

            # Assign all employee records to this department
            await self.repo.assign_employees(department_uuid, payload.employee_ids)
            await self.session.commit()

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("assign_employees: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def remove_employee(self, user_id: uuid.UUID, department_uuid: uuid.UUID, employee_id: uuid.UUID) -> None:
        logger.info("remove_employee | user_id=%s | dept_id=%s | emp_id=%s", user_id, department_uuid, employee_id)
        try:
            dept = await self.repo.get_by_id_raw(department_uuid)
            if not dept:
                raise AppException(message="Department not found.", status_code=status.HTTP_404_NOT_FOUND)

            await self.repo.remove_employee_from_department(employee_id)
            await self.session.commit()

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("remove_employee: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_department_employees(self, department_uuid: uuid.UUID) -> list[Any]:
        try:
            dept = await self.repo.get_by_id_raw(department_uuid)
            if not dept:
                raise AppException(message="Department not found.", status_code=status.HTTP_404_NOT_FOUND)

            employees = await self.repo.get_department_employees(department_uuid)
            # return custom briefs or response objects
            return employees
        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("get_department_employees: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_department_stats(self, department_uuid: uuid.UUID) -> DepartmentStats:
        try:
            dept = await self.repo.get_by_id_raw(department_uuid)
            if not dept:
                raise AppException(message="Department not found.", status_code=status.HTTP_404_NOT_FOUND)

            active_cnt = await self.repo.get_employee_count(department_uuid, active_only=True)
            inactive_cnt = await self.repo.get_inactive_employee_count(department_uuid)
            total_cnt = active_cnt + inactive_cnt
            subs_cnt = await self.repo.get_sub_departments_count(department_uuid)

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


async def get_department_service(
    session: AsyncSession = Depends(get_db_session),
) -> DepartmentService:
    return DepartmentService(
        session=session,
        department_repository=DepartmentRepository(session),
    )
