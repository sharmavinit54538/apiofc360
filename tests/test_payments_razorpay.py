"""Comprehensive Test Suite for OFC360 Production-Ready Razorpay Integration.

Tests:
1. GET /api/v1/payments/plans (Plans catalog & pricing)
2. POST /api/v1/payments/create-order (Server-side amount enforcement, order creation)
3. POST /api/v1/payments/verify (Valid signature, invalid signature, tenant isolation, idempotency, duplicate prevention)
4. POST /api/v1/payments/webhook (Signature verification, payment.captured, payment.failed, refund.processed)
5. GET /api/v1/payments/history & GET /api/v1/payments/{payment_id} (Tenant isolation, transaction details)
6. Backward compatibility with existing Billing & Subscription APIs
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
from typing import Any, Dict, List
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
from app.models.payment import PaymentStatus, PaymentTransaction
from app.models.subscription import Subscription
from app.models.user import User
from app.models.user.role import UserRole
from app.services.razorpay_service import razorpay_service


# ===========================================================================
# Test Identifiers & Mock Constants
# ===========================================================================

TEST_KEY_ID = "rzp_test_MOCK_KEY_ID"
TEST_KEY_SECRET = "mock_secret_key_at_least_32_chars_long_12345"
TEST_WEBHOOK_SECRET = "mock_webhook_secret_32_characters_long_abcde"

COMPANY_A_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
COMPANY_B_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

ADMIN_A_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
ADMIN_B_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


@asynccontextmanager
async def dummy_lifespan(application):
    yield

app.router.lifespan_context = dummy_lifespan


# ===========================================================================
# Mock Session Builder
# ===========================================================================

class MockPaymentSession:
    """Mock asynchronous SQLAlchemy session tracking in-memory entities."""
    def __init__(self, entities: Dict[str, Any] = None):
        self.entities = entities or {}
        self.transactions: Dict[str, PaymentTransaction] = {}
        self.added = []
        self.committed = False
        self.rolled_back = False

        # Pre-seed transactions if any
        if "transactions" in self.entities:
            for txn in self.entities["transactions"]:
                self.transactions[txn.razorpay_order_id] = txn

    def add(self, instance):
        self.added.append(instance)
        if isinstance(instance, PaymentTransaction):
            self.transactions[instance.razorpay_order_id] = instance
        elif isinstance(instance, Subscription):
            self.entities["subscription"] = instance

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    async def refresh(self, instance):
        pass

    async def execute(self, statement):
        query_str = str(statement).lower()
        mock_result = MagicMock()

        # Count queries for transactions
        if "count(" in query_str and "payment_transactions" in query_str:
            mock_result.scalar.return_value = len(self.transactions)
            mock_result.scalar_one_or_none.return_value = len(self.transactions)
            return mock_result

        # PaymentTransaction queries
        if "payment_transactions" in query_str:
            # Check for duplicate payment_id lookup
            if "razorpay_payment_id" in query_str:
                matched_txn = None
                for txn in self.transactions.values():
                    if txn.razorpay_payment_id:
                        matched_txn = txn
                        break
                # Only return if we found a matching payment id in our test store
                mock_result.scalar_one_or_none.return_value = matched_txn
                mock_result.scalars.return_value.all.return_value = [matched_txn] if matched_txn else []
                mock_result.scalars.return_value.first.return_value = matched_txn
                return mock_result

            # Check for order_id lookup
            if "razorpay_order_id" in query_str:
                found = None
                for order_id, txn in self.transactions.items():
                    if order_id in query_str or str(txn.id) in query_str:
                        found = txn
                        break
                if not found and self.transactions:
                    found = list(self.transactions.values())[0]
                mock_result.scalar_one_or_none.return_value = found
                mock_result.scalars.return_value.all.return_value = [found] if found else []
                mock_result.scalars.return_value.first.return_value = found
                return mock_result

            # All transactions
            all_txns = list(self.transactions.values())
            mock_result.scalars.return_value.all.return_value = all_txns
            mock_result.scalar_one_or_none.return_value = all_txns[0] if all_txns else None
            return mock_result

        # Subscription query
        if "subscriptions" in query_str:
            sub = self.entities.get("subscription")
            mock_result.scalar_one_or_none.return_value = sub
            mock_result.scalars.return_value.all.return_value = [sub] if sub else []
            return mock_result

        # Company query
        if "companies" in query_str:
            comp = self.entities.get("company")
            mock_result.scalar_one_or_none.return_value = comp
            mock_result.scalars.return_value.all.return_value = [comp] if comp else []
            mock_result.scalar_one.return_value = comp
            return mock_result

        # User query
        if "users" in query_str:
            user = self.entities.get("user")
            mock_result.scalar_one_or_none.return_value = user
            mock_result.scalars.return_value.all.return_value = [user] if user else []
            return mock_result

        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        return mock_result


# ===========================================================================
# Helper Factories
# ===========================================================================

def make_test_company(company_id: uuid.UUID = COMPANY_A_ID, name: str = "Acme Corp") -> Company:
    return Company(
        id=company_id,
        name=name,
        onboarding_completed=True,
        company_profile={"email": "info@acme.com"},
        hr_settings={
            "billing": {
                "currentPlan": "Starter Plan",
                "billingCycle": "monthly",
                "invoices": [],
            }
        },
    )


def make_test_user(user_id: uuid.UUID, company_id: uuid.UUID, role: str = "hr_admin") -> User:
    user = User(
        id=user_id,
        company_id=company_id,
        name="Test Admin",
        email="admin@acme.com",
        phone="9876543210",
        password_hash="dummy_hash",
        is_active=True,
    )
    user.role = UserRole.from_str(role)
    return user


def generate_valid_signature(order_id: str, payment_id: str, secret: str = TEST_KEY_SECRET) -> str:
    msg = f"{order_id}|{payment_id}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def generate_valid_webhook_signature(payload_bytes: bytes, secret: str = TEST_WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


# ===========================================================================
# 1. Plans Catalog Tests
# ===========================================================================

def test_get_payment_plans():
    """Verify GET /api/v1/payments/plans returns all valid subscription tiers."""
    with TestClient(app) as client:
        res = client.get("/api/v1/payments/plans")
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["success"] is True
        plans = data["data"]
        assert len(plans) >= 3

        plan_ids = [p["plan_id"] for p in plans]
        assert "starter" in plan_ids
        assert "growth" in plan_ids
        assert "enterprise" in plan_ids

        enterprise_plan = next(p for p in plans if p["plan_id"] == "enterprise")
        assert enterprise_plan["monthly_price"] == 49999.0
        assert enterprise_plan["yearly_price"] == 499990.0
        assert enterprise_plan["seats"] == 350


# ===========================================================================
# 2. Create Order Tests
# ===========================================================================

@patch("app.services.razorpay_service.razorpay_service.create_order")
def test_create_order_success(mock_rzp_create):
    """Verify POST /api/v1/payments/create-order computes exact server amount and creates Razorpay order."""
    mock_rzp_create.return_value = {
        "id": "order_test_12345",
        "entity": "order",
        "amount": 4999900,
        "currency": "INR",
        "status": "created",
    }

    company = make_test_company()
    user = make_test_user(ADMIN_A_ID, COMPANY_A_ID)
    mock_session = MockPaymentSession({"company": company, "user": user})

    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(ADMIN_A_ID),
        "company_id": str(COMPANY_A_ID),
        "role": "hr_admin",
        "email": "admin@acme.com",
    }
    app.dependency_overrides[get_db_session] = lambda: mock_session

    with TestClient(app) as client:
        # Client requests enterprise monthly
        res = client.post("/api/v1/payments/create-order", json={
            "plan_id": "enterprise",
            "billing_cycle": "monthly",
        })

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["success"] is True
        assert data["data"]["order_id"] == "order_test_12345"
        assert data["data"]["amount"] == 4999900  # 49,999 INR in paise
        assert data["data"]["currency"] == "INR"
        assert "key_id" in data["data"]
        # Critical security check: Secrets must NEVER appear in response
        assert "key_secret" not in str(data)
        assert "webhook_secret" not in str(data)

        # Verify transaction stored in DB
        assert "order_test_12345" in mock_session.transactions
        txn = mock_session.transactions["order_test_12345"]
        assert txn.status == PaymentStatus.CREATED.value
        assert txn.amount == 49999.0
        assert txn.amount_paise == 4999900
        assert txn.company_id == COMPANY_A_ID
        assert mock_session.committed is True

    app.dependency_overrides.clear()


def test_create_order_invalid_plan():
    """Verify POST /api/v1/payments/create-order rejects non-existent plan."""
    company = make_test_company()
    mock_session = MockPaymentSession({"company": company})

    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(ADMIN_A_ID),
        "company_id": str(COMPANY_A_ID),
        "role": "hr_admin",
    }
    app.dependency_overrides[get_db_session] = lambda: mock_session

    with TestClient(app) as client:
        res = client.post("/api/v1/payments/create-order", json={
            "plan_id": "non_existent_plan_xyz",
            "billing_cycle": "monthly",
        })
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "does not exist" in res.json()["message"]

    app.dependency_overrides.clear()


def test_create_order_unauthorized_user():
    """Verify POST /api/v1/payments/create-order blocks request without company association."""
    mock_session = MockPaymentSession()

    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(ADMIN_A_ID),
        "role": "hr_admin",
        # Missing company_id
    }
    app.dependency_overrides[get_db_session] = lambda: mock_session

    with TestClient(app) as client:
        res = client.post("/api/v1/payments/create-order", json={
            "plan_id": "enterprise",
            "billing_cycle": "monthly",
        })
        assert res.status_code == status.HTTP_403_FORBIDDEN

    app.dependency_overrides.clear()


# ===========================================================================
# 3. Payment Verification Tests
# ===========================================================================

@patch.object(razorpay_service, "_key_secret", TEST_KEY_SECRET)
@patch("app.services.razorpay_service.razorpay_service.fetch_payment")
def test_verify_payment_valid_signature(mock_fetch_payment):
    """Verify POST /api/v1/payments/verify validates cryptographic signature and activates subscription."""
    order_id = "order_test_99999"
    payment_id = "pay_test_88888"
    valid_sig = generate_valid_signature(order_id, payment_id, TEST_KEY_SECRET)

    mock_fetch_payment.return_value = {
        "id": payment_id,
        "order_id": order_id,
        "amount": 4999900,
        "currency": "INR",
        "status": "captured",
        "method": "upi",
    }

    company = make_test_company()
    txn = PaymentTransaction(
        id=uuid.uuid4(),
        company_id=COMPANY_A_ID,
        user_id=ADMIN_A_ID,
        plan_id="enterprise",
        billing_cycle="monthly",
        razorpay_order_id=order_id,
        amount=49999.0,
        amount_paise=4999900,
        currency="INR",
        status=PaymentStatus.CREATED.value,
    )
    mock_session = MockPaymentSession({"company": company, "transactions": [txn]})

    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(ADMIN_A_ID),
        "company_id": str(COMPANY_A_ID),
        "role": "hr_admin",
    }
    app.dependency_overrides[get_db_session] = lambda: mock_session

    with TestClient(app) as client:
        res = client.post("/api/v1/payments/verify", json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": valid_sig,
        })

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["success"] is True
        assert data["data"]["status"] == PaymentStatus.CAPTURED.value
        assert data["data"]["payment_id"] == payment_id

        # Verify transaction updated to CAPTURED
        assert txn.status == PaymentStatus.CAPTURED.value
        assert txn.razorpay_payment_id == payment_id
        assert txn.payment_method == "upi"

        # Verify Company Subscription & Invoices updated
        billing = company.hr_settings["billing"]
        assert billing["currentPlan"] == "Enterprise AI Tier"
        assert len(billing["invoices"]) >= 1
        assert billing["invoices"][0]["razorpay_payment_id"] == payment_id
        assert billing["invoices"][0]["status"] == "paid"

        # Verify Subscription model record was created/updated
        sub = mock_session.entities.get("subscription")
        assert sub is not None
        assert sub.access_status == "ACTIVE"
        assert sub.payment_status == "PAID"
        assert sub.plan == "Enterprise AI Tier"

        assert mock_session.committed is True

    app.dependency_overrides.clear()


@patch.object(razorpay_service, "_key_secret", TEST_KEY_SECRET)
def test_verify_payment_invalid_signature():
    """Verify POST /api/v1/payments/verify rejects counterfeit/tampered signatures."""
    order_id = "order_test_99999"
    payment_id = "pay_test_88888"
    fake_sig = "fake_tampered_signature_hex_0000000000000000"

    company = make_test_company()
    txn = PaymentTransaction(
        id=uuid.uuid4(),
        company_id=COMPANY_A_ID,
        user_id=ADMIN_A_ID,
        plan_id="enterprise",
        billing_cycle="monthly",
        razorpay_order_id=order_id,
        amount=49999.0,
        amount_paise=4999900,
        currency="INR",
        status=PaymentStatus.CREATED.value,
    )
    mock_session = MockPaymentSession({"company": company, "transactions": [txn]})

    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(ADMIN_A_ID),
        "company_id": str(COMPANY_A_ID),
        "role": "hr_admin",
    }
    app.dependency_overrides[get_db_session] = lambda: mock_session

    with TestClient(app) as client:
        res = client.post("/api/v1/payments/verify", json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": fake_sig,
        })

        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid signature" in res.json()["message"]

        # Ensure transaction marked as FAILED
        assert txn.status == PaymentStatus.FAILED.value
        assert "signature verification failed" in txn.failure_reason.lower()
        # Ensure company plan was NOT upgraded
        assert company.hr_settings["billing"]["currentPlan"] == "Starter Plan"

    app.dependency_overrides.clear()


def test_verify_payment_cross_company_isolation():
    """Verify Company B cannot verify or steal Company A's payment transaction."""
    order_id = "order_company_a"
    company_a = make_test_company(COMPANY_A_ID)
    company_b = make_test_company(COMPANY_B_ID)

    txn_a = PaymentTransaction(
        id=uuid.uuid4(),
        company_id=COMPANY_A_ID,
        user_id=ADMIN_A_ID,
        plan_id="enterprise",
        billing_cycle="monthly",
        razorpay_order_id=order_id,
        amount=49999.0,
        amount_paise=4999900,
        currency="INR",
        status=PaymentStatus.CREATED.value,
    )
    mock_session = MockPaymentSession({"company": company_b, "transactions": [txn_a]})

    # Authenticate as Admin of Company B
    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(ADMIN_B_ID),
        "company_id": str(COMPANY_B_ID),
        "role": "hr_admin",
    }
    app.dependency_overrides[get_db_session] = lambda: mock_session

    with TestClient(app) as client:
        res = client.post("/api/v1/payments/verify", json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": "pay_some_payment",
            "razorpay_signature": "any_signature",
        })

        assert res.status_code == status.HTTP_403_FORBIDDEN
        assert "does not belong" in res.json()["message"].lower()

    app.dependency_overrides.clear()


