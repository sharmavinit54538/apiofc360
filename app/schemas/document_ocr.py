"""Pydantic schemas for Google Document AI OCR integration."""

from datetime import datetime
from enum import Enum
from typing import Any, Generic, TypeVar
import uuid

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class DocumentTypeEnum(str, Enum):
    GENERIC = "generic"
    AADHAAR = "aadhaar"
    PAN = "pan"
    PASSPORT = "passport"
    RESUME = "resume"
    PAYSLIP = "payslip"
    INVOICE = "invoice"
    OFFER_LETTER = "offer_letter"
    EXPERIENCE_LETTER = "experience_letter"
    EDUCATION_CERTIFICATE = "education_certificate"
    BANK_STATEMENT = "bank_statement"


class EntitySchema(BaseModel):
    """Extracted Document Entity."""
    type: str = Field(..., description="Entity type/label")
    mention_text: str = Field(..., description="Text mention in document")
    confidence: float = Field(0.0, description="Extraction confidence score (0-1)")
    normalized_value: Any = Field(None, description="Parsed/normalized entity value")

    model_config = ConfigDict(from_attributes=True)


class TableCellSchema(BaseModel):
    text: str = ""
    row_span: int = 1
    col_span: int = 1
    confidence: float = 0.0


class TableRowSchema(BaseModel):
    cells: list[TableCellSchema] = Field(default_factory=list)


class TableSchema(BaseModel):
    """Extracted Table structure."""
    page_number: int = Field(1, description="Page index (1-based)")
    header_rows: list[list[str]] = Field(default_factory=list, description="Table headers")
    rows: list[list[str]] = Field(default_factory=list, description="Data rows")
    confidence: float = Field(0.0, description="Table extraction confidence score")

    model_config = ConfigDict(from_attributes=True)


class FormFieldSchema(BaseModel):
    """Extracted Key-Value Form Field."""
    field_name: str = Field(..., description="Field label / key name")
    field_value: str = Field("", description="Extracted field value")
    name_confidence: float = Field(0.0, description="Confidence of field name")
    value_confidence: float = Field(0.0, description="Confidence of field value")

    model_config = ConfigDict(from_attributes=True)


class PageSchema(BaseModel):
    """Extracted Page summary."""
    page_number: int = Field(1, description="Page index (1-based)")
    width: float = Field(0.0, description="Page dimension width")
    height: float = Field(0.0, description="Page dimension height")
    unit: str = Field("pt", description="Dimension unit")
    paragraphs_count: int = Field(0, description="Total paragraphs on page")
    lines_count: int = Field(0, description="Total text lines on page")
    tokens_count: int = Field(0, description="Total tokens/words on page")

    model_config = ConfigDict(from_attributes=True)


class DocumentOCRResponse(BaseModel):
    """Structured JSON response returned upon document upload & OCR processing."""
    document_id: str = Field(..., description="Unique UUID identifier for document")
    status: str = Field("completed", description="Processing status (completed, failed, processing)")
    page_count: int = Field(0, description="Total pages processed")
    text: str = Field("", description="Full raw extracted text")
    confidence: float = Field(0.0, description="Overall document OCR confidence score")
    entities: list[EntitySchema] = Field(default_factory=list, description="Extracted entities")
    tables: list[TableSchema] = Field(default_factory=list, description="Extracted tables")
    form_fields: list[FormFieldSchema] = Field(default_factory=list, description="Extracted form key-value fields")
    pages: list[PageSchema] = Field(default_factory=list, description="Per-page layout breakdown")
    created_at: datetime | None = Field(None, description="ISO timestamp of document creation")

    model_config = ConfigDict(from_attributes=True)


class DocumentOCRListItem(BaseModel):
    """Summary item for OCR history listing."""
    id: uuid.UUID
    original_filename: str
    stored_filename: str
    mime_type: str
    file_size: int
    document_type: str
    status: str
    page_count: int
    confidence: float
    processing_time_ms: float
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentOCRDetailResponse(BaseModel):
    """Detailed response for GET /api/v1/documents/{document_id}."""
    id: uuid.UUID
    original_filename: str
    stored_filename: str
    file_path: str
    mime_type: str
    file_size: int
    document_type: str
    status: str
    page_count: int
    extracted_text: str
    confidence: float
    processing_time_ms: float
    entities: list[EntitySchema] = Field(default_factory=list)
    tables: list[TableSchema] = Field(default_factory=list)
    form_fields: list[FormFieldSchema] = Field(default_factory=list)
    pages: list[PageSchema] = Field(default_factory=list)
    raw_response: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
