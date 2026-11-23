"""Provider-confirmed payment evidence and currency-separated collections."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal


def provider_timestamp(value, fallback: datetime | None = None) -> str:
    try:
        return datetime.fromtimestamp(int(value), timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return (fallback or datetime.now(timezone.utc)).isoformat()


def capture_problem(transaction, payment: dict, payment_id: str) -> str | None:
    """All fields must match the server-created order before granting access."""
    if payment.get("id") != payment_id or payment.get("order_id") != transaction.razorpay_order_id:
        return "Provider payment does not match the payment and order IDs."
    if payment.get("currency", "").upper() != transaction.currency.upper():
        return "Provider payment currency does not match the order."
    amount = payment.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount != transaction.amount_paise:
        return "Provider payment amount does not match the order."
    if payment.get("status") != "captured" or payment.get("captured") is not True:
        return "Payment has not been captured by the provider."
    if payment.get("amount_refunded", 0):
        return "Provider reports a refunded payment; reconciliation is required."
    return None


def collections_summary(transactions, months: list[str]) -> dict:
    """Never combine currencies or backdate receipts to a tenant creation date.

    Older CAPTURED records without validated provider evidence need reconciliation;
    their old verification path could mark unavailable/pending payments captured.
    """
    totals = {}
    trend = {}
    unverified = 0
    for txn in transactions:
        metadata = txn.payment_metadata or {}
        capture = metadata.get("capture") or {}
        if not capture.get("validated"):
            if txn.status in {"CAPTURED", "REFUNDED"}:
                unverified += 1
            continue
        currency = txn.currency.upper()
        bucket = totals.setdefault(currency, {"collections": Decimal(0), "refunds": Decimal(0)})
        amount = Decimal(txn.amount_paise) / 100
        bucket["collections"] += amount
        month = (capture.get("occurred_at") or "")[:7]
        if month in months:
            trend.setdefault((month, currency), {"collections": Decimal(0), "refunds": Decimal(0)})["collections"] += amount
        for refund in (metadata.get("refunds") or {}).values():
            if refund.get("status") != "processed":
                continue
            refund_amount = Decimal(refund["amount_paise"]) / 100
            bucket["refunds"] += refund_amount
            month = refund["occurred_at"][:7]
            if month in months:
                trend.setdefault((month, currency), {"collections": Decimal(0), "refunds": Decimal(0)})["refunds"] += refund_amount

    def numbers(bucket):
        return {**{key: float(value) for key, value in bucket.items()},
                "net_collections": float(bucket["collections"] - bucket["refunds"])}

    return {
        "by_currency": {currency: numbers(bucket) for currency, bucket in totals.items()},
        "trend": [{"month": month, "currency": currency, **numbers(bucket),
                   "revenue": float(bucket["collections"] - bucket["refunds"])}
                  for (month, currency), bucket in sorted(trend.items())],
        "unverified_legacy_transactions": unverified,
    }
