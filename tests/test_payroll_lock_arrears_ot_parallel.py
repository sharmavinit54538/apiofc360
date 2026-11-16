"""Step 3 Batch 1 golden and integration coverage.

The tests use real SQLAlchemy models against SQLite, with the same JSONB/UUID
compatibility shims used by the repository's other payroll tests.  Monetary
assertions are deliberately in integer paise.
"""
from __future__ import annotations

import io
import os
import uuid
import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from openpyxl import Workbook
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy import func, select

from app.db.base import Base
from app.db.database import get_db_session
from app.main import create_app
from app.middleware.auth import get_current_user_claims
import app.models  # noqa: F401
from app.attendance.models.attendance import Attendance
from app.attendance.services.validation_service import assert_attendance_period_editable
from app.models.company import Company
from app.models.core_modules import AttendanceRegularizationRequest
from app.models.employee import Employee
from app.models.leave import CompOffLedger
from app.models.payroll import (
    AdvanceLoan, AdvanceLoanInstallment, OvertimeEntry, PayrollAttendanceInput, PayrollRun, Payslip,
    PayrollAuditLog, SalaryStructure, StatutoryComplianceConfig,
)
from app.models.payroll_models import (
    ArrearLedger, Compensation, PayrollPeriod, PayrollRunEmployee, VariableInput,
)
from app.models.shift import Shift, ShiftAllowancePolicy
from app.services.core_modules.attendance_service import AttendanceCoreService
from app.services.payroll.arrear_service import ArrearService
from app.services.payroll.attendance_to_payroll_sync_service import AttendanceToPayrollSyncService
from app.services.payroll.accounting_service import AccountingService
from app.services.payroll.cycle_service import PayrollCycleService
from app.services.payroll.formula_evaluator import SafeFormulaEvaluator
from app.services.payroll.money import allocate_annual_paise, assert_payroll_reconciles, round_paise, round_to_rupee_paise
from app.services.payroll.parallel_comparison_service import ParallelPayrollComparisonService
from app.services.payroll.payslip_service import PayslipService
from app.services.payroll.run_service import PayrollRunService
from app.services.payroll.statutory_service import StatutoryService


TEST_TABLES = (
    "companies", "users", "employees", "employee_bank_accounts",
    "payroll_periods", "pay_cycles", "payroll_runs", "payroll_run_employees",
    "payslips", "payroll_attendance_inputs", "advance_loans", "advance_loan_installments",
    "compensations", "salary_structures", "variable_inputs",
    "overtime_entries", "overtime_policies", "attendances", "attendance_regularization_requests", "shifts",
    "shift_allowance_policies", "comp_off_ledgers", "arrear_ledgers",
    "parallel_payroll_comparison_reports", "statutory_compliance_configs",
    "employee_investment_declarations", "employee_ytd_salaries", "pay_components",
    "payroll_audit_logs",
)


@pytest.fixture
async def db_session():
    if os.getenv("PAYROLL_USE_MIGRATED_DB") == "1":
        from payroll_migrated_db import migrated_session
        async with migrated_session() as session:
            yield session
        return
    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
        SQLiteTypeCompiler.visit_JSONB = lambda self, type_, **kw: "JSON"
    tables = [Base.metadata.tables[name] for name in TEST_TABLES]
    defaults = []
    for table in tables:
        for column in table.columns:
            if column.server_default and "jsonb" in str(column.server_default.arg).lower():
                defaults.append((column, column.server_default))
                column.server_default = None
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    finally:
        for column, default in defaults:
            column.server_default = default
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _employee(company_id: uuid.UUID, code: str = "EMP-001") -> Employee:
    return Employee(
        id=uuid.uuid4(), company_id=company_id, employee_id=code,
        first_name="Asha", last_name="Sharma", personal_email=f"{code}-{uuid.uuid4().hex[:5]}@example.com",
        phone="9876543210", department="Engineering", designation="Engineer",
        joining_date=date(2024, 1, 10), pan_number="ABCDE1234F",
    )


def _period(company_id: uuid.UUID, month: int = 9, year: int = 2026, status: str = "OPEN") -> PayrollPeriod:
    last_day = calendar.monthrange(year, month)[1]
    return PayrollPeriod(
        id=uuid.uuid4(), company_id=company_id, name=f"{month}/{year}",
        start_date=date(year, month, 1), end_date=date(year, month, last_day),
        pay_date=date(year, month, last_day), period_month=month, period_year=year, status=status,
    )


