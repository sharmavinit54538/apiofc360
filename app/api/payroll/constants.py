"""Payroll Constants and Configuration defaults."""
from __future__ import annotations

# Job store for async operations
_JOB_STORE: dict[str, dict] = {}

# Role groupings
ADMIN_ROLES = ("super_admin", "hr_admin")
ADMIN_OR_MANAGER_ROLES = (
    "super_admin", "hr_admin", "executive", "manager"
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
