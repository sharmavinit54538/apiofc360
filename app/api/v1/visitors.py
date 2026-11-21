"""Visitors Management API v1."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, status, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse

router = APIRouter(prefix="/visitors", tags=["Visitors Management"])


class VisitorBase(BaseModel):
    model_config = {"extra": "forbid", "str_strip_whitespace": True}


class VisitorCreate(VisitorBase):
    name: str = Field(min_length=1, max_length=200)
    contact: str = Field(min_length=1, max_length=100)
    purpose: str = Field(min_length=1, max_length=1000)
    host_employee_id: uuid.UUID
    scheduled_at: datetime
    organization: str | None = Field(default=None, max_length=200)
    vehicle_number: str | None = Field(default=None, max_length=50)
    id_proof_type: str | None = Field(default=None, max_length=50)
    id_proof_number: str | None = Field(default=None, max_length=100)


class VisitorUpdate(VisitorBase):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    contact: str | None = Field(default=None, min_length=1, max_length=100)
    purpose: str | None = Field(default=None, min_length=1, max_length=1000)
    host_employee_id: uuid.UUID | None = None
    scheduled_at: datetime | None = None
    organization: str | None = Field(default=None, max_length=200)
    vehicle_number: str | None = Field(default=None, max_length=50)
    id_proof_type: str | None = Field(default=None, max_length=50)
    id_proof_number: str | None = Field(default=None, max_length=100)


class VisitorResponse(VisitorBase):
    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    contact: str
    purpose: str
    host_employee_id: uuid.UUID
    host_employee_name: str | None = None
    scheduled_at: datetime
    organization: str | None
    vehicle_number: str | None
    id_proof_type: str | None
    id_proof_number: str | None
    status: str  # scheduled, checked_in, checked_out, cancelled
    checked_in_at: datetime | None = None
    checked_out_at: datetime | None = None
    checked_in_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class VisitorPage(BaseModel):
    items: list[VisitorResponse]
    total: int
    page: int
    limit: int
    pages: int
    has_next: bool
    has_previous: bool


class VisitorCheckInResponse(VisitorBase):
    id: uuid.UUID
    visitor_id: uuid.UUID
    visitor_name: str
    checked_in_at: datetime
    checked_in_by: uuid.UUID
    host_employee_name: str


async def _get_company_id(claims: dict) -> uuid.UUID:
    company_id_str = claims.get("company_id")
    if not company_id_str:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Company context missing")
    return uuid.UUID(company_id_str)


async def _get_user_id(claims: dict) -> uuid.UUID:
    user_id_str = claims.get("sub")
    if not user_id_str:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Invalid user claims")
    return uuid.UUID(user_id_str)


# ── Models (inline for now - should be in models/visitor.py) ──────────────────

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class Visitor(Base):
    __tablename__ = "visitors"
    __table_args__ = (
        Index("ix_visitors_company_status", "company_id", "status"),
        Index("ix_visitors_host_employee", "host_employee_id"),
        Index("ix_visitors_scheduled_at", "scheduled_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact: Mapped[str] = mapped_column(String(100), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    host_employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    organization: Mapped[str | None] = mapped_column(String(200), nullable=True)
    vehicle_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    id_proof_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    id_proof_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="scheduled")  # scheduled, checked_in, checked_out, cancelled
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checked_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checked_in_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    checked_out_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    host_employee: Mapped["Employee"] = relationship("Employee", lazy="select")


# Import func for the model
from sqlalchemy import func


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[VisitorPage],
    summary="List visitors with pagination and filters",
)
async def list_visitors(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status", description="Filter by status"),
    host_employee_id: uuid.UUID | None = Query(None, description="Filter by host employee"),
    date_from: str | None = Query(None, description="Filter from date (YYYY-MM-DD)"),
    date_to: str | None = Query(None, description="Filter to date (YYYY-MM-DD)"),
    search: str | None = Query(None, description="Search in name, contact, purpose"),
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[VisitorPage]:
    """List visitors with pagination and filters. Organization-scoped."""
    company_id = await _get_company_id(claims)

    stmt = select(Visitor).where(Visitor.company_id == company_id)

    if status_filter:
        stmt = stmt.where(Visitor.status == status_filter)
    if host_employee_id:
        stmt = stmt.where(Visitor.host_employee_id == host_employee_id)
    if date_from:
        from datetime import date
        stmt = stmt.where(Visitor.scheduled_at >= date.fromisoformat(date_from))
    if date_to:
        from datetime import date
        stmt = stmt.where(Visitor.scheduled_at <= date.fromisoformat(date_to))
    if search:
        term = f"%{search}%"
        stmt = stmt.where(
            Visitor.name.ilike(term) |
            Visitor.contact.ilike(term) |
            Visitor.purpose.ilike(term) |
            Visitor.organization.ilike(term)
        )

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

    stmt = stmt.order_by(desc(Visitor.scheduled_at)).offset((page - 1) * limit).limit(limit)
    result = await db.execute(stmt)
    visitors = result.scalars().all()

    # Get host employee names
    host_ids = {v.host_employee_id for v in visitors}
    host_names = {}
    if host_ids:
        from app.models.employee import Employee
        host_stmt = select(Employee).where(Employee.id.in_(host_ids))
        host_res = await db.execute(host_stmt)
        for h in host_res.scalars().all():
            host_names[h.id] = f"{h.first_name} {h.last_name}".strip()

    items = []
    for v in visitors:
        items.append(VisitorResponse(
            id=v.id,
            company_id=v.company_id,
            name=v.name,
            contact=v.contact,
            purpose=v.purpose,
            host_employee_id=v.host_employee_id,
            host_employee_name=host_names.get(v.host_employee_id),
            scheduled_at=v.scheduled_at,
            organization=v.organization,
            vehicle_number=v.vehicle_number,
            id_proof_type=v.id_proof_type,
            id_proof_number=v.id_proof_number,
            status=v.status,
            checked_in_at=v.checked_in_at,
            checked_out_at=v.checked_out_at,
            checked_in_by=v.checked_in_by,
            created_at=v.created_at,
            updated_at=v.updated_at,
        ))

    pages = (total + limit - 1) // limit if limit > 0 else 1
    return APIResponse[VisitorPage](
        success=True,
        message="Visitors retrieved successfully.",
        data=VisitorPage(
            items=items,
            total=total,
            page=page,
            limit=limit,
            pages=pages,
            has_next=page < pages,
            has_previous=page > 1,
        ),
        errors=None,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[VisitorResponse],
    summary="Register a new visitor",
)
async def create_visitor(
    payload: VisitorCreate,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[VisitorResponse]:
    """Register a new visitor. Requires host employee validation."""
    company_id = await _get_company_id(claims)
    user_id = await _get_user_id(claims)

    # Validate host employee exists and belongs to company
    from app.models.employee import Employee
    host_stmt = select(Employee).where(
        Employee.id == payload.host_employee_id,
        Employee.company_id == company_id,
        Employee.is_deleted == False,
    )
    host_res = await db.execute(host_stmt)
    host = host_res.scalar_one_or_none()
    if not host:
        raise HTTPException(status_code=404, detail="Host employee not found")

    # Check for duplicate active check-in for same visitor
    existing_stmt = select(Visitor).where(
        Visitor.company_id == company_id,
        Visitor.contact == payload.contact,
        Visitor.status.in_(["scheduled", "checked_in"]),
    )
    existing_res = await db.execute(existing_stmt)
    if existing_res.scalars().first():
        raise HTTPException(status_code=409, detail="Visitor with this contact already has an active visit")

    visitor = Visitor(
        id=uuid.uuid4(),
        company_id=company_id,
        name=payload.name,
        contact=payload.contact,
        purpose=payload.purpose,
        host_employee_id=payload.host_employee_id,
        scheduled_at=payload.scheduled_at,
        organization=payload.organization,
        vehicle_number=payload.vehicle_number,
        id_proof_type=payload.id_proof_type,
        id_proof_number=payload.id_proof_number,
        status="scheduled",
    )
    db.add(visitor)
    await db.commit()
    await db.refresh(visitor)

    return APIResponse[VisitorResponse](
        success=True,
        message="Visitor registered successfully.",
        data=VisitorResponse(
            id=visitor.id,
            company_id=visitor.company_id,
            name=visitor.name,
            contact=visitor.contact,
            purpose=visitor.purpose,
            host_employee_id=visitor.host_employee_id,
            host_employee_name=f"{host.first_name} {host.last_name}".strip(),
            scheduled_at=visitor.scheduled_at,
            organization=visitor.organization,
            vehicle_number=visitor.vehicle_number,
            id_proof_type=visitor.id_proof_type,
            id_proof_number=visitor.id_proof_number,
            status=visitor.status,
            checked_in_at=visitor.checked_in_at,
            checked_out_at=visitor.checked_out_at,
            checked_in_by=visitor.checked_in_by,
            created_at=visitor.created_at,
            updated_at=visitor.updated_at,
        ),
        errors=None,
    )


@router.get(
    "/{visitor_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[VisitorResponse],
    summary="Get visitor by ID",
)
async def get_visitor(
    visitor_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[VisitorResponse]:
    """Get visitor details by ID."""
    company_id = await _get_company_id(claims)

    stmt = select(Visitor).where(
        Visitor.id == visitor_id,
        Visitor.company_id == company_id,
    )
    result = await db.execute(stmt)
    visitor = result.scalar_one_or_none()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")

    # Get host name
    from app.models.employee import Employee
    host_stmt = select(Employee).where(Employee.id == visitor.host_employee_id)
    host_res = await db.execute(host_stmt)
    host = host_res.scalar_one_or_none()

    return APIResponse[VisitorResponse](
        success=True,
        message="Visitor retrieved successfully.",
        data=VisitorResponse(
            id=visitor.id,
            company_id=visitor.company_id,
            name=visitor.name,
            contact=visitor.contact,
            purpose=visitor.purpose,
            host_employee_id=visitor.host_employee_id,
            host_employee_name=f"{host.first_name} {host.last_name}".strip() if host else None,
            scheduled_at=visitor.scheduled_at,
            organization=visitor.organization,
            vehicle_number=visitor.vehicle_number,
            id_proof_type=visitor.id_proof_type,
            id_proof_number=visitor.id_proof_number,
            status=visitor.status,
            checked_in_at=visitor.checked_in_at,
            checked_out_at=visitor.checked_out_at,
            checked_in_by=visitor.checked_in_by,
            created_at=visitor.created_at,
            updated_at=visitor.updated_at,
        ),
        errors=None,
    )


@router.patch(
    "/{visitor_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[VisitorResponse],
    summary="Update visitor details",
)
async def update_visitor(
    visitor_id: uuid.UUID,
    payload: VisitorUpdate,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[VisitorResponse]:
    """Update visitor details (only scheduled visitors can be updated)."""
    company_id = await _get_company_id(claims)

    stmt = select(Visitor).where(
        Visitor.id == visitor_id,
        Visitor.company_id == company_id,
    )
    result = await db.execute(stmt)
    visitor = result.scalar_one_or_none()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")

    if visitor.status != "scheduled":
        raise HTTPException(status_code=409, detail="Only scheduled visitors can be updated")

    changes = payload.model_dump(exclude_unset=True)
    if "host_employee_id" in changes:
        from app.models.employee import Employee
        host_stmt = select(Employee).where(
            Employee.id == changes["host_employee_id"],
            Employee.company_id == company_id,
            Employee.is_deleted == False,
        )
        host_res = await db.execute(host_stmt)
        if not host_res.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Host employee not found")

    for key, value in changes.items():
        setattr(visitor, key, value)

    visitor.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(visitor)

    # Get host name
    from app.models.employee import Employee
    host_stmt = select(Employee).where(Employee.id == visitor.host_employee_id)
    host_res = await db.execute(host_stmt)
    host = host_res.scalar_one_or_none()

    return APIResponse[VisitorResponse](
        success=True,
        message="Visitor updated successfully.",
        data=VisitorResponse(
            id=visitor.id,
            company_id=visitor.company_id,
            name=visitor.name,
            contact=visitor.contact,
            purpose=visitor.purpose,
            host_employee_id=visitor.host_employee_id,
            host_employee_name=f"{host.first_name} {host.last_name}".strip() if host else None,
            scheduled_at=visitor.scheduled_at,
            organization=visitor.organization,
            vehicle_number=visitor.vehicle_number,
            id_proof_type=visitor.id_proof_type,
            id_proof_number=visitor.id_proof_number,
            status=visitor.status,
            checked_in_at=visitor.checked_in_at,
            checked_out_at=visitor.checked_out_at,
            checked_in_by=visitor.checked_in_by,
            created_at=visitor.created_at,
            updated_at=visitor.updated_at,
        ),
        errors=None,
    )


@router.delete(
    "/{visitor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Cancel/Delete a visitor",
)
async def delete_visitor(
    visitor_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> Response:
    """Cancel a scheduled visitor or delete checked-out visitor."""
    company_id = await _get_company_id(claims)

    stmt = select(Visitor).where(
        Visitor.id == visitor_id,
        Visitor.company_id == company_id,
    )
    result = await db.execute(stmt)
    visitor = result.scalar_one_or_none()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")

    if visitor.status == "checked_in":
        raise HTTPException(status_code=409, detail="Cannot delete checked-in visitor. Check out first.")

    await db.delete(visitor)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{visitor_id}/check-in",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[VisitorCheckInResponse],
    summary="Check in a visitor",
)
async def check_in_visitor(
    visitor_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[VisitorCheckInResponse]:
    """Check in a scheduled visitor."""
    company_id = await _get_company_id(claims)
    user_id = await _get_user_id(claims)

    stmt = select(Visitor).where(
        Visitor.id == visitor_id,
        Visitor.company_id == company_id,
    )
    result = await db.execute(stmt)
    visitor = result.scalar_one_or_none()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")

    if visitor.status != "scheduled":
        raise HTTPException(status_code=409, detail=f"Visitor cannot be checked in (current status: {visitor.status})")

    visitor.status = "checked_in"
    visitor.checked_in_at = datetime.now(timezone.utc)
    visitor.checked_in_by = user_id
    visitor.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(visitor)

    # Get host name
    from app.models.employee import Employee
    host_stmt = select(Employee).where(Employee.id == visitor.host_employee_id)
    host_res = await db.execute(host_stmt)
    host = host_res.scalar_one_or_none()

    return APIResponse[VisitorCheckInResponse](
        success=True,
        message="Visitor checked in successfully.",
        data=VisitorCheckInResponse(
            id=visitor.id,
            visitor_id=visitor.id,
            visitor_name=visitor.name,
            checked_in_at=visitor.checked_in_at,
            checked_in_by=user_id,
            host_employee_name=f"{host.first_name} {host.last_name}".strip() if host else None,
        ),
        errors=None,
    )


@router.post(
    "/{visitor_id}/check-out",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[VisitorResponse],
    summary="Check out a visitor",
)
async def check_out_visitor(
    visitor_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[VisitorResponse]:
    """Check out a checked-in visitor."""
    company_id = await _get_company_id(claims)
    user_id = await _get_user_id(claims)

    stmt = select(Visitor).where(
        Visitor.id == visitor_id,
        Visitor.company_id == company_id,
    )
    result = await db.execute(stmt)
    visitor = result.scalar_one_or_none()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")

    if visitor.status != "checked_in":
        raise HTTPException(status_code=409, detail=f"Visitor cannot be checked out (current status: {visitor.status})")

    visitor.status = "checked_out"
    visitor.checked_out_at = datetime.now(timezone.utc)
    visitor.checked_out_by = user_id
    visitor.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(visitor)

    # Get host name
    from app.models.employee import Employee
    host_stmt = select(Employee).where(Employee.id == visitor.host_employee_id)
    host_res = await db.execute(host_stmt)
    host = host_res.scalar_one_or_none()

    return APIResponse[VisitorResponse](
        success=True,
        message="Visitor checked out successfully.",
        data=VisitorResponse(
            id=visitor.id,
            company_id=visitor.company_id,
            name=visitor.name,
            contact=visitor.contact,
            purpose=visitor.purpose,
            host_employee_id=visitor.host_employee_id,
            host_employee_name=f"{host.first_name} {host.last_name}".strip() if host else None,
            scheduled_at=visitor.scheduled_at,
            organization=visitor.organization,
            vehicle_number=visitor.vehicle_number,
            id_proof_type=visitor.id_proof_type,
            id_proof_number=visitor.id_proof_number,
            status=visitor.status,
            checked_in_at=visitor.checked_in_at,
            checked_out_at=visitor.checked_out_at,
            checked_in_by=visitor.checked_in_by,
            created_at=visitor.created_at,
            updated_at=visitor.updated_at,
        ),
        errors=None,
    )