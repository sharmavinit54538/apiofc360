"""Pydantic schemas for Performance Core Module."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class GoalCreateRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    employee_id: UUID
    # inferred field — confirm with product/spec owner
    title: str = Field(..., description="Goal title / objective")
    # inferred field — confirm with product/spec owner
    description: Optional[str] = None
    # inferred field — confirm with product/spec owner
    target_value: float = Field(100.0, description="Target numeric value / 100%")
    # inferred field — confirm with product/spec owner
    due_date: Optional[date] = None
    # inferred field — confirm with product/spec owner
    status: str = Field("IN_PROGRESS", description="NOT_STARTED | IN_PROGRESS | COMPLETED | MISSED")


class GoalUpdateRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    title: Optional[str] = None
    # inferred field — confirm with product/spec owner
    description: Optional[str] = None
    # inferred field — confirm with product/spec owner
    target_value: Optional[float] = None
    # inferred field — confirm with product/spec owner
    current_value: Optional[float] = None
    # inferred field — confirm with product/spec owner
    due_date: Optional[date] = None
    # inferred field — confirm with product/spec owner
    status: Optional[str] = None


class ReviewCreateRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    employee_id: UUID
    # inferred field — confirm with product/spec owner
    cycle_id: Optional[UUID] = None
    # inferred field — confirm with product/spec owner
    reviewer_id: Optional[UUID] = None
    # inferred field — confirm with product/spec owner
    self_rating: Optional[float] = None
    # inferred field — confirm with product/spec owner
    reviewer_rating: Optional[float] = None
    # inferred field — confirm with product/spec owner
    comments: Optional[str] = None
    # inferred field — confirm with product/spec owner
    status: str = Field("DRAFT", description="DRAFT | SUBMITTED | ACKNOWLEDGED")


class ReviewUpdateRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    reviewer_rating: Optional[float] = None
    # inferred field — confirm with product/spec owner
    self_rating: Optional[float] = None
    # inferred field — confirm with product/spec owner
    comments: Optional[str] = None
    # inferred field — confirm with product/spec owner
    status: Optional[str] = None
    # inferred field — confirm with product/spec owner
    promotion_recommendation: Optional[bool] = None
    # inferred field — confirm with product/spec owner
    salary_increment_percentage: Optional[float] = None


class KPICreateRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    name: str = Field(..., description="KPI name e.g. Customer Satisfaction Score")
    # inferred field — confirm with product/spec owner
    goal_id: Optional[UUID] = None
    # inferred field — confirm with product/spec owner
    weightage: float = Field(20.0, description="Percentage weight out of 100")
    # inferred field — confirm with product/spec owner
    target_value: float = Field(100.0)
    # inferred field — confirm with product/spec owner
    actual_value: float = Field(0.0)
    # inferred field — confirm with product/spec owner
    unit: str = Field("%", description="%, count, score, currency")


class GoalResponse(BaseModel):
    id: str
    employee_id: str
    title: str
    description: Optional[str] = None
    target_value: Optional[float] = None
    current_value: Optional[float] = None
    due_date: Optional[str] = None
    status: str
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class ReviewResponse(BaseModel):
    id: str
    employee_id: str
    reviewer_id: Optional[str] = None
    self_rating: Optional[float] = None
    reviewer_rating: Optional[float] = None
    status: str
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class KPIResponse(BaseModel):
    id: str
    name: str
    goal_id: Optional[str] = None
    weightage: float
    target_value: float
    actual_value: float
    unit: str
    status: str

    class Config:
        from_attributes = True