async def _seed_employee(
    db_session, *, with_comp: bool = True, fractional_pay: bool = False,
    code: str = "EMP-001",
):
    company = Company(id=uuid.uuid4(), name="Step 3 Test Co")
    employee = _employee(company.id, code=code)
    db_session.add_all([company, employee])
    await db_session.flush()
    if with_comp:
        db_session.add(Compensation(
            id=uuid.uuid4(), company_id=company.id, employee_id=employee.id,
            ctc_annual_paise=39999996 if fractional_pay else 7200000,
            basic_monthly_paise=3333333 if fractional_pay else 3000000,
            hra_monthly_paise=0 if fractional_pay else 1200000,
            special_allowance_monthly_paise=0 if fractional_pay else 600000,
            status="ACTIVE", effective_date=date(2026, 1, 1),
        ))
    await db_session.commit()
    return company, employee


def test_statutory_rounding_and_formula_golden_paise():
    assert round_to_rupee_paise(49) == 0
    assert round_to_rupee_paise(50) == 100
    assert round_to_rupee_paise(150) == 200
    # ₹200 wages: 0.75% = ₹1.50 and 3.25% = ₹6.50, both half up.
    esi = StatutoryService.calculate_esi(20000)
    assert esi["employee_esi_paise"] == 200
    assert esi["employer_esi_paise"] == 700
    assert esi["employee_esi_paise"] % 100 == 0
    assert SafeFormulaEvaluator.evaluate_paise("basic * 0.40 + 1000", {"basic": 100001}) == 41000
    assert AttendanceToPayrollSyncService.calculate_overtime_paise(
        basic_monthly_paise=3000000, ot_hours="10", multiplier="1.5"
    ) == 187500
    assert AttendanceToPayrollSyncService.calculate_overtime_paise(
        basic_monthly_paise=3000000, gross_monthly_paise=4800000,
        ot_hours="10", multiplier="2.0", use_gross=True,
    ) == 400000


def test_annual_ctc_allocation_preserves_every_paise_and_payroll_invariants():
    months = allocate_annual_paise(10_000_007)
    assert months == (833_334,) * 11 + (833_333,)
    assert sum(months) == 10_000_007
    assert_payroll_reconciles(3_333_333, 0, 3_333_333)
    with pytest.raises(ValueError, match="integrity violation"):
        assert_payroll_reconciles(3_333_333, 0, 3_333_300)


@pytest.mark.asyncio
async def test_attendance_lock_and_deadline_block_corrections(db_session):
    company, employee = await _seed_employee(db_session)
    period = _period(company.id)
    period.attendance_locked_at = datetime.now(timezone.utc)
    db_session.add(period)
    await db_session.commit()
    with pytest.raises(Exception) as locked:
        await assert_attendance_period_editable(db_session, company.id, date(2026, 9, 10))
    assert getattr(locked.value, "status_code", None) == 409
    period.attendance_locked_at = None
    period.is_locked = False
    period.status = "OPEN"
    period.regularisation_deadline = datetime.now(timezone.utc) - timedelta(days=1)
    await db_session.commit()
    with pytest.raises(Exception) as expired:
        await assert_attendance_period_editable(db_session, company.id, date(2026, 9, 10))
    assert getattr(expired.value, "status_code", None) == 409
    # Explicit HR retroactive review is allowed for the arrear-producing path.
    resolved = await assert_attendance_period_editable(
        db_session, company.id, date(2026, 9, 10), allow_retroactive=True, actor_role="hr_admin"
    )
    assert resolved.id == period.id


@pytest.mark.asyncio
async def test_locked_regularisation_approval_creates_next_period_arrear(db_session):
    company, employee = await _seed_employee(
        db_session, code=f"NEG-{uuid.uuid4().hex[:8]}"
    )
    source = _period(company.id, month=9, status="LOCKED")
    target = _period(company.id, month=10)
    attendance = Attendance(
        id=uuid.uuid4(), company_id=company.id, employee_id=employee.id,
        date=date(2026, 9, 10), check_in_time=datetime(2026, 9, 10, 9, 0), status="Present",
    )
    db_session.add_all([source, target, attendance])
    await db_session.flush()
    request = AttendanceRegularizationRequest(
        id=uuid.uuid4(), attendance_id=attendance.id, employee_id=employee.id,
        company_id=company.id, request_date=date(2026, 9, 10),
        requested_check_in=datetime(2026, 9, 10, 9, 15), reason="Biometric missed punch", status="PENDING",
    )
    db_session.add(request)
    await db_session.commit()
    reviewed = await AttendanceCoreService(db_session).review_regularization(
        request.id, decision="APPROVED", reviewer_role="hr_admin",
        reviewer_company_id=company.id, amount_paise=12345,
    )
    assert reviewed.status == "APPROVED"
    arrear = (await db_session.execute(select(ArrearLedger))).scalar_one()
    assert arrear.type == "ATTENDANCE_RETRO"
    assert arrear.amount_paise == 12345
    assert arrear.target_period_id == target.id


