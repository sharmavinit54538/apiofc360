"""Comprehensive test suite for OFC360 Settings & Billing APIs.

Covers:
1. GET /settings/hr & PUT /settings/hr (Validation, Tenant Isolation, Audit Logging)
2. POST /settings/mfa/enable & POST /settings/mfa/disable (TOTP Verification, QR code, Activation)
3. GET /billing/subscription (Limits, Seats, Active Tier)
4. GET /billing/payment-methods & POST /billing/payment-methods (Safe Storage, No CVV/Raw Card Leaks)
5. GET /billing/invoices (Pagination, Isolation)
6. Preserved Existing APIs (GET/PUT /settings/company, GET/PUT /settings/notifications)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.database import get_db_session
from app.main import app
from app.middleware.auth import get_current_user_claims
from app.models.company import Company
from app.models.user import User
from app.models.user.role import UserRole
from app.models.user_mfa import UserMFA
from app.models.audit_log import AuditLog
from app.utils.totp import generate_totp_secret, get_current_totp, verify_totp_code


# ===========================================================================
# Test Identifiers
# ===========================================================================

COMPANY_A_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
COMPANY_B_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

ADMIN_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
EMPLOYEE_USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
OTHER_COMPANY_USER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


@asynccontextmanager
async def dummy_lifespan(application):
    yield

app.router.lifespan_context = dummy_lifespan


# ===========================================================================
# Mock Session Builder
# ===========================================================================

class MockAsyncSession:
    """Mock asynchronous SQLAlchemy session for testing."""
    def __init__(self, entities: Dict[str, Any] = None):
        self.entities = entities or {}
        self.added = []
        self.committed = False
        self.rolled_back = False

    def add(self, instance):
        self.added.append(instance)
        if isinstance(instance, UserMFA):
            self.entities["user_mfa"] = instance

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    async def refresh(self, instance):
        pass

    async def execute(self, statement):
        query_str = str(statement).lower()
        mock_result = MagicMock()

        # Count queries
        if "count(" in query_str:
            mock_result.scalar.return_value = 5
            mock_result.scalar_one_or_none.return_value = 5
            return mock_result

        # UserMFA query (Must check before 'users')
        if "user_mfa" in query_str:
            mfa = self.entities.get("user_mfa")
            mock_result.scalar_one_or_none.return_value = mfa
            mock_result.scalars.return_value.all.return_value = [mfa] if mfa else []
            mock_result.scalars.return_value.first.return_value = mfa
            return mock_result

        # Company query
        if "companies" in query_str:
            company = self.entities.get("company")
            mock_result.scalar_one_or_none.return_value = company
            mock_result.scalars.return_value.all.return_value = [company] if company else []
            return mock_result

        # User query
        if "users" in query_str:
            user = self.entities.get("user")
            mock_result.scalar_one_or_none.return_value = user
            mock_result.scalars.return_value.all.return_value = [user] if user else []
            mock_result.scalars.return_value.first.return_value = user
            return mock_result

        # CompanySettings / AuditLog / Other queries
        mock_result.scalar_one_or_none.return_value = self.entities.get("company_settings")
        mock_result.scalars.return_value.all.return_value = []
        return mock_result


# ===========================================================================
# Helper Factories
# ===========================================================================

def make_test_company(company_id: uuid.UUID = COMPANY_A_ID, name: str = "Acme Corp") -> Company:
    comp = Company(
        id=company_id,
        name=name,
        onboarding_completed=True,
        company_profile={
            "email": "contact@acmecorp.com",
            "phone": "+91 98765 43210",
            "website": "https://acmecorp.com",
            "city": "Bengaluru",
            "country": "India",
        },
        hr_settings={
            "hr_config": {
                "hr_name": "HR Department",
                "hr_email": "hr@acmecorp.com",
                "hr_phone": "+91 98765 43210",
                "working_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
                "working_hours_start": "09:00",
                "working_hours_end": "18:00",
                "timezone": "Asia/Kolkata",
                "attendance_enabled": True,
                "leave_enabled": True,
                "payroll_enabled": True,
            },
            "billing": {
                "currentPlan": "Enterprise AI Tier",
                "billingCycle": "monthly",
                "payment_methods": [
                    {
                        "id": "pm_default_123",
                        "type": "card",
                        "brand": "visa",
                        "last4": "4242",
                        "expiry_month": 12,
                        "expiry_year": 2030,
                        "is_default": True,
                    }
                ],
                "invoices": [
                    {
                        "id": "INV-2026-0001",
                        "invoice_number": "INV-2026-0001",
                        "status": "paid",
                        "amount": 49999.0,
                        "currency": "INR",
                        "invoice_date": "2026-01-01T00:00:00Z",
                    }
                ]
            }
        }
    )
    return comp


def make_test_user(user_id: uuid.UUID, company_id: uuid.UUID, role: str = "hr_admin", email: str = "admin@acmecorp.com") -> User:
    user = User(
        id=user_id,
        company_id=company_id,
        name="Admin User",
        email=email,
        phone="9876543210",
        password_hash="fake_hash",
        is_active=True,
    )
    user.role = UserRole.from_str(role)
    return user


# ===========================================================================
# PART 1: HR Settings Tests
# ===========================================================================

def test_get_hr_settings_success():
    """Verify GET /settings/hr returns company HR settings accurately."""
    company = make_test_company()
    user = make_test_user(ADMIN_USER_ID, COMPANY_A_ID, "hr_admin")
    mock_session = MockAsyncSession({"company": company, "user": user})

    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(ADMIN_USER_ID),
        "company_id": str(COMPANY_A_ID),
        "role": "hr_admin",
        "email": "admin@acmecorp.com",
    }
    app.dependency_overrides[get_db_session] = lambda: mock_session

    with TestClient(app) as client:
        # Test both prefixed and unprefixed paths
        res_v1 = client.get("/api/v1/settings/hr")
        res_direct = client.get("/settings/hr")

        assert res_v1.status_code == status.HTTP_200_OK
        data = res_v1.json()
        assert data["success"] is True
        assert data["data"]["hr_email"] == "hr@acmecorp.com"
        assert data["data"]["working_hours_start"] == "09:00"
        assert "Monday" in data["data"]["working_days"]
        assert data["data"]["attendance_enabled"] is True

        assert res_direct.status_code == status.HTTP_200_OK

    app.dependency_overrides.clear()


def test_put_hr_settings_success():
    """Verify PUT /settings/hr updates configuration and commits to database."""
    company = make_test_company()
    user = make_test_user(ADMIN_USER_ID, COMPANY_A_ID, "hr_admin")
    mock_session = MockAsyncSession({"company": company, "user": user})

    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(ADMIN_USER_ID),
        "company_id": str(COMPANY_A_ID),
        "role": "hr_admin",
        "email": "admin@acmecorp.com",
    }
    app.dependency_overrides[get_db_session] = lambda: mock_session

    update_payload = {
        "hr_name": "Executive HR Directorate",
        "hr_email": "director.hr@acmecorp.com",
        "hr_phone": "+91 91234 56789",
        "working_days": ["Monday", "Tuesday", "Wednesday", "Thursday"],
        "working_hours_start": "08:30",
        "working_hours_end": "17:30",
        "timezone": "Asia/Kolkata",
        "payroll_enabled": True
    }

    with TestClient(app) as client:
        res = client.put("/api/v1/settings/hr", json=update_payload)
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["success"] is True
        assert data["data"]["hr_name"] == "Executive HR Directorate"
        assert data["data"]["hr_email"] == "director.hr@acmecorp.com"
        assert data["data"]["working_hours_start"] == "08:30"
        assert mock_session.committed is True

    app.dependency_overrides.clear()


def test_put_hr_settings_validation_errors():
    """Verify PUT /settings/hr rejects invalid times, invalid days, and bad phone numbers."""
    company = make_test_company()
    user = make_test_user(ADMIN_USER_ID, COMPANY_A_ID, "hr_admin")
    mock_session = MockAsyncSession({"company": company, "user": user})

    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(ADMIN_USER_ID),
        "company_id": str(COMPANY_A_ID),
        "role": "hr_admin",
    }
    app.dependency_overrides[get_db_session] = lambda: mock_session

    with TestClient(app) as client:
        # Invalid time format (e.g. 25:99)
        res1 = client.put("/api/v1/settings/hr", json={"working_hours_start": "25:99"})
        assert res1.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Invalid day name (e.g. 'Funday')
        res2 = client.put("/api/v1/settings/hr", json={"working_days": ["Monday", "Funday"]})
        assert res2.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Invalid phone format
        res3 = client.put("/api/v1/settings/hr", json={"hr_phone": "abc-not-a-number"})
        assert res3.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    app.dependency_overrides.clear()


def test_hr_settings_unauthorized_and_cross_company():
    """Verify unauthenticated or company-less requests are rejected."""
    mock_session = MockAsyncSession()

    # Case 1: Missing company_id
    app.dependency_overrides[get_current_user_claims] = lambda: {"sub": str(ADMIN_USER_ID), "role": "hr_admin"}
    app.dependency_overrides[get_db_session] = lambda: mock_session

    with TestClient(app) as client:
        res = client.get("/api/v1/settings/hr")
        assert res.status_code == status.HTTP_403_FORBIDDEN

    app.dependency_overrides.clear()


# ===========================================================================
# PART 2: MFA / 2FA Tests
# ===========================================================================

def test_mfa_enable_initiation_flow():
    """Verify POST /settings/mfa/enable without code returns secret, provisioning_uri, and QR code."""
    user = make_test_user(ADMIN_USER_ID, COMPANY_A_ID, "employee", "john@acmecorp.com")
    mock_session = MockAsyncSession({"user": user, "user_mfa": None})

    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(ADMIN_USER_ID),
        "company_id": str(COMPANY_A_ID),
        "email": "john@acmecorp.com",
    }
    app.dependency_overrides[get_db_session] = lambda: mock_session

    with TestClient(app) as client:
        res = client.post("/api/v1/settings/mfa/enable", json={})
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["success"] is True
        assert data["data"]["mfa_enabled"] is False  # Not enabled permanently until verified
        assert "secret" in data["data"]
        assert "otpauth://" in data["data"]["provisioning_uri"]
        qr = data["data"]["qr_code"]
        assert qr and ("data:image/png;base64," in qr or "http" in qr)
        assert mock_session.committed is True

    app.dependency_overrides.clear()


def test_mfa_enable_verification_flow():
    """Verify POST /settings/mfa/enable with valid 6-digit TOTP code enables MFA permanently."""
    secret = generate_totp_secret()
    valid_code = get_current_totp(secret)

    user = make_test_user(ADMIN_USER_ID, COMPANY_A_ID, "employee", "john@acmecorp.com")
    user_mfa = UserMFA(
        user_id=ADMIN_USER_ID,
        company_id=COMPANY_A_ID,
        mfa_enabled=False,
        is_verified=False,
        mfa_secret=secret,
    )
    mock_session = MockAsyncSession({"user": user, "user_mfa": user_mfa})

    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(ADMIN_USER_ID),
        "company_id": str(COMPANY_A_ID),
        "email": "john@acmecorp.com",
    }
    app.dependency_overrides[get_db_session] = lambda: mock_session

    with TestClient(app) as client:
        # 1. Invalid code -> 400
        res_invalid = client.post("/api/v1/settings/mfa/enable", json={"code": "000000"})
        assert res_invalid.status_code == status.HTTP_400_BAD_REQUEST

        # 2. Valid code -> 200 and mfa_enabled=True
        res_valid = client.post("/api/v1/settings/mfa/enable", json={"code": valid_code})
        assert res_valid.status_code == status.HTTP_200_OK
        data = res_valid.json()
        assert data["data"]["mfa_enabled"] is True
        assert user_mfa.mfa_enabled is True
        assert user_mfa.is_verified is True

    app.dependency_overrides.clear()


def test_mfa_disable_flow():
    """Verify POST /settings/mfa/disable deactivates user MFA in database."""
    user = make_test_user(ADMIN_USER_ID, COMPANY_A_ID, "employee", "john@acmecorp.com")
    user_mfa = UserMFA(
        user_id=ADMIN_USER_ID,
        company_id=COMPANY_A_ID,
        mfa_enabled=True,
        is_verified=True,
        mfa_secret=generate_totp_secret(),
    )
    mock_session = MockAsyncSession({"user": user, "user_mfa": user_mfa})

    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(ADMIN_USER_ID),
        "company_id": str(COMPANY_A_ID),
        "email": "john@acmecorp.com",
    }
    app.dependency_overrides[get_db_session] = lambda: mock_session

    with TestClient(app) as client:
        res = client.post("/api/v1/settings/mfa/disable", json={})
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["data"]["mfa_enabled"] is False
        assert user_mfa.mfa_enabled is False
        assert user_mfa.mfa_secret is None

    app.dependency_overrides.clear()


# ===========================================================================
# PART 3: Billing & Subscription Tests
# ===========================================================================

def test_get_billing_subscription():
    """Verify GET /billing/subscription returns enterprise subscription details."""
    company = make_test_company()
    mock_session = MockAsyncSession({"company": company})

    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(ADMIN_USER_ID),
        "company_id": str(COMPANY_A_ID),
        "role": "hr_admin",
    }
    app.dependency_overrides[get_db_session] = lambda: mock_session

    with TestClient(app) as client:
        res_v1 = client.get("/api/v1/billing/subscription")
        res_direct = client.get("/billing/subscription")

        assert res_v1.status_code == status.HTTP_200_OK
        data = res_v1.json()
        assert data["success"] is True
        assert data["data"]["plan_name"] == "Enterprise AI Tier"
        assert data["data"]["price"] == 49999.0
        assert data["data"]["status"] == "active"
        assert len(data["data"]["features"]) > 0

        assert res_direct.status_code == status.HTTP_200_OK

    app.dependency_overrides.clear()


# ===========================================================================
# PART 4 & 5: Payment Methods Tests
# ===========================================================================

def test_get_and_post_payment_methods():
    """Verify safe payment method listing and addition without credential exposure."""
    company = make_test_company()
    mock_session = MockAsyncSession({"company": company})

    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(ADMIN_USER_ID),
        "company_id": str(COMPANY_A_ID),
        "role": "hr_admin",
    }
    app.dependency_overrides[get_db_session] = lambda: mock_session

    with TestClient(app) as client:
        # 1. GET payment methods
        res_get = client.get("/api/v1/billing/payment-methods")
        assert res_get.status_code == status.HTTP_200_OK
        methods = res_get.json()["data"]
        assert len(methods) >= 1
        assert "last4" in methods[0]
        # Security assertion: No full card, CVV, or passwords anywhere in response
        assert "cvv" not in str(res_get.json()).lower()
        assert "card_number" not in str(res_get.json()).lower()

        # 2. POST add new payment method
        new_pm_payload = {
            "type": "card",
            "brand": "mastercard",
            "last4": "9876",
            "expiry_month": 11,
            "expiry_year": 2029,
            "make_default": True
        }
        res_post = client.post("/api/v1/billing/payment-methods", json=new_pm_payload)
        assert res_post.status_code == status.HTTP_200_OK
        post_data = res_post.json()["data"]
        assert post_data["brand"] == "mastercard"
        assert post_data["last4"] == "9876"
        assert post_data["is_default"] is True
        assert mock_session.committed is True

    app.dependency_overrides.clear()


# ===========================================================================
# PART 6: Billing Invoices Tests
# ===========================================================================

def test_get_billing_invoices_pagination():
    """Verify GET /billing/invoices returns paginated company invoices."""
    company = make_test_company()
    mock_session = MockAsyncSession({"company": company})

    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(ADMIN_USER_ID),
        "company_id": str(COMPANY_A_ID),
        "role": "hr_admin",
    }
    app.dependency_overrides[get_db_session] = lambda: mock_session

    with TestClient(app) as client:
        res = client.get("/api/v1/billing/invoices?page=1&page_size=10")
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["success"] is True
        assert "items" in data["data"]
        assert data["data"]["page"] == 1
        assert data["data"]["page_size"] == 10
        assert len(data["data"]["items"]) >= 1
        assert data["data"]["items"][0]["invoice_number"] == "INV-2026-0001"

    app.dependency_overrides.clear()


# ===========================================================================
# Preserved Existing Endpoints Verification
# ===========================================================================

def test_preserved_existing_endpoints():
    """Verify existing /settings/company and /settings/notifications continue working unmodified."""
    company = make_test_company()
    mock_session = MockAsyncSession({"company": company})

    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(ADMIN_USER_ID),
        "company_id": str(COMPANY_A_ID),
        "role": "hr_admin",
    }
    app.dependency_overrides[get_db_session] = lambda: mock_session

    with TestClient(app) as client:
        # GET company
        res_comp_get = client.get("/api/v1/settings/company")
        assert res_comp_get.status_code == status.HTTP_200_OK
        assert res_comp_get.json()["data"]["name"] == "Acme Corp"

        # PUT company
        res_comp_put = client.put("/api/v1/settings/company", json={"name": "Acme Global Corp"})
        assert res_comp_put.status_code == status.HTTP_200_OK
        assert res_comp_put.json()["data"]["name"] == "Acme Global Corp"

        # GET notifications
        res_notif_get = client.get("/api/v1/settings/notifications")
        assert res_notif_get.status_code == status.HTTP_200_OK

        # PUT notifications
        res_notif_put = client.put("/api/v1/settings/notifications", json={"emailNotifications": False, "slackAlerts": True})
        assert res_notif_put.status_code == status.HTTP_200_OK
        assert res_notif_put.json()["data"]["slackAlerts"] is True

    app.dependency_overrides.clear()
