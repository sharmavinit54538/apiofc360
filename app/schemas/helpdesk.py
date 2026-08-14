"""Pydantic schemas for the OFC360 Helpdesk & Support API module."""

from __future__ import annotations

from datetime import datetime
import enum
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, Field


# ===========================================================================
# Enums
# ===========================================================================

class TicketPriority(str, enum.Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    URGENT = "Urgent"


class TicketStatus(str, enum.Enum):
    OPEN = "Open"
    IN_PROGRESS = "In Progress"
    RESOLVED = "Resolved"
    CLOSED = "Closed"
    REOPENED = "Reopened"


# ===========================================================================
# Common Models
# ===========================================================================

class HelpdeskUserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str
    role: str
    avatar_url: str | None = None
    department: str | None = None


class AttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    size: int
    type: str
    url: str
    created_at: datetime = Field(..., serialization_alias="createdAt")


class PaginationMeta(BaseModel):
    total: int
    page: int
    limit: int
    totalPages: int


# ===========================================================================
# Request Schemas
# ===========================================================================

class CreateTicketRequest(BaseModel):
    category: str = Field(..., min_length=1, max_length=50, example="Payroll & Salary")
    priority: str = Field("Medium", example="High")
    subject: str = Field(..., min_length=1, max_length=255, example="July Tax Deduction mismatch")
    description: str = Field(..., min_length=1, example="Detailed problem description")
    attachmentIds: list[uuid.UUID] | None = Field(default=None)


class UpdateTicketStatusRequest(BaseModel):
    status: str = Field(..., example="Resolved")
    resolutionNotes: str | None = Field(default=None, example="Issue fixed successfully.")


class AssignTicketRequest(BaseModel):
    assignedToUserId: uuid.UUID = Field(...)
    department: str | None = Field(default=None, example="IT Support")


class AddTicketCommentRequest(BaseModel):
    message: str = Field(..., min_length=1, example="I have tried the suggested solution.")
    attachments: list[uuid.UUID] | None = Field(default=None)


class InternalNoteRequest(BaseModel):
    note: str = Field(..., min_length=1, example="RMA initiated with Dell support.")


class UpsertFAQRequest(BaseModel):
    id: uuid.UUID | None = Field(default=None)
    category: str = Field(..., min_length=1, max_length=50, example="IT Support")
    question: str = Field(..., min_length=1, example="How do I configure VPN?")
    answer: str = Field(..., min_length=1, example="Follow the company VPN setup instructions.")
    is_public: bool = Field(True)


class AIChatRequest(BaseModel):
    message: str = Field(..., min_length=1, example="How many casual leaves can I carry forward?")
    conversationHistory: list[dict[str, Any]] | None = Field(default=None)


# ===========================================================================
# Response Schemas
# ===========================================================================

class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticketId: uuid.UUID
    author: HelpdeskUserSummary
    message: str
    isAgent: bool = False
    isInternalNote: bool = False
    attachments: list[AttachmentResponse] = Field(default_factory=list)
    createdAt: datetime


class InternalNoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticketId: uuid.UUID
    author: HelpdeskUserSummary
    note: str
    createdAt: datetime


class TicketResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticketNumber: str
    requester: HelpdeskUserSummary
    assignedTo: HelpdeskUserSummary | None = None
    department: str | None = None
    category: str
    priority: str
    status: str
    subject: str
    description: str
    resolutionNotes: str | None = None
    isSlaBreached: bool = False
    slaFirstResponseDueAt: datetime | None = None
    slaResolutionDueAt: datetime | None = None
    firstRespondedAt: datetime | None = None
    resolvedAt: datetime | None = None
    closedAt: datetime | None = None
    attachments: list[AttachmentResponse] = Field(default_factory=list)
    commentsCount: int = 0
    createdAt: datetime
    updatedAt: datetime


class MyTicketsResponse(BaseModel):
    items: list[TicketResponse]
    meta: PaginationMeta


class AdminTicketsMeta(BaseModel):
    total: int
    openCount: int
    inProgressCount: int
    resolvedCount: int
    page: int
    limit: int
    totalPages: int


class AdminTicketsResponse(BaseModel):
    items: list[TicketResponse]
    meta: AdminTicketsMeta


class FAQResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: str
    question: str
    answer: str
    isPublic: bool = True
    viewCount: int = 0
    isHelpfulCount: int = 0
    createdAt: datetime
    updatedAt: datetime


class AIChatResponse(BaseModel):
    reply: str
    suggestedActions: list[str] = Field(default_factory=list)
    deflected: bool = True


class HelpdeskSLAMetricsResponse(BaseModel):
    totalTickets: int
    resolvedTickets: int
    slaComplianceRate: float
    averageFirstResponseHours: float
    averageResolutionHours: float
    categoryBreakdown: dict[str, int]
    urgentOpenCount: int