@pytest.mark.asyncio
async def test_cycle_create_lock_unlock_audit_and_tenant_guard(db_session):
    company, employee = await _seed_employee(db_session)
    deadline = datetime.now(timezone.utc) + timedelta(days=2)
    cycle = await PayrollCycleService.create_cycle(
        db_session, company_id=company.id, name="November 2026", frequency="MONTHLY",
        period_month=11, period_year=2026, start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30), regularisation_deadline=deadline,
    )
    assert cycle.regularisation_deadline.replace(tzinfo=timezone.utc) == deadline
    await PayrollCycleService.lock_attendance(db_session, cycle.id, company_id=company.id)
    assert cycle.attendance_locked_at is not None
    with pytest.raises(Exception) as missing_reason:
        await PayrollCycleService.unlock_attendance(db_session, cycle.id, reason=" ", company_id=company.id)
    assert getattr(missing_reason.value, "status_code", None) == 422
    await PayrollCycleService.unlock_attendance(db_session, cycle.id, reason="Correcting imported attendance", company_id=company.id)
    assert cycle.attendance_locked_at is None
    assert cycle.unlock_reason == "Correcting imported attendance"
    with pytest.raises(Exception) as cross_tenant:
        await PayrollCycleService.get_cycle(db_session, cycle.id, company_id=uuid.uuid4())
    assert getattr(cross_tenant.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_arrear_next_open_period_and_signed_golden_amount(db_session):
    company, employee = await _seed_employee(db_session)
    source = _period(company.id, month=9, status="LOCKED")
    target = _period(company.id, month=10)
    db_session.add_all([source, target])
    await db_session.commit()
    arrear = await ArrearService.create_arrear(
        db_session, employee_id=employee.id, company_id=company.id,
        source_period_id=source.id, arrear_type="ATTENDANCE_RETRO",
        delta_days="2.5", daily_rate_paise=100000,
    )
    await db_session.commit()
    assert arrear.target_period_id == target.id
    assert arrear.amount_paise == 250000
    assert arrear.status == "PENDING"
    assert arrear.calculation_json["delta_days"] == "2.5"


@pytest.mark.asyncio
async def test_attendance_sync_upserts_locked_ot_shift_and_comp_off(db_session):
    company, employee = await _seed_employee(db_session)
    period = _period(company.id)
    shift = Shift(
        id=uuid.uuid4(), company_id=company.id, code="NIGHT", name="Night Shift",
        start_time=datetime.strptime("22:00", "%H:%M").time(),
        end_time=datetime.strptime("06:00", "%H:%M").time(), is_overnight=True,
        duration_minutes=480, work_hours=8, is_night_shift=True, working_days=["Mon"],
    )
    db_session.add_all([
        period, shift,
        OvertimeEntry(
            id=uuid.uuid4(), company_id=company.id, employee_id=employee.id,
            period_month=9, period_year=2026, ot_hours=Decimal("10"),
            ot_rate_per_hour=Decimal("0"), ot_amount=Decimal("0"), status="APPROVED",
        ),
        ShiftAllowancePolicy(
            id=uuid.uuid4(), company_id=company.id, shift_id=shift.id,
            shift_type="NIGHT", allowance_paise=50000, is_esi_applicable=True,
            is_pf_applicable=False, is_taxable=True,
        ),
        CompOffLedger(
            id=uuid.uuid4(), company_id=company.id, employee_id=employee.id,
            worked_date=date(2026, 9, 12), worked_hours=Decimal("8"), credit_days=Decimal("1"),
            expiry_date=date(2026, 12, 31), status="ENCASHED", encashment_amount_paise=75000,
        ),
    ])
    await db_session.flush()
    db_session.add(Attendance(
        id=uuid.uuid4(), company_id=company.id, employee_id=employee.id,
        date=date(2026, 9, 12), check_in_time=datetime(2026, 9, 12, 22, 0),
        status="Present", shift_id=shift.id, shift_name="NIGHT",
    ))
    await db_session.commit()
    result = await AttendanceToPayrollSyncService.sync_on_attendance_lock(db_session, period)
    assert result["overtime_paise"] == 187500
    assert result["shift_allowance_paise"] == 50000
    assert result["comp_off_encashment_paise"] == 75000
    rows = (await db_session.execute(select(VariableInput).where(VariableInput.period_id == period.id))).scalars().all()
    assert {r.type for r in rows} == {"OVERTIME", "SHIFT_ALLOWANCE", "COMP_OFF_ENCASHMENT"}
    assert all(r.is_locked and r.status == "APPROVED" for r in rows)
    await AttendanceToPayrollSyncService.sync_on_attendance_lock(db_session, period)
    rows_after = (await db_session.execute(select(VariableInput).where(VariableInput.period_id == period.id))).scalars().all()
    assert len(rows_after) == 3


async def _seed_calculated_run(
    db_session, *, with_advance: bool = False, with_attendance_inputs: bool = False,
    fractional_pay: bool = False, period_month: int = 9, period_year: int = 2026,
    lop_basis: str = "CALENDAR_DAYS",
    attendance_lop_days: Decimal = Decimal("2"),
):
    company, employee = await _seed_employee(db_session, fractional_pay=fractional_pay)
    source_month = period_month - 1 or 12
    source_year = period_year - 1 if period_month == 1 else period_year
    source = _period(company.id, month=source_month, year=source_year, status="LOCKED")
    period = _period(company.id, month=period_month, year=period_year)
    run = PayrollRun(
        id=uuid.uuid4(), company_id=company.id, period_id=period.id,
        run_number="PR-STEP3", period_month=period_month, period_year=period_year, status="VALIDATED",
    )
    db_session.add_all([source, period, run, StatutoryComplianceConfig(
        company_id=company.id, is_active=True, pf_enabled=True, esi_enabled=True,
        pt_state="MAHARASHTRA", default_tax_regime="NEW", lop_basis=lop_basis,
        effective_from=date(2020, 1, 1),
    )])
    await db_session.flush()
    db_session.add(ArrearLedger(
        id=uuid.uuid4(), company_id=company.id, employee_id=employee.id,
        source_period_id=source.id, target_period_id=period.id, type="ATTENDANCE_RETRO",
        delta_days=Decimal("1"), amount_paise=100000, status="PENDING", calculation_json={},
    ))
    if with_advance:
        db_session.add(AdvanceLoan(
            id=uuid.uuid4(), company_id=company.id, employee_id=employee.id,
            principal_amount=Decimal("10000"), outstanding_balance=Decimal("10000"),
            emi_amount=Decimal("2500"), total_installments=4, installments_paid=0,
            start_from_month=9, start_from_year=2026, status="ACTIVE",
        ))
    if with_attendance_inputs:
        payable_days = 30 if lop_basis == "FIXED_30" else calendar.monthrange(period_year, period_month)[1]
        db_session.add(PayrollAttendanceInput(
            id=uuid.uuid4(), company_id=company.id, employee_id=employee.id,
            period_month=period_month, period_year=period_year, paid_days=Decimal(str(payable_days)),
            lop_days=attendance_lop_days, arrears=Decimal("100.00"), one_time_bonus=Decimal("250.00"),
        ))
    await db_session.commit()
    await PayrollRunService.execute_run_calculation(db_session, run.id)
    return company, employee, period, run


async def _seed_net_edge_run(
    db_session,
    *,
    gross_paise: int,
    variable_deduction_paise: int = 0,
    lop_days: Decimal = Decimal("0"),
    loan_emi_paise: int = 0,
    arrear_adjustment_paise: int = 0,
    statutory_enabled: bool = False,
):
    """Seed an isolated exact-paise run for negative-net rollback coverage."""
    company, employee = await _seed_employee(
        db_session, code=f"NEG-{uuid.uuid4().hex[:8]}"
    )
    comp = (await db_session.execute(
        select(Compensation).where(Compensation.employee_id == employee.id)
    )).scalar_one()
    comp.ctc_annual_paise = gross_paise * 12
    comp.basic_monthly_paise = gross_paise
    comp.hra_monthly_paise = 0
    comp.special_allowance_monthly_paise = 0

    period = _period(company.id)
    run = PayrollRun(
        id=uuid.uuid4(), company_id=company.id, period_id=period.id,
        run_number=f"NEG-{uuid.uuid4().hex[:8]}", period_month=period.period_month,
        period_year=period.period_year, status="VALIDATED",
    )
    config = StatutoryComplianceConfig(
        company_id=company.id, is_active=True,
        pf_enabled=statutory_enabled, esi_enabled=statutory_enabled,
        employee_pf_rate=Decimal("0.12"), employer_pf_rate=Decimal("0.12"),
        employee_esi_rate=Decimal("0.0075"), employer_esi_rate=Decimal("0.0325"),
        pt_state="MAHARASHTRA", pt_slabs=[], default_tax_regime="NEW",
        lop_basis="CALENDAR_DAYS", effective_from=date(2020, 1, 1),
    )
    db_session.add_all([period, run, config])
    await db_session.flush()

    if variable_deduction_paise:
        db_session.add(VariableInput(
            id=uuid.uuid4(), company_id=company.id, employee_id=employee.id,
            period_id=period.id, type="deduction", amount_paise=variable_deduction_paise,
            description="Negative net regression input", status="APPROVED",
        ))
    if lop_days:
        days = calendar.monthrange(period.period_year, period.period_month)[1]
        db_session.add(PayrollAttendanceInput(
            id=uuid.uuid4(), company_id=company.id, employee_id=employee.id,
            period_month=period.period_month, period_year=period.period_year,
            paid_days=Decimal(days) - lop_days, lop_days=lop_days,
            arrears=Decimal("0"), one_time_bonus=Decimal("0"),
        ))
    if loan_emi_paise:
        loan_amount = Decimal(loan_emi_paise) / 100
        db_session.add(AdvanceLoan(
            id=uuid.uuid4(), company_id=company.id, employee_id=employee.id,
            principal_amount=loan_amount, outstanding_balance=loan_amount,
            emi_amount=loan_amount, total_installments=3, installments_paid=0,
            start_from_month=period.period_month, start_from_year=period.period_year,
            status="ACTIVE",
        ))
    if arrear_adjustment_paise:
        db_session.add(ArrearLedger(
            id=uuid.uuid4(), company_id=company.id, employee_id=employee.id,
            target_period_id=period.id, type="ATTENDANCE_RETRO", delta_days=Decimal("0"),
            amount_paise=arrear_adjustment_paise, status="PENDING", calculation_json={},
        ))
    await db_session.commit()
    return company, employee, period, run


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("gross_paise", "deduction_paise", "expected_net_paise"),
    [
        (100_000, 120_000, -20_000),       # ₹1,000 gross, ₹1,200 deductions
        (0, 50_000, -50_000),               # ₹0 gross, ₹500 deductions
        (3_333_333, 3_333_334, -1),          # ₹33,333.33 vs ₹33,333.34
        (100_000, 100_000, 0),               # exact zero net is valid
        (100_000, 99_999, 1),                # ₹0.01 net is valid
    ],
)
async def test_engine_negative_net_rejection_and_boundary_nets(
    db_session, gross_paise, deduction_paise, expected_net_paise,
):
    _company, employee, _period_row, run = await _seed_net_edge_run(
        db_session, gross_paise=gross_paise,
        variable_deduction_paise=deduction_paise,
    )
    employee_id = employee.id
    run_id = run.id
    period_id = run.period_id
    if expected_net_paise < 0:
        with pytest.raises(Exception) as failure:
            await PayrollRunService.execute_run_calculation(db_session, run_id)
        assert getattr(failure.value, "status_code", None) == 422
        await db_session.refresh(run)
        assert run.status == "FAILED"
        assert run.validation_status == "ERROR"
        assert run.validation_errors[0]["code"] == "NEGATIVE_NET_PAY"
        assert str(abs(expected_net_paise)) in run.validation_errors[0]["detail"]
        failure_audit = (await db_session.execute(select(PayrollAuditLog).where(
            PayrollAuditLog.entity_id == run_id,
            PayrollAuditLog.action == "CALCULATION_FAILED",
        ))).scalar_one()
        assert failure_audit.extra_data["error_code"] == "NEGATIVE_NET_PAY"
        assert await db_session.scalar(select(func.count(Payslip.id)).where(Payslip.payroll_run_id == run_id)) == 0
        assert await db_session.scalar(select(func.count(PayrollRunEmployee.id)).where(PayrollRunEmployee.run_id == run_id)) == 0
        stored_input = (await db_session.execute(
            select(VariableInput).where(VariableInput.employee_id == employee_id)
        )).scalar_one()
        assert stored_input.amount_paise == deduction_paise
        assert stored_input.status == "APPROVED"
    else:
        await PayrollRunService.execute_run_calculation(db_session, run_id)
        run_emp = (await db_session.execute(
            select(PayrollRunEmployee).where(PayrollRunEmployee.run_id == run_id)
        )).scalar_one()
        assert run_emp.net_pay_paise == expected_net_paise
        assert run_emp.gross_earnings_paise - run_emp.total_deductions_paise == expected_net_paise


