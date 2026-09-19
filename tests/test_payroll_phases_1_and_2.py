"""Test suite for Payroll Module Phase 1 and Phase 2."""
import asyncio
import os
import sys
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
import pytest

sys.path.insert(0, os.getcwd())

from app.db.database import AsyncSessionLocal
from app.models.company import Company
from app.models.employee import Employee
from app.models.payroll import (
    EmployeeInvestmentDeclaration,
    PayCycle,
    PayrollAttendanceInput,
    Payslip,
    SalaryStructure,
    StatutoryComplianceConfig,
)
from app.models.user import User
from app.services.payroll_service import PayrollService
from app.api.payroll.services.payroll_processing_service import PayrollProcessingService


def test_tds_calculation_new_regime_below_threshold():
    """Salary below ₹7,00,000 taxable under new regime should have ₹0 TDS."""
    sal_struct = SalaryStructure(
        basic_monthly=Decimal("30000.00"),
        hra_monthly=Decimal("15000.00"),
        conveyance_monthly=Decimal("1600.00"),
        special_allowance_monthly=Decimal("3400.00"),
        annual_bonus=Decimal("0.00"),
        other_allowances=None,
        tax_regime="NEW",
        effective_from=date.today(),
    )
    # Annual gross = (30000 + 15000 + 1600 + 3400) * 12 = 50000 * 12 = 6,00,000
    # Taxable = 6,00,000 - 75,000 = 5,25,000 <= 7,00,000 -> 87A rebate applies -> 0 TDS
    config = StatutoryComplianceConfig(default_tax_regime="NEW")
    emp = Employee(id=uuid.uuid4(), employee_id="EMP001", first_name="A", last_name="B", personal_email="a@b.com", phone="123", department="IT", designation="Dev", joining_date=date.today())

    tds = PayrollService._compute_tds(emp, sal_struct, config, None, period_month=4)
    assert tds == Decimal("0.00")


def test_tds_calculation_new_regime_high_earner():
    """Annual gross ₹18,00,000 under new regime:
    Standard deduction = 75,000
    Taxable = 17,25,000
    Slabs:
    0-3L: 0
    3-7L (4L @ 5%): 20,000
    7-10L (3L @ 10%): 30,000
    10-12L (2L @ 15%): 30,000
    12-15L (3L @ 20%): 60,000
    Above 15L (2.25L @ 30%): 67,500
    Total Base Tax = 2,07,500
    + 4% Cess = 2,15,800
    Monthly (Apr, 12 months) = 2,15,800 / 12 = 17,983.33
    """
    sal_struct = SalaryStructure(
        basic_monthly=Decimal("75000.00"),
        hra_monthly=Decimal("37500.00"),
        conveyance_monthly=Decimal("10000.00"),
        special_allowance_monthly=Decimal("27500.00"),
        annual_bonus=Decimal("0.00"),
        other_allowances=None,
        tax_regime="NEW",
        effective_from=date.today(),
    )
    # Monthly gross = 1,50,000 * 12 = 18,00,000
    config = StatutoryComplianceConfig(default_tax_regime="NEW")
    emp = Employee(id=uuid.uuid4(), employee_id="EMP002", first_name="C", last_name="D", personal_email="c@d.com", phone="123", department="IT", designation="Dev", joining_date=date.today())

    tds = PayrollService._compute_tds(emp, sal_struct, config, None, period_month=4)
    assert abs(tds - Decimal("17983.33")) <= Decimal("0.05")


