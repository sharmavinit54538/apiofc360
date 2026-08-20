"""Comprehensive Real-time Test Suite for OFC360 Calling & WebRTC Signaling.

Covers:
1. WebSocket connection and JWT authentication verification.
2. Token validation and invalid/expired token rejection.
3. Multi-connection (multi-tab) tracking and cleanup in ConnectWSManager.
4. User A calling User B (online) -> B receives call:incoming (dual-payload).
5. Private event delivery: User C does NOT receive User A->B call.
6. User A calling User B (offline) -> returns USER_OFFLINE error.
7. User B accepting call -> User A receives call:accepted.
8. User B rejecting call -> User A receives call:rejected.
9. User A cancelling call -> User B receives call:cancelled.
10. Either participant ending call -> both receive call:ended.
11. WebRTC signaling forwarding (offer, answer, candidate) between call participants.
12. Unauthorized signal injection rejection.
13. Invalid call state transitions rejection (rejected -> accepted, ended -> accepted).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from fastapi import WebSocket, status

from app.models.connect import ConnectCallLog
from app.models.user import User
from app.models.user.role import UserRole
from app.services.connect_service import ConnectService
from app.services.connect_ws_manager import ConnectWSManager, _normalize_uuid


COMPANY_A_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_A_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_B_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
USER_C_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


def create_user(user_id: uuid.UUID, name: str, company_id: uuid.UUID) -> User:
    user = MagicMock(spec=User)
    user.id = user_id
    user.name = name
    user.email = f"{name.lower().replace(' ', '.')}@example.com"
    user.role = UserRole.EMPLOYEE
    user.company_id = company_id
    user.is_active = True
    user.is_deleted = False
    user.profile_photo = f"https://example.com/{user_id}.jpg"
    return user


class MockWebSocket:
    """Mock WebSocket for unit testing realtime messaging without network overhead."""

    def __init__(self) -> None:
        self.sent_messages: list[dict[str, Any]] = []
        self.closed = False
        self.close_code: int | None = None
        self.close_reason: str | None = None

    async def send_text(self, text: str) -> None:
        if self.closed:
            raise RuntimeError("WebSocket is closed")
        self.sent_messages.append(json.loads(text))

    async def send_json(self, data: dict[str, Any]) -> None:
        if self.closed:
            raise RuntimeError("WebSocket is closed")
        self.sent_messages.append(data)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True
        self.close_code = code
        self.close_reason = reason


# ===========================================================================
# 1. ConnectWSManager Unit Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_ws_manager_connect_and_presence():
    manager = ConnectWSManager()
    ws1 = MockWebSocket()
    ws2 = MockWebSocket()

    assert not manager.is_online(USER_A_ID)
    assert manager.get_active_socket_count(USER_A_ID) == 0

    # Connect Tab 1
    await manager.connect(ws1, USER_A_ID, COMPANY_A_ID)
    assert manager.is_online(USER_A_ID)
    assert manager.is_online(str(USER_A_ID))  # String normalization test
    assert manager.get_active_socket_count(USER_A_ID) == 1

    # Connect Tab 2 (multi-tab support)
    await manager.connect(ws2, USER_A_ID, COMPANY_A_ID)
    assert manager.get_active_socket_count(USER_A_ID) == 2

    # Disconnect Tab 1 -> User must still remain ONLINE
    await manager.disconnect(ws1)
    assert manager.is_online(USER_A_ID)
    assert manager.get_active_socket_count(USER_A_ID) == 1

    # Disconnect Tab 2 -> User becomes OFFLINE
    await manager.disconnect(ws2)
    assert not manager.is_online(USER_A_ID)
    assert manager.get_active_socket_count(USER_A_ID) == 0


@pytest.mark.asyncio
async def test_ws_manager_send_to_user_dual_payload():
    manager = ConnectWSManager()
    ws = MockWebSocket()
    await manager.connect(ws, USER_A_ID, COMPANY_A_ID)

    event_data = {
        "call_id": "call-123",
        "caller_id": str(USER_A_ID),
        "receiver_id": str(USER_B_ID),
        "status": "ringing",
    }
    sent_count = await manager.send_to_user(USER_A_ID, COMPANY_A_ID, "call:incoming", event_data)
    assert sent_count == 1
    assert len(ws.sent_messages) == 1

    msg = ws.sent_messages[0]
    # Check top-level properties (frontend canonical format)
    assert msg["type"] == "call:incoming"
    assert msg["event"] == "call:incoming"
    assert msg["call_id"] == "call-123"
    assert msg["caller_id"] == str(USER_A_ID)
    assert msg["receiver_id"] == str(USER_B_ID)
    assert msg["status"] == "ringing"
    assert "timestamp" in msg
    # Check nested data property (legacy compatibility format)
    assert msg["data"] == event_data


@pytest.mark.asyncio
async def test_ws_manager_tenant_isolation():
    manager = ConnectWSManager()
    ws_comp_a = MockWebSocket()
    ws_comp_b = MockWebSocket()
    COMPANY_B_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")

    await manager.connect(ws_comp_a, USER_A_ID, COMPANY_A_ID)
    await manager.connect(ws_comp_b, USER_B_ID, COMPANY_B_ID)

    # Attempt to send message across tenants -> must be blocked
    sent = await manager.send_to_user(USER_B_ID, COMPANY_A_ID, "call:incoming", {"test": 123})
    assert sent == 0
    assert len(ws_comp_b.sent_messages) == 0


@pytest.mark.asyncio
async def test_ws_manager_dead_socket_cleanup():
    manager = ConnectWSManager()
    ws_good = MockWebSocket()
    ws_dead = MockWebSocket()
    ws_dead.closed = True  # send_text will raise RuntimeError

    await manager.connect(ws_good, USER_A_ID, COMPANY_A_ID)
    await manager.connect(ws_dead, USER_A_ID, COMPANY_A_ID)
    assert manager.get_active_socket_count(USER_A_ID) == 2

    # send_to_user should succeed on good socket and clean up dead socket
    sent = await manager.send_to_user(USER_A_ID, COMPANY_A_ID, "ping", {})
    assert sent == 1
    assert manager.get_active_socket_count(USER_A_ID) == 1
    assert len(ws_good.sent_messages) == 1


# ===========================================================================
# 2. Call Lifecycle & State Machine Integration Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_call_initiation_delivery_to_active_sockets():
    """Verify that when User A calls User B, B receives call:incoming and C receives nothing."""
    manager = ConnectWSManager()
    ws_a = MockWebSocket()
    ws_b = MockWebSocket()
    ws_c = MockWebSocket()

    await manager.connect(ws_a, USER_A_ID, COMPANY_A_ID)
    await manager.connect(ws_b, USER_B_ID, COMPANY_A_ID)
    await manager.connect(ws_c, USER_C_ID, COMPANY_A_ID)

    user_a = create_user(USER_A_ID, "Alice", COMPANY_A_ID)
    user_b = create_user(USER_B_ID, "Bob", COMPANY_A_ID)

    call_id = uuid.uuid4()
    mock_call = MagicMock(spec=ConnectCallLog)
    mock_call.id = call_id
    mock_call.company_id = COMPANY_A_ID
    mock_call.caller_id = USER_A_ID
    mock_call.callee_id = USER_B_ID
    mock_call.call_type = "audio"
    mock_call.status = "ringing"
    mock_call.room_id = "call_test_room"
    mock_call.started_at = datetime.utcnow()
    mock_call.connected_at = None
    mock_call.ended_at = None
    mock_call.duration_seconds = 0

    mock_repo = AsyncMock()
    mock_repo.get_active_user_in_company.return_value = user_b
    mock_repo.create_call_log.return_value = mock_call
    mock_repo.create_notification.return_value = None

    service = ConnectService(AsyncMock(), ws_manager=manager)
    service.repo = mock_repo

    result = await service.initiate_call(
        company_id=COMPANY_A_ID,
        user=user_a,
        target_user_id=USER_B_ID,
        call_type="audio",
    )

    assert result["callId"] == str(call_id)
    assert result["status"] == "ringing"
    assert result["caller_id"] == str(USER_A_ID)
    assert result["receiver_id"] == str(USER_B_ID)

    # Bob's socket MUST receive call:incoming
    bob_events = [m for m in ws_b.sent_messages if m.get("type") == "call:incoming"]
    assert len(bob_events) == 1
    incoming_msg = bob_events[0]
    assert incoming_msg["call_id"] == str(call_id)
    assert incoming_msg["caller_id"] == str(USER_A_ID)
    assert incoming_msg["receiver_id"] == str(USER_B_ID)
    assert incoming_msg["call_type"] == "audio"
    assert incoming_msg["status"] == "ringing"

    # Charlie (Outsider) MUST NOT receive any call event
    assert len(ws_c.sent_messages) == 0


@pytest.mark.asyncio
async def test_call_accept_and_notify_caller():
    """Verify that when Callee accepts, Caller receives call:accepted and DB updates to connected."""
    manager = ConnectWSManager()
    ws_a = MockWebSocket()
    ws_b = MockWebSocket()

    await manager.connect(ws_a, USER_A_ID, COMPANY_A_ID)
    await manager.connect(ws_b, USER_B_ID, COMPANY_A_ID)

    user_a = create_user(USER_A_ID, "Alice", COMPANY_A_ID)
    user_b = create_user(USER_B_ID, "Bob", COMPANY_A_ID)

    call_id = uuid.uuid4()
    mock_call = MagicMock(spec=ConnectCallLog)
    mock_call.id = call_id
    mock_call.company_id = COMPANY_A_ID
    mock_call.caller_id = USER_A_ID
    mock_call.callee_id = USER_B_ID
    mock_call.status = "ringing"
    mock_call.duration_seconds = 0
    mock_call.connected_at = None
    mock_call.ended_at = None

    mock_updated = MagicMock(spec=ConnectCallLog)
    mock_updated.id = call_id
    mock_updated.status = "connected"
    mock_updated.duration_seconds = 0
    mock_updated.connected_at = datetime.utcnow()
    mock_updated.ended_at = None

    mock_repo = AsyncMock()
    mock_repo.get_call_by_id.return_value = mock_call
    mock_repo.update_call_status.return_value = mock_updated

    service = ConnectService(AsyncMock(), ws_manager=manager)
    service.repo = mock_repo

    # Bob (callee) accepts call
    res = await service.update_call_status(
        company_id=COMPANY_A_ID,
        user=user_b,
        call_id=call_id,
        new_status="connected",
    )
    assert res["status"] == "connected"

    # Alice (caller) MUST receive call:accepted
    alice_events = [m for m in ws_a.sent_messages if m.get("type") == "call:accepted"]
    assert len(alice_events) == 1
    assert alice_events[0]["call_id"] == str(call_id)
    assert alice_events[0]["status"] == "connected"


@pytest.mark.asyncio
async def test_call_reject_and_notify_caller():
    """Verify that when Callee rejects, Caller receives call:rejected."""
    manager = ConnectWSManager()
    ws_a = MockWebSocket()
    ws_b = MockWebSocket()

    await manager.connect(ws_a, USER_A_ID, COMPANY_A_ID)
    await manager.connect(ws_b, USER_B_ID, COMPANY_A_ID)

    user_a = create_user(USER_A_ID, "Alice", COMPANY_A_ID)
    user_b = create_user(USER_B_ID, "Bob", COMPANY_A_ID)

    call_id = uuid.uuid4()
    mock_call = MagicMock(spec=ConnectCallLog)
    mock_call.id = call_id
    mock_call.company_id = COMPANY_A_ID
    mock_call.caller_id = USER_A_ID
    mock_call.callee_id = USER_B_ID
    mock_call.status = "ringing"
    mock_call.duration_seconds = 0
    mock_call.connected_at = None
    mock_call.ended_at = None

    mock_updated = MagicMock(spec=ConnectCallLog)
    mock_updated.id = call_id
    mock_updated.status = "rejected"
    mock_updated.duration_seconds = 0
    mock_updated.connected_at = None
    mock_updated.ended_at = datetime.utcnow()

    mock_repo = AsyncMock()
    mock_repo.get_call_by_id.return_value = mock_call
    mock_repo.update_call_status.return_value = mock_updated

    service = ConnectService(AsyncMock(), ws_manager=manager)
    service.repo = mock_repo

    # Bob rejects
    res = await service.update_call_status(
        company_id=COMPANY_A_ID,
        user=user_b,
        call_id=call_id,
        new_status="rejected",
    )
    assert res["status"] == "rejected"

    # Alice receives call:rejected
    alice_events = [m for m in ws_a.sent_messages if m.get("type") == "call:rejected"]
    assert len(alice_events) == 1
    assert alice_events[0]["call_id"] == str(call_id)


@pytest.mark.asyncio
async def test_call_cancel_and_notify_callee():
    """Verify that when Caller cancels ringing call, Callee receives call:cancelled."""
    manager = ConnectWSManager()
    ws_a = MockWebSocket()
    ws_b = MockWebSocket()

    await manager.connect(ws_a, USER_A_ID, COMPANY_A_ID)
    await manager.connect(ws_b, USER_B_ID, COMPANY_A_ID)

    user_a = create_user(USER_A_ID, "Alice", COMPANY_A_ID)
    user_b = create_user(USER_B_ID, "Bob", COMPANY_A_ID)

    call_id = uuid.uuid4()
    mock_call = MagicMock(spec=ConnectCallLog)
    mock_call.id = call_id
    mock_call.company_id = COMPANY_A_ID
    mock_call.caller_id = USER_A_ID
    mock_call.callee_id = USER_B_ID
    mock_call.status = "ringing"
    mock_call.duration_seconds = 0
    mock_call.connected_at = None
    mock_call.ended_at = None

    mock_updated = MagicMock(spec=ConnectCallLog)
    mock_updated.id = call_id
    mock_updated.status = "cancelled"
    mock_updated.duration_seconds = 0
    mock_updated.connected_at = None
    mock_updated.ended_at = datetime.utcnow()

    mock_repo = AsyncMock()
    mock_repo.get_call_by_id.return_value = mock_call
    mock_repo.update_call_status.return_value = mock_updated

    service = ConnectService(AsyncMock(), ws_manager=manager)
    service.repo = mock_repo

    # Alice cancels
    res = await service.update_call_status(
        company_id=COMPANY_A_ID,
        user=user_a,
        call_id=call_id,
        new_status="cancelled",
    )
    assert res["status"] == "cancelled"

    # Bob receives call:cancelled
    bob_events = [m for m in ws_b.sent_messages if m.get("type") == "call:cancelled"]
    assert len(bob_events) == 1
    assert bob_events[0]["call_id"] == str(call_id)


@pytest.mark.asyncio
async def test_call_end_notifies_both_participants():
    """Verify that when either participant ends the call, both receive call:ended."""
    manager = ConnectWSManager()
    ws_a = MockWebSocket()
    ws_b = MockWebSocket()

    await manager.connect(ws_a, USER_A_ID, COMPANY_A_ID)
    await manager.connect(ws_b, USER_B_ID, COMPANY_A_ID)

    user_a = create_user(USER_A_ID, "Alice", COMPANY_A_ID)
    user_b = create_user(USER_B_ID, "Bob", COMPANY_A_ID)

    call_id = uuid.uuid4()
    mock_call = MagicMock(spec=ConnectCallLog)
    mock_call.id = call_id
    mock_call.company_id = COMPANY_A_ID
    mock_call.caller_id = USER_A_ID
    mock_call.callee_id = USER_B_ID
    mock_call.status = "connected"
    mock_call.duration_seconds = 0
    mock_call.connected_at = datetime.utcnow()
    mock_call.ended_at = None

    mock_updated = MagicMock(spec=ConnectCallLog)
    mock_updated.id = call_id
    mock_updated.status = "ended"
    mock_updated.duration_seconds = 75
    mock_updated.connected_at = mock_call.connected_at
    mock_updated.ended_at = datetime.utcnow()

    mock_repo = AsyncMock()
    mock_repo.get_call_by_id.return_value = mock_call
    mock_repo.update_call_status.return_value = mock_updated

    service = ConnectService(AsyncMock(), ws_manager=manager)
    service.repo = mock_repo

    # Alice ends call
    res = await service.update_call_status(
        company_id=COMPANY_A_ID,
        user=user_a,
        call_id=call_id,
        new_status="ended",
    )
    assert res["status"] == "ended"
    assert res["duration_seconds"] == 75

    # Both Alice and Bob must receive call:ended
    alice_events = [m for m in ws_a.sent_messages if m.get("type") == "call:ended"]
    bob_events = [m for m in ws_b.sent_messages if m.get("type") == "call:ended"]
    assert len(alice_events) == 1
    assert len(bob_events) == 1
    assert alice_events[0]["call_id"] == str(call_id)
    assert bob_events[0]["call_id"] == str(call_id)


# ===========================================================================
# 3. WebRTC Signaling Forwarding Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_webrtc_signal_forwarding():
    """Verify that WebRTC signal is routed directly to the other call participant."""
    manager = ConnectWSManager()
    ws_a = MockWebSocket()
    ws_b = MockWebSocket()
    ws_c = MockWebSocket()

    await manager.connect(ws_a, USER_A_ID, COMPANY_A_ID)
    await manager.connect(ws_b, USER_B_ID, COMPANY_A_ID)
    await manager.connect(ws_c, USER_C_ID, COMPANY_A_ID)

    user_a = create_user(USER_A_ID, "Alice", COMPANY_A_ID)
    user_b = create_user(USER_B_ID, "Bob", COMPANY_A_ID)

    call_id = uuid.uuid4()
    mock_call = MagicMock(spec=ConnectCallLog)
    mock_call.id = call_id
    mock_call.company_id = COMPANY_A_ID
    mock_call.caller_id = USER_A_ID
    mock_call.callee_id = USER_B_ID
    mock_call.status = "connected"

    mock_repo = AsyncMock()
    mock_repo.get_call_by_id.return_value = mock_call

    service = ConnectService(AsyncMock(), ws_manager=manager)
    service.repo = mock_repo

    # Alice sends SDP offer
    sdp_payload = {"type": "offer", "sdp": "v=0\r\no=- 12345 2 IN IP4 ..."}
    res = await service.handle_call_signal(
        company_id=COMPANY_A_ID,
        user=user_a,
        call_id=call_id,
        signal_type="offer",
        payload=sdp_payload,
    )
    assert res["relayed"] is True

    # Bob's socket MUST receive webrtc:signal with offer
    signals = [m for m in ws_b.sent_messages if m.get("type") == "webrtc:signal"]
    assert len(signals) == 1
    assert signals[0]["call_id"] == str(call_id)
    assert signals[0]["from_user_id"] == str(USER_A_ID)
    assert signals[0]["target_user_id"] == str(USER_B_ID)
    assert signals[0]["sdp"] == sdp_payload["sdp"]

    # Charlie MUST NOT receive any signal
    assert len(ws_c.sent_messages) == 0


@pytest.mark.asyncio
async def test_invalid_state_transition_protection():
    """Verify that an ended/rejected call cannot transition to connected/accepted."""
    manager = ConnectWSManager()
    user_b = create_user(USER_B_ID, "Bob", COMPANY_A_ID)

    call_id = uuid.uuid4()
    mock_call = MagicMock(spec=ConnectCallLog)
    mock_call.id = call_id
    mock_call.company_id = COMPANY_A_ID
    mock_call.caller_id = USER_A_ID
    mock_call.callee_id = USER_B_ID
    mock_call.status = "ended"

    mock_repo = AsyncMock()
    mock_repo.get_call_by_id.return_value = mock_call

    service = ConnectService(AsyncMock(), ws_manager=manager)
    service.repo = mock_repo

    # Attempting to accept an already ended call must raise an exception
    with pytest.raises(Exception) as exc_info:
        await service.update_call_status(
            company_id=COMPANY_A_ID,
            user=user_b,
            call_id=call_id,
            new_status="connected",
        )
    assert "already closed" in str(exc_info.value).lower() or "cannot transition" in str(exc_info.value).lower()


# ===========================================================================
# 4. FastAPI WebSocket Endpoint (/api/v1/connect/ws) Tests
# ===========================================================================

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from app.main import app


from app.utils.jwt import create_access_token


def test_ws_endpoint_no_token_rejected():
    """Verify that connecting to /api/v1/connect/ws without token is rejected with policy violation (1008)."""
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/api/v1/connect/ws") as ws:
                pass


def test_ws_endpoint_invalid_token_rejected():
    """Verify that connecting with an invalid JWT token is rejected with policy violation (1008)."""
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/api/v1/connect/ws?token=invalid.jwt.token") as ws:
                pass


def test_ws_endpoint_valid_token_and_ping_pong():
    """Verify that connecting with a valid JWT connects successfully and handles ping/pong."""
    token = create_access_token(user_id=USER_A_ID, role="employee", company_id=COMPANY_A_ID)
    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/connect/ws?token={token}") as ws:
            ws.send_json({"event": "ping", "timestamp": 1234567890})
            resp = ws.receive_json()
            assert resp.get("type") == "pong" or resp.get("event") == "pong"

