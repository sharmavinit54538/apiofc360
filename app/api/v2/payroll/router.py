"""Main aggregated APIRouter for Payroll v2 (78+ Endpoints)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v2.payroll.accounting import router as accounting_router
from app.api.v2.payroll.company_bank import router as company_bank_router
from app.api.v2.payroll.compensation import router as compensation_router
from app.api.v2.payroll.cycles import router as cycles_router
from app.api.v2.payroll.employee_payroll import router as employee_payroll_router
from app.api.v2.payroll.full_and_final import router as full_and_final_router
from app.api.v2.payroll.pay_components import router as pay_components_router
from app.api.v2.payroll.payment_batches import router as payment_batches_router
from app.api.v2.payroll.payslips import router as payslips_router
from app.api.v2.payroll.reports import router as reports_router
from app.api.v2.payroll.runs import router as runs_router
from app.api.v2.payroll.statutory import router as statutory_router
from app.api.v2.payroll.variable_inputs import router as variable_inputs_router

router = APIRouter(prefix="/payroll", tags=["Payroll v2"])

# Mount all domain sub-routers
router.include_router(accounting_router)
router.include_router(company_bank_router)
router.include_router(compensation_router)
router.include_router(cycles_router)
router.include_router(employee_payroll_router)
router.include_router(full_and_final_router)
router.include_router(payslips_router)
router.include_router(pay_components_router)
router.include_router(payment_batches_router)
router.include_router(reports_router)
router.include_router(runs_router)
router.include_router(statutory_router)
router.include_router(variable_inputs_router)

__all__ = ["router"]
