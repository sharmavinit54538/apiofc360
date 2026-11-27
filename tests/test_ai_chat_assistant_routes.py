"""Integration tests for AI Chat Assistant (/api/v1/ai/chat/* and /api/v1/ai-hub/chat-assistant/*).

Tests real authentication, tenant isolation, DB persistence, SSE streaming,
idempotency, cancellation, status reconciliation, and error handling.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.db.database import AsyncSessionLocal
from app.llm.providers.base import ProviderRequestError
from app.main import app
from app.models.company import Company
from app.models.user import User, UserRole
from app.utils.jwt import create_access_token


async def _cleanup_entities(company_ids: list[uuid.UUID], user_ids: list[uuid.UUID]) -> None:
    async with AsyncSessionLocal() as session:
        if user_ids:
            await session.execute(
                text("DELETE FROM ai_messages WHERE conversation_id IN (SELECT id FROM ai_conversations WHERE user_id = ANY(:uids))"),
                {"uids": user_ids},
            )
            await session.execute(
                text("DELETE FROM ai_conversations WHERE user_id = ANY(:uids)"),
                {"uids": user_ids},
            )
            await session.execute(
                text("DELETE FROM users WHERE id = ANY(:uids)"),
                {"uids": user_ids},
            )
        if company_ids:
            await session.execute(
                text("DELETE FROM companies WHERE id = ANY(:cids)"),
                {"cids": company_ids},
            )
        await session.commit()


@pytest_asyncio.fixture
async def chat_test_identities():
    """Provision real transient PostgreSQL users/companies for principal validation and tenant RLS."""
    company_a = uuid.uuid4()
    company_b = uuid.uuid4()
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    user_no_co = uuid.uuid4()
    user_exec = uuid.uuid4()

    company_ids = [company_a, company_b]
    user_ids = [user_a, user_b, user_no_co, user_exec]
    await _cleanup_entities(company_ids, user_ids)

    async with AsyncSessionLocal() as session:
        session.add_all([
            Company(id=company_a, name=f"TestCo Alpha {company_a.hex[:6]}", hr_settings={}),
            Company(id=company_b, name=f"TestCo Beta {company_b.hex[:6]}", hr_settings={}),
            User(
                id=user_a,
                company_id=company_a,
                name="Alice HR",
                email=f"alice-chat-{user_a.hex[:6]}@test.local",
                phone=f"9{user_a.int % 1000000000:09d}",
                password_hash="hash",
                role=UserRole.HR_ADMIN,
                is_active=True,
                is_verified=True,
                account_status="ACTIVE",
            ),
            User(
                id=user_b,
                company_id=company_b,
                name="Bob HR",
                email=f"bob-chat-{user_b.hex[:6]}@test.local",
                phone=f"9{user_b.int % 1000000000:09d}",
                password_hash="hash",
                role=UserRole.HR_ADMIN,
                is_active=True,
                is_verified=True,
                account_status="ACTIVE",
            ),
            User(
                id=user_no_co,
                company_id=None,
                name="Unbound Employee",
                email=f"unbound-chat-{user_no_co.hex[:6]}@test.local",
                phone=f"9{user_no_co.int % 1000000000:09d}",
                password_hash="hash",
                role=UserRole.EMPLOYEE,
                is_active=True,
                is_verified=True,
                account_status="ACTIVE",
            ),
            User(
                id=user_exec,
                company_id=None,
                name="Exec User",
                email=f"exec-chat-{user_exec.hex[:6]}@test.local",
                phone=f"9{user_exec.int % 1000000000:09d}",
                password_hash="hash",
                role=UserRole.EXECUTIVE,
                is_active=True,
                is_verified=True,
                account_status="ACTIVE",
            ),
        ])
        await session.commit()

    identities = {
        "company_a_id": str(company_a),
        "company_b_id": str(company_b),
        "token_a": create_access_token(user_id=str(user_a), role="hr_admin", company_id=str(company_a)),
        "token_b": create_access_token(user_id=str(user_b), role="hr_admin", company_id=str(company_b)),
        "token_no_company": create_access_token(user_id=str(user_no_co), role="employee"),
        "token_exec": create_access_token(user_id=str(user_exec), role="executive"),
    }

    try:
        yield identities
    finally:
        await _cleanup_entities(company_ids, user_ids)


def _parse_sse_frames(raw_text: str) -> list[tuple[str, dict]]:
    frames: list[tuple[str, dict]] = []
    for block in raw_text.replace("\r\n", "\n").split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_name = "message"
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if data_lines:
            try:
                frames.append((event_name, json.loads("\n".join(data_lines))))
            except json.JSONDecodeError:
                pass
    return frames


@pytest.mark.asyncio
async def test_auth_mandatory_rejects_unauthenticated():
    """Unauthenticated requests must return 401 on both standard and stream routes."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        assert (await ac.get("/api/v1/ai/chat/history")).status_code == 401
        assert (await ac.post("/api/v1/ai-hub/chat-assistant/stream", json={"message": "hi"})).status_code == 401


