"""EmployeeAsset schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EmployeeAssetCreate(BaseModel):
    asset_name: str = Field(..., min_length=1, max_length=150)
    asset_type: str | None = Field(None, max_length=100)
    asset_code: str | None = Field(None, max_length=50)
    assigned_date: date | None = None
    return_date: date | None = None
    condition: str | None = Field(None, max_length=50)
    notes: str | None = None


class EmployeeAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID | None
    asset_name: str
    asset_type: str | None
    asset_code: str | None
    assigned_date: date | None
    return_date: date | None
    condition: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def map_from_asset(cls, data: Any) -> Any:
        if isinstance(data, dict):
            mapped = dict(data)
            mapped["asset_name"] = mapped.get("asset_name") or mapped.get("name")
            mapped["asset_type"] = mapped.get("asset_type") or mapped.get("category")
            mapped["asset_code"] = mapped.get("asset_code") or mapped.get("tag")
            assigned_at = mapped.get("assigned_at")
            mapped["assigned_date"] = mapped.get("assigned_date") or (assigned_at.date() if isinstance(assigned_at, datetime) else assigned_at)
            mapped["return_date"] = mapped.get("return_date")
            mapped["condition"] = mapped.get("condition")
            return mapped

        assigned_at = getattr(data, "assigned_at", None)
        assigned_date = getattr(data, "assigned_date", None)
        if assigned_date is None and isinstance(assigned_at, datetime):
            assigned_date = assigned_at.date()

        return {
            "id": getattr(data, "id", None),
            "employee_id": getattr(data, "employee_id", None),
            "asset_name": getattr(data, "name", None) or getattr(data, "asset_name", None),
            "asset_type": getattr(data, "category", None) or getattr(data, "asset_type", None),
            "asset_code": getattr(data, "tag", None) or getattr(data, "asset_code", None),
            "assigned_date": assigned_date,
            "return_date": getattr(data, "return_date", None),
            "condition": getattr(data, "condition", None),
            "notes": getattr(data, "notes", None),
            "created_at": getattr(data, "created_at", None),
            "updated_at": getattr(data, "updated_at", None),
        }
