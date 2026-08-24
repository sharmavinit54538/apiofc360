"""Dedicated Razorpay Payment Gateway Service for OFC360 Platform."""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any, Dict, List, Optional, Tuple

import razorpay
from fastapi import status

from app.core.config import settings
from app.core.exceptions import AppException

logger = logging.getLogger(__name__)


# ── Canonical Server-Side Subscription Plan Catalog ───────────────────────────
PLANS_CATALOG: Dict[str, Dict[str, Any]] = {
    "starter": {
        "plan_id": "starter",
        "name": "Starter Plan",
        "description": "Essential HRMS and attendance tools for growing teams.",
        "monthly_price": 4999.0,
        "yearly_price": 49990.0,
        "currency": "INR",
        "seats": 50,
        "features": [
            "Core Employee Management",
            "Attendance & Leave Tracking",
            "Basic Reports & Analytics",
            "Standard Email Support",
        ],
        "is_popular": False,
    },
    "growth": {
        "plan_id": "growth",
        "name": "Growth Pro Tier",
        "description": "Advanced recruitment, performance AI, and payroll compliance for scaling organizations.",
        "monthly_price": 14999.0,
        "yearly_price": 149990.0,
        "currency": "INR",
        "seats": 150,
        "features": [
            "Everything in Starter",
            "AI Recruiter & Resume Matcher",
            "Automated Payroll & Tax Engine",
            "Employee Performance Review Cycles",
            "Priority Support",
        ],
        "is_popular": True,
    },
    "enterprise": {
        "plan_id": "enterprise",
        "name": "Enterprise AI Tier",
        "description": "Complete AI-powered workforce intelligence, predictive analytics, and 24/7 dedicated support.",
        "monthly_price": 49999.0,
        "yearly_price": 499990.0,
        "currency": "INR",
        "seats": 350,
        "features": [
            "Unlimited AI Workflows",
            "Autonomous Screening & Interviews",
            "Full HR & Payroll Intelligence",
            "Document Intelligence & OCR",
            "24/7 Priority Support & SLA",
            "Custom Roles & Permissions",
        ],
        "is_popular": False,
    },
}


