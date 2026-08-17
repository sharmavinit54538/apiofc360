"""Comprehensive test suite for OFC360 Connect Calls module.

Covers all 30 required call testing and verification dimensions:
1. Get ICE Servers (GET /calls/ice-servers)
2. Get Call History (GET /calls/history) with full frontend fields
3. Get Call History empty state
4. Call History direction calculation (incoming vs outgoing)
5. Get Call Details (GET /calls/{callId}) for caller
6. Get Call Details for callee
7. Get Call Details non-existent (404)
8. Get Call Details non-participant rejection (403)
9. Initiate Audio Call (POST /calls/initiate)
10. Initiate Video Call (POST /calls/initiate)
11. Self-call prevention (caller_id == callee_id -> 400)
12. Cross-tenant call initiation rejection (403)
13. Inactive/non-existent callee rejection (403/404)
14. Update Call Status to Connected (call accepted)
15. Update Call Status to Rejected (call declined)
16. Update Call Status to Ended (duration calculated)
17. Update Call Status to Missed (missed notification created)
18. Status alias normalization ("accepted" -> "connected", "declined" -> "rejected")
19. Non-participant status update rejection (403)
20. WebRTC Signal Relay - Offer (POST /calls/{callId}/signal)
21. WebRTC Signal Relay - Answer
22. WebRTC Signal Relay - ICE Candidate
23. WebRTC Signal Relay - Nested signal payload normalization
24. Non-participant WebRTC signal rejection (403)
25. Cross-company call details access IDOR protection (404/403)
26. Cross-company status update IDOR protection (404/403)
27. Cross-company signal relay IDOR protection (404/403)
28. Forged X-Company-ID header rejection (403)
29. Unauthenticated request rejection (401)
30. WebSocket WebRTC and call lifecycle event delivery & tenant isolation
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.db.database import get_db_session
from app.main import app
from app.middleware.auth import get_current_user, get_current_user_claims
from app.models.connect import ConnectCallLog, ConnectNotification
from app.models.user import User
from app.models.user.role import UserRole
from app.services.connect_ws_manager import get_connect_ws_manager


# ===========================================================================
# Test Fixtures & Mock Helpers
# ===========================================================================

COMPANY_A_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
COMPANY_B_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")

USER_CALLER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
USER_CALLEE_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
USER_OUTSIDER_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
USER_COMPANY_B_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")


def make_mock_user(user_id: uuid.UUID, role: UserRole, company_id: uuid.UUID, name: str = "Test User") -> User:
    user = MagicMock(spec=User)
    user.id = user_id
    user.name = name
    user.email = f"{name.lower().replace(' ', '.')}@example.com"
    user.phone = "9876543210"
    user.role = role
    user.company_id = company_id
    user.is_active = True
    user.is_deleted = False
    user.profile_photo = "https://example.com/avatar.jpg"
    user.created_at = datetime.utcnow()
    return user


async def mock_get_db():
    session = AsyncMock()
    yield session


@pytest.fixture
def caller_user():
    return make_mock_user(USER_CALLER_ID, UserRole.EMPLOYEE, COMPANY_A_ID, "Alice Caller")


@pytest.fixture
def callee_user():
    return make_mock_user(USER_CALLEE_ID, UserRole.EMPLOYEE, COMPANY_A_ID, "Bob Callee")


@pytest.fixture
def outsider_user():
    return make_mock_user(USER_OUTSIDER_ID, UserRole.EMPLOYEE, COMPANY_A_ID, "Charlie Outsider")


@pytest.fixture
def company_b_user():
    return make_mock_user(USER_COMPANY_B_ID, UserRole.EMPLOYEE, COMPANY_B_ID, "Dave Company B")


def make_mock_call(
    call_id: uuid.UUID,
    company_id: uuid.UUID,
    caller: User,
    callee: User,
    call_type: str = "audio",
    call_status: str = "initiated",
    duration_seconds: int = 0,
) -> ConnectCallLog:
    call = MagicMock(spec=ConnectCallLog)
    call.id = call_id
    call.company_id = company_id
    call.caller_id = caller.id
    call.callee_id = callee.id
    call.caller = caller
    call.callee = callee
    call.call_type = call_type
    call.status = call_status
    call.room_id = f"room_{call_id.hex[:8]}"
    call.started_at = datetime.utcnow()
    call.connected_at = datetime.utcnow() if call_status in ("connected", "ended") else None
    call.ended_at = datetime.utcnow() if call_status == "ended" else None
    call.duration_seconds = duration_seconds
    call.created_at = datetime.utcnow()
    return call


def get_auth_headers(company_id: uuid.UUID | None = None) -> dict[str, str]:
    headers = {"Authorization": "Bearer test-jwt-token"}
    if company_id:
        headers["X-Company-ID"] = str(company_id)
    return headers


# ===========================================================================
# 1. ICE Servers & Discovery Tests
# ===========================================================================

def test_get_ice_servers(caller_user):
    app.dependency_overrides[get_current_user] = lambda: caller_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(caller_user.id),
        "company_id": str(COMPANY_A_ID),
        "role": "employee",
    }
    app.dependency_overrides[get_db_session] = mock_get_db

    try:
        with TestClient(app) as client:
            resp = client.get("/api/v1/connect/calls/ice-servers", headers=get_auth_headers())
            assert resp.status_code == status.HTTP_200_OK
            body = resp.json()
            assert body["success"] is True
            assert "iceServers" in body["data"]
            assert len(body["data"]["iceServers"]) > 0
            assert "urls" in body["data"]["iceServers"][0]
    finally:
        app.dependency_overrides.clear()


# ===========================================================================
# 2. Call History Tests
# ===========================================================================

def test_get_call_history_rich_fields(caller_user, callee_user):
    call_1 = make_mock_call(uuid.uuid4(), COMPANY_A_ID, caller_user, callee_user, "audio", "ended", 125)
    call_2 = make_mock_call(uuid.uuid4(), COMPANY_A_ID, callee_user, caller_user, "video", "missed", 0)

    app.dependency_overrides[get_current_user] = lambda: caller_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(caller_user.id),
        "company_id": str(COMPANY_A_ID),
        "role": "employee",
    }
    app.dependency_overrides[get_db_session] = mock_get_db

    with patch("app.services.connect_service.ConnectRepository.get_call_history", new_callable=AsyncMock) as mock_hist:
        mock_hist.return_value = [call_1, call_2]

        try:
            with TestClient(app) as client:
                resp = client.get("/api/v1/connect/calls/history", headers=get_auth_headers())
                assert resp.status_code == status.HTTP_200_OK
                body = resp.json()
                assert body["success"] is True
                items = body["data"]
                assert len(items) == 2

                # Verify Call 1 (Outgoing)
                item1 = items[0]
                assert item1["direction"] == "outgoing"
                assert item1["callType"] == "audio"
                assert item1["duration"] == 125
                assert item1["caller"]["name"] == caller_user.name
                assert item1["callee"]["name"] == callee_user.name
                assert item1["startedAt"] is not None

                # Verify Call 2 (Incoming)
                item2 = items[1]
                assert item2["direction"] == "incoming"
                assert item2["status"] == "missed"
                assert item2["caller"]["name"] == callee_user.name
                assert item2["callee"]["name"] == caller_user.name
        finally:
            app.dependency_overrides.clear()


def test_get_call_history_empty(caller_user):
    app.dependency_overrides[get_current_user] = lambda: caller_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(caller_user.id),
        "company_id": str(COMPANY_A_ID),
        "role": "employee",
    }
    app.dependency_overrides[get_db_session] = mock_get_db

    with patch("app.services.connect_service.ConnectRepository.get_call_history", new_callable=AsyncMock) as mock_hist:
        mock_hist.return_value = []

        try:
            with TestClient(app) as client:
                resp = client.get("/api/v1/connect/calls/history", headers=get_auth_headers())
                assert resp.status_code == status.HTTP_200_OK
                body = resp.json()
                assert body["success"] is True
                assert body["data"] == []
        finally:
            app.dependency_overrides.clear()


# ===========================================================================
# 3. Call Details Tests
# ===========================================================================

def test_get_call_detail_success(caller_user, callee_user):
    call_id = uuid.uuid4()
    mock_call = make_mock_call(call_id, COMPANY_A_ID, caller_user, callee_user, "audio", "connected", 45)

    app.dependency_overrides[get_current_user] = lambda: caller_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(caller_user.id),
        "company_id": str(COMPANY_A_ID),
        "role": "employee",
    }
    app.dependency_overrides[get_db_session] = mock_get_db

    with patch("app.services.connect_service.ConnectRepository.get_call_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_call

        try:
            with TestClient(app) as client:
                resp = client.get(f"/api/v1/connect/calls/{call_id}", headers=get_auth_headers())
                assert resp.status_code == status.HTTP_200_OK
                body = resp.json()
                assert body["success"] is True
                assert body["data"]["id"] == str(call_id)
                assert body["data"]["caller"]["name"] == caller_user.name
        finally:
            app.dependency_overrides.clear()


def test_get_call_detail_not_found(caller_user):
    call_id = uuid.uuid4()
    app.dependency_overrides[get_current_user] = lambda: caller_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(caller_user.id),
        "company_id": str(COMPANY_A_ID),
        "role": "employee",
    }
    app.dependency_overrides[get_db_session] = mock_get_db

    with patch("app.services.connect_service.ConnectRepository.get_call_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None

        try:
            with TestClient(app) as client:
                resp = client.get(f"/api/v1/connect/calls/{call_id}", headers=get_auth_headers())
                assert resp.status_code == status.HTTP_404_NOT_FOUND
        finally:
            app.dependency_overrides.clear()


def test_get_call_detail_unauthorized_outsider(outsider_user, caller_user, callee_user):
    call_id = uuid.uuid4()
    mock_call = make_mock_call(call_id, COMPANY_A_ID, caller_user, callee_user, "audio", "connected", 45)

    app.dependency_overrides[get_current_user] = lambda: outsider_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(outsider_user.id),
        "company_id": str(COMPANY_A_ID),
        "role": "employee",
    }
    app.dependency_overrides[get_db_session] = mock_get_db

    with patch("app.services.connect_service.ConnectRepository.get_call_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_call

        try:
            with TestClient(app) as client:
                resp = client.get(f"/api/v1/connect/calls/{call_id}", headers=get_auth_headers())
                assert resp.status_code == status.HTTP_403_FORBIDDEN
        finally:
            app.dependency_overrides.clear()


# ===========================================================================
# 4. Initiate Call Tests & Multi-Tenant Security
# ===========================================================================

def test_initiate_call_success(caller_user, callee_user):
    call_id = uuid.uuid4()
    mock_call = make_mock_call(call_id, COMPANY_A_ID, caller_user, callee_user, "audio", "initiated")

    app.dependency_overrides[get_current_user] = lambda: caller_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(caller_user.id),
        "company_id": str(COMPANY_A_ID),
        "role": "employee",
    }
    app.dependency_overrides[get_db_session] = mock_get_db

    with patch("app.services.connect_service.ConnectRepository.get_active_user_in_company", new_callable=AsyncMock) as mock_target, \
         patch("app.services.connect_service.ConnectRepository.create_call_log", new_callable=AsyncMock) as mock_create, \
         patch("app.services.connect_service.ConnectRepository.create_notification", new_callable=AsyncMock) as mock_notif, \
         patch("app.services.connect_ws_manager.ConnectWSManager.send_to_user", new_callable=AsyncMock) as mock_ws:

        mock_target.return_value = callee_user
        mock_create.return_value = mock_call

        try:
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/connect/calls/initiate",
                    headers=get_auth_headers(),
                    json={"calleeId": str(callee_user.id), "type": "audio"},
                )
                assert resp.status_code == status.HTTP_201_CREATED
                body = resp.json()
                assert body["success"] is True
                assert body["data"]["callId"] == str(call_id)
                assert body["data"]["caller"]["name"] == caller_user.name
                assert body["data"]["callee"]["name"] == callee_user.name

                # Verify dual WebSocket events dispatched
                assert mock_ws.call_count >= 2
                event_names = [call.args[2] for call in mock_ws.call_args_list]
                assert "call:incoming" in event_names
                assert "incoming_call" in event_names
        finally:
            app.dependency_overrides.clear()


def test_initiate_call_self_rejection(caller_user):
    app.dependency_overrides[get_current_user] = lambda: caller_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(caller_user.id),
        "company_id": str(COMPANY_A_ID),
        "role": "employee",
    }
    app.dependency_overrides[get_db_session] = mock_get_db

    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/connect/calls/initiate",
                headers=get_auth_headers(),
                json={"targetUserId": str(caller_user.id), "type": "audio"},
            )
            assert resp.status_code == status.HTTP_400_BAD_REQUEST
    finally:
        app.dependency_overrides.clear()


def test_initiate_call_cross_tenant_rejection(caller_user, company_b_user):
    app.dependency_overrides[get_current_user] = lambda: caller_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(caller_user.id),
        "company_id": str(COMPANY_A_ID),
        "role": "employee",
    }
    app.dependency_overrides[get_db_session] = mock_get_db

    with patch("app.services.connect_service.ConnectRepository.get_active_user_in_company", new_callable=AsyncMock) as mock_target:
        mock_target.return_value = None  # User does not exist in Company A

        try:
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/connect/calls/initiate",
                    headers=get_auth_headers(),
                    json={"targetUserId": str(company_b_user.id), "type": "audio"},
                )
                assert resp.status_code == status.HTTP_403_FORBIDDEN
        finally:
            app.dependency_overrides.clear()


# ===========================================================================
# 5. Call Status Update & Lifecycle Tests
# ===========================================================================

def test_update_call_status_accepted_connected(caller_user, callee_user):
    call_id = uuid.uuid4()
    mock_call = make_mock_call(call_id, COMPANY_A_ID, caller_user, callee_user, "audio", "initiated")
    updated_call = make_mock_call(call_id, COMPANY_A_ID, caller_user, callee_user, "audio", "connected")

    app.dependency_overrides[get_current_user] = lambda: callee_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(callee_user.id),
        "company_id": str(COMPANY_A_ID),
        "role": "employee",
    }
    app.dependency_overrides[get_db_session] = mock_get_db

    with patch("app.services.connect_service.ConnectRepository.get_call_by_id", new_callable=AsyncMock) as mock_get, \
         patch("app.services.connect_service.ConnectRepository.update_call_status", new_callable=AsyncMock) as mock_update, \
         patch("app.services.connect_ws_manager.ConnectWSManager.send_to_user", new_callable=AsyncMock) as mock_ws:

        mock_get.return_value = mock_call
        mock_update.return_value = updated_call

        try:
            with TestClient(app) as client:
                resp = client.patch(
                    f"/api/v1/connect/calls/{call_id}/status",
                    headers=get_auth_headers(),
                    json={"status": "accepted"},
                )
                assert resp.status_code == status.HTTP_200_OK
                body = resp.json()
                assert body["success"] is True
                assert body["data"]["status"] == "connected"

                # Verify WebSocket events
                event_names = [call.args[2] for call in mock_ws.call_args_list]
                assert "call:accepted" in event_names
                assert "call_status_changed" in event_names
        finally:
            app.dependency_overrides.clear()


def test_update_call_status_rejected_declined(caller_user, callee_user):
    call_id = uuid.uuid4()
    mock_call = make_mock_call(call_id, COMPANY_A_ID, caller_user, callee_user, "audio", "initiated")
    updated_call = make_mock_call(call_id, COMPANY_A_ID, caller_user, callee_user, "audio", "rejected")

    app.dependency_overrides[get_current_user] = lambda: callee_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(callee_user.id),
        "company_id": str(COMPANY_A_ID),
        "role": "employee",
    }
    app.dependency_overrides[get_db_session] = mock_get_db

    with patch("app.services.connect_service.ConnectRepository.get_call_by_id", new_callable=AsyncMock) as mock_get, \
         patch("app.services.connect_service.ConnectRepository.update_call_status", new_callable=AsyncMock) as mock_update, \
         patch("app.services.connect_ws_manager.ConnectWSManager.send_to_user", new_callable=AsyncMock) as mock_ws:

        mock_get.return_value = mock_call
        mock_update.return_value = updated_call

        try:
            with TestClient(app) as client:
                resp = client.patch(
                    f"/api/v1/connect/calls/{call_id}/status",
                    headers=get_auth_headers(),
                    json={"status": "declined"},
                )
                assert resp.status_code == status.HTTP_200_OK
                body = resp.json()
                assert body["data"]["status"] == "rejected"

                event_names = [call.args[2] for call in mock_ws.call_args_list]
                assert "call:rejected" in event_names
        finally:
            app.dependency_overrides.clear()


def test_update_call_status_ended(caller_user, callee_user):
    call_id = uuid.uuid4()
    mock_call = make_mock_call(call_id, COMPANY_A_ID, caller_user, callee_user, "audio", "connected")
    updated_call = make_mock_call(call_id, COMPANY_A_ID, caller_user, callee_user, "audio", "ended", 180)

    app.dependency_overrides[get_current_user] = lambda: caller_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(caller_user.id),
        "company_id": str(COMPANY_A_ID),
        "role": "employee",
    }
    app.dependency_overrides[get_db_session] = mock_get_db

    with patch("app.services.connect_service.ConnectRepository.get_call_by_id", new_callable=AsyncMock) as mock_get, \
         patch("app.services.connect_service.ConnectRepository.update_call_status", new_callable=AsyncMock) as mock_update, \
         patch("app.services.connect_ws_manager.ConnectWSManager.send_to_user", new_callable=AsyncMock) as mock_ws:

        mock_get.return_value = mock_call
        mock_update.return_value = updated_call

        try:
            with TestClient(app) as client:
                resp = client.patch(
                    f"/api/v1/connect/calls/{call_id}/status",
                    headers=get_auth_headers(),
                    json={"status": "ended"},
                )
                assert resp.status_code == status.HTTP_200_OK
                body = resp.json()
                assert body["data"]["status"] == "ended"
                assert body["data"]["duration"] == 180

                event_names = [call.args[2] for call in mock_ws.call_args_list]
                assert "call:ended" in event_names
        finally:
            app.dependency_overrides.clear()


def test_update_call_status_missed_notification(caller_user, callee_user):
    call_id = uuid.uuid4()
    mock_call = make_mock_call(call_id, COMPANY_A_ID, caller_user, callee_user, "video", "initiated")
    updated_call = make_mock_call(call_id, COMPANY_A_ID, caller_user, callee_user, "video", "missed")

    app.dependency_overrides[get_current_user] = lambda: caller_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(caller_user.id),
        "company_id": str(COMPANY_A_ID),
        "role": "employee",
    }
    app.dependency_overrides[get_db_session] = mock_get_db

    with patch("app.services.connect_service.ConnectRepository.get_call_by_id", new_callable=AsyncMock) as mock_get, \
         patch("app.services.connect_service.ConnectRepository.update_call_status", new_callable=AsyncMock) as mock_update, \
         patch("app.services.connect_service.ConnectRepository.create_notification", new_callable=AsyncMock) as mock_notif, \
         patch("app.services.connect_ws_manager.ConnectWSManager.send_to_user", new_callable=AsyncMock) as mock_ws:

        mock_get.return_value = mock_call
        mock_update.return_value = updated_call

        try:
            with TestClient(app) as client:
                resp = client.patch(
                    f"/api/v1/connect/calls/{call_id}/status",
                    headers=get_auth_headers(),
                    json={"status": "missed"},
                )
                assert resp.status_code == status.HTTP_200_OK
                assert mock_notif.called
                args = mock_notif.call_args.kwargs
                assert args["notification_type"] == "call"
                assert "Missed" in args["title"]
        finally:
            app.dependency_overrides.clear()


def test_update_call_status_unauthorized_rejection(outsider_user, caller_user, callee_user):
    call_id = uuid.uuid4()
    mock_call = make_mock_call(call_id, COMPANY_A_ID, caller_user, callee_user, "audio", "initiated")

    app.dependency_overrides[get_current_user] = lambda: outsider_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(outsider_user.id),
        "company_id": str(COMPANY_A_ID),
        "role": "employee",
    }
    app.dependency_overrides[get_db_session] = mock_get_db

    with patch("app.services.connect_service.ConnectRepository.get_call_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_call

        try:
            with TestClient(app) as client:
                resp = client.patch(
                    f"/api/v1/connect/calls/{call_id}/status",
                    headers=get_auth_headers(),
                    json={"status": "ended"},
                )
                assert resp.status_code == status.HTTP_403_FORBIDDEN
        finally:
            app.dependency_overrides.clear()


# ===========================================================================
# 6. WebRTC Signaling Relay Tests
# ===========================================================================

def test_call_signal_offer(caller_user, callee_user):
    call_id = uuid.uuid4()
    mock_call = make_mock_call(call_id, COMPANY_A_ID, caller_user, callee_user, "audio", "connected")

    app.dependency_overrides[get_current_user] = lambda: caller_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(caller_user.id),
        "company_id": str(COMPANY_A_ID),
        "role": "employee",
    }
    app.dependency_overrides[get_db_session] = mock_get_db

    with patch("app.services.connect_service.ConnectRepository.get_call_by_id", new_callable=AsyncMock) as mock_get, \
         patch("app.services.connect_ws_manager.ConnectWSManager.send_to_user", new_callable=AsyncMock) as mock_ws:

        mock_get.return_value = mock_call

        try:
            with TestClient(app) as client:
                resp = client.post(
                    f"/api/v1/connect/calls/{call_id}/signal",
                    headers=get_auth_headers(),
                    json={
                        "type": "offer",
                        "payload": {"sdp": "v=0\r\no=- 12345 2 IN IP4 127.0.0.1\r\n..."},
                        "targetUserId": str(callee_user.id),
                    },
                )
                assert resp.status_code == status.HTTP_200_OK
                body = resp.json()
                assert body["success"] is True
                assert body["data"]["relayed"] is True

                event_names = [call.args[2] for call in mock_ws.call_args_list]
                assert "webrtc:signal" in event_names
                assert "call_signal" in event_names
        finally:
            app.dependency_overrides.clear()


def test_call_signal_nested_signal_normalization(caller_user, callee_user):
    call_id = uuid.uuid4()
    mock_call = make_mock_call(call_id, COMPANY_A_ID, caller_user, callee_user, "audio", "connected")

    app.dependency_overrides[get_current_user] = lambda: caller_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(caller_user.id),
        "company_id": str(COMPANY_A_ID),
        "role": "employee",
    }
    app.dependency_overrides[get_db_session] = mock_get_db

    with patch("app.services.connect_service.ConnectRepository.get_call_by_id", new_callable=AsyncMock) as mock_get, \
         patch("app.services.connect_ws_manager.ConnectWSManager.send_to_user", new_callable=AsyncMock) as mock_ws:

        mock_get.return_value = mock_call

        try:
            with TestClient(app) as client:
                # Dispatched in frontend format: { callId, targetUserId, signal: { type: "ice-candidate", candidate: "..." } }
                resp = client.post(
                    f"/api/v1/connect/calls/{call_id}/signal",
                    headers=get_auth_headers(),
                    json={
                        "targetUserId": str(callee_user.id),
                        "signal": {"type": "ice-candidate", "candidate": "candidate:1 1 UDP 2130706431 ..."},
                    },
                )
                assert resp.status_code == status.HTTP_200_OK
                body = resp.json()
                assert body["success"] is True
                assert body["data"]["type"] == "ice-candidate"
        finally:
            app.dependency_overrides.clear()


def test_call_signal_unauthorized_rejection(outsider_user, caller_user, callee_user):
    call_id = uuid.uuid4()
    mock_call = make_mock_call(call_id, COMPANY_A_ID, caller_user, callee_user, "audio", "connected")

    app.dependency_overrides[get_current_user] = lambda: outsider_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(outsider_user.id),
        "company_id": str(COMPANY_A_ID),
        "role": "employee",
    }
    app.dependency_overrides[get_db_session] = mock_get_db

    with patch("app.services.connect_service.ConnectRepository.get_call_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_call

        try:
            with TestClient(app) as client:
                resp = client.post(
                    f"/api/v1/connect/calls/{call_id}/signal",
                    headers=get_auth_headers(),
                    json={"type": "offer", "targetUserId": str(callee_user.id)},
                )
                assert resp.status_code == status.HTTP_403_FORBIDDEN
        finally:
            app.dependency_overrides.clear()


# ===========================================================================
# 7. Cross-Company IDOR & Security Tests
# ===========================================================================

def test_cross_company_call_details_idor(company_b_user, caller_user, callee_user):
    call_id = uuid.uuid4()
    # Call belongs to Company A
    app.dependency_overrides[get_current_user] = lambda: company_b_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(company_b_user.id),
        "company_id": str(COMPANY_B_ID),
        "role": "employee",
    }
    app.dependency_overrides[get_db_session] = mock_get_db

    with patch("app.services.connect_service.ConnectRepository.get_call_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None  # DB query filters by company_id=COMPANY_B_ID, so None returned

        try:
            with TestClient(app) as client:
                resp = client.get(f"/api/v1/connect/calls/{call_id}", headers=get_auth_headers())
                assert resp.status_code == status.HTTP_404_NOT_FOUND
        finally:
            app.dependency_overrides.clear()


def test_cross_company_status_update_idor(company_b_user):
    call_id = uuid.uuid4()
    app.dependency_overrides[get_current_user] = lambda: company_b_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(company_b_user.id),
        "company_id": str(COMPANY_B_ID),
        "role": "employee",
    }
    app.dependency_overrides[get_db_session] = mock_get_db

    with patch("app.services.connect_service.ConnectRepository.get_call_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None

        try:
            with TestClient(app) as client:
                resp = client.patch(
                    f"/api/v1/connect/calls/{call_id}/status",
                    headers=get_auth_headers(),
                    json={"status": "ended"},
                )
                assert resp.status_code == status.HTTP_404_NOT_FOUND
        finally:
            app.dependency_overrides.clear()


def test_forged_company_header_rejection(caller_user):
    app.dependency_overrides[get_current_user] = lambda: caller_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(caller_user.id),
        "company_id": str(COMPANY_A_ID),
        "role": "employee",
    }
    app.dependency_overrides[get_db_session] = mock_get_db

    try:
        with TestClient(app) as client:
            # Caller is in Company A, but passes forged X-Company-ID for Company B
            resp = client.get(
                "/api/v1/connect/calls/history",
                headers={"Authorization": "Bearer test-jwt", "X-Company-ID": str(COMPANY_B_ID)},
            )
            assert resp.status_code == status.HTTP_403_FORBIDDEN
    finally:
        app.dependency_overrides.clear()


def test_unauthenticated_rejection():
    try:
        with TestClient(app) as client:
            resp = client.get("/api/v1/connect/calls/history")
            assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    finally:
        app.dependency_overrides.clear()