@pytest.mark.asyncio
async def test_negative_net_rolls_back_loan_and_arrear_then_retry_succeeds(db_session):
    _company, employee, _period_row, run = await _seed_net_edge_run(
        db_session, gross_paise=100_000, variable_deduction_paise=100_000,
        loan_emi_paise=120_000, arrear_adjustment_paise=50_000,
    )
    employee_id = employee.id
    run_id = run.id
    period_id = run.period_id
    loan_before = (await db_session.execute(
        select(AdvanceLoan).where(AdvanceLoan.employee_id == employee_id)
    )).scalar_one()
    with pytest.raises(Exception) as failure:
        await PayrollRunService.execute_run_calculation(db_session, run_id)
    assert getattr(failure.value, "status_code", None) == 422
    await db_session.refresh(loan_before)
    assert loan_before.outstanding_balance == Decimal("1200.00")
    assert loan_before.installments_paid == 0
    assert await db_session.scalar(select(func.count(AdvanceLoanInstallment.id)).where(
        AdvanceLoanInstallment.loan_id == loan_before.id,
    )) == 0
    arrear = (await db_session.execute(
        select(ArrearLedger).where(ArrearLedger.target_period_id == period_id)
    )).scalar_one()
    assert arrear.status == "PENDING"
    assert arrear.applied_run_id is None

    # Correct the unresolved installment amount and retry through the actual
    # lifecycle method. The arrear then offsets the adjusted loan recovery.
    loan_before.emi_amount = Decimal("500.00")
    await db_session.commit()
    retried = await PayrollRunService.retry_run(db_session, run_id)
    assert retried.status == "PROCESSED"
    run_emp = (await db_session.execute(
        select(PayrollRunEmployee).where(PayrollRunEmployee.run_id == run_id)
    )).scalar_one()
    assert run_emp.net_pay_paise >= 0
    assert run_emp.net_pay_paise == run_emp.gross_earnings_paise - run_emp.total_deductions_paise


