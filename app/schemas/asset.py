"""Pydantic schemas for Asset Management."""

from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
import uuid
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Valid asset statuses
VALID_ASSET_STATUSES = {
    "available", "assigned", "under-repair", "maintenance",
    "lost", "retired", "disposed", "archived",
}


def _normalize_whitespace(v: str | None) -> str | None:
    """Strip leading/trailing whitespace and collapse internal whitespace."""
    if v is None:
        return None
    v = v.strip()
    if v == "":
        return None
    return v


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
    status: str
    completion_date: date | None = None
    estimated_cost: Decimal | None = None
    completion_notes: str | None = None

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
    is_deleted: bool = False
    employee_id: uuid.UUID | None = None
    lost_date: date | None = None
    lost_reason: str | None = None
    last_known_holder_id: uuid.UUID | None = None
    
    assignmentHistory: list[AssetAssignmentHistoryResponse] = Field([], serialization_alias="assignmentHistory")
    maintenanceHistory: list[AssetMaintenanceRecordResponse] = Field([], serialization_alias="maintenanceHistory")
    timeline: list[dict] = Field([])
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

            # Check employee relationship - try multiple ways
            employee_obj = None
            if hasattr(data, "employee"):
                employee_obj = data.employee
            elif "employee" in state.dict:
                employee_obj = state.dict["employee"]
            
            if employee_obj:
                data.assignedTo = f"{employee_obj.first_name} {employee_obj.last_name}"
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
        # Note: This is intentionally synchronous since it's pure in-memory computation
        # (no I/O) and runs during response serialization. For large lists, consider
        # caching or generating on demand.
        try:
            from app.core.config import settings
            import qrcode
            import qrcode.image.svg
            import io
            import base64

            # QR encodes the scannable URL
            qr_content = f"{settings.FRONTEND_BASE_URL}/dashboard/assets?scan={data.id}"
            factory = qrcode.image.svg.SvgImage
            img = qrcode.make(qr_content, image_factory=factory, box_size=4)
            
            stream = io.BytesIO()
            img.save(stream)
            svg_bytes = stream.getvalue()
            
            base64_svg = base64.b64encode(svg_bytes).decode("utf-8")
            data.qrCodeData = f"data:image/svg+xml;base64,{base64_svg}"
        except Exception:
            data.qrCodeData = None

        return data


