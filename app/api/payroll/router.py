"""Main aggregated APIRouter for Payroll module."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.payroll.routes.pay_cycles import router as pay_cycles_router
from app.api.payroll.routes.salary_processing import router as salary_processing_router
from app.api.payroll.routes.approvals import router as approvals_router
from app.api.payroll.routes.salary_structure import router as salary_structure_router
from app.api.payroll.routes.payslips import router as payslips_router
from app.api.payroll.routes.overtime import router as overtime_router
from app.api.payroll.routes.bonuses import router as bonuses_router
from app.api.payroll.routes.deductions import router as deductions_router
from app.api.payroll.routes.reimbursements import router as reimbursements_router
from app.api.payroll.routes.advances import router as advances_router
from app.api.payroll.routes.bank_transfer import router as bank_transfer_router
from app.api.payroll.routes.compliance import router as compliance_router
from app.api.payroll.routes.reports import router as reports_router
from app.api.payroll.routes.dashboard import router as dashboard_router
from app.api.payroll.routes.analytics import router as analytics_router
from app.api.payroll.routes.copilot import router as copilot_router
from app.api.payroll.routes.settings import router as settings_router
from app.api.payroll.routes.tax import router as tax_router
from app.api.payroll.routes.components import router as components_router
from app.api.payroll.routes.allowances import router as allowances_router
from app.api.payroll.routes.tax_settings import router as tax_settings_router
from app.api.payroll.routes.overtime_settings import router as overtime_settings_router
from app.api.payroll.routes.compliance_full import router as compliance_full_router
from app.api.payroll.routes.templates_full import router as templates_full_router
from app.api.payroll.routes.security_settings import router as security_settings_router

router = APIRouter(prefix="/payroll", tags=["Payroll"])

# Include all domain sub-routers
router.include_router(pay_cycles_router)
router.include_router(salary_processing_router)
router.include_router(approvals_router)
router.include_router(salary_structure_router)
router.include_router(payslips_router)
router.include_router(overtime_router)
router.include_router(bonuses_router)
router.include_router(deductions_router)
router.include_router(reimbursements_router)
router.include_router(advances_router)
router.include_router(bank_transfer_router)
router.include_router(compliance_router)
router.include_router(reports_router)
router.include_router(dashboard_router)
router.include_router(analytics_router)
router.include_router(copilot_router)
router.include_router(settings_router)
router.include_router(tax_router)
router.include_router(components_router)
router.include_router(allowances_router)
router.include_router(tax_settings_router)
router.include_router(overtime_settings_router)
router.include_router(compliance_full_router)
router.include_router(templates_full_router)
router.include_router(security_settings_router)
