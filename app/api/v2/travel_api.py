"""FastAPI router for Travel Request Management."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, Query, status, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, or_, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.rbac import require_employee_or_above, require_admin_or_manager, RoleEnum
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims, get_current_employee, get_current_company
from app.models.employee import Employee
from app.models.travel import TravelRequest
from app.schemas.auth import APIResponse

router = APIRouter(
    prefix="/travel",
    tags=["Travel Management"],
    dependencies=[Depends(require_employee_or_above)],
)

# Travel status workflow definition
TRAVEL_STATUS_WORKFLOW = {
    "draft": ["manager-review", "cancelled"],
    "manager-review": ["hr-review", "finance-review", "rejected", "draft"],
    "hr-review": ["finance-review", "approved", "rejected", "manager-review"],
    "finance-review": ["approved", "rejected", "hr-review"],
    "approved": ["rejected"],
    "rejected": ["draft"],
    "cancelled": ["draft"],
}

# Stage-specific approver roles
STAGE_APPROVER_ROLES = {
    "manager-review": {RoleEnum.MANAGER.value, RoleEnum.HR_ADMIN.value, RoleEnum.EXECUTIVE.value},
    "hr-review": {RoleEnum.HR_ADMIN.value, RoleEnum.EXECUTIVE.value},
    "finance-review": {RoleEnum.HR_ADMIN.value, RoleEnum.EXECUTIVE.value, "finance"},
    "approved": {RoleEnum.HR_ADMIN.value, RoleEnum.EXECUTIVE.value, RoleEnum.MANAGER.value, "finance"},
    "rejected": {RoleEnum.MANAGER.value, RoleEnum.HR_ADMIN.value, RoleEnum.EXECUTIVE.value, "finance"},
}

# ---------------- Pydantic Schemas ----------------
class TravelRequestCreate(BaseModel):
    type: str = Field("domestic", description="domestic | international")
    purpose: str
    destination: str
    travel_date: date
    return_date: date
    budget: Decimal = Field(default=0.00)
    currency: str = "INR"
    hotel: Optional[str] = None
    transportation: Optional[str] = None

class TravelRequestUpdate(BaseModel):
    type: Optional[str] = None
    purpose: Optional[str] = None
    destination: Optional[str] = None
    travel_date: Optional[date] = None
    return_date: Optional[date] = None
    budget: Optional[Decimal] = None
    currency: Optional[str] = None
    hotel: Optional[str] = None
    transportation: Optional[str] = None

class AdvanceRequest(BaseModel):
    stage: str
    note: Optional[str] = None

class TravelRequestResponse(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str
    type: str
    purpose: str
    destination: str
    travel_date: date
    return_date: date
    budget: float
    currency: str
    status: str
    hotel: Optional[str] = None
    transportation: Optional[str] = None
    history: Optional[List[Dict[str, Any]]] = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_model(cls, travel: TravelRequest) -> "TravelRequestResponse":
        emp_name = "Unknown Employee"
        if travel.employee:
            emp_name = f"{travel.employee.first_name} {travel.employee.last_name}".strip()

        return cls(
            id=travel.id,
            employee_id=travel.employee_id,
            employee_name=emp_name,
            type=travel.type,
            purpose=travel.purpose,
            destination=travel.destination,
            travel_date=travel.travel_date,
            return_date=travel.return_date,
            budget=float(travel.budget),
            currency=travel.currency,
            status=travel.status,
            hotel=travel.hotel,
            transportation=travel.transportation,
            history=travel.history,
            created_at=travel.created_at,
            updated_at=travel.updated_at
        )

class TravelStatsResponse(BaseModel):
    total: int
    pending: int
    approved: int
    budget: float


# ---------------- Helper Functions ----------------
async def _get_current_employee_id(claims: dict, db: AsyncSession) -> uuid.UUID:
    """Resolve current employee ID from logged-in user claims."""
    user_id_raw = claims.get("sub")
    if not user_id_raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user association.")

    user_id = uuid.UUID(str(user_id_raw))
    from app.repositories.employee_repository import EmployeeRepository
    emp_repo = EmployeeRepository(db)
    employee = await emp_repo.get_by_user_id(user_id)
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee profile not found.")
    return employee.id


async def _get_current_company_id(claims: dict) -> uuid.UUID:
    """Resolve current company ID from claims."""
    company_id_raw = claims.get("company_id")
    if not company_id_raw:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is not associated with a company.")
    return uuid.UUID(str(company_id_raw))


def _validate_travel_status_transition(current_status: str, new_status: str) -> bool:
    """Validate if status transition is allowed per workflow."""
    allowed = TRAVEL_STATUS_WORKFLOW.get(current_status, [])
    return new_status in allowed


def _validate_approver_authority(role: str, stage: str) -> bool:
    """Validate if role has authority to approve at given stage."""
    allowed_roles = STAGE_APPROVER_ROLES.get(stage, set())
    return role in allowed_roles


async def _get_employee_with_company(db: AsyncSession, employee_id: uuid.UUID, company_id: uuid.UUID) -> Employee | None:
    """Get employee ensuring they belong to the specified company."""
    stmt = select(Employee).where(
        and_(
            Employee.id == employee_id,
            Employee.company_id == company_id,
            Employee.is_deleted == False
        )
    )
    res = await db.execute(stmt)
    return res.scalar_one_or_none()


async def _check_reporting_relationship(db: AsyncSession, manager_employee_id: uuid.UUID, target_employee_id: uuid.UUID) -> bool:
    """Check if manager_employee_id is in the reporting chain of target_employee_id."""
    # Direct manager
    stmt = select(Employee).where(
        and_(
            Employee.id == target_employee_id,
            Employee.manager_id == manager_employee_id
        )
    )
    res = await db.execute(stmt)
    direct_report = res.scalar_one_or_none()
    if direct_report:
        return True

    # Check indirect reports (team leads, etc.) - traverse up the chain
    current_id = target_employee_id
    visited = set()
    while current_id and current_id not in visited:
        visited.add(current_id)
        stmt = select(Employee.manager_id).where(Employee.id == current_id)
        res = await db.execute(stmt)
        current_id = res.scalar_one_or_none()
        if current_id == manager_employee_id:
            return True
    return False


# ---------------- API Endpoints ----------------

@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[List[TravelRequestResponse]],
    summary="List all travel requests with filtering and searching"
)
async def list_travel_requests(
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=100),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    current_employee: Employee = Depends(get_current_employee),
    current_company: Employee = Depends(get_current_company),
) -> APIResponse[List[TravelRequestResponse]]:
    company_id = current_company.company_id
    user_role = (claims.get("role") or "").lower().strip()

    # Base query - tenant isolated
    stmt = select(TravelRequest).join(Employee).options(
        selectinload(TravelRequest.employee)
    ).where(Employee.company_id == company_id)

    # Employee can only see their own requests
    if user_role == RoleEnum.EMPLOYEE.value:
        stmt = stmt.where(TravelRequest.employee_id == current_employee.id)
    # Manager can see their team's requests
    elif user_role == RoleEnum.MANAGER.value:
        # Get all direct and indirect reports
        from app.repositories.employee_repository import EmployeeRepository
        emp_repo = EmployeeRepository(db)
        # For now, allow manager to see all in company - can be refined with team hierarchy
        pass
    # HR Admin and Executive can see all in company
    # Super Admin should not automatically see cross-tenant data

    if status_filter and status_filter != "all":
        stmt = stmt.where(TravelRequest.status == status_filter)

    if search:
        search_term = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Employee.first_name).like(search_term),
                func.lower(Employee.last_name).like(search_term),
                func.lower(TravelRequest.destination).like(search_term),
                func.lower(TravelRequest.purpose).like(search_term)
            )
        )

    # Sort and paginate
    stmt = stmt.order_by(TravelRequest.created_at.desc())
    stmt = stmt.offset((page - 1) * limit).limit(limit)

    result = await db.execute(stmt)
    travels = result.scalars().all()

    data = [TravelRequestResponse.from_orm_model(t) for t in travels]
    return APIResponse[List[TravelRequestResponse]](
        success=True,
        message="Travel requests retrieved successfully.",
        data=data
    )


@router.get(
    "/stats",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[TravelStatsResponse],
    summary="Get travel request summary statistics"
)
async def get_travel_stats(
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    current_company: Employee = Depends(get_current_company),
) -> APIResponse[TravelStatsResponse]:
    company_id = current_company.company_id
    user_role = (claims.get("role") or "").lower().strip()

    # Base queries - tenant isolated
    base_join = select(TravelRequest).join(Employee).where(Employee.company_id == company_id)

    # Employee only sees their own stats
    if user_role == RoleEnum.EMPLOYEE.value:
        current_employee = await _get_current_employee_id(claims, db)
        base_join = base_join.where(TravelRequest.employee_id == current_employee)

    # Total count
    total_stmt = select(func.count()).select_from(base_join.subquery())
    total_res = await db.execute(total_stmt)
    total = total_res.scalar() or 0

    # Pending approval count
    pending_stmt = select(func.count()).select_from(
        base_join.where(~TravelRequest.status.in_(["approved", "rejected", "draft", "cancelled"])).subquery()
    )
    pending_res = await db.execute(pending_stmt)
    pending = pending_res.scalar() or 0

    # Approved count
    approved_stmt = select(func.count()).select_from(
        base_join.where(TravelRequest.status == "approved").subquery()
    )
    approved_res = await db.execute(approved_stmt)
    approved = approved_res.scalar() or 0

    # Budget sum for approved
    budget_stmt = select(func.sum(TravelRequest.budget)).select_from(
        base_join.where(TravelRequest.status == "approved").subquery()
    )
    budget_res = await db.execute(budget_stmt)
    budget = float(budget_res.scalar() or 0.0)

    data = TravelStatsResponse(
        total=total,
        pending=pending,
        approved=approved,
        budget=budget
    )
    return APIResponse[TravelStatsResponse](
        success=True,
        message="Travel statistics retrieved successfully.",
        data=data
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[TravelRequestResponse],
    summary="Create a new travel request"
)
async def create_travel_request(
    body: TravelRequestCreate,
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    current_employee: Employee = Depends(get_current_employee),
) -> APIResponse[TravelRequestResponse]:
    company_id = current_employee.company_id

    # Validate travel type
    if body.type not in ("domestic", "international"):
        raise HTTPException(status_code=400, detail="Travel type must be 'domestic' or 'international'.")

    # Validate dates
    if body.travel_date > body.return_date:
        raise HTTPException(status_code=400, detail="Travel date cannot be after return date.")
    if body.travel_date < date.today():
        raise HTTPException(status_code=400, detail="Travel date cannot be in the past.")

    # Validate budget
    if body.budget < 0:
        raise HTTPException(status_code=400, detail="Budget cannot be negative.")

    # Employee can only create for themselves
    db_travel = TravelRequest(
        employee_id=current_employee.id,
        type=body.type,
        purpose=body.purpose,
        destination=body.destination,
        travel_date=body.travel_date,
        return_date=body.return_date,
        budget=body.budget,
        currency=body.currency,
        hotel=body.hotel,
        transportation=body.transportation,
        status="draft",
        history=[{
            "stage": "draft",
            "at": datetime.now().isoformat(),
            "actor_id": str(current_employee.id),
            "actor_name": f"{current_employee.first_name} {current_employee.last_name}",
            "note": "Created travel request"
        }]
    )

    db.add(db_travel)
    await db.commit()

    # Eager load the employee relationship
    stmt = select(TravelRequest).options(
        selectinload(TravelRequest.employee)
    ).where(TravelRequest.id == db_travel.id)

    res = await db.execute(stmt)
    refreshed_travel = res.scalar_one()

    return APIResponse[TravelRequestResponse](
        success=True,
        message="Travel request created successfully.",
        data=TravelRequestResponse.from_orm_model(refreshed_travel)
    )


@router.put(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[TravelRequestResponse],
    summary="Update travel request details (only allowed in draft or rejected state)"
)
async def update_travel_request(
    id: uuid.UUID,
    body: TravelRequestUpdate,
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    current_employee: Employee = Depends(get_current_employee),
    current_company: Employee = Depends(get_current_company),
) -> APIResponse[TravelRequestResponse]:
    company_id = current_company.company_id

    # Fetch with tenant isolation
    stmt = select(TravelRequest).join(Employee).where(
        and_(
            TravelRequest.id == id,
            Employee.company_id == company_id
        )
    ).options(selectinload(TravelRequest.employee))
    res = await db.execute(stmt)
    travel = res.scalar_one_or_none()
    if not travel:
        raise HTTPException(status_code=404, detail="Travel request not found.")

    # Authorization: Only owner can update in draft/rejected state
    if travel.employee_id != current_employee.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this travel request.")

    # Only allow updates in editable states
    if travel.status not in ("draft", "rejected", "cancelled"):
        raise HTTPException(status_code=403, detail=f"Cannot update travel request in '{travel.status}' state.")

    # Validate and apply updates
    if body.type is not None:
        if body.type not in ("domestic", "international"):
            raise HTTPException(status_code=400, detail="Travel type must be 'domestic' or 'international'.")
        travel.type = body.type
    if body.purpose is not None:
        travel.purpose = body.purpose
    if body.destination is not None:
        travel.destination = body.destination
    if body.travel_date is not None:
        travel.travel_date = body.travel_date
    if body.return_date is not None:
        travel.return_date = body.return_date
    if body.budget is not None:
        if body.budget < 0:
            raise HTTPException(status_code=400, detail="Budget cannot be negative.")
        travel.budget = body.budget
    if body.currency is not None:
        travel.currency = body.currency
    if body.hotel is not None:
        travel.hotel = body.hotel
    if body.transportation is not None:
        travel.transportation = body.transportation

    # Validate dates
    if travel.travel_date > travel.return_date:
        raise HTTPException(status_code=400, detail="Travel date cannot be after return date.")
    if travel.travel_date < date.today() and travel.status == "draft":
        raise HTTPException(status_code=400, detail="Travel date cannot be in the past for draft requests.")

    await db.commit()

    # Reload with employee
    stmt = select(TravelRequest).options(
        selectinload(TravelRequest.employee)
    ).where(TravelRequest.id == id)
    res = await db.execute(stmt)
    refreshed_travel = res.scalar_one()

    return APIResponse[TravelRequestResponse](
        success=True,
        message="Travel request updated successfully.",
        data=TravelRequestResponse.from_orm_model(refreshed_travel)
    )


@router.post(
    "/{id}/advance",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[TravelRequestResponse],
    summary="Advance travel request to the next workflow stage"
)
async def advance_travel_request(
    id: uuid.UUID,
    body: AdvanceRequest,
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    current_employee: Employee = Depends(get_current_employee),
    current_company: Employee = Depends(get_current_company),
) -> APIResponse[TravelRequestResponse]:
    company_id = current_company.company_id
    user_role = (claims.get("role") or "").lower().strip()

    # Fetch with tenant isolation
    stmt = select(TravelRequest).join(Employee).where(
        and_(
            TravelRequest.id == id,
            Employee.company_id == company_id
        )
    ).options(selectinload(TravelRequest.employee))
    res = await db.execute(stmt)
    travel = res.scalar_one_or_none()
    if not travel:
        raise HTTPException(status_code=404, detail="Travel request not found.")

    # Prevent self-approval
    if travel.employee_id == current_employee.id:
        raise HTTPException(status_code=403, detail="Cannot approve or advance your own travel request.")

    # Validate status transition
    if not _validate_travel_status_transition(travel.status, body.stage):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status transition from '{travel.status}' to '{body.stage}'."
        )

    # Validate approver authority for the target stage
    if body.stage in ("manager-review", "hr-review", "finance-review", "approved", "rejected"):
        if not _validate_approver_authority(user_role, body.stage):
            raise HTTPException(
                status_code=403,
                detail=f"Role '{user_role}' does not have authority to advance to '{body.stage}'."
            )

        # Additional check for manager-review: must be manager of the employee
        if body.stage == "manager-review":
            is_manager = await _check_reporting_relationship(db, current_employee.id, travel.employee_id)
            if not is_manager and user_role not in (RoleEnum.HR_ADMIN.value, RoleEnum.EXECUTIVE.value):
                raise HTTPException(
                    status_code=403,
                    detail="Only the reporting manager, HR Admin, or Executive can advance to manager-review."
                )

    # Apply transition
    travel.status = body.stage
    hist = list(travel.history or [])
    hist.append({
        "stage": body.stage,
        "at": datetime.now().isoformat(),
        "actor_id": str(current_employee.id),
        "actor_name": f"{current_employee.first_name} {current_employee.last_name}",
        "actor_role": user_role,
        "note": body.note or f"Advanced to {body.stage}"
    })
    travel.history = hist

    await db.commit()

    # Reload with employee
    stmt = select(TravelRequest).options(
        selectinload(TravelRequest.employee)
    ).where(TravelRequest.id == id)
    res = await db.execute(stmt)
    refreshed_travel = res.scalar_one()

    return APIResponse[TravelRequestResponse](
        success=True,
        message=f"Travel request advanced to {body.stage}.",
        data=TravelRequestResponse.from_orm_model(refreshed_travel)
    )


@router.delete(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Delete a travel request (only allowed in draft state by owner)"
)
async def delete_travel_request(
    id: uuid.UUID,
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    current_employee: Employee = Depends(get_current_employee),
    current_company: Employee = Depends(get_current_company),
) -> APIResponse[None]:
    company_id = current_company.company_id

    # Fetch with tenant isolation
    stmt = select(TravelRequest).join(Employee).where(
        and_(
            TravelRequest.id == id,
            Employee.company_id == company_id
        )
    )
    res = await db.execute(stmt)
    travel = res.scalar_one_or_none()
    if not travel:
        raise HTTPException(status_code=404, detail="Travel request not found.")

    # Authorization: Only owner can delete in draft state
    if travel.employee_id != current_employee.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this travel request.")

    if travel.status != "draft":
        raise HTTPException(status_code=403, detail="Only draft travel requests can be deleted.")

    await db.delete(travel)
    await db.commit()

    return APIResponse[None](
        success=True,
        message="Travel request deleted successfully.",
        data=None
    )