class AssetCreate(BaseModel):
    tag: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    category: str = Field(..., min_length=1, max_length=100)
    serial: str | None = Field(None, max_length=150)
    vendor: str | None = Field(None, max_length=255)
    purchase_date: date | None = None
    warranty_until: date | None = None
    brand: str | None = Field(None, max_length=150)
    model: str | None = Field(None, max_length=150)
    purchase_cost: Decimal | None = None
    location: str | None = Field(None, max_length=5000)
    notes: str | None = Field(None, max_length=10000)
    description: str | None = Field(None, max_length=10000)
    image_url: str | None = Field(None, max_length=2048)  # Cloudinary image URL

    # Normalize whitespace on string fields
    @field_validator("tag", "name", "category", "serial", "vendor", "brand", "model", "location", "notes", "description", mode="before")
    @classmethod
    def normalize_whitespace(cls, v: str | None) -> str | None:
        return _normalize_whitespace(v)

    @field_validator("purchase_cost", mode="before")
    @classmethod
    def validate_purchase_cost(cls, v):
        if v is not None:
            cost = Decimal(str(v))
            if cost < 0:
                raise ValueError("Purchase cost must not be negative.")
        return v

    @field_validator("image_url", mode="before")
    @classmethod
    def validate_image_url(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        v = str(v).strip()
        # Reject base64 data URLs being stored directly
        if v.startswith("data:"):
            raise ValueError("Base64 data URLs are not allowed. Upload images using the /assets/upload-image endpoint.")
        # Reject blob URLs
        if v.startswith("blob:"):
            raise ValueError("Blob URLs are not allowed. Upload images using the /assets/upload-image endpoint.")
        # Must be a valid URL
        if not v.startswith(("http://", "https://", "/")):
            raise ValueError("Invalid image URL format. Must be an HTTP(S) URL or a relative path.")
        return v

    @model_validator(mode="after")
    def validate_dates(self):
        if self.purchase_date and self.warranty_until:
            if self.warranty_until < self.purchase_date:
                raise ValueError("Warranty expiry date cannot be before purchase date.")
        return self


class AssetUpdate(BaseModel):
    # Retain supplied status so the service rejects lifecycle bypasses explicitly.
    status: str | None = None
    name: str | None = Field(None, min_length=1, max_length=255)
    category: str | None = Field(None, min_length=1, max_length=100)
    serial: str | None = Field(None, max_length=150)
    vendor: str | None = Field(None, max_length=255)
    purchase_date: date | None = None
    warranty_until: date | None = None
    brand: str | None = Field(None, max_length=150)
    model: str | None = Field(None, max_length=150)
    purchase_cost: Decimal | None = None
    location: str | None = Field(None, max_length=5000)
    notes: str | None = Field(None, max_length=10000)
    description: str | None = Field(None, max_length=10000)
    image_url: str | None = Field(None, max_length=2048)  # Cloudinary image URL

    # Normalize whitespace on string fields
    @field_validator("name", "category", "serial", "vendor", "brand", "model", "location", "notes", "description", mode="before")
    @classmethod
    def normalize_whitespace(cls, v: str | None) -> str | None:
        return _normalize_whitespace(v)

    @field_validator("purchase_cost", mode="before")
    @classmethod
    def validate_purchase_cost(cls, v):
        if v is not None:
            cost = Decimal(str(v))
            if cost < 0:
                raise ValueError("Purchase cost must not be negative.")
        return v

    @field_validator("image_url", mode="before")
    @classmethod
    def validate_image_url(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        v = str(v).strip()
        if v.startswith("data:"):
            raise ValueError("Base64 data URLs are not allowed. Upload images using the /assets/upload-image endpoint.")
        if v.startswith("blob:"):
            raise ValueError("Blob URLs are not allowed. Upload images using the /assets/upload-image endpoint.")
        if not v.startswith(("http://", "https://", "/")):
            raise ValueError("Invalid image URL format. Must be an HTTP(S) URL or a relative path.")
        return v

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_ASSET_STATUSES:
            raise ValueError(f"Invalid status '{v}'. Must be one of: {', '.join(sorted(VALID_ASSET_STATUSES))}.")
        return v

    @model_validator(mode="after")
    def validate_dates(self):
        if self.purchase_date and self.warranty_until:
            if self.warranty_until < self.purchase_date:
                raise ValueError("Warranty expiry date cannot be before purchase date.")
        return self


class AssetAssignRequest(BaseModel):
    employee_id: uuid.UUID
    expected_return_date: date | None = None
    notes: str | None = None


class AssetTransferRequest(BaseModel):
    target_employee_id: uuid.UUID
    expected_return_date: date | None = None
    notes: str | None = None


class AssetLostRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=5000)
    lost_date: date | None = None


class AssetRequestCreate(BaseModel):
    request_type: str = Field(..., min_length=1, max_length=50)
    category: str = Field(..., min_length=1, max_length=100)
    justification: str = Field(..., min_length=1, max_length=5000)
    preferred_brand: str | None = Field(None, max_length=100)
    preferred_model: str | None = Field(None, max_length=100)
    estimated_cost: float | None = None

    @field_validator("estimated_cost", mode="before")
    @classmethod
    def validate_estimated_cost(cls, v):
        if v is not None and v < 0:
            raise ValueError("Estimated cost must not be negative.")
        return v


class AssetRequestUpdate(BaseModel):
    status: str | None = None
    rejection_reason: str | None = None
    approver_id: uuid.UUID | None = None


class AssetRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str
    request_type: str
    category: str
    justification: str
    preferred_brand: str | None = None
    preferred_model: str | None = None
    estimated_cost: float | None = None
    status: str
    approver_id: uuid.UUID | None = None
    approved_at: datetime | None = None
    rejection_reason: str | None = None
    assigned_asset_id: uuid.UUID | None = None
    fulfilled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AssetDamageReportCreate(BaseModel):
    asset_id: uuid.UUID
    damage_type: str = Field(..., min_length=1, max_length=50)
    severity: str = Field(..., min_length=1, max_length=20)
    description: str = Field(..., min_length=1, max_length=5000)
    location_of_incident: str | None = Field(None, max_length=200)
    incident_date: date | None = None


class AssetDamageReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    asset_id: uuid.UUID
    asset_tag: str
    asset_name: str
    reported_by_id: uuid.UUID
    reported_by_name: str
    damage_type: str
    severity: str
    description: str
    location_of_incident: str | None = None
    incident_date: date | None = None
    status: str
    maintenance_record_id: uuid.UUID | None = None
    resolved_at: datetime | None = None
    resolution_notes: str | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def map_relationship_fields(cls, data: any) -> any:
        if hasattr(data, "asset") and data.asset:
            data.asset_tag = data.asset.tag
            data.asset_name = data.asset.name
        if hasattr(data, "reported_by") and data.reported_by:
            data.reported_by_name = f"{data.reported_by.first_name} {data.reported_by.last_name}"
        return data


class AssetMaintenanceCreate(BaseModel):
    request_date: date | None = None
    vendor: str
    estimated_cost: Decimal | None = None
    cost: Decimal = Decimal("0.0")
    notes: str | None = None


class AssetMaintenanceComplete(BaseModel):
    completion_date: date | None = None
    actual_cost: Decimal | None = None
    completion_notes: str | None = None


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
    active_warranty_assets: int
    expiring_warranty_assets: int
    expired_warranty_assets: int
    unknown_warranty_assets: int
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


class AssetPublicResponse(BaseModel):
    """Public-facing asset schema for QR code scanning - limited fields only."""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    tag: str
    name: str
    category: str
    serial: str | None = None
    brand: str | None = None
    model: str | None = None
    status: str
    location: str | None = None
    description: str | None = None
    imageUrl: str | None = Field(None, serialization_alias="imageUrl")
    qrCodeData: str | None = Field(None, serialization_alias="qrCodeData")

    @model_validator(mode="before")
    @classmethod
    def populate_custom_fields(cls, data: any) -> any:
        if hasattr(data, "image_url"):
            data.imageUrl = data.image_url

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

