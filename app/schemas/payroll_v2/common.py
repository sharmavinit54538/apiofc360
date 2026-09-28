"""Base and common schemas for Payroll module."""

from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar
from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class PayrollBaseModel(BaseModel):
    """Base Pydantic model with camelCase and snake_case population support."""
    model_config = ConfigDict(
        populate_by_name=True,
        from_attributes=True,
        arbitrary_types_allowed=True,
    )


class GenericResponse(PayrollBaseModel, Generic[T]):
    success: bool = True
    data: Optional[T] = None
    message: str = "Operation successful"
    error: Optional[str] = None
