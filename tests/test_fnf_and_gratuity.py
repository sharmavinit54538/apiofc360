"""Test suite for Phase 3: Full & Final Settlement (FNF) and Gratuity."""
import asyncio
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import pytest

sys.path.insert(0, os.getcwd())

from app.db.database import AsyncSessionLocal
from app.models.company import Company
from app.models.employee import Employee
from app.models.employee_leave_policy import EmployeeLeavePolicy
from app.models.exit import EmployeeExit, FnfSettlement
from app.models.leave_type import LeaveType
from app.models.payroll import AdvanceLoan, SalaryStructure
from app.services.fnf_calculation_service import FnfCalculationService
from app.services.exit_service import ExitService
from app.schemas.exit import FnfCreate


def test_gratuity_under_five_years_is_zero():
    """Service < 5 years (e.g. 4 years) is not eligible for gratuity under Gratuity Act."""
    joining = date(2020, 1, 1)
    last_working = date(2024, 1, 1) # 4 years
    basic = Decimal("50000.00")

    gratuity = FnfCalculationService.compute_gratuity(basic, joining, last_working)
    assert gratuity == Decimal("0.00")


def test_gratuity_exact_five_years():
    """Exact 5 years with ₹52,000 basic:
    Formula = (15 / 26) * 52000 * 5 = 1,50,000.00
    """
    joining = date(2019, 1, 1)
    last_working = date(2024, 1, 5) # 5 years
    basic = Decimal("52000.00")

    gratuity = FnfCalculationService.compute_gratuity(basic, joining, last_working)
    assert gratuity == Decimal("150000.00")


def test_gratuity_fractional_rounding():
    """6 years and 8 months service rounds up to 7 years:
    Formula = (15 / 26) * 52000 * 7 = 2,10,000.00
    """
    joining = date(2017, 1, 1)
    last_working = date(2023, 9, 1) # 6 years 8 months
    basic = Decimal("52000.00")

    gratuity = FnfCalculationService.compute_gratuity(basic, joining, last_working)
    assert gratuity == Decimal("210000.00")


def test_leave_encashment():
    """12 unused days with ₹60,000 monthly basic:
    Encashment = 12 * (60000 / 30) = 24,000.00
    """
    encashment = FnfCalculationService.compute_leave_encashment(Decimal("12.0"), Decimal("60000.00"))
    assert encashment == Decimal("24000.00")


def test_notice_recovery():
    """Notice required 30 days, actual served 10 days -> 20 days recovery.
    Per day = 60000 / 30 = 2000. Recovery = 40,000.
    """
    recovery, payout = FnfCalculationService.compute_notice_recovery(
        required_notice_days=30,
        actual_notice_days=10,
        basic_monthly=Decimal("60000.00"),
    )
    assert recovery == Decimal("40000.00")
    assert payout == Decimal("0.00")


@pytest.mark.asyncio
async def test_end_to_end_fnf_preview_and_submission():
    """Seed exiting employee with 6 years tenure, unused leave, active loan, and calculate FNF."""
    async with AsyncSessionLocal() as db:
        test_company = Company(
            id=uuid.uuid4(),
            name=f"Test FNF Corp {uuid.uuid4().hex[:6]}",
        )
        db.add(test_company)
        await db.flush()

        emp = Employee(
            id=uuid.uuid4(),
            company_id=test_company.id,
            employee_id=f"EMP-{uuid.uuid4().hex[:4]}",
            first_name="Senior",
            last_name="Staff",
            personal_email=f"senior_{uuid.uuid4().hex[:4]}@test.com",
            phone="9876543299",
            department="Operations",
            designation="Manager",
            joining_date=date(2018, 1, 1),
            status="ACTIVE",
            is_active=True,
        )
        db.add(emp)
        await db.flush()

        # Active salary structure (Basic = 52,000)
        sal = SalaryStructure(
            id=uuid.uuid4(),
            company_id=test_company.id,
            employee_id=emp.id,
            annual_ctc=Decimal("1200000.00"),
            basic_monthly=Decimal("52000.00"),
            hra_monthly=Decimal("26000.00"),
            conveyance_monthly=Decimal("4000.00"),
            special_allowance_monthly=Decimal("8000.00"),
            annual_bonus=Decimal("120000.00"),
            tax_regime="NEW",
            effective_from=date(2018, 1, 1),
            is_active=True,
        )
        db.add(sal)

        # Leave Policy with 10 unused days
        lt = LeaveType(
            id=uuid.uuid4(),
            company_id=test_company.id,
            name="Earned Leave",
            code=f"EL-{uuid.uuid4().hex[:4]}",
            days_allowed=18,
            is_active=True,
        )
        db.add(lt)
        await db.flush()

        elp = EmployeeLeavePolicy(
            id=uuid.uuid4(),
            employee_id=emp.id,
            leave_type_id=lt.id,
            total_days=Decimal("18.0"),
            used_days=Decimal("8.0"), # 10 unused
            year=2024,
            is_active=True,
        )
        db.add(elp)

        # Active loan with 15,000 outstanding
        loan = AdvanceLoan(
            id=uuid.uuid4(),
            company_id=test_company.id,
            employee_id=emp.id,
            loan_type="SALARY_ADVANCE",
            principal_amount=Decimal("30000.00"),
            outstanding_balance=Decimal("15000.00"),
            total_installments=6,
            installments_paid=3,
            emi_amount=Decimal("5000.00"),
            status="ACTIVE",
        )
        db.add(loan)

        # Employee Exit Record (6 years 8 months tenure: Jan 1 2018 -> Sep 1 2024)
        exit_obj = EmployeeExit(
            id=uuid.uuid4(),
            employee_id=emp.id,
            reason="Relocating to another city",
            exit_type="RESIGNATION",
            last_working_date=date(2024, 9, 15),
            status="IN_PROGRESS",
            created_at=datetime(2024, 8, 15, 10, 0, 0, tzinfo=timezone.utc),
        )
        db.add(exit_obj)
        await db.commit()

        # Run FNF preview
        exit_service = ExitService(db)
        preview = await exit_service.get_fnf_preview(exit_obj.id)

        # Assert Gratuity: ~7 years * (15/26) * 52,000 = 210,000
        assert preview["gratuity"] == 210000.00
        # Assert Leave Encashment: 10 * (52000 / 30) = 17,333.33
        assert abs(preview["leave_encashment"] - 17333.33) <= 0.05
        # Assert Loan Recovery = 15,000
        assert preview["loan_recovery"] == 15000.00
        # Assert net payable > 0
        assert preview["net_payable_amount"] > 0

        # Submit FNF with auto-calculated defaults
        fnf_res = await exit_service.submit_fnf(exit_obj.id, FnfCreate())
        assert fnf_res.gratuity == Decimal("210000.00")
        assert fnf_res.loan_recovery == Decimal("15000.00")
        assert fnf_res.net_payable_amount > Decimal("0.00")

        # Verify in DB
        db_fnf = await exit_service.repo.get_fnf_by_exit_id(exit_obj.id)
        assert db_fnf is not None
        assert db_fnf.gratuity == Decimal("210000.00")
        assert db_fnf.loan_recovery == Decimal("15000.00")
