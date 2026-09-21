"""Pydantic schemas for Razorpay Payment Gateway integration."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateOrderPayload(BaseModel):
    """Payload to initiate a Razorpay payment order."""
    plan_id: str = Field(..., min_length=1, max_length=100, description="Subscription plan ID or code (e.g. starter, growth, enterprise)")
    billing_cycle: str = Field("monthly", description="Billing frequency: 'monthly' or 'yearly'")

    @field_validator("billing_cycle")
    @classmethod
    def validate_billing_cycle(cls, v: str) -> str:
        clean = (v or "").strip().lower()
        if clean not in {"monthly", "yearly", "annual"}:
            raise ValueError("billing_cycle must be either 'monthly' or 'yearly'")
        return "yearly" if clean == "annual" else clean

    @field_validator("plan_id")
    @classmethod
    def validate_plan_id(cls, v: str) -> str:
        clean = (v or "").strip().lower()
        if not clean:
            raise ValueError("plan_id cannot be empty")
        return clean


class CreateOrderResponseData(BaseModel):
    """Response data for create order endpoint (contains NO secrets)."""
    order_id: str = Field(..., description="Razorpay order ID (order_xxxxx)")
    amount: int = Field(..., description="Calculated charge amount in paise (e.g. 4999900)")
    currency: str = Field("INR", description="Three-letter ISO currency code")
    key_id: str = Field(..., description="Public Razorpay Key ID for client checkout")
    plan_id: str = Field(..., description="Selected plan identifier")
    plan_name: str = Field(..., description="Human readable plan name")
    billing_cycle: str = Field(..., description="Billing cycle: monthly or yearly")

    model_config = ConfigDict(populate_by_name=True)


class VerifyPaymentPayload(BaseModel):
    """Payload to verify a completed Razorpay payment."""
    razorpay_order_id: str = Field(..., min_length=5, description="Razorpay order ID")
    razorpay_payment_id: str = Field(..., min_length=5, description="Razorpay payment ID (pay_xxxxx)")
    razorpay_signature: str = Field(..., min_length=10, description="Razorpay HMAC SHA256 signature")

    @field_validator("razorpay_order_id", "razorpay_payment_id", "razorpay_signature")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        clean = (v or "").strip()
        if not clean:
            raise ValueError("Field cannot be empty or whitespace.")
        return clean


class PlanDetail(BaseModel):
    """Subscription plan details from backend catalog."""
    plan_id: str
    name: str
    description: str
    monthly_price: float
    yearly_price: float
    currency: str = "INR"
    seats: int
    features: List[str]
    is_popular: bool = False


class PaymentTransactionResponseData(BaseModel):
    """Safe representation of a payment transaction."""
    id: str
    company_id: str
    user_id: Optional[str] = None
    plan_id: str
    billing_cycle: str
    razorpay_order_id: str
    razorpay_payment_id: Optional[str] = None
    amount: float
    currency: str = "INR"
    status: str
    payment_method: Optional[str] = None
    created_at: str
    updated_at: str

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class PaymentHistoryPaginationData(BaseModel):
    """Paginated payment transaction list."""
    items: List[PaymentTransactionResponseData]
    page: int = 1
    page_size: int = 20
    total: int = 0
    pages: int = 1