@pytest.mark.asyncio
async def test_full_lop_with_loan_and_negative_adjustment_fail_without_postings(db_session):
    _company, employee, _period_row, run = await _seed_net_edge_run(
        db_session, gross_paise=100_000, lop_days=Decimal("30"), loan_emi_paise=50_000,
    )
    run_id = run.id
    employee_id = employee.id
    with pytest.raises(Exception) as failure:
        await PayrollRunService.execute_run_calculation(db_session, run_id)
    assert getattr(failure.value, "status_code", None) == 422
    loan = (await db_session.execute(
        select(AdvanceLoan).where(AdvanceLoan.employee_id == employee_id)
    )).scalar_one()
    assert loan.outstanding_balance == Decimal("500.00")
    assert loan.installments_paid == 0
    assert await db_session.scalar(select(func.count(Payslip.id)).where(Payslip.payroll_run_id == run_id)) == 0

    _company, employee, _period_row, negative_run = await _seed_net_edge_run(
        db_session, gross_paise=100_000, arrear_adjustment_paise=-150_000,
    )
    negative_run_id = negative_run.id
    negative_period_id = negative_run.period_id
    with pytest.raises(Exception) as negative_adjustment:
        await PayrollRunService.execute_run_calculation(db_session, negative_run_id)
    assert getattr(negative_adjustment.value, "status_code", None) == 422
    negative_arrear = (await db_session.execute(
        select(ArrearLedger).where(ArrearLedger.target_period_id == negative_period_id)
    )).scalar_one()
    assert negative_arrear.amount_paise == -150_000
    assert negative_arrear.status == "PENDING"
    assert await db_session.scalar(select(func.count(Payslip.id)).where(Payslip.payroll_run_id == negative_run_id)) == 0


