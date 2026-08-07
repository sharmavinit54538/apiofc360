"""Payroll Constants and Configuration defaults."""
from __future__ import annotations

# Job store for async operations
_JOB_STORE: dict[str, dict] = {}

# Role groupings
ADMIN_ROLES = ("admin", "ceo", "cfo")
ADMIN_OR_MANAGER_ROLES = (
    "admin", "manager", "ceo", "cfo", "cto", "coo", "cmo", "clo", "ciso", "cio"
)

# Status constants
PAY_CYCLE_STATUSES = ("DRAFT", "LOCKED", "APPROVED", "DISBURSED", "VOID")
PAYSLIP_STATUSES = ("GENERATED", "PENDING")
PAYSLIP_PAYMENT_STATUSES = ("UNPAID", "PAID", "PROCESSING", "FAILED")
REIMBURSEMENT_STATUSES = ("SUBMITTED", "APPROVED", "REJECTED", "PAID")
BONUS_AWARD_STATUSES = ("PENDING", "APPROVED", "REJECTED", "PAID")
LOAN_STATUSES = ("DISBURSED", "ACTIVE", "CLOSED", "SETTLED")

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
