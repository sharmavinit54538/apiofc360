"""Pydantic schemas for AI Chat Assistant (Aurix AI Copilot) module APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field, model_validator


MessageLifecycleState = Literal[
    "pending",
    "sending",
    "accepted",
    "generating",
    "streaming",
    "completed",
    "failed",
    "cancelled",
    "retrying",
    "interrupted",
]


class SourceCitation(BaseModel):
    """Citation source for RAG knowledge answers."""

    document: str = Field(..., description="Title of document")
    title: Optional[str] = Field(None, description="Document title alias")
    section: str = Field(..., description="Section header")
    snippet: Optional[str] = Field(None, description="Section snippet alias")
    page: Optional[int] = Field(None, description="Page number")
    similarity: Optional[float] = Field(None, description="Vector similarity score 0-1")

    model_config = ConfigDict(from_attributes=True)

    def model_post_init(self, __context: Any) -> None:
        if self.title is None:
            self.title = self.document
        if self.snippet is None:
            self.snippet = self.section


class ChartData(BaseModel):
    """Interactive chart payload."""

    title: str = Field(..., description="Chart title")
    chart_type: str = Field("bar", description="bar | line | pie | donut")
    data: list[dict[str, Any]] = Field(default_factory=list, description="Chart dataset")

    model_config = ConfigDict(from_attributes=True)


class TableData(BaseModel):
    """Tabular data payload."""

    title: str = Field(..., description="Table title")
    headers: list[str] = Field(default_factory=list, description="Column headers")
    rows: list[list[Any]] = Field(default_factory=list, description="Data rows")

    model_config = ConfigDict(from_attributes=True)


class ChatAssistantRequest(BaseModel):
    """Payload for natural language chat queries supporting message and query key aliases."""

    query: Optional[str] = Field(None, description="User prompt or question")
    message: Optional[str] = Field(None, description="User message text")
    content: Optional[str] = Field(None, description="User message text alias")
    prompt: Optional[str] = Field(None, description="User prompt alias")
    conversation_id: Optional[str] = Field(None, description="Existing conversation UUID")
    conversationId: Optional[str] = Field(None, alias="conversationId", description="CamelCase conversation UUID alias")
    session_id: Optional[str] = Field(None, description="Session UUID alias")
    department_id: Optional[uuid.UUID] = Field(None, description="Filter by department")
    date_range: Optional[str] = Field(None, description="Date filter e.g. 2026-07-01 to 2026-07-24")
    role: Optional[str] = Field(None, description="User role context")
    project_id: Optional[uuid.UUID] = Field(None, description="Filter by project")
    agent_id: Optional[str] = Field(None, alias="agentId", description="Optional agent id")
    client_message_id: Optional[str] = Field(None, alias="clientMessageId", description="Client-generated idempotency identifier")
    request_id: Optional[str] = Field(None, alias="requestId", description="Optional client tracing request ID")
    stream: bool = Field(False, description="Whether client prefers streaming response")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def normalize_payload(cls, data: Any) -> Any:
        """Normalize flexible payload fields so frontend variations never trigger 422."""
        if isinstance(data, dict):
            # Normalize message-like fields to 'message'
            msg = data.get("message") or data.get("content") or data.get("prompt") or data.get("query")
            if msg is not None:
                data["message"] = msg
            # Normalize conversation_id fields
            conv_id = data.get("conversationId") or data.get("session_id")
            if conv_id is not None and data.get("conversation_id") is None:
                data["conversation_id"] = conv_id
            # Normalize client_message_id fields
            cmid = data.get("clientMessageId") or data.get("client_message_id")
            if cmid is not None and data.get("client_message_id") is None:
                data["client_message_id"] = str(cmid)
        return data

    def get_message_text(self) -> str:
        """Get the normalized message text."""
        return (self.message or self.content or self.prompt or self.query or "").strip()

    def get_conversation_id(self) -> Optional[str]:
        """Get the normalized conversation ID."""
        return self.conversation_id or self.conversationId or self.session_id

    def get_client_message_id(self) -> Optional[str]:
        """Get the normalized client message identifier."""
        raw = self.client_message_id
        return raw.strip()[:128] if isinstance(raw, str) and raw.strip() else None


class CreateConversationRequest(BaseModel):
    """Payload to create a new chat conversation."""

    title: Optional[str] = Field("New Conversation", description="Conversation title")
    initial_message: Optional[str] = Field(None, alias="initialMessage", description="Optional initial message")
    agent_id: Optional[str] = Field(None, alias="agentId", description="Optional agent id")
    message: Optional[str] = Field(None, description="Optional message text")
    query: Optional[str] = Field(None, description="Optional prompt query")
    content: Optional[str] = Field(None, description="Optional content text")
    prompt: Optional[str] = Field(None, description="Optional prompt text")
    department_id: Optional[uuid.UUID] = Field(None, description="Filter by department")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def normalize_payload(cls, data: Any) -> Any:
        """Normalize flexible payload fields."""
        if isinstance(data, dict):
            msg = data.get("initial_message") or data.get("message") or data.get("content") or data.get("prompt") or data.get("query")
            if msg is not None:
                data["initial_message"] = msg
        return data


class ChatMessageItem(BaseModel):
    """Serialized chat message returned in conversation details."""

    id: str
    messageId: Optional[str] = None
    message_id: Optional[str] = None
    conversationId: str
    conversation_id: Optional[str] = None
    role: str
    sender: str
    content: str
    message: Optional[str] = None
    timestamp: str
    createdAt: Optional[str] = None
    created_at: Optional[str] = None
    status: str = "completed"
    clientMessageId: Optional[str] = None
    client_message_id: Optional[str] = None
    sources: list[SourceCitation] = Field(default_factory=list)
    charts: list[ChartData] = Field(default_factory=list)
    tables: list[TableData] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    metadata: Optional[dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    def model_post_init(self, __context: Any) -> None:
        if self.messageId is None:
            self.messageId = self.id
        if self.message_id is None:
            self.message_id = self.id
        if self.conversation_id is None:
            self.conversation_id = self.conversationId
        if self.message is None:
            self.message = self.content
        if self.createdAt is None:
            self.createdAt = self.timestamp
        if self.created_at is None:
            self.created_at = self.timestamp
        if self.clientMessageId is None and self.client_message_id is not None:
            self.clientMessageId = self.client_message_id
        elif self.client_message_id is None and self.clientMessageId is not None:
            self.client_message_id = self.clientMessageId


class ChatAssistantResponse(BaseModel):
    """Response payload matching frontend chat requirements."""

    answer: str = Field(..., description="AI generated answer in markdown format")
    content: Optional[str] = Field(None, description="Alias matching frontend content field")
    reply: Optional[str] = Field(None, description="Alias for frontend reply field")
    message: Optional[str] = Field(None, description="Alias for frontend message field")
    confidence: float = Field(..., description="Confidence score 0-1")
    sources: list[SourceCitation] = Field(default_factory=list, description="Source document citations")
    charts: list[ChartData] = Field(default_factory=list, description="Chart visual objects")
    tables: list[TableData] = Field(default_factory=list, description="Tabular data objects")
    followUpQuestions: list[str] = Field(default_factory=list, description="CamelCase follow-up questions")
    follow_up_questions: list[str] = Field(default_factory=list, description="Snake_case follow-up questions")
    suggestions: list[str] = Field(default_factory=list, description="Suggested next actions")
    conversationId: str = Field(..., description="CamelCase conversation UUID")
    conversation_id: str = Field(..., description="Snake_case conversation UUID")
    session_id: Optional[str] = Field(None, description="Session ID alias")
    title: Optional[str] = Field(None, description="Conversation title")
    messages: list[ChatMessageItem] = Field(default_factory=list, description="Ordered messages when fetching conversation detail")
    role: str = Field("ai", description="Message sender role")
    messageId: Optional[str] = Field(None, description="Message UUID")
    message_id: Optional[str] = Field(None, description="Message UUID")
    clientMessageId: Optional[str] = Field(None, description="Client-generated idempotency identifier")
    client_message_id: Optional[str] = Field(None, description="Snake_case client message ID")
    status: str = Field("completed", description="Message delivery lifecycle state")
    requestId: Optional[str] = Field(None, description="Tracing request ID")
    request_id: Optional[str] = Field(None, description="Snake_case tracing request ID")
    timingMs: Optional[float] = Field(None, description="Total backend request latency in ms")
    timing_ms: Optional[float] = Field(None, description="Snake_case total backend request latency in ms")
    model: Optional[str] = Field(None, description="Model name used")
    provider: Optional[str] = Field(None, description="Provider name used")
    ai_available: bool = Field(True, description="Whether AI/LLM service was available for this response")
    degraded: bool = Field(False, description="Whether response is degraded due to LLM unavailability")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    def model_post_init(self, __context: Any) -> None:
        if self.content is None:
            self.content = self.answer
        if self.reply is None:
            self.reply = self.answer
        if self.message is None:
            self.message = self.answer
        if not self.suggestions and self.follow_up_questions:
            self.suggestions = list(self.follow_up_questions)
        if self.messageId is None:
            mid = str(uuid.uuid4())
            self.messageId = mid
            self.message_id = mid
        elif self.message_id is None:
            self.message_id = self.messageId
        if self.session_id is None:
            self.session_id = self.conversation_id
        if self.clientMessageId is None and self.client_message_id is not None:
            self.clientMessageId = self.client_message_id
        elif self.client_message_id is None and self.clientMessageId is not None:
            self.client_message_id = self.clientMessageId
        if self.requestId is None and self.request_id is not None:
            self.requestId = self.request_id
        elif self.request_id is None and self.requestId is not None:
            self.request_id = self.requestId
        if self.timingMs is None and self.timing_ms is not None:
            self.timingMs = self.timing_ms
        elif self.timing_ms is None and self.timingMs is not None:
            self.timing_ms = self.timingMs


class MessageDeliveryStatusResponse(BaseModel):
    """Status reconciliation payload for idempotent message delivery."""

    conversationId: str
    conversation_id: str
    clientMessageId: str
    client_message_id: str
    status: str
    found: bool = True
    message: Optional[ChatMessageItem] = None
    response: Optional[ChatAssistantResponse] = None
    partialContent: Optional[str] = None
    error: Optional[str] = None
    updatedAt: Optional[str] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ReportGeneratePayload(BaseModel):
    """Payload for HR Report Generation."""

    report_type: str = Field("ATTENDANCE", description="ATTENDANCE | PAYROLL | LEAVE | PERFORMANCE | RECRUITMENT | COMPLIANCE")
    department_id: Optional[uuid.UUID] = None
    date_range: Optional[str] = "2026-07-01 to 2026-07-24"


class AnalyticsQueryPayload(BaseModel):
    """Payload for Workforce Analytics query."""

    metric_type: str = Field("HEADCOUNT", description="HEADCOUNT | ATTRITION | HIRING | PRODUCTIVITY | UTILIZATION | OVERTIME")
    department_id: Optional[uuid.UUID] = None


class RecommendationsPayload(BaseModel):
    """Payload for AI Recommendations engine."""

    domain: str = Field("RETENTION", description="PROMOTION | RETENTION | HIRING | TRAINING | COST_OPTIMIZATION")
    department_id: Optional[uuid.UUID] = None


class ChatSuggestionsResponse(BaseModel):
    """Suggested prompts for frontend copilot."""

    suggested_prompts: list[str] = Field(default_factory=list)
    popular_queries: list[str] = Field(default_factory=list)
    role_based_prompts: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ConversationHistoryItem(BaseModel):
    """Conversation history summary item."""

    conversation_id: str
    conversationId: Optional[str] = None
    title: str
    last_message: str
    lastMessage: Optional[str] = None
    message_count: int
    messageCount: Optional[int] = None
    updated_at: datetime
    updatedAt: Optional[str] = None
    agentId: Optional[str] = "general-copilot"

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    def model_post_init(self, __context: Any) -> None:
        if self.conversationId is None:
            self.conversationId = self.conversation_id
        if self.lastMessage is None:
            self.lastMessage = self.last_message
        if self.messageCount is None:
            self.messageCount = self.message_count
        if self.updatedAt is None:
            self.updatedAt = self.updated_at.isoformat()


class ChatHistoryResponse(BaseModel):
    """List of past chat conversations."""

    total_conversations: int
    total: Optional[int] = None
    history: list[ConversationHistoryItem] = Field(default_factory=list)
    items: Optional[list[ConversationHistoryItem]] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    def model_post_init(self, __context: Any) -> None:
        if self.total is None:
            self.total = self.total_conversations
        if self.items is None:
            self.items = list(self.history)


class ChatFeedbackRequest(BaseModel):
    """User feedback payload for chat response."""

    conversation_id: Optional[str] = Field(None, alias="conversationId")
    message_id: Optional[str] = Field(None, alias="messageId")
    rating: int = Field(..., description="Rating: up/down/1-5", ge=1, le=5)
    feedback: Optional[str] = Field(None, description="Optional text feedback")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def normalize_rating(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if data.get("conversation_id") is None and data.get("conversationId") is not None:
                data["conversation_id"] = data["conversationId"]
            if data.get("message_id") is None and data.get("messageId") is not None:
                data["message_id"] = data["messageId"]
            if "rating" in data:
                rating = data["rating"]
                if isinstance(rating, str):
                    lowered = rating.strip().lower()
                    if lowered == "up":
                        data["rating"] = 5
                    elif lowered == "down":
                        data["rating"] = 1
                    elif lowered in {"-1", "0"}:
                        data["rating"] = 1
                elif isinstance(rating, (int, float)) and rating <= 0:
                    data["rating"] = 1
        return data