@pytest.mark.asyncio
async def test_multiple_statutory_deductions_cannot_be_hidden_by_negative_net(db_session):
    _company, _employee, _period_row, run = await _seed_net_edge_run(
        db_session, gross_paise=4_800_000, variable_deduction_paise=10_000_000,
        statutory_enabled=True,
    )
    run_id = run.id
    with pytest.raises(Exception) as failure:
        await PayrollRunService.execute_run_calculation(db_session, run_id)
    assert getattr(failure.value, "status_code", None) == 422
    await db_session.refresh(run)
    assert run.status == "FAILED"
    assert run.validation_errors[0]["code"] == "NEGATIVE_NET_PAY"
    assert await db_session.scalar(select(func.count(Payslip.id)).where(Payslip.payroll_run_id == run_id)) == 0
    assert await db_session.scalar(select(func.count(PayrollRunEmployee.id)).where(PayrollRunEmployee.run_id == run_id)) == 0


@pytest.mark.asyncio
async def test_production_engine_applies_arrear_and_preserves_exact_net_and_pdf(db_session):
    company, employee, period, run = await _seed_calculated_run(db_session)
    run_emp = (await db_session.execute(select(PayrollRunEmployee).where(PayrollRunEmployee.run_id == run.id))).scalar_one()
    assert run_emp.earnings_breakup["arrears_paise"] == 100000
    assert run_emp.net_pay_paise == run_emp.gross_earnings_paise - run_emp.total_deductions_paise
    assert run_emp.gross_earnings_paise >= 100000
    arrear = (await db_session.execute(select(ArrearLedger))).scalar_one()
    assert arrear.status == "APPLIED"
    assert arrear.applied_run_id == run.id
    payslip = (await db_session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalar_one()
    assert payslip.arrears == Decimal("1000.00")
    content, filename = await PayslipService.get_payslip_file(db_session, run.id, employee.id)
    assert content.startswith(b"%PDF")
    assert filename.endswith(".pdf")


@pytest.mark.asyncio
async def test_production_engine_preserves_paise_in_net_pay(db_session):
    _company, _employee_row, _period_row, run = await _seed_calculated_run(
        db_session, fractional_pay=True,
    )
    run_emp = (await db_session.execute(
        select(PayrollRunEmployee).where(PayrollRunEmployee.run_id == run.id)
    )).scalar_one()
    assert run_emp.gross_earnings_paise % 100 == 33
    assert run_emp.net_pay_paise == run_emp.gross_earnings_paise - run_emp.total_deductions_paise
    assert run_emp.net_pay_paise % 100 == 33


@pytest.mark.asyncio
async def test_engine_prorates_lop_and_consumes_advance_and_attendance_inputs(db_session):
    company, employee, period, run = await _seed_calculated_run(
        db_session, with_advance=True, with_attendance_inputs=True,
    )
    run_emp = (await db_session.execute(select(PayrollRunEmployee).where(PayrollRunEmployee.run_id == run.id))).scalar_one()
    assert run_emp.paid_days == Decimal("28.0")
    assert run_emp.earnings_breakup["basic_paise"] == 2800000
    assert run_emp.earnings_breakup["arrears_paise"] == 110000
    assert run_emp.earnings_breakup["one_time_bonus_paise"] == 25000
    assert run_emp.deductions_breakup["advance_recovery_paise"] == 250000
    assert run_emp.net_pay_paise == run_emp.gross_earnings_paise - run_emp.total_deductions_paise
    loan = (await db_session.execute(select(AdvanceLoan).where(AdvanceLoan.employee_id == employee.id))).scalar_one()
    assert loan.outstanding_balance == Decimal("7500.00")
    assert loan.installments_paid == 1
    assert await PayrollRunService._advance_deduction_for_employee(db_session, run, employee.id) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("month", "year", "lop_basis", "lop_days", "expected_paid", "denominator"),
    [
        (2, 2026, "CALENDAR_DAYS", Decimal("0.5"), Decimal("27.5"), 28),
        (2, 2024, "CALENDAR_DAYS", Decimal("3.5"), Decimal("25.5"), 29),
        (4, 2026, "CALENDAR_DAYS", Decimal("1.0"), Decimal("29.0"), 30),
        (5, 2026, "CALENDAR_DAYS", Decimal("31.0"), Decimal("0.0"), 31),
        (2, 2026, "FIXED_30", Decimal("0.5"), Decimal("29.5"), 30),
    ],
)
async def test_engine_uses_effective_lop_basis_and_period_days(
    db_session, month, year, lop_basis, lop_days, expected_paid, denominator,
):
    # Keep period and run years aligned for the leap-year scenario.
    company, employee, period, run = await _seed_calculated_run(
        db_session, with_attendance_inputs=True, period_month=month, period_year=year,
        lop_basis=lop_basis, attendance_lop_days=lop_days,
    )
    run_emp = (await db_session.execute(
        select(PayrollRunEmployee).where(
            PayrollRunEmployee.run_id == run.id, PayrollRunEmployee.employee_id == employee.id,
        )
    )).scalar_one()
    assert run_emp.paid_days == expected_paid
    assert run_emp.earnings_breakup["basic_paise"] == round_paise(
        Decimal(3_000_000) * expected_paid / Decimal(denominator)
    )


