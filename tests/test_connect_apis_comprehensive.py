"""Comprehensive test suite for all 40 OFC360 Connect Backend APIs."""

from __future__ import annotations

import asyncio
from datetime import datetime
import io
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.database import get_db_session
from app.main import app
from app.middleware.auth import get_current_user, get_current_user_claims
from app.models.user import User
from app.models.user.role import UserRole


# ===========================================================================
# Test Fixtures & Mock Helpers
# ===========================================================================

TEST_COMPANY_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_COMPANY_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")

EMPLOYEE_USER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
TARGET_USER_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
HR_ADMIN_USER_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")


def make_mock_user(user_id: uuid.UUID, role: UserRole, company_id: uuid.UUID, name: str = "Test User") -> User:
    user = MagicMock(spec=User)
    user.id = user_id
    user.name = name
    user.email = f"{name.lower().replace(' ', '.')}@example.com"
    user.phone = "9876543210"
    user.role = role
    user.company_id = company_id
    user.is_active = True
    user.profile_photo = None
    user.created_at = datetime.utcnow()
    return user


from contextlib import asynccontextmanager

@asynccontextmanager
async def dummy_lifespan(application):
    yield

app.router.lifespan_context = dummy_lifespan


async def mock_get_db():
    session = AsyncMock()
    yield session


@pytest.fixture(autouse=True)
def mock_lifespan_db():
    with patch("app.main.init_db_with_retry", new_callable=AsyncMock) as mock_init, \
         patch("app.main.auto_screen_unscreened_leads", new_callable=AsyncMock) as mock_screen:
        mock_init.return_value = True
        mock_screen.return_value = None
        yield mock_init


@pytest.fixture
def employee_user():
    return make_mock_user(EMPLOYEE_USER_ID, UserRole.EMPLOYEE, TEST_COMPANY_ID, "Employee User")


@pytest.fixture
def hr_admin_user():
    return make_mock_user(HR_ADMIN_USER_ID, UserRole.HR_ADMIN, TEST_COMPANY_ID, "HR Admin")


@pytest.fixture
def target_user():
    return make_mock_user(TARGET_USER_ID, UserRole.EMPLOYEE, TEST_COMPANY_ID, "Target User")


@pytest.fixture
def client_employee(employee_user):
    """Test client authenticated as standard employee."""
    app.dependency_overrides[get_current_user] = lambda: employee_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(employee_user.id),
        "role": "employee",
        "company_id": str(TEST_COMPANY_ID),
        "type": "access",
    }
    app.dependency_overrides[get_db_session] = mock_get_db
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def client_hr_admin(hr_admin_user):
    """Test client authenticated as HR Admin."""
    app.dependency_overrides[get_current_user] = lambda: hr_admin_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(hr_admin_user.id),
        "role": "hr_admin",
        "company_id": str(TEST_COMPANY_ID),
        "type": "access",
    }
    app.dependency_overrides[get_db_session] = mock_get_db
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.clear()


# ===========================================================================
# A. USER DISCOVERY & DIRECTORY TESTS
# ===========================================================================