def test_tds_calculation_old_regime_with_exemptions():
    """Old regime calculation with 80C, 80D, and HRA exemption."""
    sal_struct = SalaryStructure(
        basic_monthly=Decimal("50000.00"),
        hra_monthly=Decimal("25000.00"),
        conveyance_monthly=Decimal("5000.00"),
        special_allowance_monthly=Decimal("10000.00"),
        annual_bonus=Decimal("0.00"),
        other_allowances=None,
        tax_regime="OLD",
        is_metro_city=True,
        rent_paid_monthly=Decimal("20000.00"),
        effective_from=date.today(),
    )
    # Annual gross = 90,000 * 12 = 10,80,000
    # Standard deduction = 50,000
    # Annual basic = 6,00,000; Annual HRA = 3,00,000; Annual rent = 2,40,000
    # HRA exemption: min(3,00,000, 2,40,000 - 60,000, 3,00,000) = min(3L, 1.8L, 3L) = 1,80,000
    # 80C = 1,50,000, 80D = 25,000
    # Total deductions = 50k + 1.8L + 1.5L + 25k = 4,05,000
    # Taxable = 10,80,000 - 4,05,000 = 6,75,000
    # Slabs:
    # 0-2.5L: 0
    # 2.5-5L (2.5L @ 5%): 12,500
    # 5-6.75L (1.75L @ 20%): 35,000
    # Total = 47,500
    # + 4% cess = 49,400
    # Monthly (Apr, 12 months) = 49,400 / 12 = 4,116.67
    decl = EmployeeInvestmentDeclaration(
        section_80c=Decimal("150000.00"),
        section_80d=Decimal("25000.00"),
        section_80ccd1b_nps=Decimal("0.00"),
        home_loan_interest_24b=Decimal("0.00"),
        section_80g=Decimal("0.00"),
        other_deductions=Decimal("0.00"),
    )
    config = StatutoryComplianceConfig(default_tax_regime="OLD")
    emp = Employee(id=uuid.uuid4(), employee_id="EMP003", first_name="E", last_name="F", personal_email="e@f.com", phone="123", department="HR", designation="Lead", joining_date=date.today())

    tds = PayrollService._compute_tds(emp, sal_struct, config, decl, period_month=4)
    assert abs(tds - Decimal("4116.67")) <= Decimal("0.05")


def test_pt_calculation_states():
    """Test state-wise PT slab lookups."""
    # Telangana
    assert PayrollService._compute_pt(Decimal("14000.00"), "TELANGANA", 4) == Decimal("0.00")
    assert PayrollService._compute_pt(Decimal("18000.00"), "TELANGANA", 4) == Decimal("150.00")
    assert PayrollService._compute_pt(Decimal("25000.00"), "TELANGANA", 4) == Decimal("200.00")

    # Maharashtra (Feb ₹300 vs normal ₹200)
    assert PayrollService._compute_pt(Decimal("15000.00"), "MAHARASHTRA", 5) == Decimal("200.00")
    assert PayrollService._compute_pt(Decimal("15000.00"), "MAHARASHTRA", 2) == Decimal("300.00")

    # Karnataka
    assert PayrollService._compute_pt(Decimal("14999.00"), "KARNATAKA", 4) == Decimal("0.00")
    assert PayrollService._compute_pt(Decimal("15000.00"), "KARNATAKA", 4) == Decimal("200.00")

    # West Bengal
    assert PayrollService._compute_pt(Decimal("12000.00"), "WEST BENGAL", 4) == Decimal("110.00")
    assert PayrollService._compute_pt(Decimal("18000.00"), "WEST BENGAL", 4) == Decimal("130.00")
    assert PayrollService._compute_pt(Decimal("30000.00"), "WEST BENGAL", 4) == Decimal("150.00")
    assert PayrollService._compute_pt(Decimal("50000.00"), "WEST BENGAL", 4) == Decimal("200.00")


