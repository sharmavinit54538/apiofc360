"""Payroll Constants and Configuration defaults."""
from __future__ import annotations

from app.models.user.role import RoleEnum

# Job store for async operations
_JOB_STORE: dict[str, dict] = {}

# Canonical Role groupings using RoleEnum
ADMIN_ROLES = (
    RoleEnum.SUPER_ADMIN.value,
    RoleEnum.HR_ADMIN.value,
    RoleEnum.IT_ADMIN.value,
)

ADMIN_OR_MANAGER_ROLES = (
    RoleEnum.SUPER_ADMIN.value,
    RoleEnum.HR_ADMIN.value,
    RoleEnum.IT_ADMIN.value,
    RoleEnum.EXECUTIVE.value,
    RoleEnum.MANAGER.value,
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