def test_api_1_get_colleagues(client_employee):
    """1. GET /api/v1/connect/colleagues with search, department, and presence filters."""
    with patch("app.services.connect_service.ConnectRepository.get_colleagues", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = ([{
            "id": TARGET_USER_ID,
            "name": "Target User",
            "email": "target@example.com",
            "phone": "9876543210",
            "role": "employee",
            "department": "Engineering",
            "designation": "Backend Engineer",
            "avatar_url": None,
            "presence_status": "online",
            "custom_status": "Coding",
            "last_seen_at": datetime.utcnow(),
        }], 1)

        response = client_employee.get("/api/v1/connect/colleagues?search=Target&department=Engineering&presence=online&page=1&limit=20")
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert "colleagues" in body["data"]
        assert len(body["data"]["colleagues"]) == 1
        assert body["data"]["colleagues"][0]["name"] == "Target User"


def test_api_2_unified_search(client_employee):
    """2. GET /api/v1/connect/search across people, channels, messages, and files."""
    with patch("app.services.connect_service.ConnectRepository.unified_search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = {
            "people": [{"id": TARGET_USER_ID, "name": "Target User", "email": "target@example.com", "role": "employee"}],
            "channels": [{"id": uuid.uuid4(), "name": "General", "description": "Company channel"}],
            "messages": [{"id": uuid.uuid4(), "content": "Hello team", "sender_name": "Target User"}],
            "files": [{"id": uuid.uuid4(), "file_name": "report.pdf", "file_url": "/uploads/report.pdf"}],
        }

        response = client_employee.get("/api/v1/connect/search?q=team")
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert len(body["data"]["people"]) == 1
        assert len(body["data"]["channels"]) == 1
        assert len(body["data"]["messages"]) == 1
        assert len(body["data"]["files"]) == 1


# ===========================================================================
# B. DIRECT MESSAGING & CONVERSATIONS TESTS
# ===========================================================================

def test_api_3_get_conversations(client_employee):
    """3. GET /api/v1/connect/conversations"""
    with patch("app.services.connect_service.ConnectRepository.get_user_conversations", new_callable=AsyncMock) as mock_convs:
        mock_conv = MagicMock()
        mock_conv.id = uuid.uuid4()
        mock_conv.company_id = TEST_COMPANY_ID
        mock_conv.last_message_preview = "Hello!"
        mock_conv.last_message_at = datetime.utcnow()
        mock_conv.created_at = datetime.utcnow()
        mock_conv.updated_at = datetime.utcnow()
        mock_conv.participants = []
        mock_convs.return_value = [mock_conv]

        response = client_employee.get("/api/v1/connect/conversations")
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert len(body["data"]) == 1


def test_api_4_create_conversation_idempotent(client_employee):
    """4. POST /api/v1/connect/conversations (idempotent)"""
    with patch("app.services.connect_service.ConnectRepository.get_or_create_dm_conversation", new_callable=AsyncMock) as mock_create:
        conv_id = uuid.uuid4()
        mock_conv = MagicMock()
        mock_conv.id = conv_id
        mock_conv.company_id = TEST_COMPANY_ID
        mock_conv.last_message_preview = None
        mock_conv.last_message_at = None
        mock_conv.created_at = datetime.utcnow()
        mock_conv.updated_at = datetime.utcnow()
        mock_conv.participants = []
        mock_create.return_value = (mock_conv, True)

        response = client_employee.post(
            "/api/v1/connect/conversations",
            json={"targetUserId": str(TARGET_USER_ID)},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["id"] == str(conv_id)


def test_api_5_get_conversation_messages(client_employee):
    """5. GET /api/v1/connect/conversations/{conversationId}/messages"""
    conv_id = uuid.uuid4()
    with patch("app.services.connect_service.ConnectRepository.is_user_in_conversation", new_callable=AsyncMock) as mock_part, \
         patch("app.services.connect_service.ConnectRepository.get_conversation_messages", new_callable=AsyncMock) as mock_msgs:
        mock_part.return_value = True
        mock_msg = MagicMock()
        mock_msg.id = uuid.uuid4()
        mock_msg.conversation_id = conv_id
        mock_msg.channel_id = None
        mock_msg.sender_id = EMPLOYEE_USER_ID
        mock_msg.sender = MagicMock(name="Employee User", profile_photo=None)
        mock_msg.content = "Test message content"
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
        mock_msgs.return_value = [mock_msg]

        response = client_employee.get(f"/api/v1/connect/conversations/{conv_id}/messages")
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert len(body["data"]) == 1
        assert body["data"][0]["content"] == "Test message content"


def test_api_6_send_conversation_message(client_employee):
    """6. POST /api/v1/connect/conversations/{conversationId}/messages"""
    conv_id = uuid.uuid4()
    with patch("app.services.connect_service.ConnectRepository.is_user_in_conversation", new_callable=AsyncMock) as mock_part, \
         patch("app.services.connect_service.ConnectRepository.create_message", new_callable=AsyncMock) as mock_create, \
         patch("app.services.connect_service.ConnectRepository.get_conversation_by_id", new_callable=AsyncMock) as mock_get_conv:
        mock_part.return_value = True
        mock_msg = MagicMock()
        mock_msg.id = uuid.uuid4()
        mock_msg.conversation_id = conv_id
        mock_msg.channel_id = None
        mock_msg.sender_id = EMPLOYEE_USER_ID
        mock_msg.sender = MagicMock(name="Employee User", profile_photo=None)
        mock_msg.content = "New chat message"
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
        mock_create.return_value = mock_msg
        mock_get_conv.return_value = None

        response = client_employee.post(
            f"/api/v1/connect/conversations/{conv_id}/messages",
            json={"text": "New chat message"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["success"] is True
        assert body["data"]["content"] == "New chat message"


def test_api_7_toggle_reaction(client_employee):
    """7. POST /api/v1/connect/messages/{messageId}/reactions"""
    msg_id = uuid.uuid4()
    with patch("app.services.connect_service.ConnectRepository.get_message_by_id", new_callable=AsyncMock) as mock_get, \
         patch("app.services.connect_service.ConnectRepository.toggle_message_reaction", new_callable=AsyncMock) as mock_toggle:
        mock_msg = MagicMock()
        mock_msg.id = msg_id
        mock_msg.conversation_id = None
        mock_msg.channel_id = None
        mock_msg.reactions = []
        mock_msg.attachments = []
        mock_msg.sender = MagicMock(name="Sender", profile_photo=None)
        mock_get.return_value = mock_msg
        mock_toggle.return_value = (MagicMock(), True)

        response = client_employee.post(
            f"/api/v1/connect/messages/{msg_id}/reactions",
            json={"emoji": "👍"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["is_added"] is True


def test_api_8_pin_message(client_employee):
    """8. PATCH /api/v1/connect/messages/{messageId}/pin"""
    msg_id = uuid.uuid4()
    with patch("app.services.connect_service.ConnectRepository.get_message_by_id", new_callable=AsyncMock) as mock_get, \
         patch("app.services.connect_service.ConnectRepository.toggle_message_pin", new_callable=AsyncMock) as mock_pin:
        mock_msg = MagicMock()
        mock_msg.id = msg_id
        mock_msg.conversation_id = None
        mock_msg.channel_id = None
        mock_msg.is_pinned = True
        mock_msg.pinned_at = datetime.utcnow()
        mock_msg.pinned_by = EMPLOYEE_USER_ID
        mock_msg.reactions = []
        mock_msg.attachments = []
        mock_msg.sender = MagicMock(name="Sender", profile_photo=None)
        mock_get.return_value = mock_msg
        mock_pin.return_value = mock_msg

        response = client_employee.patch(
            f"/api/v1/connect/messages/{msg_id}/pin",
            json={"isPinned": True},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["is_pinned"] is True


def test_api_9_delete_message_forbidden(client_employee):
    """9. DELETE /api/v1/connect/messages/{messageId} - employee forbidden to delete other's message."""
    msg_id = uuid.uuid4()
    other_user_id = uuid.uuid4()

    with patch("app.services.connect_service.ConnectRepository.get_message_by_id", new_callable=AsyncMock) as mock_get:
        mock_msg = MagicMock()
        mock_msg.id = msg_id
        mock_msg.sender_id = other_user_id
        mock_msg.conversation_id = None
        mock_msg.channel_id = None
        mock_get.return_value = mock_msg

        res = client_employee.delete(f"/api/v1/connect/messages/{msg_id}")
        assert res.status_code == 403


def test_api_9_delete_message_hr_admin_allowed(client_hr_admin):
    """9. DELETE /api/v1/connect/messages/{messageId} - hr_admin authorized to delete message."""
    msg_id = uuid.uuid4()
    other_user_id = uuid.uuid4()

    with patch("app.services.connect_service.ConnectRepository.get_message_by_id", new_callable=AsyncMock) as mock_get, \
         patch("app.services.connect_service.ConnectRepository.soft_delete_message", new_callable=AsyncMock) as mock_del:
        mock_msg = MagicMock()
        mock_msg.id = msg_id
        mock_msg.sender_id = other_user_id
        mock_msg.conversation_id = None
        mock_msg.channel_id = None
        mock_get.return_value = mock_msg

        res = client_hr_admin.delete(f"/api/v1/connect/messages/{msg_id}")
        assert res.status_code == 200
        assert res.json()["success"] is True


def test_api_10_and_11_message_thread(client_employee):
    """10 & 11. GET & POST /api/v1/connect/messages/{parentMessageId}/thread"""
    parent_id = uuid.uuid4()
    with patch("app.services.connect_service.ConnectRepository.get_message_by_id", new_callable=AsyncMock) as mock_get, \
         patch("app.services.connect_service.ConnectRepository.get_thread_messages", new_callable=AsyncMock) as mock_thread, \
         patch("app.services.connect_service.ConnectRepository.create_message", new_callable=AsyncMock) as mock_create:
        mock_parent = MagicMock()
        mock_parent.id = parent_id
        mock_parent.conversation_id = None
        mock_parent.channel_id = None
        mock_get.return_value = mock_parent

        mock_reply = MagicMock()
        mock_reply.id = uuid.uuid4()
        mock_reply.conversation_id = None
        mock_reply.channel_id = None
        mock_reply.sender_id = EMPLOYEE_USER_ID
        mock_reply.sender = MagicMock(name="Employee User", profile_photo=None)
        mock_reply.content = "Reply to parent"
        mock_reply.voice_url = None
        mock_reply.voice_duration = None
        mock_reply.is_pinned = False
        mock_reply.pinned_at = None
        mock_reply.pinned_by = None
        mock_reply.reply_to_id = None
        mock_reply.parent_message_id = parent_id
        mock_reply.reactions = []
        mock_reply.attachments = []
        mock_reply.is_deleted = False
        mock_reply.created_at = datetime.utcnow()
        mock_reply.updated_at = datetime.utcnow()

        mock_thread.return_value = [mock_reply]
        mock_create.return_value = mock_reply

        # 10. GET thread
        get_res = client_employee.get(f"/api/v1/connect/messages/{parent_id}/thread")
        assert get_res.status_code == 200
        assert len(get_res.json()["data"]) == 1

        # 11. POST thread reply
        post_res = client_employee.post(
            f"/api/v1/connect/messages/{parent_id}/thread",
            json={"text": "Reply to parent"},
        )
        assert post_res.status_code == 201
        assert post_res.json()["data"]["content"] == "Reply to parent"


# ===========================================================================
# C. TEAM CHANNELS TESTS
# ===========================================================================

def test_api_12_and_13_channels(client_employee):
    """12 & 13. GET & POST /api/v1/connect/channels"""
    chan_id = uuid.uuid4()
    with patch("app.services.connect_service.ConnectRepository.get_channels", new_callable=AsyncMock) as mock_get, \
         patch("app.services.connect_service.ConnectRepository.create_channel", new_callable=AsyncMock) as mock_create:
        mock_chan = MagicMock()
        mock_chan.id = chan_id
        mock_chan.name = "Engineering"
        mock_chan.description = "Eng team"
        mock_chan.is_private = False
        mock_chan.is_archived = False
        mock_chan.created_by = EMPLOYEE_USER_ID
        mock_chan.members = []
        mock_chan.created_at = datetime.utcnow()
        mock_chan.updated_at = datetime.utcnow()
        mock_chan.creator = MagicMock(name="Creator", profile_photo=None)

        mock_get.return_value = [mock_chan]
        mock_create.return_value = mock_chan

        # 12. GET channels
        res_get = client_employee.get("/api/v1/connect/channels?search=Eng")
        assert res_get.status_code == 200
        assert len(res_get.json()["data"]) == 1

        # 13. POST channel
        res_post = client_employee.post(
            "/api/v1/connect/channels",
            json={"name": "Engineering", "description": "Eng team", "isPrivate": False, "memberIds": []},
        )
        assert res_post.status_code == 201
        assert res_post.json()["data"]["name"] == "Engineering"


def test_api_14_to_18_channel_ops(client_employee):
    """14 to 18. Channel details, messages, post, leave, archive."""
    chan_id = uuid.uuid4()
    with patch("app.services.connect_service.ConnectRepository.get_channel_by_id", new_callable=AsyncMock) as mock_get_chan, \
         patch("app.services.connect_service.ConnectRepository.get_channel_messages", new_callable=AsyncMock) as mock_get_msgs, \
         patch("app.services.connect_service.ConnectRepository.create_message", new_callable=AsyncMock) as mock_post_msg, \
         patch("app.services.connect_service.ConnectRepository.remove_channel_member", new_callable=AsyncMock) as mock_leave, \
         patch("app.services.connect_service.ConnectRepository.archive_channel", new_callable=AsyncMock) as mock_archive:
        mock_chan = MagicMock()
        mock_chan.id = chan_id
        mock_chan.name = "General"
        mock_chan.description = "All hands"
        mock_chan.is_private = False
        mock_chan.is_archived = False
        mock_chan.created_by = EMPLOYEE_USER_ID
        mock_chan.members = []
        mock_chan.created_at = datetime.utcnow()
        mock_chan.updated_at = datetime.utcnow()
        mock_chan.creator = MagicMock(name="Creator", profile_photo=None)
        mock_get_chan.return_value = mock_chan
        mock_archive.return_value = mock_chan

        mock_msg = MagicMock()
        mock_msg.id = uuid.uuid4()
        mock_msg.conversation_id = None
        mock_msg.channel_id = chan_id
        mock_msg.sender_id = EMPLOYEE_USER_ID
        mock_msg.sender = MagicMock(name="Employee User", profile_photo=None)
        mock_msg.content = "Channel announcement"
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
        mock_get_msgs.return_value = [mock_msg]
        mock_post_msg.return_value = mock_msg

        # 14. GET channel detail
        res14 = client_employee.get(f"/api/v1/connect/channels/{chan_id}")
        assert res14.status_code == 200
        assert res14.json()["data"]["name"] == "General"

        # 15. GET channel messages
        res15 = client_employee.get(f"/api/v1/connect/channels/{chan_id}/messages")
        assert res15.status_code == 200
        assert len(res15.json()["data"]) == 1

        # 16. POST channel message
        res16 = client_employee.post(f"/api/v1/connect/channels/{chan_id}/messages", json={"text": "Channel announcement"})
        assert res16.status_code == 201

        # 17. POST leave channel
        res17 = client_employee.post(f"/api/v1/connect/channels/{chan_id}/leave")
        assert res17.status_code == 200
        assert res17.json()["data"]["left"] is True

        # 18. PATCH archive channel
        res18 = client_employee.patch(f"/api/v1/connect/channels/{chan_id}/archive", json={"isArchived": True})
        assert res18.status_code == 200


# ===========================================================================
# D. CALLS & WEBRTC TESTS
# ===========================================================================

def test_api_19_to_22_calls_and_signaling(client_employee):
    """19 to 22. Call history, initiate, status update, WebRTC signal relay."""
    call_id = uuid.uuid4()
    with patch("app.services.connect_service.ConnectRepository.get_call_history", new_callable=AsyncMock) as mock_hist, \
         patch("app.services.connect_service.ConnectRepository.create_call_log", new_callable=AsyncMock) as mock_init, \
         patch("app.services.connect_service.ConnectRepository.get_call_by_id", new_callable=AsyncMock) as mock_get_call, \
         patch("app.services.connect_service.ConnectRepository.update_call_status", new_callable=AsyncMock) as mock_upd_call:
        mock_call = MagicMock()
        mock_call.id = call_id
        mock_call.caller_id = EMPLOYEE_USER_ID
        mock_call.caller = MagicMock(name="Caller", profile_photo=None)
        mock_call.callee_id = TARGET_USER_ID
        mock_call.callee = MagicMock(name="Callee", profile_photo=None)
        mock_call.call_type = "video"
        mock_call.status = "initiated"
        mock_call.room_id = "call_room_123"
        mock_call.duration_seconds = 45
        mock_call.started_at = datetime.utcnow()
        mock_call.connected_at = datetime.utcnow()
        mock_call.ended_at = datetime.utcnow()
        mock_call.created_at = datetime.utcnow()

        mock_hist.return_value = [mock_call]
        mock_init.return_value = mock_call
        mock_get_call.return_value = mock_call
        mock_upd_call.return_value = mock_call

        # 19. GET call history
        res19 = client_employee.get("/api/v1/connect/calls/history")
        assert res19.status_code == 200
        assert len(res19.json()["data"]) == 1

        # 20. POST initiate call
        res20 = client_employee.post(
            "/api/v1/connect/calls/initiate",
            json={"targetUserId": str(TARGET_USER_ID), "type": "video"},
        )
        assert res20.status_code == 201
        assert res20.json()["data"]["call_type"] == "video"

        # 21. PATCH update call status
        res21 = client_employee.patch(
            f"/api/v1/connect/calls/{call_id}/status",
            json={"status": "connected"},
        )
        assert res21.status_code == 200

        # 22. POST WebRTC signal relay
        res22 = client_employee.post(
            f"/api/v1/connect/calls/{call_id}/signal",
            json={"type": "offer", "payload": {"sdp": "v=0..."}, "targetUserId": str(TARGET_USER_ID)},
        )
        assert res22.status_code == 200
        assert res22.json()["data"]["relayed"] is True


# ===========================================================================
# E. VIDEO MEETINGS TESTS
# ===========================================================================

def test_api_23_to_28_meetings(client_employee):
    """23 to 28. Meetings listing, create, details, join, leave, in-meeting chat."""
    meeting_id = uuid.uuid4()
    with patch("app.services.connect_service.ConnectRepository.get_user_meetings", new_callable=AsyncMock) as mock_get_meets, \
         patch("app.services.connect_service.ConnectRepository.create_meeting", new_callable=AsyncMock) as mock_create_meet, \
         patch("app.services.connect_service.ConnectRepository.get_meeting_by_id", new_callable=AsyncMock) as mock_get_m, \
         patch("app.services.connect_service.ConnectRepository.join_meeting", new_callable=AsyncMock) as mock_join_m, \
         patch("app.services.connect_service.ConnectRepository.leave_meeting", new_callable=AsyncMock) as mock_leave_m, \
         patch("app.services.connect_service.ConnectRepository.add_meeting_message", new_callable=AsyncMock) as mock_msg_m:
        mock_meeting = MagicMock()
        mock_meeting.id = meeting_id
        mock_meeting.title = "Weekly Sync"
        mock_meeting.description = "Status updates"
        mock_meeting.meeting_code = "meet-abc12345"
        mock_meeting.meeting_type = "scheduled"
        mock_meeting.status = "scheduled"
        mock_meeting.host_id = EMPLOYEE_USER_ID
        mock_meeting.host = MagicMock(name="Host", profile_photo=None)
        mock_meeting.start_time = datetime.utcnow()
        mock_meeting.end_time = None
        mock_meeting.duration_minutes = 30
        mock_meeting.allow_screen_share = True
        mock_meeting.allow_microphone = True
        mock_meeting.allow_camera = True
        mock_meeting.is_private = False
        mock_meeting.participants = []
        mock_meeting.created_at = datetime.utcnow()

        mock_get_meets.return_value = [mock_meeting]
        mock_create_meet.return_value = mock_meeting
        mock_get_m.return_value = mock_meeting
        mock_join_m.return_value = MagicMock(role="participant")
        mock_leave_m.return_value = mock_meeting
        mock_msg_m.return_value = MagicMock(id=uuid.uuid4(), created_at=datetime.utcnow())

        # 23. GET meetings
        res23 = client_employee.get("/api/v1/connect/meetings")
        assert res23.status_code == 200
        assert len(res23.json()["data"]) == 1

        # 24. POST create meeting
        res24 = client_employee.post(
            "/api/v1/connect/meetings",
            json={"title": "Weekly Sync", "type": "scheduled", "duration": 30, "participantIds": []},
        )
        assert res24.status_code == 201

        # 25. GET meeting detail
        res25 = client_employee.get(f"/api/v1/connect/meetings/{meeting_id}")
        assert res25.status_code == 200

        # 26. POST join meeting
        res26 = client_employee.post(f"/api/v1/connect/meetings/{meeting_id}/join")
        assert res26.status_code == 200

        # 27. POST leave meeting
        res27 = client_employee.post(f"/api/v1/connect/meetings/{meeting_id}/leave", json={"endForEveryone": False})
        assert res27.status_code == 200

        # 28. POST in-meeting chat message
        res28 = client_employee.post(f"/api/v1/connect/meetings/{meeting_id}/messages", json={"message": "Hello everyone!"})
        assert res28.status_code == 201


# ===========================================================================
# F. SHARED FILES TESTS
# ===========================================================================

def test_api_29_to_31_shared_files(client_employee):
    """29 to 31. Shared files list, upload multipart/form-data, delete with authorization."""
    file_id = uuid.uuid4()
    with patch("app.services.connect_service.ConnectRepository.get_shared_files", new_callable=AsyncMock) as mock_get_f, \
         patch("app.services.connect_service.ConnectRepository.create_shared_file", new_callable=AsyncMock) as mock_create_f, \
         patch("app.services.connect_service.ConnectRepository.get_shared_file_by_id", new_callable=AsyncMock) as mock_get_one, \
         patch("app.services.connect_service.ConnectRepository.delete_shared_file", new_callable=AsyncMock) as mock_del_f:
        mock_file = MagicMock()
        mock_file.id = file_id
        mock_file.file_name = "spec.pdf"
        mock_file.file_url = "/uploads/connect/spec.pdf"
        mock_file.file_path = "/tmp/spec.pdf"
        mock_file.file_type = "application/pdf"
        mock_file.file_category = "documents"
        mock_file.file_size = 1024
        mock_file.uploader_id = EMPLOYEE_USER_ID
        mock_file.uploader = MagicMock(name="Employee User")
        mock_file.created_at = datetime.utcnow()

        mock_get_f.return_value = ([mock_file], 1)
        mock_create_f.return_value = mock_file
        mock_get_one.return_value = mock_file

        # 29. GET files
        res29 = client_employee.get("/api/v1/connect/files?filter=documents")
        assert res29.status_code == 200
        assert len(res29.json()["data"]["files"]) == 1

        # 30. POST upload file
        file_content = b"%PDF-1.4 dummy pdf content for testing"
        res30 = client_employee.post(
            "/api/v1/connect/files/upload",
            files={"file": ("spec.pdf", io.BytesIO(file_content), "application/pdf")},
        )
        assert res30.status_code == 201
        assert res30.json()["data"]["file_name"] == "spec.pdf"

        # 31. DELETE file (owner)
        res31 = client_employee.delete(f"/api/v1/connect/files/{file_id}")
        assert res31.status_code == 200
        assert res31.json()["data"]["deleted"] is True


def test_api_31_delete_shared_file_admin_allowed(client_hr_admin):
    """31. DELETE file (HR Admin deleting employee's file)."""
    file_id = uuid.uuid4()
    with patch("app.services.connect_service.ConnectRepository.get_shared_file_by_id", new_callable=AsyncMock) as mock_get_one, \
         patch("app.services.connect_service.ConnectRepository.delete_shared_file", new_callable=AsyncMock) as mock_del_f:
        mock_file = MagicMock()
        mock_file.id = file_id
        mock_file.uploader_id = EMPLOYEE_USER_ID
        mock_file.file_path = "/tmp/spec.pdf"
        mock_get_one.return_value = mock_file

        res = client_hr_admin.delete(f"/api/v1/connect/files/{file_id}")
        assert res.status_code == 200
        assert res.json()["data"]["deleted"] is True


# ===========================================================================
# G. PRESENCE TESTS
# ===========================================================================

def test_api_32_and_33_presence(client_employee):
    """32 & 33. Update presence and batch presence lookup."""
    with patch("app.services.connect_service.ConnectRepository.upsert_presence", new_callable=AsyncMock) as mock_upd, \
         patch("app.services.connect_service.ConnectRepository.get_batch_presence", new_callable=AsyncMock) as mock_batch:
        mock_pres = MagicMock()
        mock_pres.status = "busy"
        mock_pres.custom_status = "In a meeting"
        mock_pres.last_seen_at = datetime.utcnow()
        mock_pres.updated_at = datetime.utcnow()
        mock_pres.user_id = EMPLOYEE_USER_ID
        mock_upd.return_value = mock_pres
        mock_batch.return_value = [mock_pres]

        # 32. PUT presence
        res32 = client_employee.put("/api/v1/connect/presence", json={"status": "busy", "customStatus": "In a meeting"})
        assert res32.status_code == 200
        assert res32.json()["data"]["status"] == "busy"

        # 33. POST presence batch
        res33 = client_employee.post("/api/v1/connect/presence/batch", json={"userIds": [str(EMPLOYEE_USER_ID)]})
        assert res33.status_code == 200
        assert len(res33.json()["data"]) == 1


# ===========================================================================
# H. NOTIFICATIONS TESTS
# ===========================================================================

def test_api_34_to_36_notifications(client_employee):
    """34 to 36. Notifications list, mark read, clear."""
    notif_id = uuid.uuid4()
    with patch("app.services.connect_service.ConnectRepository.get_notifications", new_callable=AsyncMock) as mock_get, \
         patch("app.services.connect_service.ConnectRepository.mark_notification_read", new_callable=AsyncMock) as mock_read, \
         patch("app.services.connect_service.ConnectRepository.delete_user_notifications", new_callable=AsyncMock) as mock_del:
        mock_n = MagicMock()
        mock_n.id = notif_id
        mock_n.notification_type = "message"
        mock_n.title = "New message"
        mock_n.body = "Hey there"
        mock_n.resource_type = "conversation"
        mock_n.resource_id = str(uuid.uuid4())
        mock_n.is_read = False
        mock_n.read_at = None
        mock_n.sender_id = TARGET_USER_ID
        mock_n.sender = MagicMock(name="Target User")
        mock_n.created_at = datetime.utcnow()

        mock_get.return_value = [mock_n]
        mock_read.return_value = mock_n

        # 34. GET notifications
        res34 = client_employee.get("/api/v1/connect/notifications?unreadOnly=true")
        assert res34.status_code == 200
        assert len(res34.json()["data"]) == 1

        # 35. PATCH mark read
        res35 = client_employee.patch(f"/api/v1/connect/notifications/{notif_id}/read")
        assert res35.status_code == 200

        # 36. DELETE clear notifications
        res36 = client_employee.delete("/api/v1/connect/notifications")
        assert res36.status_code == 200
        assert res36.json()["data"]["cleared"] is True


# ===========================================================================
# I. SOUND SETTINGS TESTS
# ===========================================================================

def test_api_37_and_38_sound_settings(client_employee):
    """37 & 38. GET and PUT sound settings."""
    with patch("app.services.connect_service.ConnectRepository.get_sound_settings", new_callable=AsyncMock) as mock_get, \
         patch("app.services.connect_service.ConnectRepository.upsert_sound_settings", new_callable=AsyncMock) as mock_set:
        mock_s = MagicMock()
        mock_s.master_volume = 90
        mock_s.is_muted = False
        mock_s.incoming_call_chime = True
        mock_s.outgoing_call_chime = True
        mock_s.message_chime = True
        mock_s.mention_chime = True
        mock_s.meeting_chime = True
        mock_s.ringtone = "aurix_default_ringtone.mp3"
        mock_s.notification_tone = "aurix_default_notification.mp3"

        mock_get.return_value = mock_s
        mock_set.return_value = mock_s

        # 37. GET sound settings
        res37 = client_employee.get("/api/v1/connect/settings/sound")
        assert res37.status_code == 200
        assert res37.json()["data"]["masterVolume"] == 90

        # 38. PUT sound settings
        res38 = client_employee.put("/api/v1/connect/settings/sound", json={"masterVolume": 90, "isMuted": False})
        assert res38.status_code == 200
        assert res38.json()["data"]["masterVolume"] == 90


# ===========================================================================
# J. AI COPILOT TESTS
# ===========================================================================

@pytest.mark.parametrize("action", ["professional", "generate_reply", "tone", "shorten", "expand", "summarize"])
def test_api_39_ai_transform_actions(client_employee, action):
    """39. POST /api/v1/connect/ai/transform for all 6 actions."""
    with patch("app.llm.client.LLMClient.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = f"AI transformed for {action}"

        response = client_employee.post(
            "/api/v1/connect/ai/transform",
            json={"text": "Pls finish the report asap", "action": action, "tone": "urgent"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["action"] == action
        assert "transformed_text" in body["data"]


# ===========================================================================
# K. MAIL DISPATCH TESTS
# ===========================================================================

def test_api_40_mail_dispatch(client_employee):
    """40. POST /api/v1/connect/mail/dispatch with recipient validation."""
    with patch("app.services.email_service.send_email", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = None

        response = client_employee.post(
            "/api/v1/connect/mail/dispatch",
            json={
                "to": ["colleague@example.com"],
                "subject": "Sprint Review Notes",
                "body": "Hi team, please find attached the review notes.",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["dispatched"] is True
        assert body["data"]["recipient_count"] == 1


# ===========================================================================
# TENANT ISOLATION SECURITY TESTS
# ===========================================================================

def test_tenant_isolation_forbidden_cross_company(client_employee):
    """Security: Prevent cross-tenant access when X-Company-ID header does not match user's company."""
    response = client_employee.get(
        "/api/v1/connect/colleagues",
        headers={"X-Company-ID": str(OTHER_COMPANY_ID)},
    )
    assert response.status_code == 403
    assert response.json()["success"] is False
    assert "Access denied" in response.json()["message"]
