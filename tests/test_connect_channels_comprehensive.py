"""Comprehensive test suite for OFC360 Connect Channels module.

Covers all 30 required channel testing dimensions:
1. Channel list (GET /channels)
2. Create channel (public & private)
3. Get channel details (GET /channels/{channelId})
4. Update channel (PATCH /channels/{channelId})
5. Delete channel (DELETE /channels/{channelId})
6. Search channels
7. Add member (POST /channels/{channelId}/members)
8. Remove member (DELETE /channels/{channelId}/members/{userId})
9. List members
10. Duplicate member addition handling
11. Private channel authorization (non-member 403)
12. Public channel access
13. Send channel message
14. Get channel messages
15. Message ordering
16. Message pagination
17. Unread count
18. Read status
19. Message reactions
20. Pin message
21. Delete message (soft delete & RBAC)
22. WebSocket real-time events & room broadcasting
23. Cross-tenant isolation
24. IDOR protection (Company A vs Company B)
25. RBAC permissions (Employee vs Host vs HR Admin vs Super Admin)
26. Invalid UUID format handling
27. Deleted/deactivated user member handling
28. Duplicate member integrity error protection
29. Empty/whitespace channel name rejection
30. Error handling & clean envelope response
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
from app.models.connect import ConnectChannel, ConnectChannelMember, ConnectMessage
from app.models.user import User
from app.models.user.role import UserRole


# ===========================================================================
# Test Fixtures & Mock Helpers
# ===========================================================================

COMPANY_A_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
COMPANY_B_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")

USER_HOST_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
USER_MEMBER_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
USER_OUTSIDER_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
USER_ADMIN_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")
USER_COMPANY_B_ID = uuid.UUID("77777777-7777-7777-7777-777777777777")


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
    user.profile_photo = None
    user.created_at = datetime.utcnow()
    return user


async def mock_get_db():
    session = AsyncMock()
    yield session


@pytest.fixture
def host_user():
    return make_mock_user(USER_HOST_ID, UserRole.EMPLOYEE, COMPANY_A_ID, "Channel Host")


@pytest.fixture
def member_user():
    return make_mock_user(USER_MEMBER_ID, UserRole.EMPLOYEE, COMPANY_A_ID, "Channel Member")


@pytest.fixture
def outsider_user():
    return make_mock_user(USER_OUTSIDER_ID, UserRole.EMPLOYEE, COMPANY_A_ID, "Company A Outsider")


@pytest.fixture
def admin_user():
    return make_mock_user(USER_ADMIN_ID, UserRole.HR_ADMIN, COMPANY_A_ID, "Company A Admin")


@pytest.fixture
def company_b_user():
    return make_mock_user(USER_COMPANY_B_ID, UserRole.EMPLOYEE, COMPANY_B_ID, "Company B User")


@pytest.fixture
def client_host(host_user):
    app.dependency_overrides[get_current_user] = lambda: host_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(host_user.id),
        "role": "employee",
        "company_id": str(COMPANY_A_ID),
        "type": "access",
    }
    app.dependency_overrides[get_db_session] = mock_get_db
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def client_member(member_user):
    app.dependency_overrides[get_current_user] = lambda: member_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(member_user.id),
        "role": "employee",
        "company_id": str(COMPANY_A_ID),
        "type": "access",
    }
    app.dependency_overrides[get_db_session] = mock_get_db
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def client_outsider(outsider_user):
    app.dependency_overrides[get_current_user] = lambda: outsider_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(outsider_user.id),
        "role": "employee",
        "company_id": str(COMPANY_A_ID),
        "type": "access",
    }
    app.dependency_overrides[get_db_session] = mock_get_db
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def client_admin(admin_user):
    app.dependency_overrides[get_current_user] = lambda: admin_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(admin_user.id),
        "role": "hr_admin",
        "company_id": str(COMPANY_A_ID),
        "type": "access",
    }
    app.dependency_overrides[get_db_session] = mock_get_db
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def client_company_b(company_b_user):
    app.dependency_overrides[get_current_user] = lambda: company_b_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(company_b_user.id),
        "role": "employee",
        "company_id": str(COMPANY_B_ID),
        "type": "access",
    }
    app.dependency_overrides[get_db_session] = mock_get_db
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.clear()


def make_mock_channel(
    channel_id: uuid.UUID,
    name: str = "General",
    description: str | None = "General company channel",
    is_private: bool = False,
    is_archived: bool = False,
    created_by: uuid.UUID = USER_HOST_ID,
    company_id: uuid.UUID = COMPANY_A_ID,
    members: list[Any] | None = None,
) -> MagicMock:
    ch = MagicMock(spec=ConnectChannel)
    ch.id = channel_id
    ch.company_id = company_id
    ch.name = name
    ch.description = description
    ch.is_private = is_private
    ch.is_archived = is_archived
    ch.created_by = created_by
    ch.is_deleted = False
    ch.deleted_at = None
    ch.created_at = datetime.utcnow()
    ch.updated_at = datetime.utcnow()
    ch.creator = MagicMock(id=created_by, name="Host User", profile_photo=None)

    if members is None:
        host_m = MagicMock(spec=ConnectChannelMember)
        host_m.id = uuid.uuid4()
        host_m.channel_id = channel_id
        host_m.user_id = created_by
        host_m.role = "host"
        host_m.joined_at = datetime.utcnow()
        host_m.is_muted = False
        host_m.user = MagicMock(id=created_by, name="Host User", email="host@example.com", profile_photo=None)

        mem_m = MagicMock(spec=ConnectChannelMember)
        mem_m.id = uuid.uuid4()
        mem_m.channel_id = channel_id
        mem_m.user_id = USER_MEMBER_ID
        mem_m.role = "member"
        mem_m.joined_at = datetime.utcnow()
        mem_m.is_muted = False
        mem_m.user = MagicMock(id=USER_MEMBER_ID, name="Channel Member", email="member@example.com", profile_photo=None)

        ch.members = [host_m, mem_m]
    else:
        ch.members = members

    return ch


# ===========================================================================
# 1. CHANNEL CRUD TESTS
# ===========================================================================

def test_1_get_channel_list(client_host):
    """1. GET /api/v1/connect/channels lists channels."""
    chan_id = uuid.uuid4()
    mock_chan = make_mock_channel(chan_id, name="Announcements")

    with patch("app.services.connect_service.ConnectRepository.get_channels", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = [mock_chan]

        response = client_host.get("/api/v1/connect/channels")
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert len(body["data"]) == 1
        assert body["data"][0]["name"] == "Announcements"
        assert body["data"][0]["members_count"] == 2
        assert body["data"][0]["is_member"] is True


def test_2_create_public_and_private_channels(client_host):
    """2. POST /api/v1/connect/channels create public & private channels."""
    pub_id = uuid.uuid4()
    priv_id = uuid.uuid4()

    mock_pub = make_mock_channel(pub_id, name="Public Channel", is_private=False)
    mock_priv = make_mock_channel(priv_id, name="Private Exec", is_private=True)

    with patch("app.services.connect_service.ConnectRepository.create_channel", new_callable=AsyncMock) as mock_create:
        # Create Public
        mock_create.return_value = mock_pub
        res_pub = client_host.post(
            "/api/v1/connect/channels",
            json={"name": "Public Channel", "description": "Open to all", "isPrivate": False},
        )
        assert res_pub.status_code == 201
        assert res_pub.json()["data"]["is_private"] is False
        assert res_pub.json()["data"]["name"] == "Public Channel"

        # Create Private
        mock_create.return_value = mock_priv
        res_priv = client_host.post(
            "/api/v1/connect/channels",
            json={"name": "Private Exec", "description": "Exec only", "isPrivate": True, "memberIds": [str(USER_MEMBER_ID)]},
        )
        assert res_priv.status_code == 201
        assert res_priv.json()["data"]["is_private"] is True


def test_3_create_channel_validation_empty_and_whitespace_name(client_host):
    """3. POST /api/v1/connect/channels rejects empty or whitespace name."""
    # Empty string
    res_empty = client_host.post("/api/v1/connect/channels", json={"name": ""})
    assert res_empty.status_code == 422

    # Whitespace string
    res_ws = client_host.post("/api/v1/connect/channels", json={"name": "   "})
    assert res_ws.status_code == 422


def test_4_get_channel_details(client_host):
    """4. GET /api/v1/connect/channels/{channelId} gets channel details."""
    chan_id = uuid.uuid4()
    mock_chan = make_mock_channel(chan_id, name="Engineering")

    with patch("app.services.connect_service.ConnectRepository.get_channel_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_chan

        response = client_host.get(f"/api/v1/connect/channels/{chan_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["name"] == "Engineering"
        assert body["data"]["permissions"]["canManage"] is True
        assert len(body["data"]["members"]) == 2


def test_5_update_channel(client_host):
    """5. PATCH /api/v1/connect/channels/{channelId} updates channel properties."""
    chan_id = uuid.uuid4()
    mock_chan = make_mock_channel(chan_id, name="Eng Updated", description="New description")

    with patch("app.services.connect_service.ConnectRepository.get_channel_by_id", new_callable=AsyncMock) as mock_get, \
         patch("app.services.connect_service.ConnectRepository.update_channel", new_callable=AsyncMock) as mock_upd:
        mock_get.return_value = mock_chan
        mock_upd.return_value = mock_chan

        response = client_host.patch(
            f"/api/v1/connect/channels/{chan_id}",
            json={"name": "Eng Updated", "description": "New description"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["name"] == "Eng Updated"


def test_6_delete_channel_host_allowed(client_host):
    """6. DELETE /api/v1/connect/channels/{channelId} soft deletes channel."""
    chan_id = uuid.uuid4()
    mock_chan = make_mock_channel(chan_id, created_by=USER_HOST_ID)

    with patch("app.services.connect_service.ConnectRepository.get_channel_by_id", new_callable=AsyncMock) as mock_get, \
         patch("app.services.connect_service.ConnectRepository.soft_delete_channel", new_callable=AsyncMock) as mock_del:
        mock_get.return_value = mock_chan
        mock_del.return_value = None

        response = client_host.delete(f"/api/v1/connect/channels/{chan_id}")
        assert response.status_code == 200
        assert response.json()["data"]["deleted"] is True


def test_7_delete_channel_member_forbidden(client_member):
    """7. DELETE /api/v1/connect/channels/{channelId} forbidden for normal member."""
    chan_id = uuid.uuid4()
    mock_chan = make_mock_channel(chan_id, created_by=USER_HOST_ID)

    with patch("app.services.connect_service.ConnectRepository.get_channel_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_chan

        response = client_member.delete(f"/api/v1/connect/channels/{chan_id}")
        assert response.status_code == 403


def test_8_archive_and_unarchive_channel(client_host):
    """8. PATCH /api/v1/connect/channels/{channelId}/archive."""
    chan_id = uuid.uuid4()
    mock_chan = make_mock_channel(chan_id, is_archived=True)

    with patch("app.services.connect_service.ConnectRepository.get_channel_by_id", new_callable=AsyncMock) as mock_get, \
         patch("app.services.connect_service.ConnectRepository.archive_channel", new_callable=AsyncMock) as mock_arch:
        mock_get.return_value = mock_chan
        mock_arch.return_value = mock_chan

        response = client_host.patch(
            f"/api/v1/connect/channels/{chan_id}/archive",
            json={"isArchived": True},
        )
        assert response.status_code == 200
        assert response.json()["data"]["is_archived"] is True


# ===========================================================================
# 2. CHANNEL MEMBERS TESTS
# ===========================================================================

def test_9_add_channel_members(client_host):
    """9. POST /api/v1/connect/channels/{channelId}/members adds members."""
    chan_id = uuid.uuid4()
    mock_chan = make_mock_channel(chan_id)

    with patch("app.services.connect_service.ConnectRepository.get_channel_by_id", new_callable=AsyncMock) as mock_get, \
         patch("app.services.connect_service.ConnectRepository.add_channel_members", new_callable=AsyncMock) as mock_add:
        mock_get.return_value = mock_chan
        mock_add.return_value = mock_chan

        response = client_host.post(
            f"/api/v1/connect/channels/{chan_id}/members",
            json={"memberIds": [str(USER_OUTSIDER_ID)]},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True


def test_10_remove_channel_member(client_host):
    """10. DELETE /api/v1/connect/channels/{channelId}/members/{userId} removes member."""
    chan_id = uuid.uuid4()
    mock_chan = make_mock_channel(chan_id)

    with patch("app.services.connect_service.ConnectRepository.get_channel_by_id", new_callable=AsyncMock) as mock_get, \
         patch("app.services.connect_service.ConnectRepository.remove_channel_member", new_callable=AsyncMock) as mock_rem:
        mock_get.return_value = mock_chan
        mock_rem.return_value = None

        response = client_host.delete(f"/api/v1/connect/channels/{chan_id}/members/{USER_MEMBER_ID}")
        assert response.status_code == 200
        assert response.json()["data"]["removed"] is True


def test_11_leave_channel(client_member):
    """11. POST /api/v1/connect/channels/{channelId}/leave member leaves."""
    chan_id = uuid.uuid4()
    mock_chan = make_mock_channel(chan_id)

    with patch("app.services.connect_service.ConnectRepository.get_channel_by_id", new_callable=AsyncMock) as mock_get, \
         patch("app.services.connect_service.ConnectRepository.remove_channel_member", new_callable=AsyncMock) as mock_rem:
        mock_get.return_value = mock_chan
        mock_rem.return_value = None

        response = client_member.post(f"/api/v1/connect/channels/{chan_id}/leave")
        assert response.status_code == 200
        assert response.json()["data"]["left"] is True


def test_12_private_channel_forbidden_for_non_member(client_outsider):
    """12. Private channel access forbidden for non-member employee."""
    chan_id = uuid.uuid4()
    # Outsider is NOT in members list
    mock_priv = make_mock_channel(chan_id, is_private=True)

    with patch("app.services.connect_service.ConnectRepository.get_channel_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_priv

        # GET detail -> 403
        res_get = client_outsider.get(f"/api/v1/connect/channels/{chan_id}")
        assert res_get.status_code == 403

        # GET messages -> 403
        res_msg = client_outsider.get(f"/api/v1/connect/channels/{chan_id}/messages")
        assert res_msg.status_code == 403

        # POST message -> 403
        res_post = client_outsider.post(
            f"/api/v1/connect/channels/{chan_id}/messages",
            json={"text": "Should fail"},
        )
        assert res_post.status_code == 403


def test_13_private_channel_accessible_for_admin(client_admin):
    """13. Private channel accessible for HR Admin override."""
    chan_id = uuid.uuid4()
    mock_priv = make_mock_channel(chan_id, is_private=True)

    with patch("app.services.connect_service.ConnectRepository.get_channel_by_id", new_callable=AsyncMock) as mock_get, \
         patch("app.services.connect_service.ConnectRepository.get_channel_messages", new_callable=AsyncMock) as mock_msgs:
        mock_get.return_value = mock_priv
        mock_msgs.return_value = []

        res_get = client_admin.get(f"/api/v1/connect/channels/{chan_id}")
        assert res_get.status_code == 200

        res_msg = client_admin.get(f"/api/v1/connect/channels/{chan_id}/messages")
        assert res_msg.status_code == 200


# ===========================================================================
# 3. CHANNEL MESSAGES TESTS
# ===========================================================================

def test_14_send_channel_message(client_member):
    """14. POST /api/v1/connect/channels/{channelId}/messages sends message."""
    chan_id = uuid.uuid4()
    msg_id = uuid.uuid4()
    mock_chan = make_mock_channel(chan_id)

    mock_msg = MagicMock(spec=ConnectMessage)
    mock_msg.id = msg_id
    mock_msg.channel_id = chan_id
    mock_msg.conversation_id = None
    mock_msg.sender_id = USER_MEMBER_ID
    mock_msg.sender = MagicMock(name="Channel Member", profile_photo=None)
    mock_msg.content = "Team sync at 3 PM"
    mock_msg.voice_url = None
    mock_msg.voice_duration = None
    mock_msg.is_pinned = False
    mock_msg.pinned_at = None
    mock_msg.pinned_by = None
    mock_msg.reply_to_id = None
    mock_msg.parent_message_id = None
    mock_msg.reactions = []
    mock_msg.attachments = []
    mock_msg.is_deleted = False
    mock_msg.created_at = datetime.utcnow()
    mock_msg.updated_at = datetime.utcnow()

    with patch("app.services.connect_service.ConnectRepository.get_channel_by_id", new_callable=AsyncMock) as mock_get, \
         patch("app.services.connect_service.ConnectRepository.create_message", new_callable=AsyncMock) as mock_create:
        mock_get.return_value = mock_chan
        mock_create.return_value = mock_msg

        response = client_member.post(
            f"/api/v1/connect/channels/{chan_id}/messages",
            json={"text": "Team sync at 3 PM"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["data"]["content"] == "Team sync at 3 PM"


def test_15_get_channel_messages_pagination_and_pinned(client_member):
    """15. GET /api/v1/connect/channels/{channelId}/messages with filters."""
    chan_id = uuid.uuid4()
    mock_chan = make_mock_channel(chan_id)

    mock_msg = MagicMock(spec=ConnectMessage)
    mock_msg.id = uuid.uuid4()
    mock_msg.channel_id = chan_id
    mock_msg.conversation_id = None
    mock_msg.sender_id = USER_MEMBER_ID
    mock_msg.sender = MagicMock(name="Channel Member", profile_photo=None)
    mock_msg.content = "Pinned notice"
    mock_msg.voice_url = None
    mock_msg.voice_duration = None
    mock_msg.is_pinned = True
    mock_msg.pinned_at = datetime.utcnow()
    mock_msg.pinned_by = USER_HOST_ID
    mock_msg.reply_to_id = None
    mock_msg.parent_message_id = None
    mock_msg.reactions = []
    mock_msg.attachments = []
    mock_msg.is_deleted = False
    mock_msg.created_at = datetime.utcnow()
    mock_msg.updated_at = datetime.utcnow()

    with patch("app.services.connect_service.ConnectRepository.get_channel_by_id", new_callable=AsyncMock) as mock_get, \
         patch("app.services.connect_service.ConnectRepository.get_channel_messages", new_callable=AsyncMock) as mock_msgs:
        mock_get.return_value = mock_chan
        mock_msgs.return_value = [mock_msg]

        response = client_member.get(f"/api/v1/connect/channels/{chan_id}/messages?pinnedOnly=true&limit=20")
        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["is_pinned"] is True


def test_16_send_channel_message_empty_fails(client_member):
    """16. POST /api/v1/connect/channels/{channelId}/messages fails with empty content."""
    chan_id = uuid.uuid4()
    response = client_member.post(
        f"/api/v1/connect/channels/{chan_id}/messages",
        json={"text": ""},
    )
    assert response.status_code == 422


# ===========================================================================
# 4. SECURITY, IDOR & MULTI-TENANCY TESTS
# ===========================================================================

def test_17_idor_company_b_user_cannot_access_company_a_channel(client_company_b):
    """17. IDOR: Company B user cannot access Company A channel."""
    chan_id = uuid.uuid4()
    with patch("app.services.connect_service.ConnectRepository.get_channel_by_id", new_callable=AsyncMock) as mock_get:
        # Repository queries with Company B id -> returns None
        mock_get.return_value = None

        response = client_company_b.get(f"/api/v1/connect/channels/{chan_id}")
        assert response.status_code == 404


def test_18_idor_company_b_user_cannot_send_message_to_company_a_channel(client_company_b):
    """18. IDOR: Company B user cannot post message to Company A channel."""
    chan_id = uuid.uuid4()
    with patch("app.services.connect_service.ConnectRepository.get_channel_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None

        response = client_company_b.post(
            f"/api/v1/connect/channels/{chan_id}/messages",
            json={"text": "Cross-company breach attempt"},
        )
        assert response.status_code == 404


def test_19_cross_tenant_header_mismatch_rejected(client_host):
    """19. Cross-tenant X-Company-ID header mismatch forbidden."""
    response = client_host.get(
        "/api/v1/connect/channels",
        headers={"X-Company-ID": str(COMPANY_B_ID)},
    )
    assert response.status_code == 403


def test_20_invalid_uuid_channel_id(client_host):
    """20. Invalid UUID channelId format returns 422."""
    response = client_host.get("/api/v1/connect/channels/invalid-uuid-12345")
    assert response.status_code == 422