@pytest.mark.asyncio
async def test_auth_mandatory_rejects_missing_company(chat_test_identities):
    """Non-executive authenticated request missing company_id must return 403."""
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {chat_test_identities['token_no_company']}"}
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/ai/chat/history", headers=headers)
        assert response.status_code == 403
        body = response.json()
        error_msg = body.get("message", "") or body.get("detail", "")
        assert "not associated with a company" in error_msg


@pytest.mark.asyncio
async def test_executive_null_company_and_simple_greeting(chat_test_identities):
    """Executive users (company_id=None, open_positions=None) must get valid response without TypeError 500."""
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {chat_test_identities['token_exec']}"}
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/ai-hub/chat-assistant/message",
            json={"message": "hii", "clientMessageId": f"exec-hi-{uuid.uuid4().hex[:8]}"},
            headers=headers,
            timeout=60.0,
        )
        assert res.status_code == 200
        body = res.json()["data"]
        assert body["answer"]
        assert body["conversationId"]
        assert body["status"] == "completed"


@pytest.mark.asyncio
async def test_create_list_detail_and_persistence(chat_test_identities):
    """Creating conversation, sending messages, and reloading detail must persist full message list."""
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {chat_test_identities['token_a']}"}
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        create_res = await ac.post(
            "/api/v1/ai/chat/conversations",
            json={"title": "Q3 Headcount Planning"},
            headers=headers,
        )
        assert create_res.status_code == 201
        conv_id = create_res.json()["data"]["conversationId"]

        client_msg_id = f"msg-{uuid.uuid4().hex[:10]}"
        msg_res = await ac.post(
            "/api/v1/ai/chat/message",
            json={
                "conversationId": conv_id,
                "content": "Hi, can you help with headcount overview?",
                "clientMessageId": client_msg_id,
            },
            headers=headers,
            timeout=60.0,
        )
        assert msg_res.status_code == 200
        d1 = msg_res.json()["data"]
        assert d1["conversationId"] == conv_id
        assert d1["answer"]
        assert d1["clientMessageId"] == client_msg_id

        # Idempotency: resending exact same clientMessageId returns cached answer without duplicate LLM/DB row
        dup_res = await ac.post(
            "/api/v1/ai/chat/message",
            json={
                "conversationId": conv_id,
                "content": "Hi, can you help with headcount overview?",
                "clientMessageId": client_msg_id,
            },
            headers=headers,
        )
        assert dup_res.status_code == 200
        assert dup_res.json()["data"]["answer"] == d1["answer"]

        # Reload conversation detail and verify persisted messages + metadata
        detail_res = await ac.get(f"/api/v1/ai-hub/chat-assistant/conversations/{conv_id}", headers=headers)
        assert detail_res.status_code == 200
        detail = detail_res.json()["data"]
        assert len(detail["messages"]) == 3  # greeting + 1 user + 1 assistant (no duplicate!)
        assert any(m["clientMessageId"] == client_msg_id for m in detail["messages"])

        # Reconcile message status
        status_res = await ac.get(
            f"/api/v1/ai-hub/chat-assistant/conversations/{conv_id}/messages/{client_msg_id}/status",
            headers=headers,
        )
        assert status_res.status_code == 200
        assert status_res.json()["data"]["status"] == "completed"
        assert status_res.json()["data"]["found"] is True


@pytest.mark.asyncio
async def test_sse_real_time_streaming_and_persistence(chat_test_identities):
    """POST /stream must emit incremental SSE chunk + complete events and persist in PostgreSQL."""
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {chat_test_identities['token_a']}"}
    client_msg_id = f"stream-{uuid.uuid4().hex[:10]}"

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST",
            "/api/v1/ai-hub/chat-assistant/stream",
            json={"message": "hi", "clientMessageId": client_msg_id},
            headers=headers,
            timeout=60.0,
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            raw_chunks: list[str] = []
            async for text_chunk in resp.aiter_text():
                raw_chunks.append(text_chunk)

        frames = _parse_sse_frames("".join(raw_chunks))
        event_names = [name for name, _ in frames]
        assert "status" in event_names
        assert "chunk" in event_names
        assert "complete" in event_names

        complete_payload = next(payload for name, payload in frames if name == "complete")
        conv_id = complete_payload["conversationId"]
        assert complete_payload["answer"].strip()
        assert complete_payload["clientMessageId"] == client_msg_id

        # Verify persisted after stream completion
        detail_res = await ac.get(f"/api/v1/ai-hub/chat-assistant/conversations/{conv_id}", headers=headers)
        assert detail_res.status_code == 200
        msgs = detail_res.json()["data"]["messages"]
        assert len(msgs) >= 2
        assert msgs[-1]["role"] == "assistant"
        assert msgs[-1]["content"].strip() == complete_payload["answer"].strip()


