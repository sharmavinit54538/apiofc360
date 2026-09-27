"""Tests for AI Chat Assistant (/api/v1/ai/chat/*) routes, multi-tenancy, and auth."""

from __future__ import annotations

import uuid
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.utils.jwt import create_access_token


@pytest.fixture
def company_a_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def company_b_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def token_company_a(company_a_id: str) -> str:
    return create_access_token(
        user_id=str(uuid.uuid4()),
        role="hr_manager",
        company_id=company_a_id,
    )


@pytest.fixture
def token_company_b(company_b_id: str) -> str:
    return create_access_token(
        user_id=str(uuid.uuid4()),
        role="hr_manager",
        company_id=company_b_id,
    )


@pytest.fixture
def token_no_company() -> str:
    return create_access_token(
        user_id=str(uuid.uuid4()),
        role="employee",
    )


@pytest.mark.asyncio
async def test_auth_mandatory_rejects_unauthenticated():
    """Unauthenticated request must return 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/ai/chat/history")
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_mandatory_rejects_missing_company(token_no_company: str):
    """Authenticated request missing company_id must return 403."""
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {token_no_company}"}
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/ai/chat/history", headers=headers)
        assert response.status_code == 403
        body = response.json()
        error_msg = body.get("message", "") or body.get("detail", "")
        assert "not associated with a company" in error_msg


@pytest.mark.asyncio
async def test_create_and_list_conversations(token_company_a: str, company_a_id: str):
    """Test creating conversation and listing it via /history and /conversations."""
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {token_company_a}"}
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create via POST /api/v1/ai/chat/conversations
        create_res = await ac.post(
            "/api/v1/ai/chat/conversations",
            json={"title": "Q3 Headcount Planning", "initialMessage": "Analyze our hiring pace"},
            headers=headers,
        )
        assert create_res.status_code in (200, 201)
        data = create_res.json()["data"]
        conv_id = data["conversationId"]
        assert conv_id
        assert data["conversation_id"] == conv_id
        assert data["answer"]
        assert data["content"] == data["answer"]

        # List via GET /api/v1/ai/chat/history
        list_res = await ac.get("/api/v1/ai/chat/history", headers=headers)
        assert list_res.status_code == 200
        hist_data = list_res.json()["data"]
        assert hist_data["total_conversations"] >= 1
        conv_ids = [c["conversation_id"] for c in hist_data["history"]]
        assert conv_id in conv_ids

        # List via GET /api/v1/ai/chat/conversations alias
        list_alias_res = await ac.get("/api/v1/ai/chat/conversations", headers=headers)
        assert list_alias_res.status_code == 200
        assert list_alias_res.json()["data"]["total_conversations"] == hist_data["total_conversations"]


@pytest.mark.asyncio
async def test_send_message_aliases(token_company_a: str):
    """Test POST /api/v1/ai/chat and POST /api/v1/ai/chat/message aliases."""
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {token_company_a}"}
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Standard POST /api/v1/ai/chat with content and conversationId
        res1 = await ac.post(
            "/api/v1/ai/chat",
            json={"content": "What is our current attrition rate?"},
            headers=headers,
        )
        assert res1.status_code == 200
        d1 = res1.json()["data"]
        assert d1["conversationId"]
        assert d1["answer"]

        # Alias POST /api/v1/ai/chat/message
        res2 = await ac.post(
            "/api/v1/ai/chat/message",
            json={"conversationId": d1["conversationId"], "content": "How does it compare to last year?"},
            headers=headers,
        )
        assert res2.status_code == 200
        d2 = res2.json()["data"]
        assert d2["conversationId"] == d1["conversationId"]


@pytest.mark.asyncio
async def test_tenant_isolation(
    token_company_a: str,
    token_company_b: str,
    company_a_id: str,
    company_b_id: str,
):
    """Company B cannot access or delete Company A's conversations."""
    transport = ASGITransport(app=app)
    headers_a = {"Authorization": f"Bearer {token_company_a}"}
    headers_b = {"Authorization": f"Bearer {token_company_b}"}

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Company A creates a conversation
        create_res = await ac.post(
            "/api/v1/ai/chat/conversations",
            json={"title": "Confidential Executive Compensation"},
            headers=headers_a,
        )
        assert create_res.status_code in (200, 201)
        conv_id = create_res.json()["data"]["conversationId"]

        # 2. Company B tries to get detail -> 404
        get_b_res = await ac.get(f"/api/v1/ai/chat/conversations/{conv_id}", headers=headers_b)
        assert get_b_res.status_code == 404

        # 3. Company B tries to delete -> 404
        del_b_res = await ac.delete(f"/api/v1/ai/chat/conversations/{conv_id}", headers=headers_b)
        assert del_b_res.status_code == 404

        # 4. Company A gets detail -> 200
        get_a_res = await ac.get(f"/api/v1/ai/chat/conversations/{conv_id}", headers=headers_a)
        assert get_a_res.status_code == 200
        assert get_a_res.json()["data"]["conversationId"] == conv_id

        # 5. Company A deletes conversation -> 200
        del_a_res = await ac.delete(f"/api/v1/ai/chat/conversations/{conv_id}", headers=headers_a)
        assert del_a_res.status_code == 200
        assert del_a_res.json()["data"]["deleted"] is True