@pytest.mark.asyncio
async def test_canonical_run_transitions(db_session):
    company, employee, period, run = await _seed_calculated_run(db_session)
    from payroll_migrated_db import seed_payroll_actor
    actor_id = await seed_payroll_actor(db_session, company.id)
    assert run.status == "PROCESSED"
    await PayrollRunService.submit_for_approval(db_session, run.id)
    assert run.status == "PENDING_APPROVAL"
    await PayrollRunService.approve_run(db_session, run.id, user_id=actor_id, user_role="hr_admin")
    assert run.status == "APPROVED"
    await PayrollRunService.finalize_run(db_session, run.id, user_id=actor_id, user_role="hr_admin")
    assert run.status == "LOCKED" and run.is_locked
    with pytest.raises(Exception) as locked_retry:
        await PayrollRunService.retry_run(db_session, run.id)
    assert getattr(locked_retry.value, "status_code", None) == 409
    await PayrollRunService.mark_paid(db_session, run.id, user_id=actor_id, user_role="hr_admin")
    assert run.status == "PAID" and run.paid_at is not None


@pytest.mark.asyncio
async def test_accounting_export_reconciles_exact_paise_and_tenant_period(db_session):
    company, _employee_row, period, _run = await _seed_calculated_run(db_session)
    result = await AccountingService.export_accounting_entries(
        db_session, period.id, company_id=company.id,
    )
    assert result["is_balanced"] is True
    assert result["total_debits_paise"] == result["total_credits_paise"]
    assert any(entry["account_code"] == "2006" for entry in result["entries"])