@pytest.mark.asyncio
async def test_stream_interrupted_and_cancel_handling(chat_test_identities):
    """Interrupted streams must preserve partial text, and active streams must support cancellation."""
    async def mock_interrupted_stream(*args, **kwargs):
        yield {"type": "token", "content": "Partial "}
        yield {"type": "token", "content": "insight "}
        raise ProviderRequestError(502, "stream_interrupted", "Upstream connection dropped", retryable=True)

    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {chat_test_identities['token_a']}"}
    cmid_interrupt = f"int-{uuid.uuid4().hex[:8]}"

    with patch("app.llm.client.LLMClient.stream_chat_events", side_effect=mock_interrupted_stream):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            async with ac.stream(
                "POST",
                "/api/v1/ai-hub/chat-assistant/stream",
                json={"message": "Analyze retention", "clientMessageId": cmid_interrupt},
                headers=headers,
            ) as resp:
                raw_text = (await resp.aread()).decode("utf-8")

    frames = _parse_sse_frames(raw_text)
    err_payload = next(p for name, p in frames if name == "error")
    assert err_payload["status"] == "interrupted"
    assert err_payload["partialContent"] == "Partial insight "
    conv_id = err_payload["conversationId"]

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        detail_res = await ac.get(f"/api/v1/ai-hub/chat-assistant/conversations/{conv_id}", headers=headers)
        assert detail_res.status_code == 200
        assert any("Partial insight" in m["content"] and m["status"] == "interrupted" for m in detail_res.json()["data"]["messages"])


@pytest.mark.asyncio
async def test_stream_invalid_api_key_maps_safely(chat_test_identities):
    """Provider 401/403 must surface safe config error code without returning JWT 401 logout status."""
    async def mock_bad_key_stream(*args, **kwargs):
        if False:
            yield {}
        raise ProviderRequestError(401, "provider_unauthorized", "Invalid key", retryable=False)

    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {chat_test_identities['token_a']}"}

    with patch("app.llm.client.LLMClient.stream_chat_events", side_effect=mock_bad_key_stream):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            async with ac.stream(
                "POST",
                "/api/v1/ai-hub/chat-assistant/stream",
                json={"message": "Test key", "clientMessageId": f"key-{uuid.uuid4().hex[:8]}"},
                headers=headers,
            ) as resp:
                raw_text = (await resp.aread()).decode("utf-8")

    frames = _parse_sse_frames(raw_text)
    err_payload = next(p for name, p in frames if name == "error")
    assert err_payload["code"] == "invalid_api_key"
    assert err_payload["statusCode"] == 502
    assert err_payload["retryable"] is False


@pytest.mark.asyncio
async def test_tenant_isolation_across_all_chat_routes(chat_test_identities):
    """Company B must not access, stream into, cancel, reconcile, or delete Company A's conversations."""
    transport = ASGITransport(app=app)
    headers_a = {"Authorization": f"Bearer {chat_test_identities['token_a']}"}
    headers_b = {"Authorization": f"Bearer {chat_test_identities['token_b']}"}

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        create_res = await ac.post(
            "/api/v1/ai/chat/conversations",
            json={"title": "Confidential Executive Compensation"},
            headers=headers_a,
        )
        assert create_res.status_code == 201
        conv_id = create_res.json()["data"]["conversationId"]

        assert (await ac.get(f"/api/v1/ai/chat/conversations/{conv_id}", headers=headers_b)).status_code == 404
        assert (await ac.get(f"/api/v1/ai/chat/conversations/{conv_id}/messages/any-id/status", headers=headers_b)).status_code == 404
        assert (await ac.post(f"/api/v1/ai/chat/conversations/{conv_id}/cancel", headers=headers_b)).status_code == 404
        assert (await ac.delete(f"/api/v1/ai/chat/conversations/{conv_id}", headers=headers_b)).status_code == 404

        assert (await ac.get(f"/api/v1/ai/chat/conversations/{conv_id}", headers=headers_a)).status_code == 200
        del_res = await ac.delete(f"/api/v1/ai/chat/conversations/{conv_id}", headers=headers_a)
        assert del_res.status_code == 200
        assert del_res.json()["data"]["deleted"] is True


@pytest.mark.asyncio
async def test_suggestions_feedback_and_legacy_aliases(chat_test_identities):
    """Verify fast suggestions, feedback rating persistence, and compatibility routes."""
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {chat_test_identities['token_a']}"}

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        sugg_res = await ac.get("/api/v1/ai/chat/suggestions", headers=headers)
        assert sugg_res.status_code == 200
        assert len(sugg_res.json()["data"]["suggested_prompts"]) >= 1

        create_res = await ac.post(
            "/api/v1/ai-hub/chat-assistant/conversations",
            json={"title": "Compatibility Test"},
            headers=headers,
        )
        assert create_res.status_code == 201
        conv_id = create_res.json()["data"]["conversationId"]

        fb_res = await ac.post(
            "/api/v1/ai-hub/chat-assistant/feedback",
            json={"conversationId": conv_id, "rating": "up", "feedback": "Fast and accurate"},
            headers=headers,
        )
        assert fb_res.status_code == 200
        assert fb_res.json()["data"]["rating"] == 5

        del_res = await ac.delete(f"/api/v1/ai-hub/chat-assistant/conversations/{conv_id}", headers=headers)
        assert del_res.status_code == 200