@pytest.mark.asyncio
async def test_history_and_feedback_endpoints(token_company_a: str):
    """Test /history endpoints, suggestions, and feedback."""
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {token_company_a}"}

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Create a conversation
        create_res = await ac.post(
            "/api/v1/ai/chat",
            json={"message": "Can you generate a summary of our leave policies?"},
            headers=headers,
        )
        assert create_res.status_code == 200
        conv_id = create_res.json()["data"]["conversation_id"]

        # 2. Get history detail via /history/{conv_id}
        hist_detail_res = await ac.get(f"/api/v1/ai/chat/history/{conv_id}", headers=headers)
        assert hist_detail_res.status_code == 200
        assert hist_detail_res.json()["data"]["conversation_id"] == conv_id

        # 3. Suggestions via /suggestions
        sugg_res = await ac.get("/api/v1/ai/chat/suggestions", headers=headers)
        assert sugg_res.status_code == 200
        sugg_data = sugg_res.json()["data"]
        assert "suggested_prompts" in sugg_data

        # 4. Feedback via /feedback
        fb_res = await ac.post(
            "/api/v1/ai/chat/feedback",
            json={"conversation_id": conv_id, "rating": 5, "feedback": "Very helpful!"},
            headers=headers,
        )
        assert fb_res.status_code == 200
        assert fb_res.json()["data"]["rating"] == 5

        # 5. Delete via /history/{conv_id}
        del_res = await ac.delete(f"/api/v1/ai/chat/history/{conv_id}", headers=headers)
        assert del_res.status_code == 200
        assert del_res.json()["data"]["deleted"] is True


@pytest.mark.asyncio
async def test_specialized_ai_chat_endpoints(token_company_a: str):
    """Test /report, /analytics, /recommendations specialized chat endpoints."""
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {token_company_a}"}

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Report
        report_res = await ac.post(
            "/api/v1/ai/chat/report",
            json={"report_type": "ATTENDANCE", "date_range": "2026-07-01 to 2026-07-24"},
            headers=headers,
        )
        assert report_res.status_code == 200
        assert report_res.json()["data"]["answer"]

        # Analytics
        analytics_res = await ac.post(
            "/api/v1/ai/chat/analytics",
            json={"metric_type": "HEADCOUNT"},
            headers=headers,
        )
        assert analytics_res.status_code == 200
        assert analytics_res.json()["data"]["answer"]

        # Recommendations
        rec_res = await ac.post(
            "/api/v1/ai/chat/recommendations",
            json={"domain": "RETENTION"},
            headers=headers,
        )
        assert rec_res.status_code == 200
        assert rec_res.json()["data"]["answer"]


@pytest.mark.asyncio
async def test_ai_hub_backward_compatibility_endpoints(token_company_a: str):
    """Verify that legacy /api/v1/ai-hub/chat-assistant/* endpoints work via compatibility bridge."""
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {token_company_a}"}

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create
        create_res = await ac.post(
            "/api/v1/ai-hub/chat-assistant/conversations",
            json={"title": "Compatibility Test", "initialMessage": "Hello from legacy frontend"},
            headers=headers,
        )
        assert create_res.status_code == 201
        conv_id = create_res.json()["data"]["conversationId"]

        # List
        list_res = await ac.get("/api/v1/ai-hub/chat-assistant/conversations", headers=headers)
        assert list_res.status_code == 200

        # Detail
        detail_res = await ac.get(f"/api/v1/ai-hub/chat-assistant/conversations/{conv_id}", headers=headers)
        assert detail_res.status_code == 200

        # Message
        msg_res = await ac.post(
            "/api/v1/ai-hub/chat-assistant/message",
            json={"conversationId": conv_id, "content": "Follow up question"},
            headers=headers,
        )
        assert msg_res.status_code == 200

        # Delete
        del_res = await ac.delete(f"/api/v1/ai-hub/chat-assistant/conversations/{conv_id}", headers=headers)
        assert del_res.status_code == 200