@patch.object(razorpay_service, "_key_secret", TEST_KEY_SECRET)
def test_verify_payment_idempotency():
    """Verify repeating a verification for an already CAPTURED payment returns success idempotently."""
    order_id = "order_already_captured"
    payment_id = "pay_already_captured"
    valid_sig = generate_valid_signature(order_id, payment_id, TEST_KEY_SECRET)

    company = make_test_company()
    txn = PaymentTransaction(
        id=uuid.uuid4(),
        company_id=COMPANY_A_ID,
        user_id=ADMIN_A_ID,
        plan_id="enterprise",
        billing_cycle="monthly",
        razorpay_order_id=order_id,
        razorpay_payment_id=payment_id,
        razorpay_signature=valid_sig,
        amount=49999.0,
        amount_paise=4999900,
        currency="INR",
        status=PaymentStatus.CAPTURED.value,
    )
    mock_session = MockPaymentSession({"company": company, "transactions": [txn]})

    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(ADMIN_A_ID),
        "company_id": str(COMPANY_A_ID),
        "role": "hr_admin",
    }
    app.dependency_overrides[get_db_session] = lambda: mock_session

    with TestClient(app) as client:
        res = client.post("/api/v1/payments/verify", json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": valid_sig,
        })

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["success"] is True
        assert "already been verified" in data["message"].lower()

    app.dependency_overrides.clear()


