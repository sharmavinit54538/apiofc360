"""FastAPI router for Travel Request Management."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, Query, status, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.rbac import require_employee_or_above
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.employee import Employee
from app.models.travel import TravelRequest
from app.schemas.auth import APIResponse

router = APIRouter(
    prefix="/travel",
    tags=["Travel Management"],
    dependencies=[Depends(require_employee_or_above)],
)

# ---------------- Pydantic Schemas ----------------
class TravelRequestCreate(BaseModel):
    employee_id: uuid.UUID
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
    status: Optional[str] = None

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
    db: AsyncSession = Depends(get_db_session)
) -> APIResponse[List[TravelRequestResponse]]:
    stmt = select(TravelRequest).join(Employee).options(selectinload(TravelRequest.employee))
    
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
    db: AsyncSession = Depends(get_db_session)
) -> APIResponse[TravelStatsResponse]:
    # Total count
    total_stmt = select(func.count(TravelRequest.id)).join(Employee)
    total_res = await db.execute(total_stmt)
    total = total_res.scalar() or 0
    
    # Pending approval count
    pending_stmt = select(func.count(TravelRequest.id)).join(Employee).where(
        ~TravelRequest.status.in_(["approved", "rejected", "draft"])
    )
    pending_res = await db.execute(pending_stmt)
    pending = pending_res.scalar() or 0
    
    # Approved count
    approved_stmt = select(func.count(TravelRequest.id)).join(Employee).where(
        TravelRequest.status == "approved"
    )
    approved_res = await db.execute(approved_stmt)
    approved = approved_res.scalar() or 0
    
    # Budget sum for approved
    budget_stmt = select(func.sum(TravelRequest.budget)).join(Employee).where(
        TravelRequest.status == "approved"
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
    db: AsyncSession = Depends(get_db_session)
) -> APIResponse[TravelRequestResponse]:
    # Verify employee exists
    emp_res = await db.execute(select(Employee).where(Employee.id == body.employee_id))
    employee = emp_res.scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee profile not found.")
        
    db_travel = TravelRequest(
        employee_id=body.employee_id,
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
    summary="Update travel request details"
)
async def update_travel_request(
    id: uuid.UUID,
    body: TravelRequestUpdate,
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session)
) -> APIResponse[TravelRequestResponse]:
    stmt = select(TravelRequest).where(TravelRequest.id == id)
    res = await db.execute(stmt)
    travel = res.scalar_one_or_none()
    if not travel:
        raise HTTPException(status_code=404, detail="Travel request not found.")
        
    if body.type is not None: travel.type = body.type
    if body.purpose is not None: travel.purpose = body.purpose
    if body.destination is not None: travel.destination = body.destination
    if body.travel_date is not None: travel.travel_date = body.travel_date
    if body.return_date is not None: travel.return_date = body.return_date
    if body.budget is not None: travel.budget = body.budget
    if body.currency is not None: travel.currency = body.currency
    if body.hotel is not None: travel.hotel = body.hotel
    if body.transportation is not None: travel.transportation = body.transportation
    
    if body.status is not None:
        travel.status = body.status
        hist = list(travel.history or [])
        hist.append({
            "stage": body.status,
            "at": datetime.now().isoformat(),
            "note": "Updated request state"
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
    db: AsyncSession = Depends(get_db_session)
) -> APIResponse[TravelRequestResponse]:
    stmt = select(TravelRequest).where(TravelRequest.id == id)
    res = await db.execute(stmt)
    travel = res.scalar_one_or_none()
    if not travel:
        raise HTTPException(status_code=404, detail="Travel request not found.")
        
    travel.status = body.stage
    hist = list(travel.history or [])
    hist.append({
        "stage": body.stage,
        "at": datetime.now().isoformat(),
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
    summary="Delete a travel request"
)
async def delete_travel_request(
    id: uuid.UUID,
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session)
) -> APIResponse[None]:
    stmt = select(TravelRequest).where(TravelRequest.id == id)
    res = await db.execute(stmt)
    travel = res.scalar_one_or_none()
    if not travel:
        raise HTTPException(status_code=404, detail="Travel request not found.")
        
    await db.delete(travel)
    await db.commit()
    
    return APIResponse[None](
        success=True,
        message="Travel request deleted successfully.",
        data=None
    )
