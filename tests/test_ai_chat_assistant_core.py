"""Core tests for AI Chat Assistant service (mocked Ollama, no real model needed)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import AIConversation, AIMessage
from app.models.employee import Employee
from app.models.leave import LeaveRequest
from app.models.payroll import PayCycle, StatutoryComplianceConfig
from app.schemas.chat_assistant import ChatAssistantRequest
from app.schemas.leave import LeaveBalanceResponse
from app.services.chat_assistant_service import ChatAssistantService


@pytest.fixture
def mock_session():
    """Create a mock AsyncSession."""
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client."""
    client = AsyncMock()
    client.chat = AsyncMock(return_value="AI response with analysis")
    client.check_health = AsyncMock(return_value={
        "ollama": {"healthy": True, "models": ["llama3.2:3b", "nomic-embed-text:latest"]}
    })
    return client


@pytest.fixture
def sample_company_id():
    return uuid.uuid4()


@pytest.fixture
def sample_user_id():
    return uuid.uuid4()


@pytest.fixture
def sample_employee_id():
    return uuid.uuid4()


class TestChatAssistantService:
    """Tests for ChatAssistantService with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_process_chat_sends_history_to_llm(
        self,
        mock_session,
        mock_llm_client,
        sample_company_id,
        sample_user_id,
        sample_employee_id,
    ):
        """Verify that conversation history is sent to the LLM via chat() method."""
        with patch("app.services.chat_assistant_service.get_llm_client", return_value=mock_llm_client):
            with patch("app.services.chat_assistant_service.ChatAssistantRepository") as mock_repo_class:
                mock_repo = mock_repo_class.return_value
                mock_repo.get_workforce_metrics = AsyncMock(return_value={
                    "total_employees": 100,
                    "attrition_rate": 5.2,
                    "open_positions": 3,
                    "new_hires_month": 5,
                    "department_headcount": [
                        {"department": "Engineering", "count": 40},
                        {"department": "Sales", "count": 30},
                    ],
                })
                mock_repo.get_policy_citations = AsyncMock(return_value=[])

                # Mock DB conversation lookup
                mock_conv = AIConversation(
                    id=uuid.uuid4(),
                    user_id=sample_user_id,
                    company_id=sample_company_id,
                    title="Test Conversation",
                )
                mock_msg1 = AIMessage(
                    id=uuid.uuid4(),
                    conversation_id=mock_conv.id,
                    role="user",
                    message="What is our headcount?",
                )
                mock_msg2 = AIMessage(
                    id=uuid.uuid4(),
                    conversation_id=mock_conv.id,
                    role="assistant",
                    message="You have 100 employees.",
                )
                mock_msg3 = AIMessage(
                    id=uuid.uuid4(),
                    conversation_id=mock_conv.id,
                    role="user",
                    message="How many in Engineering?",
                )

                # Mock session.execute to return conversation and messages
                async def mock_execute(stmt):
                    result = MagicMock()
                    # Check if querying conversation
                    if "ai_conversations" in str(stmt):
                        result.scalar_one_or_none = MagicMock(return_value=mock_conv)
                    # Check if querying messages
                    elif "ai_messages" in str(stmt):
                        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mock_msg1, mock_msg2, mock_msg3])))
                    else:
                        result.scalar_one_or_none = MagicMock(return_value=None)
                        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
                    return result

                mock_session.execute = mock_execute

                service = ChatAssistantService(session=mock_session)
                service.llm = mock_llm_client

                request = ChatAssistantRequest(
                    message="How many in Engineering?",
                    conversation_id=str(mock_conv.id),
                )

                response = await service.process_chat(
                    request=request,
                    company_id=sample_company_id,
                    user_id=sample_user_id,
                )

                # Verify LLM chat was called with messages including history
                mock_llm_client.chat.assert_called_once()
                call_args = mock_llm_client.chat.call_args
                messages = call_args.kwargs.get("messages", [])

                # Should have system prompt, context, history messages, and current user message
                assert len(messages) >= 4  # system + context + 2 history + current user
                # Check that history messages are included
                user_messages = [m for m in messages if m.get("role") == "user"]
                assert len(user_messages) >= 2  # Previous user message + current

                # The last user message should be the current query
                assert user_messages[-1]["content"] == "How many in Engineering?"

    @pytest.mark.asyncio
    async def test_user_a_cannot_read_user_b_conversation(
        self,
        mock_session,
        mock_llm_client,
        sample_company_id,
    ):
        """Verify that User A cannot access User B's conversation (returns 404)."""
        user_a_id = uuid.uuid4()
        user_b_id = uuid.uuid4()
        conv_id = uuid.uuid4()

        with patch("app.services.chat_assistant_service.get_llm_client", return_value=mock_llm_client):
            with patch("app.services.chat_assistant_service.ChatAssistantRepository") as mock_repo_class:
                mock_repo = mock_repo_class.return_value
                mock_repo.get_workforce_metrics = AsyncMock(return_value={"total_employees": 100})
                mock_repo.get_policy_citations = AsyncMock(return_value=[])

                # Mock conversation belonging to user_b
                mock_conv = AIConversation(
                    id=conv_id,
                    user_id=user_b_id,
                    company_id=sample_company_id,
                    title="User B's Conversation",
                )

                async def mock_execute(stmt):
                    result = MagicMock()
                    if "ai_conversations" in str(stmt):
                        result.scalar_one_or_none = MagicMock(return_value=mock_conv)
                    else:
                        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
                    return result

                mock_session.execute = mock_execute

                service = ChatAssistantService(session=mock_session)
                service.llm = mock_llm_client

                # User A tries to access User B's conversation
                request = ChatAssistantRequest(
                    message="Follow up",
                    conversation_id=str(conv_id),
                )

                from app.core.exceptions import NotFoundException
                with pytest.raises(NotFoundException) as exc_info:
                    await service.process_chat(
                        request=request,
                        company_id=sample_company_id,
                        user_id=user_a_id,
                    )

                assert "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_ollama_failure_returns_clear_unavailable_message(
        self,
        mock_session,
        sample_company_id,
        sample_user_id,
    ):
        """Verify that Ollama timeout/error returns clear 'AI unavailable' message with data snapshot."""
        mock_llm_client = AsyncMock()
        mock_llm_client.chat = AsyncMock(side_effect=TimeoutError("LLM request timed out"))
        mock_llm_client.check_health = AsyncMock(return_value={
            "ollama": {"healthy": False, "error": "connection refused"}
        })

        with patch("app.services.chat_assistant_service.get_llm_client", return_value=mock_llm_client):
            with patch("app.services.chat_assistant_service.ChatAssistantRepository") as mock_repo_class:
                mock_repo = mock_repo_class.return_value
                mock_repo.get_workforce_metrics = AsyncMock(return_value={
                    "total_employees": 150,
                    "attrition_rate": 8.5,
                    "open_positions": 5,
                    "new_hires_month": 10,
                    "department_headcount": [
                        {"department": "Engineering", "count": 60},
                        {"department": "Sales", "count": 40},
                    ],
                })
                mock_repo.get_policy_citations = AsyncMock(return_value=[])

                # Mock conversation
                mock_conv = AIConversation(
                    id=uuid.uuid4(),
                    user_id=sample_user_id,
                    company_id=sample_company_id,
                    title="Test",
                )

                async def mock_execute(stmt):
                    result = MagicMock()
                    if "ai_conversations" in str(stmt):
                        result.scalar_one_or_none = MagicMock(return_value=mock_conv)
                    elif "ai_messages" in str(stmt):
                        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
                    else:
                        result.scalar_one_or_none = MagicMock(return_value=None)
                        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
                    return result

                mock_session.execute = mock_execute

                service = ChatAssistantService(session=mock_session)
                service.llm = mock_llm_client

                request = ChatAssistantRequest(message="What is our attrition rate?")

                response = await service.process_chat(
                    request=request,
                    company_id=sample_company_id,
                    user_id=sample_user_id,
                )

                # Verify degraded response
                assert response.ai_available is False
                assert response.degraded is True
                assert "AI Service Unavailable" in response.answer or "AI service is currently unavailable" in response.answer
                assert "150" in response.answer  # Total employees in snapshot
                assert "8.5%" in response.answer or "8.5" in response.answer  # Attrition rate
                assert response.confidence < 0.5  # Reduced confidence

    @pytest.mark.asyncio
    async def test_conversations_survive_service_restart(
        self,
        mock_session,
        mock_llm_client,
        sample_company_id,
        sample_user_id,
    ):
        """Verify that conversations are persisted in DB and survive service restart."""
        conv_id = uuid.uuid4()

        with patch("app.services.chat_assistant_service.get_llm_client", return_value=mock_llm_client):
            with patch("app.services.chat_assistant_service.ChatAssistantRepository") as mock_repo_class:
                mock_repo = mock_repo_class.return_value
                mock_repo.get_workforce_metrics = AsyncMock(return_value={"total_employees": 100})
                mock_repo.get_policy_citations = AsyncMock(return_value=[])

                # First request - create conversation
                mock_conv = AIConversation(
                    id=conv_id,
                    user_id=sample_user_id,
                    company_id=sample_company_id,
                    title="Test Conversation",
                )

                call_count = [0]

                async def mock_execute(stmt):
                    call_count[0] += 1
                    result = MagicMock()
                    if "ai_conversations" in str(stmt):
                        result.scalar_one_or_none = MagicMock(return_value=mock_conv)
                    elif "ai_messages" in str(stmt):
                        if call_count[0] == 1:
                            # First call - no history
                            result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
                        else:
                            # Subsequent calls - has history
                            msg1 = AIMessage(id=uuid.uuid4(), conversation_id=conv_id, role="user", message="Hello")
                            msg2 = AIMessage(id=uuid.uuid4(), conversation_id=conv_id, role="assistant", message="Hi there")
                            result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[msg1, msg2])))
                    return result

                mock_session.execute = mock_execute

                service = ChatAssistantService(session=mock_session)
                service.llm = mock_llm_client

                # First message
                request1 = ChatAssistantRequest(message="Hello", conversation_id=str(conv_id))
                response1 = await service.process_chat(request=request1, company_id=sample_company_id, user_id=sample_user_id)

                # Verify messages were saved
                assert mock_session.add.call_count >= 2  # user message + assistant message
                assert mock_session.commit.called or mock_session.flush.called

                # Simulate service restart - new service instance
                service2 = ChatAssistantService(session=mock_session)
                service2.llm = mock_llm_client

                # Second message - should have history
                request2 = ChatAssistantRequest(message="How are you?", conversation_id=str(conv_id))
                response2 = await service2.process_chat(request=request2, company_id=sample_company_id, user_id=sample_user_id)

                # Verify history was sent to LLM
                call_args = mock_llm_client.chat.call_args_list[-1]
                messages = call_args.kwargs.get("messages", [])
                user_messages = [m for m in messages if m.get("role") == "user"]
                # Should have both the first "Hello" and current "How are you?"
                assert any("Hello" in m["content"] for m in user_messages)

    @pytest.mark.asyncio
    async def test_get_history_filters_by_user_id(
        self,
        mock_session,
        mock_llm_client,
        sample_company_id,
        sample_user_id,
    ):
        """Verify get_history only returns conversations for the current user."""
        from datetime import datetime, timezone
        user_a_id = uuid.uuid4()
        user_b_id = uuid.uuid4()

        conv_a = AIConversation(id=uuid.uuid4(), user_id=user_a_id, company_id=sample_company_id, title="User A Conv", updated_at=datetime.now(timezone.utc))
        conv_b = AIConversation(id=uuid.uuid4(), user_id=user_b_id, company_id=sample_company_id, title="User B Conv", updated_at=datetime.now(timezone.utc))

        # Mock messages for last_message
        msg_a = AIMessage(id=uuid.uuid4(), conversation_id=conv_a.id, role="user", message="Hello from A")
        msg_b = AIMessage(id=uuid.uuid4(), conversation_id=conv_b.id, role="user", message="Hello from B")

        # Track which user_id was used in the query
        query_user_id = [None]

        with patch("app.services.chat_assistant_service.ChatAssistantRepository") as mock_repo_class:
            mock_repo = mock_repo_class.return_value

            async def mock_execute(stmt):
                result = MagicMock()
                stmt_str = str(stmt).lower()
                if "ai_conversations" in stmt_str:
                    # Check if the statement has user_id filter by looking at the compiled query
                    # The user_id filter is applied via .where(AIConversation.user_id == user_id)
                    # We'll check if the statement has a WHERE clause referencing user_id
                    # For simplicity, just return user_a's conversation when user_id is provided
                    # (the service method passes user_id=user_a_id)
                    if "user_id" in stmt_str and "where" in stmt_str:
                        # Return only user_a's conversation (simulating the filter working)
                        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[conv_a])))
                    else:
                        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[conv_a, conv_b])))
                elif "ai_messages" in stmt_str and "conversation_id" in stmt_str:
                    # Return last message for the conversation being queried
                    if str(conv_a.id).lower() in stmt_str:
                        result.scalar_one_or_none = MagicMock(return_value=msg_a)
                    elif str(conv_b.id).lower() in stmt_str:
                        result.scalar_one_or_none = MagicMock(return_value=msg_b)
                    else:
                        result.scalar_one_or_none = MagicMock(return_value=None)
                elif "count" in stmt_str:
                    result.scalar = MagicMock(return_value=1)
                else:
                    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
                    result.scalar = MagicMock(return_value=0)
                    result.scalar_one_or_none = MagicMock(return_value=None)
                return result

            mock_session.execute = mock_execute

            service = ChatAssistantService(session=mock_session)

            # User A should only see their own conversation
            history = await service.get_history(company_id=sample_company_id, user_id=user_a_id)
            assert history.total_conversations == 1
            assert history.history[0].title == "User A Conv"

    @pytest.mark.asyncio
    async def test_enriched_context_includes_leave_for_leave_queries(
        self,
        mock_session,
        mock_llm_client,
        sample_company_id,
        sample_user_id,
        sample_employee_id,
    ):
        """Verify that leave balances are included in context for leave-related queries."""
        with patch("app.services.chat_assistant_service.get_llm_client", return_value=mock_llm_client):
            with patch("app.services.chat_assistant_service.ChatAssistantRepository") as mock_repo_class:
                with patch("app.services.leave_service.LeaveService") as mock_leave_service_class:
                    mock_repo = mock_repo_class.return_value
                    mock_repo.get_workforce_metrics = AsyncMock(return_value={
                        "total_employees": 100,
                        "attrition_rate": 5.0,
                        "open_positions": 2,
                        "new_hires_month": 3,
                        "department_headcount": [],
                    })
                    mock_repo.get_policy_citations = AsyncMock(return_value=[])

                    # Mock LeaveService
                    mock_leave_service = mock_leave_service_class.return_value
                    mock_leave_service.get_leave_balances = AsyncMock(return_value=[
                        LeaveBalanceResponse(leave_type="Sick Leave", total_days=12.0, used_days=3.0, remaining_days=9.0),
                        LeaveBalanceResponse(leave_type="Vacation Leave", total_days=15.0, used_days=5.0, remaining_days=10.0),
                    ])

                    # Mock employee lookup for user
                    mock_emp = Employee(id=sample_employee_id, user_id=sample_user_id, role="employee", company_id=sample_company_id)

                    async def mock_execute(stmt):
                        result = MagicMock()
                        stmt_str = str(stmt).lower()
                        if "employees" in stmt_str and "user_id" in stmt_str:
                            result.scalar_one_or_none = MagicMock(return_value=mock_emp)
                        elif "ai_conversations" in stmt_str:
                            mock_conv = AIConversation(id=uuid.uuid4(), user_id=sample_user_id, company_id=sample_company_id, title="Test")
                            result.scalar_one_or_none = MagicMock(return_value=mock_conv)
                        elif "ai_messages" in stmt_str:
                            result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
                        else:
                            result.scalar_one_or_none = MagicMock(return_value=None)
                            result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
                        return result

                    mock_session.execute = mock_execute

                    service = ChatAssistantService(session=mock_session)
                    service.llm = mock_llm_client

                    request = ChatAssistantRequest(message="What are my leave balances?")
                    response = await service.process_chat(request=request, company_id=sample_company_id, user_id=sample_user_id)

                    # Verify context was sent to LLM includes leave data
                    call_args = mock_llm_client.chat.call_args
                    messages = call_args.kwargs.get("messages", [])
                    # Find the context message (system role with context)
                    context_msgs = [m for m in messages if m.get("role") == "system" and "Leave Balances" in m.get("content", "")]
                    assert len(context_msgs) > 0
                    context = context_msgs[0]["content"]
                    assert "Sick Leave" in context
                    assert "Vacation Leave" in context


if __name__ == "__main__":
    pytest.main([__file__, "-v"])