@pytest.mark.asyncio
async def test_parallel_csv_comparison_persists_paise_variances(db_session):
    company, employee, period, run = await _seed_calculated_run(db_session)
    run_emp = (await db_session.execute(select(PayrollRunEmployee).where(PayrollRunEmployee.run_id == run.id))).scalar_one()
    ps = (await db_session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalar_one()
    values = {
        "gross": run_emp.gross_earnings_paise, "basic": run_emp.earnings_breakup["basic_paise"],
        "pf": run_emp.deductions_breakup["pf_paise"], "esi": run_emp.deductions_breakup["esi_paise"],
        "pt": run_emp.deductions_breakup["pt_paise"], "lwf": run_emp.deductions_breakup["lwf_paise"],
        "tds": run_emp.deductions_breakup["tds_paise"], "net_pay": run_emp.net_pay_paise,
    }
    headers = "employee_code,gross,basic,pf,esi,pt,lwf,tds,net_pay\n"
    amounts = [values[h] for h in ("gross", "basic", "pf", "esi", "pt", "lwf", "tds", "net_pay")]
    amounts[0] -= 50  # half a rupee: a rounding-only variance
    csv_content = headers + employee.employee_id + "," + ",".join(f"{Decimal(v) / 100:.3f}" for v in amounts) + "\n"
    rows = ParallelPayrollComparisonService.parse_legacy_file(csv_content.encode(), "legacy.csv")
    report = await ParallelPayrollComparisonService.compare_rows(
        db_session, run_id=run.id, legacy_rows=rows, legacy_content=csv_content.encode(), legacy_file_name="legacy.csv"
    )
    assert report.employee_variances[0]["heads"]["gross"]["variance_paise"] == 50
    assert "ROUNDING_DIFF" in report.employee_variances[0]["diagnoses"]
    assert report.head_variances["gross"]["variance_paise"] == 50
    assert report.summary["rounding"] == "ROUND_HALF_UP_NEAREST_RUPEE"


@pytest.mark.asyncio
async def test_parallel_comparison_http_routes(db_session):
    company, employee, period, run = await _seed_calculated_run(db_session)
    from payroll_migrated_db import seed_payroll_actor
    actor_id = await seed_payroll_actor(db_session, company.id)
    run_emp = (await db_session.execute(select(PayrollRunEmployee).where(PayrollRunEmployee.run_id == run.id))).scalar_one()
    values = {
        "gross": run_emp.gross_earnings_paise,
        "basic": run_emp.earnings_breakup["basic_paise"],
        "pf": run_emp.deductions_breakup["pf_paise"],
        "esi": run_emp.deductions_breakup["esi_paise"],
        "pt": run_emp.deductions_breakup["pt_paise"],
        "lwf": run_emp.deductions_breakup["lwf_paise"],
        "tds": run_emp.deductions_breakup["tds_paise"],
        "net_pay": run_emp.net_pay_paise,
    }
    csv_content = "employee_code,gross,basic,pf,esi,pt,lwf,tds,net_pay\n" + employee.employee_id + "," + ",".join(
        f"{Decimal(values[h]) / 100:.2f}" for h in ("gross", "basic", "pf", "esi", "pt", "lwf", "tds", "net_pay")
    ) + "\n"
    app = create_app()
    async def override_db():
        yield db_session
    claims = {"sub": str(actor_id), "role": "hr_admin", "company_id": str(company.id)}
    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_current_user_claims] = lambda: claims
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v2/payroll/runs/{run.id}/parallel-compare",
                files={"file": ("legacy.csv", csv_content.encode(), "text/csv")},
            )
            assert response.status_code == 200, response.text
            report_id = response.json()["data"]["report_id"]
            fetched = await client.get(f"/api/v2/payroll/reports/comparison?reportId={report_id}")
            assert fetched.status_code == 200, fetched.text
            assert fetched.json()["data"]["summary"]["matched_employees"] == 1
    finally:
        app.dependency_overrides.clear()


def test_parallel_xlsx_parser_and_diagnoses():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["employee_code", "gross", "basic", "pf", "esi", "pt", "lwf", "tds", "net_pay"])
    sheet.append(["EMP-001", 1000, 500, 60, 0, 0, 0, 0, 940])
    output = io.BytesIO()
    workbook.save(output)
    rows = ParallelPayrollComparisonService.parse_legacy_file(output.getvalue(), "legacy.xlsx")
    assert rows[0]["gross"] == 100000
    legacy = {"basic": 2000000, "lop_days": "2", "tax_regime": "OLD"}
    system = {"basic": 2000000, "lop_days": "0", "tax_regime": "NEW"}
    heads = {h: {"variance_paise": 0} for h in ParallelPayrollComparisonService.HEADS}
    heads["pf"]["variance_paise"] = 12000
    heads["tds"]["variance_paise"] = 5000
    diagnoses = ParallelPayrollComparisonService._diagnose(legacy, system, heads)
    assert "LOP_DAYS_MISMATCH" in diagnoses
    assert "PF_CEILING_DIFF" in diagnoses
    assert "TAX_REGIME_DIFF" in diagnoses
