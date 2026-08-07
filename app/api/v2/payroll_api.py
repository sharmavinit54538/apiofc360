"""API v2 — Payroll Module Facade.

Refactored Clean Architecture implementation.
Re-exports router and core handlers/dependencies for complete backward compatibility.
"""
from __future__ import annotations

from app.api.payroll.dependencies import DB, Claims
from app.api.payroll.helpers import safe_float, safe_isoformat, safe_uuid_str
from app.api.payroll.permissions import (
    _require_admin,
    _require_admin_or_manager,
    _role,
    _uid,
)
from app.api.payroll.responses import error_response, success_response
from app.api.payroll.router import router
from app.api.payroll.routes.pay_cycles import (
    create_payroll_cycle as create_pay_cycle,
    get_payroll_cycle_details as get_pay_cycle,
    list_payroll_cycles as list_pay_cycles,
)
from app.api.payroll.routes.salary_processing import (
    approve_salary_processing_run,
    get_salary_processing_hero,
    trigger_salary_processing_run,
)
from app.api.payroll.serializers import (
    _att_dict,
    _decl_dict,
    _payslip_dict,
    _run_dict,
    _salary_dict,
    _statutory_dict,
)

__all__ = [
    "router",
    "DB",
    "Claims",
    "_uid",
    "_role",
    "_require_admin",
    "_require_admin_or_manager",
    "_run_dict",
    "_payslip_dict",
    "_salary_dict",
    "_att_dict",
    "_statutory_dict",
    "_decl_dict",
    "get_salary_processing_hero",
    "trigger_salary_processing_run",
    "approve_salary_processing_run",
    "list_pay_cycles",
    "create_pay_cycle",
    "get_pay_cycle",
    "success_response",
    "error_response",
]