@pytest.mark.asyncio
async def test_end_to_end_payroll_run():
    """Seed test company, employees, salary structures, and trigger live payroll run."""
    async with AsyncSessionLocal() as db:
        # Create test company
        test_company = Company(
            id=uuid.uuid4(),
            name=f"Test Payroll Corp {uuid.uuid4().hex[:6]}",
        )
        db.add(test_company)
        await db.flush()

        # Create statutory config
        stat_config = StatutoryComplianceConfig(
            id=uuid.uuid4(),
            company_id=test_company.id,
            pf_enabled=True,
            employee_pf_rate=Decimal("0.12"),
            employer_pf_rate=Decimal("0.12"),
            pf_wage_ceiling=Decimal("15000.00"),
            esi_enabled=True,
            employee_esi_rate=Decimal("0.0075"),
            employer_esi_rate=Decimal("0.0325"),
            esi_wage_ceiling=Decimal("21000.00"),
            pt_state="TELANGANA",
            default_tax_regime="NEW",
            is_active=True,
        )
        db.add(stat_config)

        # Create 2 employees
        emp1 = Employee(
            id=uuid.uuid4(),
            company_id=test_company.id,
            employee_id=f"EMP-{uuid.uuid4().hex[:4]}",
            first_name="Jane",
            last_name="Doe",
            personal_email=f"jane_{uuid.uuid4().hex[:4]}@test.com",
            phone="9876543210",
            department="Engineering",
            designation="Software Engineer",
            joining_date=date(2023, 1, 1),
            status="ACTIVE",
            is_active=True,
        )
        emp2 = Employee(
            id=uuid.uuid4(),
            company_id=test_company.id,
            employee_id=f"EMP-{uuid.uuid4().hex[:4]}",
            first_name="John",
            last_name="Smith",
            personal_email=f"john_{uuid.uuid4().hex[:4]}@test.com",
            phone="9876543211",
            department="Product",
            designation="Product Manager",
            joining_date=date(2022, 6, 1),
            status="ACTIVE",
            is_active=True,
        )
        db.add_all([emp1, emp2])
        await db.flush()

        # Create salary structures (including other_allowances)
        sal1 = SalaryStructure(
            id=uuid.uuid4(),
            company_id=test_company.id,
            employee_id=emp1.id,
            annual_ctc=Decimal("600000.00"),
            basic_monthly=Decimal("25000.00"),
            hra_monthly=Decimal("12500.00"),
            conveyance_monthly=Decimal("2500.00"),
            special_allowance_monthly=Decimal("5000.00"),
            other_allowances={"Internet": 1500, "Food Coupon": 2000},
            annual_bonus=Decimal("42000.00"),
            tax_regime="NEW",
            effective_from=date(2023, 1, 1),
            is_active=True,
        )
        sal2 = SalaryStructure(
            id=uuid.uuid4(),
            company_id=test_company.id,
            employee_id=emp2.id,
            annual_ctc=Decimal("1200000.00"),
            basic_monthly=Decimal("50000.00"),
            hra_monthly=Decimal("25000.00"),
            conveyance_monthly=Decimal("5000.00"),
            special_allowance_monthly=Decimal("10000.00"),
            other_allowances=None,
            annual_bonus=Decimal("120000.00"),
            tax_regime="NEW",
            effective_from=date(2022, 6, 1),
            is_active=True,
        )
        db.add_all([sal1, sal2])
        await db.commit()

        # Trigger run via PayrollProcessingService
        service = PayrollProcessingService(db)
        run_res = await service.trigger_run(
            body={"company_id": str(test_company.id), "period_month": 4, "period_year": 2026},
            claims={"company_id": str(test_company.id), "role": "admin", "sub": str(uuid.uuid4())}
        )

        assert run_res["total_employees"] == 2
        assert run_res["total_gross"] > 0
        assert run_res["total_net"] > 0
        assert run_res["status"] == "VALIDATED"

        # Verify payslip rows in database
        payslips = await service.repo.get_payslips_for_cycle(uuid.UUID(run_res["run_id"]))
        assert len(payslips) == 2
        for p in payslips:
            assert p.basic > 0
            assert p.gross_earnings > 0
            assert p.net_pay > 0
            assert p.employee_pf > 0
            assert p.professional_tax == Decimal("200.00")

        # Verify other_allowances on emp1 payslip
        emp1_payslip = next(p for p in payslips if p.employee_id == emp1.id)
        assert emp1_payslip.other_allowances_total == Decimal("3500.00")

        # Test approve
        approve_res = await service.approve_run(
            body={"run_id": run_res["run_id"]},
            claims={"company_id": str(test_company.id), "role": "admin", "sub": str(uuid.uuid4())}
        )
        assert approve_res["status"] == "APPROVED"

        # Test bank transfer generation
        bank_res = await service.initiate_bank_transfer(
            body={"run_id": run_res["run_id"]},
            claims={"company_id": str(test_company.id), "role": "admin", "sub": str(uuid.uuid4())}
        )
        assert bank_res["status"] == "GENERATED"
        assert bank_res["total_records"] == 2

        # Test rollback
        rollback_res = await service.rollback_run(
            body={"run_id": run_res["run_id"]},
            claims={"company_id": str(test_company.id), "role": "admin", "sub": str(uuid.uuid4())}
        )
        assert rollback_res["status"] == "ROLLED_BACK"

        # Verify payslips deleted
        payslips_after = await service.repo.get_payslips_for_cycle(uuid.UUID(run_res["run_id"]))
        assert len(payslips_after) == 0