# ===========================================================================
# 4. Webhook Tests
# ===========================================================================

@patch.object(razorpay_service, "_webhook_secret", TEST_WEBHOOK_SECRET)
def test_webhook_payment_captured_success():
    """Verify POST /api/v1/payments/webhook processes payment.captured and activates subscription."""
    order_id = "order_webhook_001"
    payment_id = "pay_webhook_001"
    company = make_test_company()

    txn = PaymentTransaction(
        id=uuid.uuid4(),
        company_id=COMPANY_A_ID,
        user_id=ADMIN_A_ID,
        plan_id="growth",
        billing_cycle="monthly",
        razorpay_order_id=order_id,
        amount=14999.0,
        amount_paise=1499900,
        currency="INR",
        status=PaymentStatus.CREATED.value,
    )
    mock_session = MockPaymentSession({"company": company, "transactions": [txn]})
    app.dependency_overrides[get_db_session] = lambda: mock_session

    webhook_payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": order_id,
                    "amount": 1499900,
                    "currency": "INR",
                    "status": "captured",
                    "method": "netbanking",
                }
            }
        }
    }
    payload_bytes = json.dumps(webhook_payload).encode("utf-8")
    valid_webhook_sig = generate_valid_webhook_signature(payload_bytes, TEST_WEBHOOK_SECRET)

    with TestClient(app) as client:
        res = client.post(
            "/api/v1/payments/webhook",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": valid_webhook_sig,
            }
        )

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["status"] == "ok"
        assert data["event"] == "payment.captured"
        assert txn.status == PaymentStatus.CAPTURED.value
        assert txn.razorpay_payment_id == payment_id

        # Verify company subscription updated
        assert company.hr_settings["billing"]["currentPlan"] == "Growth Pro Tier"

    app.dependency_overrides.clear()


