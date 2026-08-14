"""Comprehensive test suite for all 14 OFC360 Helpdesk & Support Backend APIs."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
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

TEST_COMPANY_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
OTHER_COMPANY_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

EMPLOYEE_USER_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
OTHER_EMPLOYEE_ID = uuid.UUID("66666666-7777-8888-9999-000000000000")
MANAGER_USER_ID = uuid.UUID("22222222-3333-4444-5555-666666666666")
HR_ADMIN_USER_ID = uuid.UUID("33333333-4444-5555-6666-777777777777")
IT_ADMIN_USER_ID = uuid.UUID("44444444-5555-6666-7777-888888888888")


def make_mock_user(user_id: uuid.UUID, role: UserRole, company_id: uuid.UUID, name: str = "Test User") -> User:
    user = MagicMock(spec=User)
    user.id = user_id
    user.name = name
    user.first_name = name.split()[0]
    user.last_name = name.split()[1] if len(name.split()) > 1 else ""
    user.email = f"{name.lower().replace(' ', '.')}@example.com"
    user.phone = "9876543210"
    user.role = role
    user.company_id = company_id
    user.is_active = True
    user.profile_photo = None
    user.department = "IT Support" if role == UserRole.IT_ADMIN else "Engineering"
    user.created_at = datetime.now(timezone.utc)
    return user


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
def manager_user():
    return make_mock_user(MANAGER_USER_ID, UserRole.MANAGER, TEST_COMPANY_ID, "Manager User")


@pytest.fixture
def hr_admin_user():
    return make_mock_user(HR_ADMIN_USER_ID, UserRole.HR_ADMIN, TEST_COMPANY_ID, "HR Admin")


@pytest.fixture
def it_admin_user():
    return make_mock_user(IT_ADMIN_USER_ID, UserRole.IT_ADMIN, TEST_COMPANY_ID, "IT Admin")


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
def client_manager(manager_user):
    """Test client authenticated as Manager."""
    app.dependency_overrides[get_current_user] = lambda: manager_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(manager_user.id),
        "role": "manager",
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


@pytest.fixture
def client_it_admin(it_admin_user):
    """Test client authenticated as IT Admin."""
    app.dependency_overrides[get_current_user] = lambda: it_admin_user
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(it_admin_user.id),
        "role": "it_admin",
        "company_id": str(TEST_COMPANY_ID),
        "type": "access",
    }
    app.dependency_overrides[get_db_session] = mock_get_db
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.clear()


def make_mock_ticket(
    ticket_id: uuid.UUID,
    requester_id: uuid.UUID = EMPLOYEE_USER_ID,
    assigned_to_id: uuid.UUID | None = None,
    status: str = "Open",
    priority: str = "High",
    ticket_number: str = "TICKET-8422",
) -> MagicMock:
    t = MagicMock()
    t.id = ticket_id
    t.company_id = TEST_COMPANY_ID
    t.ticket_number = ticket_number
    t.requester_id = requester_id
    t.assigned_to_id = assigned_to_id
    t.department = "IT Support"
    t.category = "Payroll & Salary"
    t.priority = priority
    t.status = status
    t.subject = "July Tax Deduction mismatch"
    t.description = "Detailed problem description"
    t.resolution_notes = None
    t.sla_first_response_due_at = datetime.now(timezone.utc)
    t.sla_resolution_due_at = datetime.now(timezone.utc)
    t.first_responded_at = None
    t.resolved_at = None
    t.closed_at = None
    t.attachments = []
    t.comments = []
    t.internal_notes = []
    t.created_at = datetime.now(timezone.utc)
    t.updated_at = datetime.now(timezone.utc)

    # Requester user mock
    req = MagicMock(spec=User)
    req.id = requester_id
    req.name = "Employee User"
    req.email = "employee.user@example.com"
    req.role = UserRole.EMPLOYEE
    req.profile_photo = None
    req.department = "Engineering"
    t.requester = req

    # Assigned to user mock
    if assigned_to_id:
        ass = MagicMock(spec=User)
        ass.id = assigned_to_id
        ass.name = "IT Agent"
        ass.email = "it.agent@example.com"
        ass.role = UserRole.IT_ADMIN
        ass.profile_photo = None
        ass.department = "IT Support"
        t.assigned_to = ass
    else:
        t.assigned_to = None

    return t


# ===========================================================================
# 1. getMySupportTickets
# ===========================================================================

def test_api_1_get_my_support_tickets(client_employee):
    """1. GET /api/v1/helpdesk/tickets/my with query filters and pagination."""
    ticket_id = uuid.uuid4()
    mock_ticket = make_mock_ticket(ticket_id, requester_id=EMPLOYEE_USER_ID)

    with patch("app.services.helpdesk_service.HelpdeskRepository.get_my_tickets", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = ([mock_ticket], 1)

        response = client_employee.get("/api/v1/helpdesk/tickets/my?status=ALL&category=Payroll&search=Tax&page=1&limit=20")
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert "items" in body["data"]
        assert len(body["data"]["items"]) == 1
        assert body["data"]["items"][0]["ticketNumber"] == "TICKET-8422"
        assert body["data"]["meta"]["total"] == 1


# ===========================================================================
# 2. createSupportTicket
# ===========================================================================

def test_api_2_create_support_ticket(client_employee):
    """2. POST /api/v1/helpdesk/tickets - ticket creation with auto SLA calculation."""
    ticket_id = uuid.uuid4()
    mock_ticket = make_mock_ticket(ticket_id, requester_id=EMPLOYEE_USER_ID, priority="High", ticket_number="TICKET-1234")

    with patch("app.services.helpdesk_service.HelpdeskRepository.create_ticket", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_ticket

        response = client_employee.post(
            "/api/v1/helpdesk/tickets",
            json={
                "category": "Payroll & Salary",
                "priority": "High",
                "subject": "July Tax Deduction mismatch",
                "description": "Detailed problem description",
                "attachmentIds": [],
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["success"] is True
        assert body["data"]["ticketNumber"] == "TICKET-1234"
        assert body["data"]["status"] == "Open"
        assert body["data"]["priority"] == "High"


# ===========================================================================
# 3. getTicketById
# ===========================================================================

def test_api_3_get_ticket_by_id_owner(client_employee):
    """3. GET /api/v1/helpdesk/tickets/{ticketId} - owner access."""
    ticket_id = uuid.uuid4()
    mock_ticket = make_mock_ticket(ticket_id, requester_id=EMPLOYEE_USER_ID)

    with patch("app.services.helpdesk_service.HelpdeskRepository.get_ticket_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_ticket

        response = client_employee.get(f"/api/v1/helpdesk/tickets/{ticket_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["id"] == str(ticket_id)


def test_api_3_get_ticket_by_id_idor_forbidden(client_employee):
    """3. GET /api/v1/helpdesk/tickets/{ticketId} - IDOR prevented on other user's ticket."""
    ticket_id = uuid.uuid4()
    mock_ticket = make_mock_ticket(ticket_id, requester_id=OTHER_EMPLOYEE_ID)

    with patch("app.services.helpdesk_service.HelpdeskRepository.get_ticket_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_ticket

        response = client_employee.get(f"/api/v1/helpdesk/tickets/{ticket_id}")
        assert response.status_code == 403
        assert response.json()["success"] is False


def test_api_3_get_ticket_by_id_admin_allowed(client_hr_admin):
    """3. GET /api/v1/helpdesk/tickets/{ticketId} - HR admin allowed full company ticket access."""
    ticket_id = uuid.uuid4()
    mock_ticket = make_mock_ticket(ticket_id, requester_id=EMPLOYEE_USER_ID)

    with patch("app.services.helpdesk_service.HelpdeskRepository.get_ticket_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_ticket

        response = client_hr_admin.get(f"/api/v1/helpdesk/tickets/{ticket_id}")
        assert response.status_code == 200
        assert response.json()["success"] is True


# ===========================================================================
# 4. getTicketComments
# ===========================================================================

def test_api_4_get_ticket_comments(client_employee):
    """4. GET /api/v1/helpdesk/tickets/{ticketId}/comments - discussion comments."""
    ticket_id = uuid.uuid4()
    comment_id = uuid.uuid4()
    mock_ticket = make_mock_ticket(ticket_id, requester_id=EMPLOYEE_USER_ID)

    mock_comment = MagicMock()
    mock_comment.id = comment_id
    mock_comment.ticket_id = ticket_id
    mock_comment.author_id = EMPLOYEE_USER_ID
    mock_comment.author = mock_ticket.requester
    mock_comment.message = "I have uploaded the relevant tax slips."
    mock_comment.attachments = []
    mock_comment.created_at = datetime.now(timezone.utc)

    with patch("app.services.helpdesk_service.HelpdeskRepository.get_ticket_by_id", new_callable=AsyncMock) as mock_get_t, \
         patch("app.services.helpdesk_service.HelpdeskRepository.get_ticket_comments", new_callable=AsyncMock) as mock_get_c:
        mock_get_t.return_value = mock_ticket
        mock_get_c.return_value = [mock_comment]

        response = client_employee.get(f"/api/v1/helpdesk/tickets/{ticket_id}/comments")
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert len(body["data"]) == 1
        assert body["data"][0]["message"] == "I have uploaded the relevant tax slips."
        assert body["data"][0]["isInternalNote"] is False


# ===========================================================================
# 5. addTicketComment
# ===========================================================================

def test_api_5_add_ticket_comment(client_employee):
    """5. POST /api/v1/helpdesk/tickets/{ticketId}/comments - post comment."""
    ticket_id = uuid.uuid4()
    comment_id = uuid.uuid4()
    mock_ticket = make_mock_ticket(ticket_id, requester_id=EMPLOYEE_USER_ID)

    mock_comment = MagicMock()
    mock_comment.id = comment_id
    mock_comment.ticket_id = ticket_id
    mock_comment.author_id = EMPLOYEE_USER_ID
    mock_comment.author = mock_ticket.requester
    mock_comment.message = "I tried the proposed fix."
    mock_comment.attachments = []
    mock_comment.created_at = datetime.now(timezone.utc)

    with patch("app.services.helpdesk_service.HelpdeskRepository.get_ticket_by_id", new_callable=AsyncMock) as mock_get_t, \
         patch("app.services.helpdesk_service.HelpdeskRepository.add_comment", new_callable=AsyncMock) as mock_add_c:
        mock_get_t.return_value = mock_ticket
        mock_add_c.return_value = mock_comment

        response = client_employee.post(
            f"/api/v1/helpdesk/tickets/{ticket_id}/comments",
            json={"message": "I tried the proposed fix.", "attachments": []},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["success"] is True
        assert body["data"]["message"] == "I tried the proposed fix."


def test_api_5_add_ticket_comment_closed_forbidden(client_employee):
    """5. POST comment on closed ticket rejected."""
    ticket_id = uuid.uuid4()
    mock_ticket = make_mock_ticket(ticket_id, requester_id=EMPLOYEE_USER_ID, status="Closed")

    with patch("app.services.helpdesk_service.HelpdeskRepository.get_ticket_by_id", new_callable=AsyncMock) as mock_get_t:
        mock_get_t.return_value = mock_ticket

        response = client_employee.post(
            f"/api/v1/helpdesk/tickets/{ticket_id}/comments",
            json={"message": "Replying to closed ticket"},
        )
        assert response.status_code == 422
        assert "Cannot reply to a closed ticket" in response.json()["message"]


# ===========================================================================
# 6. uploadTicketAttachment
# ===========================================================================

def test_api_6_upload_ticket_attachment(client_employee):
    """6. POST /api/v1/helpdesk/tickets/attachments/upload - file upload."""
    att_id = uuid.uuid4()
    mock_att = MagicMock()
    mock_att.id = att_id
    mock_att.name = "tax_slip.pdf"
    mock_att.size = 1024
    mock_att.type = "application/pdf"
    mock_att.url = f"/uploads/helpdesk/hd_{att_id.hex}.pdf"
    mock_att.created_at = datetime.now(timezone.utc)

    with patch("app.services.helpdesk_service.HelpdeskRepository.create_attachment", new_callable=AsyncMock) as mock_create_a:
        mock_create_a.return_value = mock_att

        file_bytes = b"%PDF-1.4 dummy pdf document content"
        response = client_employee.post(
            "/api/v1/helpdesk/tickets/attachments/upload",
            files={"file": ("tax_slip.pdf", io.BytesIO(file_bytes), "application/pdf")},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["success"] is True
        assert body["data"]["name"] == "tax_slip.pdf"


def test_api_6_upload_oversized_attachment_413(client_employee):
    """6. Oversized attachment (>10MB) returns 413 Payload Too Large."""
    oversized_bytes = b"0" * (11 * 1024 * 1024)
    response = client_employee.post(
        "/api/v1/helpdesk/tickets/attachments/upload",
        files={"file": ("large_dump.zip", io.BytesIO(oversized_bytes), "application/zip")},
    )
    assert response.status_code == 413
    assert "exceeds maximum allowed limit" in response.json()["message"]


# ===========================================================================
# 7. getAllHelpdeskTickets (Admin)
# ===========================================================================

def test_api_7_get_all_admin_tickets(client_hr_admin):
    """7. GET /api/v1/helpdesk/admin/tickets - admin overview with counts."""
    ticket_id = uuid.uuid4()
    mock_ticket = make_mock_ticket(ticket_id, requester_id=EMPLOYEE_USER_ID)

    counts = {
        "total": 24,
        "openCount": 8,
        "inProgressCount": 11,
        "resolvedCount": 5,
        "filteredTotal": 1,
    }

    with patch("app.services.helpdesk_service.HelpdeskRepository.get_all_admin_tickets", new_callable=AsyncMock) as mock_get_all:
        mock_get_all.return_value = ([mock_ticket], counts)

        response = client_hr_admin.get("/api/v1/helpdesk/admin/tickets?status=Open&priority=High&page=1&limit=30")
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert len(body["data"]["items"]) == 1
        assert body["data"]["meta"]["openCount"] == 8
        assert body["data"]["meta"]["inProgressCount"] == 11
        assert body["data"]["meta"]["resolvedCount"] == 5


def test_api_7_get_all_admin_tickets_employee_forbidden(client_employee):
    """7. Regular employee forbidden from accessing admin tickets view."""
    response = client_employee.get("/api/v1/helpdesk/admin/tickets")
    assert response.status_code == 403


# ===========================================================================
# 8. updateTicketStatus
# ===========================================================================

def test_api_8_update_ticket_status_valid(client_it_admin):
    """8. PATCH /api/v1/helpdesk/tickets/{ticketId}/status - transition Open -> In Progress."""
    ticket_id = uuid.uuid4()
    mock_ticket = make_mock_ticket(ticket_id, status="Open")
    updated_ticket = make_mock_ticket(ticket_id, status="In Progress")

    with patch("app.services.helpdesk_service.HelpdeskRepository.get_ticket_by_id", new_callable=AsyncMock) as mock_get_t, \
         patch("app.services.helpdesk_service.HelpdeskRepository.update_ticket_status", new_callable=AsyncMock) as mock_upd_s:
        mock_get_t.return_value = mock_ticket
        mock_upd_s.return_value = updated_ticket

        response = client_it_admin.patch(
            f"/api/v1/helpdesk/tickets/{ticket_id}/status",
            json={"status": "In Progress"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["status"] == "In Progress"


def test_api_8_update_ticket_status_invalid_transition(client_it_admin):
    """8. Invalid transition Closed -> In Progress rejected."""
    ticket_id = uuid.uuid4()
    mock_ticket = make_mock_ticket(ticket_id, status="Closed")

    with patch("app.services.helpdesk_service.HelpdeskRepository.get_ticket_by_id", new_callable=AsyncMock) as mock_get_t:
        mock_get_t.return_value = mock_ticket

        response = client_it_admin.patch(
            f"/api/v1/helpdesk/tickets/{ticket_id}/status",
            json={"status": "In Progress"},
        )
        assert response.status_code == 422
        assert "Cannot transition ticket" in response.json()["message"]


# ===========================================================================
# 9. assignTicketAgent
# ===========================================================================

def test_api_9_assign_ticket_agent(client_it_admin):
    """9. PATCH /api/v1/helpdesk/tickets/{ticketId}/assign - assign agent."""
    ticket_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    mock_ticket = make_mock_ticket(ticket_id, assigned_to_id=None)
    assigned_ticket = make_mock_ticket(ticket_id, assigned_to_id=agent_id)

    mock_agent_user = make_mock_user(agent_id, UserRole.IT_ADMIN, TEST_COMPANY_ID, "IT Agent")

    with patch("app.services.helpdesk_service.HelpdeskRepository.get_ticket_by_id", new_callable=AsyncMock) as mock_get_t, \
         patch("app.services.helpdesk_service.HelpdeskRepository.assign_ticket_agent", new_callable=AsyncMock) as mock_assign, \
         patch("sqlalchemy.ext.asyncio.AsyncSession.execute", new_callable=AsyncMock) as mock_exec:
        mock_get_t.return_value = mock_ticket
        mock_assign.return_value = assigned_ticket

        # Mock DB select for agent user
        exec_res = MagicMock()
        exec_res.scalar_one_or_none.return_value = mock_agent_user
        mock_exec.return_value = exec_res

        response = client_it_admin.patch(
            f"/api/v1/helpdesk/tickets/{ticket_id}/assign",
            json={"assignedToUserId": str(agent_id), "department": "IT Support"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["assignedTo"]["id"] == str(agent_id)


# ===========================================================================
# 10. addInternalTicketNote
# ===========================================================================

def test_api_10_add_internal_note_staff_allowed(client_it_admin):
    """10. POST /api/v1/helpdesk/tickets/{ticketId}/internal-notes - staff note."""
    ticket_id = uuid.uuid4()
    note_id = uuid.uuid4()
    mock_ticket = make_mock_ticket(ticket_id)

    mock_note = MagicMock()
    mock_note.id = note_id
    mock_note.ticket_id = ticket_id
    mock_note.author_id = IT_ADMIN_USER_ID
    mock_note.author = make_mock_user(IT_ADMIN_USER_ID, UserRole.IT_ADMIN, TEST_COMPANY_ID, "IT Admin")
    mock_note.note = "RMA initiated with Dell support."
    mock_note.created_at = datetime.now(timezone.utc)

    with patch("app.services.helpdesk_service.HelpdeskRepository.get_ticket_by_id", new_callable=AsyncMock) as mock_get_t, \
         patch("app.services.helpdesk_service.HelpdeskRepository.add_internal_note", new_callable=AsyncMock) as mock_add_n:
        mock_get_t.return_value = mock_ticket
        mock_add_n.return_value = mock_note

        response = client_it_admin.post(
            f"/api/v1/helpdesk/tickets/{ticket_id}/internal-notes",
            json={"note": "RMA initiated with Dell support."},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["success"] is True
        assert body["data"]["note"] == "RMA initiated with Dell support."


def test_api_10_add_internal_note_employee_forbidden(client_employee):
    """10. Employee forbidden from creating internal staff notes."""
    ticket_id = uuid.uuid4()
    response = client_employee.post(
        f"/api/v1/helpdesk/tickets/{ticket_id}/internal-notes",
        json={"note": "Employee trying to add internal note"},
    )
    assert response.status_code == 403


# ===========================================================================
# 11. getHelpdeskFAQs
# ===========================================================================

def test_api_11_get_helpdesk_faqs(client_employee):
    """11. GET /api/v1/helpdesk/faqs - knowledge base retrieval."""
    mock_faq = MagicMock()
    mock_faq.id = uuid.uuid4()
    mock_faq.category = "IT Support"
    mock_faq.question = "How do I configure VPN?"
    mock_faq.answer = "Follow the company VPN setup instructions."
    mock_faq.is_public = True
    mock_faq.view_count = 15
    mock_faq.is_helpful_count = 12
    mock_faq.created_at = datetime.now(timezone.utc)
    mock_faq.updated_at = datetime.now(timezone.utc)

    with patch("app.services.helpdesk_service.HelpdeskRepository.get_faqs", new_callable=AsyncMock) as mock_get_faqs:
        mock_get_faqs.return_value = [mock_faq]

        response = client_employee.get("/api/v1/helpdesk/faqs?category=IT Support&search=VPN")
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert len(body["data"]) == 1
        assert body["data"][0]["question"] == "How do I configure VPN?"


# ===========================================================================
# 12. upsertHelpdeskFAQ (Admin)
# ===========================================================================

def test_api_12_upsert_helpdesk_faq_admin_allowed(client_it_admin):
    """12. POST /api/v1/helpdesk/admin/faqs - admin upsert FAQ."""
    mock_faq = MagicMock()
    mock_faq.id = uuid.uuid4()
    mock_faq.category = "IT Support"
    mock_faq.question = "How do I configure VPN?"
    mock_faq.answer = "Follow the company VPN setup instructions."
    mock_faq.is_public = True
    mock_faq.view_count = 0
    mock_faq.is_helpful_count = 0
    mock_faq.created_at = datetime.now(timezone.utc)
    mock_faq.updated_at = datetime.now(timezone.utc)

    with patch("app.services.helpdesk_service.HelpdeskRepository.upsert_faq", new_callable=AsyncMock) as mock_upsert:
        mock_upsert.return_value = mock_faq

        response = client_it_admin.post(
            "/api/v1/helpdesk/admin/faqs",
            json={
                "category": "IT Support",
                "question": "How do I configure VPN?",
                "answer": "Follow the company VPN setup instructions.",
                "is_public": True,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["question"] == "How do I configure VPN?"


def test_api_12_upsert_helpdesk_faq_employee_forbidden(client_employee):
    """12. Employee forbidden from managing FAQs."""
    response = client_employee.post(
        "/api/v1/helpdesk/admin/faqs",
        json={"category": "IT", "question": "Q?", "answer": "A."},
    )
    assert response.status_code == 403


# ===========================================================================
# 13. executeSupportAIChat
# ===========================================================================

def test_api_13_execute_support_ai_chat(client_employee):
    """13. POST /api/v1/helpdesk/ai/chat - AI copilot support chat."""
    mock_faq = MagicMock()
    mock_faq.question = "How many casual leaves can I carry forward?"
    mock_faq.answer = "You can carry forward up to 8 casual leaves per year."

    with patch("app.services.helpdesk_service.HelpdeskRepository.get_faqs", new_callable=AsyncMock) as mock_faqs, \
         patch("app.llm.client.LLMClient.chat", new_callable=AsyncMock) as mock_chat:
        mock_faqs.return_value = [mock_faq]
        mock_chat.return_value = "You can carry forward a maximum of 8 casual leaves into the next calendar year."

        response = client_employee.post(
            "/api/v1/helpdesk/ai/chat",
            json={
                "message": "How many casual leaves can I carry forward?",
                "conversationHistory": [],
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert "casual leaves" in body["data"]["reply"]
        assert body["data"]["deflected"] is True
        assert "Raise Support Ticket" in body["data"]["suggestedActions"]


def test_api_13_ai_chat_rate_limit_429(client_employee):
    """13. AI rate limit handled and returned as 429."""
    with patch("app.services.helpdesk_service.HelpdeskRepository.get_faqs", new_callable=AsyncMock) as mock_faqs, \
         patch("app.llm.client.LLMClient.chat", new_callable=AsyncMock) as mock_chat:
        mock_faqs.return_value = []
        mock_chat.side_effect = Exception("Rate limit reached 429")

        response = client_employee.post(
            "/api/v1/helpdesk/ai/chat",
            json={"message": "Help with VPN"},
        )
        assert response.status_code == 429
        assert "high load" in response.json()["message"]


# ===========================================================================
# 14. getHelpdeskSLAMetrics (Admin)
# ===========================================================================

def test_api_14_get_helpdesk_sla_metrics_admin(client_hr_admin):
    """14. GET /api/v1/helpdesk/admin/metrics - actual DB metrics."""
    metrics = {
        "totalTickets": 45,
        "resolvedTickets": 38,
        "slaComplianceRate": 92.5,
        "averageFirstResponseHours": 2.4,
        "averageResolutionHours": 18.6,
        "categoryBreakdown": {"IT Support": 20, "Payroll & Salary": 15, "General": 10},
        "urgentOpenCount": 2,
    }

    with patch("app.services.helpdesk_service.HelpdeskRepository.calculate_sla_metrics", new_callable=AsyncMock) as mock_m:
        mock_m.return_value = metrics

        response = client_hr_admin.get("/api/v1/helpdesk/admin/metrics")
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["totalTickets"] == 45
        assert body["data"]["slaComplianceRate"] == 92.5
        assert body["data"]["averageResolutionHours"] == 18.6


def test_api_14_get_helpdesk_sla_metrics_employee_forbidden(client_employee):
    """14. Employee forbidden from accessing SLA metrics."""
    response = client_employee.get("/api/v1/helpdesk/admin/metrics")
    assert response.status_code == 403


# ===========================================================================
# Security & Tenant Isolation Tests
# ===========================================================================

def test_tenant_isolation_mismatch_403(client_employee):
    """Security: Prevent cross-tenant ticket access when X-Company-ID header does not match JWT company."""
    response = client_employee.get(
        "/api/v1/helpdesk/tickets/my",
        headers={"X-Company-ID": str(OTHER_COMPANY_ID)},
    )
    assert response.status_code == 403
    assert response.json()["success"] is False
    assert "Access denied" in response.json()["message"]
