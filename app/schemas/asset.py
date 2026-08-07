"""Pydantic schemas for Asset Management."""

from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
import uuid
from pydantic import BaseModel, ConfigDict, Field, model_validator


class AssetAssignmentHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    employee: str = Field(..., serialization_alias="employee")
    department: str
    assignDate: date = Field(..., serialization_alias="assignDate")
    expectedReturnDate: date | None = Field(None, serialization_alias="expectedReturnDate")
    actualReturnDate: date | None = Field(None, serialization_alias="actualReturnDate")
    notes: str | None = None

    @model_validator(mode="before")
    @classmethod
    def map_aliases_before(cls, data: any) -> any:
        if hasattr(data, "employee_name"):
            data.employee = data.employee_name
        if hasattr(data, "assign_date"):
            data.assignDate = data.assign_date
        if hasattr(data, "expected_return_date"):
            data.expectedReturnDate = data.expected_return_date
        if hasattr(data, "actual_return_date"):
            data.actualReturnDate = data.actual_return_date
        return data


class AssetMaintenanceRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    requestDate: date = Field(..., serialization_alias="requestDate")
    serviceDate: date | None = Field(None, serialization_alias="serviceDate")
    vendor: str
    cost: float
    notes: str | None = None

    @model_validator(mode="before")
    @classmethod
    def map_aliases_before(cls, data: any) -> any:
        if hasattr(data, "request_date"):
            data.requestDate = data.request_date
        if hasattr(data, "service_date"):
            data.serviceDate = data.service_date
        return data


class AssetTimelineEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    event: str
    performedBy: str = Field(..., serialization_alias="performedBy")
    timestamp: datetime
    notes: str | None = None

    @model_validator(mode="before")
    @classmethod
    def map_aliases_before(cls, data: any) -> any:
        if isinstance(data, dict):
            if "performed_by" in data:
                data["performedBy"] = data["performed_by"]
            elif "performedBy" in data:
                data["performed_by"] = data["performedBy"]
        else:
            if hasattr(data, "performed_by"):
                setattr(data, "performedBy", getattr(data, "performed_by"))
        return data


class AssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    tag: str
    name: str
    category: str
    serial: str | None = None
    vendor: str | None = None
    purchaseDate: date | None = Field(None, serialization_alias="purchaseDate")
    warrantyUntil: date | None = Field(None, serialization_alias="warrantyUntil")
    status: str
    assignedTo: str | None = Field(None, serialization_alias="assignedTo")
    assignedAt: datetime | None = Field(None, serialization_alias="assignedAt")
    nextMaintenance: date | None = Field(None, serialization_alias="nextMaintenance")
    notes: str | None = None
    brand: str | None = None
    model: str | None = None
    purchaseCost: float | None = Field(None, serialization_alias="purchaseCost")
    repairCost: float | None = Field(0.0, serialization_alias="repairCost")
    location: str | None = None
    description: str | None = None
    imageUrl: str | None = Field(None, serialization_alias="imageUrl")
    
    assignmentHistory: list[AssetAssignmentHistoryResponse] = Field([], serialization_alias="assignmentHistory")
    maintenanceHistory: list[AssetMaintenanceRecordResponse] = Field([], serialization_alias="maintenanceHistory")
    timeline: list[AssetTimelineEventResponse] = Field([])
    qrCodeData: str | None = Field(None, serialization_alias="qrCodeData")

    @model_validator(mode="before")
    @classmethod
    def populate_custom_fields(cls, data: any) -> any:
        if hasattr(data, "purchase_date"):
            data.purchaseDate = data.purchase_date
        if hasattr(data, "warranty_until"):
            data.warrantyUntil = data.warranty_until
        if hasattr(data, "assigned_at"):
            data.assignedAt = data.assigned_at
        if hasattr(data, "next_maintenance"):
            data.nextMaintenance = data.next_maintenance
        if hasattr(data, "purchase_cost"):
            data.purchaseCost = float(data.purchase_cost) if data.purchase_cost is not None else None
        if hasattr(data, "image_url"):
            data.imageUrl = data.image_url
            
        # Map relationship fields only if they are already loaded to avoid MissingGreenlet
        from sqlalchemy.orm.attributes import instance_state
        
        is_orm = True
        try:
            state = instance_state(data)
        except Exception:
            is_orm = False

        if is_orm:
            if "assignment_history" in state.dict:
                data.assignmentHistory = data.assignment_history
            else:
                data.assignmentHistory = []

            if "maintenance_history" in state.dict:
                data.maintenanceHistory = data.maintenance_history
                data.repairCost = sum(float(record.cost) for record in data.maintenance_history if record.cost is not None)
            else:
                data.maintenanceHistory = []
                data.repairCost = 0.0

            if "employee" in state.dict and data.employee:
                data.assignedTo = f"{data.employee.first_name} {data.employee.last_name}"
            else:
                data.assignedTo = None
        else:
            if hasattr(data, "assignment_history"):
                data.assignmentHistory = data.assignment_history
            else:
                data.assignmentHistory = []

            if hasattr(data, "maintenance_history"):
                data.maintenanceHistory = data.maintenance_history
                data.repairCost = sum(float(record.cost) for record in data.maintenance_history if record.cost is not None)
            else:
                data.maintenanceHistory = []
                data.repairCost = 0.0

            if hasattr(data, "employee") and data.employee:
                data.assignedTo = f"{data.employee.first_name} {data.employee.last_name}"
            else:
                data.assignedTo = None

        # Generate backend QR code data URI
        try:
            from app.core.config import settings
            import qrcode
            import qrcode.image.svg
            import io
            import base64

            # QR encodes the scannable URL
            qr_content = f"{settings.FRONTEND_BASE_URL}/dashboard/assets?scan={data.id}"
            factory = qrcode.image.svg.SvgImage
            img = qrcode.make(qr_content, image_factory=factory)
            
            stream = io.BytesIO()
            img.save(stream)
            svg_bytes = stream.getvalue()
            
            base64_svg = base64.b64encode(svg_bytes).decode("utf-8")
            data.qrCodeData = f"data:image/svg+xml;base64,{base64_svg}"
        except Exception:
            data.qrCodeData = None

        return data


class AssetCreate(BaseModel):
    tag: str
    name: str
    category: str
    serial: str | None = None
    vendor: str | None = None
    purchase_date: date | None = None
    warranty_until: date | None = None
    brand: str | None = None
    model: str | None = None
    purchase_cost: Decimal | None = None
    location: str | None = None
    notes: str | None = None
    description: str | None = None
    image_url: str | None = None  # Cloudinary image URL


class AssetUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    serial: str | None = None
    vendor: str | None = None
    purchase_date: date | None = None
    warranty_until: date | None = None
    brand: str | None = None
    model: str | None = None
    purchase_cost: Decimal | None = None
    location: str | None = None
    notes: str | None = None
    description: str | None = None
    status: str | None = None
    image_url: str | None = None  # Cloudinary image URL


class AssetAssignRequest(BaseModel):
    employee_name: str
    department: str
    expected_return_date: date | None = None
    notes: str | None = None


class AssetMaintenanceCreate(BaseModel):
    request_date: date | None = None
    vendor: str
    cost: Decimal = Decimal("0.0")
    notes: str | None = None


class CategoryCount(BaseModel):
    name: str
    value: int


class StatusCount(BaseModel):
    name: str
    value: int


class AssetAnalyticsResponse(BaseModel):
    total_assets: int
    available_assets: int
    assigned_assets: int
    under_repair_assets: int
    lost_assets: int
    expiring_warranty_assets: int
    category_distribution: list[CategoryCount]
    status_distribution: list[StatusCount]
    total_valuation: float
    repair_costs_by_category: list[dict]


class AssetListResponse(BaseModel):
    items: list[AssetResponse]
    total: int
    page: int
    limit: int


class AssetFilterOptionsResponse(BaseModel):
    vendors: list[str]
    locations: list[str]
    departments: list[str]