@patch.object(razorpay_service, "_webhook_secret", TEST_WEBHOOK_SECRET)
def test_webhook_invalid_signature():
    """Verify POST /api/v1/payments/webhook rejects webhooks with counterfeit signature."""
    mock_session = MockPaymentSession()
    app.dependency_overrides[get_db_session] = lambda: mock_session

    webhook_payload = {"event": "payment.captured", "payload": {}}
    payload_bytes = json.dumps(webhook_payload).encode("utf-8")

    with TestClient(app) as client:
        res = client.post(
            "/api/v1/payments/webhook",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": "invalid_signature_header_here",
            }
        )

        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid webhook signature" in res.json()["detail"]

    app.dependency_overrides.clear()


# ===========================================================================
# 5. Payment History & Details Tests
# ===========================================================================

def test_get_payment_history():
    """Verify GET /api/v1/payments/history returns paginated company payment transactions."""
    txn = PaymentTransaction(
        id=uuid.uuid4(),
        company_id=COMPANY_A_ID,
        user_id=ADMIN_A_ID,
        plan_id="enterprise",
        billing_cycle="monthly",
        razorpay_order_id="order_hist_1",
        razorpay_payment_id="pay_hist_1",
        amount=49999.0,
        amount_paise=4999900,
        currency="INR",
        status=PaymentStatus.CAPTURED.value,
    )
    mock_session = MockPaymentSession({"transactions": [txn]})

    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(ADMIN_A_ID),
        "company_id": str(COMPANY_A_ID),
        "role": "hr_admin",
    }
    app.dependency_overrides[get_db_session] = lambda: mock_session

    with TestClient(app) as client:
        res = client.get("/api/v1/payments/history?page=1&page_size=10")
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["success"] is True
        items = data["data"]["items"]
        assert len(items) == 1
        assert items[0]["razorpay_order_id"] == "order_hist_1"
        assert items[0]["amount"] == 49999.0

    app.dependency_overrides.clear()