class RazorpayService:
    """Production service encapsulating all Razorpay interactions with zero secret leaks."""

    def __init__(self):
        self._key_id = settings.RAZORPAY_KEY_ID
        self._key_secret = (
            settings.RAZORPAY_KEY_SECRET.get_secret_value()
            if hasattr(settings.RAZORPAY_KEY_SECRET, "get_secret_value")
            else str(settings.RAZORPAY_KEY_SECRET or "")
        )
        self._webhook_secret = (
            settings.RAZORPAY_WEBHOOK_SECRET.get_secret_value()
            if hasattr(settings.RAZORPAY_WEBHOOK_SECRET, "get_secret_value")
            else str(settings.RAZORPAY_WEBHOOK_SECRET or "")
        )

    @property
    def key_id(self) -> str:
        """Public key identifier for frontend checkout consumption."""
        return self._key_id

    def get_client(self) -> razorpay.Client:
        """Return authenticated Razorpay SDK client."""
        if not self._key_id or not self._key_secret:
            logger.error("Razorpay keys are missing or not configured in environment.")
            raise AppException(
                message="Payment gateway is currently unavailable. Please contact administrator.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return razorpay.Client(auth=(self._key_id, self._key_secret))

    @staticmethod
    def get_all_plans() -> List[Dict[str, Any]]:
        """Return the available subscription plans catalog."""
        return list(PLANS_CATALOG.values())

    @staticmethod
    def get_plan_details(plan_id: str, billing_cycle: str = "monthly") -> Tuple[Dict[str, Any], float, int]:
        """
        Validate requested plan against canonical backend catalog and calculate server-side amount.
        Returns: (plan_dict, amount_in_rupees, amount_in_paise)
        NEVER trusts client-supplied amount.
        """
        clean_plan_id = (plan_id or "").strip().lower()
        # Handle variants like "starter_monthly", "enterprise_tier", "plan-enterprise"
        resolved_key = None
        for key in PLANS_CATALOG:
            if key == clean_plan_id or key in clean_plan_id:
                resolved_key = key
                break

        if not resolved_key or resolved_key not in PLANS_CATALOG:
            logger.warning("Invalid subscription plan requested: '%s'", plan_id)
            raise AppException(
                message=f"Plan '{plan_id}' does not exist. Available plans: {', '.join(PLANS_CATALOG.keys())}.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        plan = PLANS_CATALOG[resolved_key]
        cycle = (billing_cycle or "monthly").strip().lower()
        if cycle in {"yearly", "annual", "year"}:
            amount_rupees = float(plan["yearly_price"])
        else:
            amount_rupees = float(plan["monthly_price"])

        # Convert to paise (1 INR = 100 paise)
        amount_paise = int(round(amount_rupees * 100))
        return plan, amount_rupees, amount_paise

    def create_order(
        self,
        amount_paise: int,
        currency: str = "INR",
        receipt: Optional[str] = None,
        notes: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create a new payment order via Razorpay API.
        """
        client = self.get_client()
        order_data = {
            "amount": amount_paise,
            "currency": currency or settings.RAZORPAY_CURRENCY or "INR",
            "receipt": receipt or f"rcpt_{hashlib.md5(str(amount_paise).encode()).hexdigest()[:12]}",
            "notes": notes or {},
            "payment_capture": 1,  # Auto-capture payment upon authorization
        }

        try:
            logger.info("Initiating Razorpay order creation for receipt: %s", order_data["receipt"])
            razorpay_order = client.order.create(data=order_data)
            logger.info("Razorpay order created successfully: %s", razorpay_order.get("id"))
            return razorpay_order
        except Exception as e:
            logger.error("Razorpay order creation failed: %s", str(e), exc_info=True)
            raise AppException(
                message="Failed to create payment order with payment gateway.",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

    def fetch_order(self, order_id: str) -> Dict[str, Any]:
        """Fetch order details from Razorpay."""
        client = self.get_client()
        try:
            return client.order.fetch(order_id)
        except Exception as e:
            logger.error("Failed to fetch Razorpay order %s: %s", order_id, str(e))
            raise AppException(
                message="Unable to fetch order details from payment gateway.",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

    def fetch_payment(self, payment_id: str) -> Dict[str, Any]:
        """Fetch payment details from Razorpay."""
        client = self.get_client()
        try:
            return client.payment.fetch(payment_id)
        except Exception as e:
            logger.error("Failed to fetch Razorpay payment %s: %s", payment_id, str(e))
            raise AppException(
                message="Unable to fetch payment details from payment gateway.",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

    def verify_payment_signature(
        self,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
    ) -> bool:
        """
        Cryptographically verify the Razorpay HMAC-SHA256 signature using the SECRET KEY.
        Returns True if signature is valid, False otherwise.
        """
        if not self._key_secret:
            logger.error("Cannot verify payment signature: RAZORPAY_KEY_SECRET is not configured.")
            return False

        if not razorpay_order_id or not razorpay_payment_id or not razorpay_signature:
            return False

        msg = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
        secret_bytes = self._key_secret.encode("utf-8")
        expected_signature = hmac.new(secret_bytes, msg, hashlib.sha256).hexdigest()

        is_valid = hmac.compare_digest(expected_signature, razorpay_signature.strip())
        if not is_valid:
            logger.warning(
                "Payment signature verification failed for order %s and payment %s",
                razorpay_order_id,
                razorpay_payment_id,
            )
        return is_valid

    def verify_webhook_signature(self, body_bytes: bytes, signature_header: str) -> bool:
        """
        Cryptographically verify the incoming Razorpay webhook signature header.
        Uses RAZORPAY_WEBHOOK_SECRET if set, falling back to RAZORPAY_KEY_SECRET.
        """
        secret = self._webhook_secret or self._key_secret
        if not secret:
            logger.error("Cannot verify webhook signature: Webhook secret is not configured.")
            return False

        if not signature_header or not body_bytes:
            return False

        secret_bytes = secret.encode("utf-8")
        expected_signature = hmac.new(secret_bytes, body_bytes, hashlib.sha256).hexdigest()

        return hmac.compare_digest(expected_signature, signature_header.strip())

    def refund_payment(
        self,
        payment_id: str,
        amount_paise: Optional[int] = None,
        notes: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Issue a refund for a captured payment."""
        client = self.get_client()
        refund_data: Dict[str, Any] = {"notes": notes or {}}
        if amount_paise is not None:
            refund_data["amount"] = amount_paise

        try:
            logger.info("Initiating refund for Razorpay payment %s", payment_id)
            refund = client.payment.refund(payment_id, refund_data)
            logger.info("Refund initiated successfully: %s", refund.get("id"))
            return refund
        except Exception as e:
            logger.error("Refund failed for payment %s: %s", payment_id, str(e))
            raise AppException(
                message="Failed to issue refund with payment gateway.",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )


# Singleton service instance
razorpay_service = RazorpayService()
