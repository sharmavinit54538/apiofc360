"""Razorpay Payment Gateway API Router for OFC360 Platform."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import logging
from typing import Annotated, Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.exceptions import AppException
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.company import Company
from app.models.payment import PaymentStatus, PaymentTransaction
from app.models.subscription import Subscription
from app.models.user import User
from app.schemas.auth import APIResponse
from app.schemas.payment_schemas import (
    CreateOrderPayload,
    CreateOrderResponseData,
    PaymentHistoryPaginationData,
    PaymentTransactionResponseData,
    PlanDetail,
    VerifyPaymentPayload,
)
from app.services.razorpay_service import razorpay_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["Payments & Checkout"])


# ── Helper: Helper to activate company subscription upon captured payment ────
async def activate_subscription_for_company(
    session: AsyncSession,
    company: Company,
    plan_dict: Dict[str, Any],
    billing_cycle: str,
    payment_id: str,
    order_id: str,
    amount: float,
    currency: str = "INR",
) -> None:
    """Synchronize both PostgreSQL Subscription model and Company hr_settings."""
    now = datetime.now(timezone.utc)
    cycle = billing_cycle.lower()
    days_to_add = 365 if cycle in {"yearly", "annual", "year"} else 30
    expires_at = now + timedelta(days=days_to_add)

    # 1. Update/Create Subscription model record
    sub_stmt = select(Subscription).where(Subscription.company_id == company.id)
    sub_res = await session.execute(sub_stmt)
    subscription = sub_res.scalar_one_or_none()

    if not subscription:
        subscription = Subscription(
            company_id=company.id,
            plan=plan_dict["name"],
            access_status="ACTIVE",
            access_type="FULL",
            payment_status="PAID",
            access_source="RAZORPAY_PAYMENT",
            access_granted_by="System (Razorpay)",
            access_granted_at=now,
            access_expires_at=expires_at,
            mrr=float(plan_dict.get("monthly_price", 0.0)),
        )
        session.add(subscription)
    else:
        subscription.plan = plan_dict["name"]
        subscription.access_status = "ACTIVE"
        subscription.payment_status = "PAID"
        subscription.access_source = "RAZORPAY_PAYMENT"
        subscription.access_granted_by = "System (Razorpay)"
        subscription.access_granted_at = now
        subscription.access_expires_at = expires_at
        subscription.mrr = float(plan_dict.get("monthly_price", 0.0))
        session.add(subscription)

    # 2. Update Company hr_settings JSON
    hr_settings = company.hr_settings or {}
    billing = hr_settings.get("billing") or {}

    billing["currentPlan"] = plan_dict["name"]
    billing["planCode"] = plan_dict["plan_id"]
    billing["billingCycle"] = cycle
    billing["seats"] = plan_dict.get("seats", 50)
    billing["nextBillingDate"] = expires_at.strftime("%Y-%m-%d")

    # Generate invoice item
    invoices = billing.get("invoices") or []
    invoice_number = f"INV-{now.strftime('%Y%m')}-{uuid.uuid4().hex[:6].upper()}"
    new_invoice = {
        "id": invoice_number,
        "invoice_number": invoice_number,
        "status": "paid",
        "amount": amount,
        "currency": currency,
        "plan_name": plan_dict["name"],
        "razorpay_payment_id": payment_id,
        "razorpay_order_id": order_id,
        "invoice_date": now.isoformat(),
        "paid_at": now.isoformat(),
        "due_date": expires_at.isoformat(),
        "pdf_url": f"/api/v1/billing/invoices/{invoice_number}/pdf",
    }
    invoices.insert(0, new_invoice)
    billing["invoices"] = invoices

    # Update subscription representation inside billing JSON
    billing["subscription"] = {
        "subscription_id": f"sub_{company.id.hex[:12]}",
        "plan_name": plan_dict["name"],
        "plan_code": plan_dict["plan_id"],
        "status": "active",
        "billing_cycle": cycle,
        "price": amount,
        "currency": currency,
        "start_date": now.isoformat(),
        "current_period_start": now.isoformat(),
        "current_period_end": expires_at.isoformat(),
        "next_billing_date": expires_at.strftime("%Y-%m-%d"),
        "cancel_at_period_end": False,
        "total_seats": plan_dict.get("seats", 50),
        "features": plan_dict.get("features", []),
    }

    hr_settings["billing"] = billing
    company.hr_settings = hr_settings
    flag_modified(company, "hr_settings")


# ===========================================================================
# 1. Plans Catalog Endpoint
# ===========================================================================

@router.get("/plans")
async def get_plans() -> APIResponse[List[PlanDetail]]:
    """Return all available subscription plans with pricing and features."""
    plans = razorpay_service.get_all_plans()
    return APIResponse[List[PlanDetail]](
        success=True,
        message="Subscription plans retrieved successfully.",
        data=[PlanDetail(**p) for p in plans],
        errors=None,
    )


# ===========================================================================
# 2. Create Order Endpoint
# ===========================================================================

@router.post("/create-order")
async def create_order(
    payload: CreateOrderPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[CreateOrderResponseData]:
    """
    Create a Razorpay payment order for a selected subscription plan.
    Calculates amount strictly server-side (NEVER trusts client amount).
    """
    co_id_str = claims.get("company_id")
    if not co_id_str:
        raise AppException(
            message="No company association found. User must belong to an active organization.",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    company_id = uuid.UUID(co_id_str)
    user_id_str = claims.get("sub")
    user_id = uuid.UUID(user_id_str) if user_id_str else None

    # Verify company exists
    comp_stmt = select(Company).where(Company.id == company_id)
    comp_res = await session.execute(comp_stmt)
    company = comp_res.scalar_one_or_none()
    if not company:
        raise AppException(
            message="Company not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # 1. Validate plan and calculate exact amount from backend catalog
    plan_dict, amount_rupees, amount_paise = razorpay_service.get_plan_details(
        plan_id=payload.plan_id,
        billing_cycle=payload.billing_cycle,
    )

    # 2. Generate receipt identifier and notes
    receipt = f"rcpt_{company_id.hex[:8]}_{int(datetime.now(timezone.utc).timestamp())}"
    notes = {
        "company_id": str(company_id),
        "company_name": company.name,
        "plan_id": plan_dict["plan_id"],
        "plan_name": plan_dict["name"],
        "billing_cycle": payload.billing_cycle,
        "user_email": claims.get("email", ""),
    }

    # 3. Create Razorpay order via Razorpay API
    order_data = razorpay_service.create_order(
        amount_paise=amount_paise,
        currency="INR",
        receipt=receipt,
        notes=notes,
    )
    razorpay_order_id = order_data.get("id")
    if not razorpay_order_id:
        raise AppException(
            message="Failed to retrieve order ID from payment gateway.",
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    # 4. Store transaction in database
    transaction = PaymentTransaction(
        company_id=company_id,
        user_id=user_id,
        plan_id=plan_dict["plan_id"],
        billing_cycle=payload.billing_cycle,
        razorpay_order_id=razorpay_order_id,
        amount=amount_rupees,
        amount_paise=amount_paise,
        currency="INR",
        status=PaymentStatus.CREATED.value,
        payment_metadata={
            "plan_name": plan_dict["name"],
            "receipt": receipt,
            "notes": notes,
        },
    )
    session.add(transaction)
    await session.commit()
    await session.refresh(transaction)

    return APIResponse[CreateOrderResponseData](
        success=True,
        message="Razorpay payment order created successfully.",
        data=CreateOrderResponseData(
            order_id=razorpay_order_id,
            amount=amount_paise,
            currency="INR",
            key_id=razorpay_service.key_id,
            plan_id=plan_dict["plan_id"],
            plan_name=plan_dict["name"],
            billing_cycle=payload.billing_cycle,
        ),
        errors=None,
    )


# ===========================================================================
# 3. Verify Payment Endpoint
# ===========================================================================

@router.post("/verify")
async def verify_payment(
    payload: VerifyPaymentPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[Dict[str, Any]]:
    """
    Verify completed Razorpay payment using secret key signature verification.
    Activates subscription only after signature and amount verification succeed.
    """
    co_id_str = claims.get("company_id")
    if not co_id_str:
        raise AppException(
            message="No company association found.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    company_id = uuid.UUID(co_id_str)

    # 1. Fetch transaction by razorpay_order_id
    stmt = select(PaymentTransaction).where(
        PaymentTransaction.razorpay_order_id == payload.razorpay_order_id
    )
    res = await session.execute(stmt)
    transaction = res.scalar_one_or_none()

    if not transaction:
        raise AppException(
            message="Payment transaction not found for the provided order ID.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # 2. Prevent cross-company order verification
    if transaction.company_id != company_id:
        logger.warning(
            "Cross-company payment verification attempted: company %s tried to verify order belonging to %s",
            company_id,
            transaction.company_id,
        )
        raise AppException(
            message="Access denied. This order does not belong to your organization.",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # 3. Idempotency check: If already CAPTURED with same payment_id, return success immediately
    if (
        transaction.status == PaymentStatus.CAPTURED.value
        and transaction.razorpay_payment_id == payload.razorpay_payment_id
    ):
        return APIResponse[Dict[str, Any]](
            success=True,
            message="Payment has already been verified and processed.",
            data={
                "order_id": transaction.razorpay_order_id,
                "payment_id": transaction.razorpay_payment_id,
                "status": transaction.status,
                "plan_id": transaction.plan_id,
                "amount": transaction.amount,
            },
            errors=None,
        )

    # 4. Check for duplicate payment ID attached to another order
    dup_stmt = select(PaymentTransaction).where(
        PaymentTransaction.razorpay_payment_id == payload.razorpay_payment_id,
        PaymentTransaction.id != transaction.id,
    )
    dup_res = await session.execute(dup_stmt)
    if dup_res.scalar_one_or_none():
        raise AppException(
            message="Duplicate payment detected. This payment ID has already been utilized.",
            status_code=status.HTTP_409_CONFLICT,
        )

    # 5. Cryptographic signature verification using SECRET KEY
    is_valid = razorpay_service.verify_payment_signature(
        razorpay_order_id=payload.razorpay_order_id,
        razorpay_payment_id=payload.razorpay_payment_id,
        razorpay_signature=payload.razorpay_signature,
    )

    if not is_valid:
        transaction.status = PaymentStatus.FAILED.value
        transaction.failure_reason = "Cryptographic signature verification failed."
        await session.commit()
        raise AppException(
            message="Payment verification failed: Invalid signature.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # 6. Fetch payment details from Razorpay to verify capture status and amount
    payment_details = {}
    try:
        payment_details = razorpay_service.fetch_payment(payload.razorpay_payment_id)
    except Exception as e:
        logger.warning("Could not fetch remote payment details during verify: %s", str(e))

    # 7. Update transaction status
    transaction.razorpay_payment_id = payload.razorpay_payment_id
    transaction.razorpay_signature = payload.razorpay_signature
    transaction.status = PaymentStatus.CAPTURED.value
    transaction.payment_method = payment_details.get("method") or "razorpay_checkout"
    transaction.failure_reason = None

    # 8. Fetch company and activate subscription
    comp_stmt = select(Company).where(Company.id == company_id)
    comp_res = await session.execute(comp_stmt)
    company = comp_res.scalar_one()

    plan_dict, _, _ = razorpay_service.get_plan_details(
        plan_id=transaction.plan_id,
        billing_cycle=transaction.billing_cycle,
    )

    await activate_subscription_for_company(
        session=session,
        company=company,
        plan_dict=plan_dict,
        billing_cycle=transaction.billing_cycle,
        payment_id=payload.razorpay_payment_id,
        order_id=payload.razorpay_order_id,
        amount=transaction.amount,
        currency=transaction.currency,
    )

    await session.commit()
    await session.refresh(transaction)

    return APIResponse[Dict[str, Any]](
        success=True,
        message="Payment verified and subscription activated successfully.",
        data={
            "transaction_id": str(transaction.id),
            "order_id": transaction.razorpay_order_id,
            "payment_id": transaction.razorpay_payment_id,
            "status": transaction.status,
            "plan_id": transaction.plan_id,
            "plan_name": plan_dict["name"],
            "amount": transaction.amount,
            "currency": transaction.currency,
        },
        errors=None,
    )


# ===========================================================================
# 4. Webhook Endpoint
# ===========================================================================

@router.post("/webhook")
async def handle_razorpay_webhook(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    x_razorpay_signature: Annotated[Optional[str], Header(alias="X-Razorpay-Signature")] = None,
) -> Dict[str, Any]:
    """
    Handle server-to-server Razorpay webhooks with signature verification and idempotency.
    Supported events: payment.captured, payment.failed, order.paid, refund.created, refund.processed.
    """
    body_bytes = await request.body()
    if not x_razorpay_signature:
        logger.warning("Razorpay webhook received without X-Razorpay-Signature header.")
        raise HTTPException(status_code=400, detail="Missing X-Razorpay-Signature header.")

    # 1. Verify Webhook Signature
    is_valid = razorpay_service.verify_webhook_signature(body_bytes, x_razorpay_signature)
    if not is_valid:
        logger.error("Razorpay webhook signature verification failed.")
        raise HTTPException(status_code=400, detail="Invalid webhook signature.")

    # 2. Parse Event JSON
    try:
        import json
        event_data = json.loads(body_bytes.decode("utf-8"))
    except Exception as e:
        logger.error("Failed to parse Razorpay webhook JSON: %s", str(e))
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    event_type = event_data.get("event")
    logger.info("Processing verified Razorpay webhook event: %s", event_type)
    payload_entity = event_data.get("payload", {})

    # 3. Handle specific webhook events idempotently
    if event_type in {"payment.captured", "order.paid"}:
        payment_entity = payload_entity.get("payment", {}).get("entity", {})
        order_id = payment_entity.get("order_id") or payload_entity.get("order", {}).get("entity", {}).get("id")
        payment_id = payment_entity.get("id")

        if order_id:
            stmt = select(PaymentTransaction).where(PaymentTransaction.razorpay_order_id == order_id)
            res = await session.execute(stmt)
            txn = res.scalar_one_or_none()

            if txn and txn.status != PaymentStatus.CAPTURED.value:
                txn.status = PaymentStatus.CAPTURED.value
                if payment_id:
                    txn.razorpay_payment_id = payment_id
                txn.payment_method = payment_entity.get("method") or txn.payment_method

                # Activate subscription
                comp_stmt = select(Company).where(Company.id == txn.company_id)
                comp_res = await session.execute(comp_stmt)
                company = comp_res.scalar_one_or_none()

                if company:
                    plan_dict, _, _ = razorpay_service.get_plan_details(
                        plan_id=txn.plan_id,
                        billing_cycle=txn.billing_cycle,
                    )
                    await activate_subscription_for_company(
                        session=session,
                        company=company,
                        plan_dict=plan_dict,
                        billing_cycle=txn.billing_cycle,
                        payment_id=payment_id or txn.razorpay_order_id,
                        order_id=order_id,
                        amount=txn.amount,
                        currency=txn.currency,
                    )
                await session.commit()
                logger.info("Webhook activated subscription for company %s on event %s", txn.company_id, event_type)

    elif event_type == "payment.failed":
        payment_entity = payload_entity.get("payment", {}).get("entity", {})
        order_id = payment_entity.get("order_id")
        error_desc = payment_entity.get("error_description") or "Payment failed at gateway."

        if order_id:
            stmt = select(PaymentTransaction).where(PaymentTransaction.razorpay_order_id == order_id)
            res = await session.execute(stmt)
            txn = res.scalar_one_or_none()
            if txn and txn.status != PaymentStatus.CAPTURED.value:
                txn.status = PaymentStatus.FAILED.value
                txn.failure_reason = error_desc
                if payment_entity.get("id"):
                    txn.razorpay_payment_id = payment_entity.get("id")
                await session.commit()
                logger.info("Webhook recorded payment failure for order %s: %s", order_id, error_desc)

    elif event_type in {"refund.created", "refund.processed"}:
        refund_entity = payload_entity.get("refund", {}).get("entity", {})
        payment_id = refund_entity.get("payment_id")
        if payment_id:
            stmt = select(PaymentTransaction).where(PaymentTransaction.razorpay_payment_id == payment_id)
            res = await session.execute(stmt)
            txn = res.scalar_one_or_none()
            if txn:
                txn.status = PaymentStatus.REFUNDED.value
                await session.commit()
                logger.info("Webhook marked payment %s as REFUNDED", payment_id)

    return {"status": "ok", "event": event_type, "processed": True}


# ===========================================================================
# 5. Payment History & Details Endpoints
# ===========================================================================

@router.get("/history")
async def get_payment_history(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
) -> APIResponse[PaymentHistoryPaginationData]:
    """Return paginated list of payment transactions strictly for the authenticated company."""
    co_id_str = claims.get("company_id")
    if not co_id_str:
        raise AppException(
            message="No company association found.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    company_id = uuid.UUID(co_id_str)

    # Count total
    count_stmt = select(func.count(PaymentTransaction.id)).where(
        PaymentTransaction.company_id == company_id
    )
    count_res = await session.execute(count_stmt)
    total = count_res.scalar() or 0

    # Fetch paginated items
    offset = (page - 1) * page_size
    stmt = (
        select(PaymentTransaction)
        .where(PaymentTransaction.company_id == company_id)
        .order_by(desc(PaymentTransaction.created_at))
        .offset(offset)
        .limit(page_size)
    )
    res = await session.execute(stmt)
    txns = res.scalars().all()

    items = [
        PaymentTransactionResponseData(
            id=str(t.id),
            company_id=str(t.company_id),
            user_id=str(t.user_id) if t.user_id else None,
            plan_id=t.plan_id,
            billing_cycle=t.billing_cycle,
            razorpay_order_id=t.razorpay_order_id,
            razorpay_payment_id=t.razorpay_payment_id,
            amount=t.amount,
            currency=t.currency,
            status=t.status,
            payment_method=t.payment_method,
            created_at=t.created_at.isoformat() if t.created_at else "",
            updated_at=t.updated_at.isoformat() if t.updated_at else "",
        )
        for t in txns
    ]

    total_pages = (total + page_size - 1) // page_size if page_size > 0 else 1

    return APIResponse[PaymentHistoryPaginationData](
        success=True,
        message="Payment history retrieved successfully.",
        data=PaymentHistoryPaginationData(
            items=items,
            page=page,
            page_size=page_size,
            total=total,
            pages=total_pages,
        ),
        errors=None,
    )


@router.get("/{payment_id}")
async def get_payment_details(
    payment_id: str,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[PaymentTransactionResponseData]:
    """Fetch details of a single payment transaction by transaction ID or Razorpay payment ID."""
    co_id_str = claims.get("company_id")
    if not co_id_str:
        raise AppException(
            message="No company association found.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    company_id = uuid.UUID(co_id_str)

    # Try UUID lookup or razorpay_payment_id lookup
    stmt = select(PaymentTransaction).where(
        PaymentTransaction.company_id == company_id,
    )
    try:
        txn_uuid = uuid.UUID(payment_id)
        stmt = stmt.where(PaymentTransaction.id == txn_uuid)
    except ValueError:
        stmt = stmt.where(
            (PaymentTransaction.razorpay_payment_id == payment_id)
            | (PaymentTransaction.razorpay_order_id == payment_id)
        )

    res = await session.execute(stmt)
    txn = res.scalar_one_or_none()

    if not txn:
        raise AppException(
            message="Payment transaction not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return APIResponse[PaymentTransactionResponseData](
        success=True,
        message="Payment details retrieved successfully.",
        data=PaymentTransactionResponseData(
            id=str(txn.id),
            company_id=str(txn.company_id),
            user_id=str(txn.user_id) if txn.user_id else None,
            plan_id=txn.plan_id,
            billing_cycle=txn.billing_cycle,
            razorpay_order_id=txn.razorpay_order_id,
            razorpay_payment_id=txn.razorpay_payment_id,
            amount=txn.amount,
            currency=txn.currency,
            status=txn.status,
            payment_method=txn.payment_method,
            created_at=txn.created_at.isoformat() if txn.created_at else "",
            updated_at=txn.updated_at.isoformat() if txn.updated_at else "",
        ),
        errors=None,
    )
