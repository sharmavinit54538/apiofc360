"""Persist and reconcile deterministic scenarios through the real payroll engine.

Requires a migrated, disposable PostgreSQL database and explicit opt-in:
  PAYROLL_POSTGRES_TEST_URL=postgresql+asyncpg://.../payroll_verify_...
  PAYROLL_TEST_DISPOSABLE=1
  python scripts/payroll_engine_stress.py --count 10000 --seed 36020261114

Inputs/results remain in PostgreSQL and JSONL; the database owner performs cleanup.
Each scenario is one employee calculation. Batching only shares a run's policy
and period; it never replaces the engine with a mathematical helper.
"""
from __future__ import annotations

import argparse
import asyncio
import calendar
import hashlib
import inspect
import json
import os
import random
import sys
import time
import traceback
import uuid
from collections import Counter, defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def scenarios(count: int, seed: int) -> list[dict]:
    result = []
    periods = [(2026, 2), (2024, 2), (2026, 4), (2026, 5), (2026, 6), (2026, 12)]
    for index in range(count):
        rng = random.Random(seed + index)
        year, month = periods[(index // 100) % len(periods)]
        policy = "FIXED_30" if (index // 100) % 2 else "CALENDAR_DAYS"
        denominator = 30 if policy == "FIXED_30" else calendar.monthrange(year, month)[1]
        edge = index % 40
        negative = index % 100 == 99
        monthly = [3_333_333, 10_000_007, 2_000_000, 1_500_001, 1_999_999][index % 5]
        annual = 10_000_007 if index % 13 == 0 else monthly * 12 + index % 12
        monthly = annual // 12
        basic, hra = monthly // 2, monthly // 5
        lop = ["0", "0.5", "3.5", str(denominator)][index % 4]
        overtime, bonus = rng.randrange(0, 50_001), rng.randrange(0, 10_001)
        arrear = rng.randrange(0, 10_001) if index % 3 == 0 else 0
        deductions = [rng.randrange(0, 5001), rng.randrange(0, 5001)]
        loan = rng.randrange(1, 5001) if index % 7 == 0 else 0
        edge_kind = "ordinary"
        statutory = True
        state = ["MH", "KA", "DL"][(index // 200) % 3]
        if lop == str(denominator):
            overtime = bonus = arrear = loan = 0
            deductions = [0, 0]
            edge_kind = "full_lop"
        if edge in (0, 1) or negative:
            # UP's default schedule has no PT/LWF deduction. This keeps the
            # explicit zero/one-paise cases isolated from nonzero state levies
            # such as Delhi's semi-annual LWF, which would correctly reject
            # a one-paise net as negative pay.
            statutory, state, lop = False, "UP", "0"
            monthly = 100_000 if negative else (0 if edge == 0 else 1)
            annual, basic, hra = monthly * 12, monthly, 0
            overtime = bonus = 0
            arrear = 500 if negative else 0
            loan = 1000 if negative else 0
            deductions = [200_000 if negative else 0, 0]
            edge_kind = "negative" if negative else ("zero_net" if edge == 0 else "one_paise_net")
        joining = date(year, month, 15).isoformat() if index % 19 == 0 else "2020-01-01"
        # The engine consumes explicit attendance; automatic hire/exit date
        # proration is intentionally not claimed by this harness.
        if joining != "2020-01-01" and edge_kind == "ordinary":
            lop = "14"
        result.append({
            "scenario": index, "seed": seed, "year": year, "month": month,
            "policy": policy, "denominator": denominator, "state": state,
            "statutory_enabled": statutory, "annual_ctc_paise": annual,
            "basic_paise": basic, "hra_paise": hra, "special_paise": monthly - basic - hra,
            "lop_days": lop, "joining_date": joining,
            "exit_attendance_override": index % 23 == 0,
            "overtime_paise": overtime, "bonus_paise": bonus, "arrear_paise": arrear,
            "deduction_inputs_paise": deductions, "loan_paise": loan,
            "loan_type": "ADVANCE" if index % 2 else "LOAN",
            "prior_compensation": index % 11 == 0, "edge": edge_kind,
            "rule_configuration": {
                "employee_pf_rate": "0.12", "employer_pf_rate": "0.12", "pf_wage_ceiling_rupees": "15000",
                "employee_esi_rate": "0.0075", "employer_esi_rate": "0.0325", "esi_wage_ceiling_rupees": "21000",
                "tax_regime": "NEW", "financial_year": f"{year if month >= 4 else year - 1}-{year + 1 if month >= 4 else year}",
                "state_schedule_source": "APPLICATION_DEFAULTS_NOT_LEGALLY_CERTIFIED",
            },
        })
        if result[-1]["exit_attendance_override"] and edge_kind == "ordinary":
            result[-1]["lop_days"] = str(denominator - 15)
    return result


def expected_gross(item: dict) -> int:
    base, remainder = divmod(item["annual_ctc_paise"], 12)
    special = item["special_paise"] + (item["month"] <= remainder)
    assert item["basic_paise"] + item["hra_paise"] + item["special_paise"] == base
    ratio = (Decimal(item["denominator"]) - Decimal(item["lop_days"])) / item["denominator"]
    rounded = lambda value: int((Decimal(value) * ratio).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return sum(rounded(v) for v in [item["basic_paise"], item["hra_paise"], special]) + item["overtime_paise"] + item["bonus_paise"] + item["arrear_paise"]


async def main(args: argparse.Namespace) -> int:
    from sqlalchemy.engine import make_url
    url_text = os.environ.get("PAYROLL_POSTGRES_TEST_URL", "")
    if not url_text or os.environ.get("PAYROLL_TEST_DISPOSABLE") != "1":
        raise SystemExit("Set PAYROLL_POSTGRES_TEST_URL and PAYROLL_TEST_DISPOSABLE=1 for a disposable database.")
    url = make_url(url_text)
    if url.drivername != "postgresql+asyncpg" or url.host not in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit("Stress harness accepts loopback PostgreSQL+asyncpg only.")
    if not (url.database or "").startswith(("payroll_verify_", "payroll_test_", "test_")):
        raise SystemExit("Disposable database name must start payroll_verify_, payroll_test_, or test_.")
    os.environ["DATABASE_URL"] = url_text
    os.environ["FIELD_ENCRYPTION_KEY"] = "0" * 64
    os.environ["USE_CELERY"] = "false"
    from fastapi import HTTPException
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import app.models  # noqa: F401
    from app.models.company import Company
    from app.models.employee import Employee
    from app.models.payroll import (
        AdvanceLoan,
        AdvanceLoanInstallment,
        PayrollAttendanceInput,
        PayrollRun,
        Payslip,
        StatutoryComplianceConfig,
    )
    from app.models.payroll_models import (
        ArrearLedger,
        Compensation,
        PaymentBatch,
        PaymentBatchItem,
        PayrollPeriod,
        PayrollRunEmployee,
        VariableInput,
    )
    from app.services.payroll.payment_batch_service import PaymentBatchService
    from app.services.payroll.run_service import PayrollRunService

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    # Exclusive creation makes rerunning into an existing evidence directory fail.
    inputs_file = (output / "inputs.jsonl").open("x", encoding="utf-8")
    results_file = (output / "results.jsonl").open("x", encoding="utf-8")
    failures_file = (output / "failures.jsonl").open("x", encoding="utf-8")
    generated = scenarios(args.count, args.seed)
    for item in generated:
        inputs_file.write(json.dumps(item, sort_keys=True) + "\n")
    inputs_file.close()
    code_digest = hashlib.sha256(b"".join((ROOT / file).read_bytes() for file in (
        "app/services/payroll/run_service.py", "app/services/payroll/statutory_service.py", "app/services/payroll/money.py",
    ))).hexdigest()
    engine = create_async_engine(url_text, pool_size=args.concurrency, max_overflow=2)
    sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    namespace = uuid.uuid4()
    counters = Counter()
    scenario_passes = Counter()
    by_scenario = {}
    cover = Counter()
    started = time.perf_counter()
    groups = defaultdict(list)
    for item in generated:
        key = (item["year"], item["month"], item["policy"], item["state"], item["statutory_enabled"])
        if item["edge"] == "negative":
            key += (item["scenario"],)
        groups[key].append(item)
    batches = [items[start:start + args.batch_size] for items in groups.values() for start in range(0, len(items), args.batch_size)]
    semaphore = asyncio.Semaphore(args.concurrency)

    async def exercise(items: list[dict], batch_index: int, repetition: int) -> None:
        async with semaphore:
            first = items[0]
            prefix = f"stress-{namespace.hex[:10]}-{batch_index}-{repetition}"
            company_id, period_id, run_id = [uuid.uuid5(namespace, prefix + suffix) for suffix in ("tenant", "period", "run")]
            employee_ids = {item["scenario"]: uuid.uuid5(namespace, prefix + f"-{item['scenario']}") for item in items}
            try:
                async with sessions() as session:
                    session.add(Company(id=company_id, name=prefix))
                    await session.flush()
                    config = StatutoryComplianceConfig(
                        id=uuid.uuid5(namespace, prefix + "config"), company_id=company_id,
                        is_active=True, effective_from=date(2020, 1, 1),
                        pf_enabled=first["statutory_enabled"], esi_enabled=first["statutory_enabled"],
                        pt_state=first["state"], pt_slabs=[], lop_basis=first["policy"],
                        default_tax_regime="NEW", payroll_maker_checker_enforced=False,
                        formula_version="STRESS_CONFIG_1", source_note="Synthetic disposable verification policy; not legal certification",
                    )
                    period = PayrollPeriod(
                        id=period_id, company_id=company_id, name=prefix,
                        start_date=date(first["year"], first["month"], 1),
                        end_date=date(first["year"], first["month"], calendar.monthrange(first["year"], first["month"])[1]),
                        pay_date=date(first["year"], first["month"], calendar.monthrange(first["year"], first["month"])[1]),
                        period_month=first["month"], period_year=first["year"], status="OPEN",
                    )
                    session.add_all([config, period])
                    for item in items:
                        eid = employee_ids[item["scenario"]]
                        session.add(Employee(
                            # The production column is VARCHAR(20); UUID hex is
                            # 32 characters and fails before the engine runs.
                            id=eid, company_id=company_id,
                            employee_id=f"R{repetition}{item['scenario']:08d}",
                            first_name="Synthetic", last_name="Payroll", personal_email=f"{eid.hex}@example.test",
                            phone="9876543210", department="Verification", designation="Test",
                            joining_date=date.fromisoformat(item["joining_date"]), work_location=item["state"],
                            is_deleted=False, status="ACTIVE",
                        ))
                    await session.flush()
                    session.add(PayrollRun(id=run_id, company_id=company_id, period_id=period_id,
                        run_number=prefix, period_month=first["month"], period_year=first["year"], status="VALIDATED"))
                    for item in items:
                        eid = employee_ids[item["scenario"]]
                        common = {"company_id": company_id, "employee_id": eid}
                        session.add(Compensation(**common, ctc_annual_paise=item["annual_ctc_paise"],
                            basic_monthly_paise=item["basic_paise"], hra_monthly_paise=item["hra_paise"],
                            special_allowance_monthly_paise=item["special_paise"], status="ACTIVE", effective_date=period.start_date))
                        if item["prior_compensation"]:
                            session.add(Compensation(**common, ctc_annual_paise=12, basic_monthly_paise=1,
                                hra_monthly_paise=0, special_allowance_monthly_paise=0, status="SUPERSEDED", effective_date=date(2019, 1, 1)))
                        session.add(PayrollAttendanceInput(**common, period_month=first["month"], period_year=first["year"],
                            paid_days=Decimal(item["denominator"]) - Decimal(item["lop_days"]), lop_days=Decimal(item["lop_days"])))
                        for kind, amount in [("OVERTIME", item["overtime_paise"]), ("BONUS", item["bonus_paise"]),
                            *(('deduction', value) for value in item["deduction_inputs_paise"])]:
                            if amount:
                                session.add(VariableInput(**common, period_id=period_id, type=kind, amount_paise=amount,
                                    status="APPROVED", description="Deterministic synthetic stress input"))
                        if item["arrear_paise"]:
                            session.add(ArrearLedger(**common, target_period_id=period_id, type="SALARY_REVISION",
                                delta_days=Decimal(0), amount_paise=item["arrear_paise"], status="PENDING", calculation_json={"scenario": item["scenario"]}))
                        if item["loan_paise"]:
                            amount = Decimal(item["loan_paise"]) / 100
                            session.add(AdvanceLoan(**common, loan_type=item["loan_type"], principal_amount=amount,
                                outstanding_balance=amount, emi_amount=amount, total_installments=1,
                                start_from_month=first["month"], start_from_year=first["year"], status="ACTIVE"))
                    await session.commit()
                    if first["edge"] == "negative":
                        try:
                            await PayrollRunService.execute_run_calculation(session, run_id, company_id=company_id)
                        except HTTPException as exc:
                            assert exc.status_code == 422, str(exc)
                        else:
                            raise AssertionError("Negative net was not rejected")
                        await session.rollback()
                        assert await session.scalar(select(func.count(Payslip.id)).where(Payslip.payroll_run_id == run_id)) == 0
                        assert await session.scalar(select(func.count(PayrollRunEmployee.id)).where(PayrollRunEmployee.run_id == run_id)) == 0
                        loan = (await session.execute(select(AdvanceLoan).where(AdvanceLoan.company_id == company_id))).scalar_one()
                        assert loan.installments_paid == 0
                        rows = (await session.execute(select(VariableInput).where(VariableInput.period_id == period_id, VariableInput.type == "deduction"))).scalars().all()
                        for row in rows:
                            row.amount_paise = 0
                        await session.commit()
                        await PayrollRunService.retry_run(session, run_id)
                        counters["negative_rejections_and_recoveries"] += len(items)
                    else:
                        await PayrollRunService.execute_run_calculation(session, run_id, company_id=company_id)
                    await PayrollRunService.submit_for_approval(session, run_id, company_id=company_id)
                    await PayrollRunService.approve_run(session, run_id, company_id=company_id)
                    await PayrollRunService.finalize_run(session, run_id, company_id=company_id)
                    payment_kwargs = {"run_id": run_id, "source_account_id": "stress-test-only", "payment_mode": "NEFT"}
                    if "company_id" in inspect.signature(PaymentBatchService.create_batch_from_run).parameters:
                        payment_kwargs["company_id"] = company_id
                    batch = await PaymentBatchService.create_batch_from_run(session, **payment_kwargs)
                    repeated = await PaymentBatchService.create_batch_from_run(session, **payment_kwargs)
                    assert batch.id == repeated.id, "Duplicate request created an additional payment batch"
                    posting_rows = (await session.execute(select(PayrollRunEmployee).where(PayrollRunEmployee.run_id == run_id))).scalars().all()
                    payslips = (await session.execute(select(Payslip).where(Payslip.payroll_run_id == run_id))).scalars().all()
                    payments = (await session.execute(select(PaymentBatchItem).where(PaymentBatchItem.batch_id == batch.id))).scalars().all()
                    assert len(posting_rows) == len(payslips) == len(payments) == len(items)
                    assert await session.scalar(select(func.count(PaymentBatch.id)).where(PaymentBatch.run_id == run_id)) == 1
                    posts = {row.employee_id: row for row in posting_rows}
                    slips = {row.employee_id: row for row in payslips}
                    pay = {row.employee_id: row for row in payments}
                    run = await session.get(PayrollRun, run_id)
                    assert run.status == "LOCKED" and run.is_locked
                    assert run.total_gross_paise == sum(row.gross_earnings_paise for row in posting_rows)
                    assert run.total_deductions_paise == sum(row.total_deductions_paise for row in posting_rows)
                    assert run.total_net_paise == sum(row.net_pay_paise for row in posting_rows)
                    validated = []
                    for item in items:
                        eid = employee_ids[item["scenario"]]
                        row, slip, payment = posts[eid], slips[eid], pay[eid]
                        assert row.company_id == slip.company_id == payment.company_id == company_id
                        earning = row.earnings_breakup
                        deductions = row.deductions_breakup
                        components = sum(earning[key] for key in ("basic_paise", "hra_paise", "special_paise", "conveyance_paise", "lta_paise", "statutory_bonus_paise", "reimbursement_paise", "variable_paise", "arrears_paise", "one_time_bonus_paise")) + sum(earning["other_fixed_paise"].values()) + sum(earning["custom_paise"].values())
                        deducted = sum(deductions[key] for key in ("pf_paise", "esi_paise", "pt_paise", "lwf_paise", "tds_paise", "advance_recovery_paise", "variable_deductions_paise", "custom_deductions_paise", "country_employee_deductions_paise"))
                        assert components == row.gross_earnings_paise == expected_gross(item)
                        assert deducted == row.total_deductions_paise
                        assert components - deducted - row.net_pay_paise == 0
                        assert Decimal(slip.gross_earnings) * 100 == components
                        assert Decimal(slip.total_deductions) * 100 == deducted
                        assert Decimal(slip.net_pay) * 100 == row.net_pay_paise
                        assert row.net_pay_paise == payment.amount_paise  # exact paise settlement, zero adjustment
                        output_row = {"scenario": item["scenario"], "repetition": repetition, "company_id": str(company_id), "run_id": str(run_id),
                            "employee_id": str(eid), "gross_paise": components, "deductions_paise": deducted, "net_paise": row.net_pay_paise,
                            "settlement_adjustment_paise": 0, "payment_amount_paise": payment.amount_paise, "variance_paise": 0,
                            "payroll_variance_rupees": "0.000000", "payment_variance_rupees": "0.000000",
                            "policy": first["policy"], "config_id": str(config.id), "statutory_rule_version": deductions["statutory_rule_version"],
                            "statutory_config_version": config.formula_version, "code_sha256": code_digest,
                            "statutory_components_paise": {key: deductions[key] for key in ("pf_paise", "esi_paise", "pt_paise", "tds_paise", "lwf_paise")}}
                        fingerprint = (components, deducted, row.net_pay_paise, json.dumps(earning, sort_keys=True), json.dumps(deductions, sort_keys=True))
                        if repetition > 0:
                            assert by_scenario[item["scenario"]] == fingerprint, "Nondeterministic repeated engine output"
                        validated.append((item, output_row, fingerprint))
                    # Locked runs cannot be replayed or altered; committed effects stay unique.
                    try:
                        await PayrollRunService.execute_run_calculation(session, run_id, company_id=company_id)
                    except HTTPException as exc:
                        assert exc.status_code == 409
                        await session.rollback()
                    else:
                        raise AssertionError("Locked run accepted a calculation replay")
                    recoveries = await session.scalar(select(func.count(AdvanceLoanInstallment.id)).join(AdvanceLoan).where(AdvanceLoan.company_id == company_id))
                    assert recoveries == sum(bool(item["loan_paise"]) for item in items)
                    for item, output_row, fingerprint in validated:
                        if repetition == 0:
                            by_scenario[item["scenario"]] = fingerprint
                        results_file.write(json.dumps(output_row, sort_keys=True) + "\n")
                        counters["employee_evaluations_passed"] += 1
                        scenario_passes[item["scenario"]] += 1
                        cover[item["edge"]] += 1
                        for key, value in output_row["statutory_components_paise"].items():
                            cover[key] += bool(value)
                    counters["runs_passed"] += 1
            except Exception as exc:  # noqa: BLE001 - every failed scenario must be recorded, then exit nonzero
                counters["employee_evaluations_failed"] += len(items)
                failures_file.write(json.dumps({"scenarios": [item["scenario"] for item in items], "repetition": repetition, "run_id": str(run_id), "error_type": type(exc).__name__, "error": str(exc), "traceback": traceback.format_exc()}, sort_keys=True) + "\n")
                failures_file.flush()
            finally:
                results_file.flush()
                done = counters["employee_evaluations_passed"] + counters["employee_evaluations_failed"]
                if done % 500 == 0:
                    print(json.dumps({"evaluations_completed": done, "elapsed_seconds": round(time.perf_counter() - started, 2), **counters}), flush=True)

    async def annual_cycle() -> dict:
        """Reconcile one persisted annual contract through twelve real monthly runs."""
        annual = 10_000_007
        company_id = uuid.uuid5(namespace, "annual-tenant")
        employee_id = uuid.uuid5(namespace, "annual-employee")
        actual = []
        async with sessions() as session:
            session.add(Company(id=company_id, name=f"Annual CTC stress {namespace.hex[:10]}"))
            await session.flush()
            session.add(Employee(id=employee_id, company_id=company_id,
                employee_id=f"AN{namespace.hex[:18]}",
                first_name="Annual", last_name="Verification", personal_email=f"{employee_id.hex}@example.test",
                phone="9876543210", department="Verification", designation="Test", joining_date=date(2020, 1, 1),
                work_location="DL", is_deleted=False, status="ACTIVE"))
            await session.flush()
            session.add_all([
                Compensation(company_id=company_id, employee_id=employee_id, ctc_annual_paise=annual,
                    basic_monthly_paise=annual // 12, hra_monthly_paise=0, special_allowance_monthly_paise=0,
                    effective_date=date(2020, 1, 1), status="ACTIVE"),
                StatutoryComplianceConfig(company_id=company_id, is_active=True, effective_from=date(2020, 1, 1),
                    pf_enabled=False, esi_enabled=False, pt_state="DL", pt_slabs=[], lop_basis="CALENDAR_DAYS",
                    default_tax_regime="NEW", payroll_maker_checker_enforced=False, formula_version="STRESS_ANNUAL_CTC_1"),
            ])
            await session.commit()
            for month in range(1, 13):
                last = calendar.monthrange(2026, month)[1]
                period_id, run_id = uuid.uuid4(), uuid.uuid4()
                session.add(PayrollPeriod(id=period_id, company_id=company_id, name=f"Annual {month}",
                    start_date=date(2026, month, 1), end_date=date(2026, month, last), pay_date=date(2026, month, last),
                    period_month=month, period_year=2026, status="OPEN"))
                await session.flush()
                session.add(PayrollRun(id=run_id, company_id=company_id, period_id=period_id,
                    run_number=f"CTC-{namespace.hex[:10]}-{month}", period_month=month, period_year=2026, status="VALIDATED"))
                await session.commit()
                await PayrollRunService.execute_run_calculation(session, run_id, company_id=company_id)
                posting = (await session.execute(select(PayrollRunEmployee).where(PayrollRunEmployee.run_id == run_id))).scalar_one()
                assert posting.gross_earnings_paise == annual // 12 + int(month <= annual % 12)
                actual.append({"month": month, "run_id": str(run_id), "gross_paise": posting.gross_earnings_paise})
                await PayrollRunService.submit_for_approval(session, run_id, company_id=company_id)
                await PayrollRunService.approve_run(session, run_id, company_id=company_id)
                await PayrollRunService.finalize_run(session, run_id, company_id=company_id)
            total = await session.scalar(select(func.sum(PayrollRunEmployee.gross_earnings_paise)).where(PayrollRunEmployee.employee_id == employee_id))
            total = int(total or 0)
            assert total == annual
            return {"annual_ctc_paise": annual, "allocated_ctc_paise": total, "variance_rupees": "0.000000", "monthly_runs": actual}

    annual_result = None
    try:
        for repetition in range(args.repeats):
            await asyncio.gather(*(exercise(items, index, repetition) for index, items in enumerate(batches)))
        try:
            annual_result = await annual_cycle()
            (output / "annual_ctc.json").write_text(json.dumps(annual_result, indent=2), encoding="utf-8")
            counters["annual_ctc_engine_months_passed"] = 12
        except Exception as exc:  # noqa: BLE001 - preserve failed real-engine evidence
            counters["annual_ctc_cohort_failed"] = 1
            failures_file.write(json.dumps({"cohort": "annual_ctc", "error_type": type(exc).__name__, "error": str(exc), "traceback": traceback.format_exc()}) + "\n")
    finally:
        await engine.dispose()
        results_file.close()
        failures_file.close()
    elapsed = time.perf_counter() - started
    summary = {"seed": args.seed, "logical_scenarios": args.count, "repeats": args.repeats, **counters,
        "logical_scenarios_passed": sum(value == args.repeats for value in scenario_passes.values()),
        "logical_scenarios_failed": args.count - sum(value == args.repeats for value in scenario_passes.values()),
        "elapsed_seconds": round(elapsed, 3), "evaluations_per_second": round(sum((counters["employee_evaluations_passed"], counters["employee_evaluations_failed"])) / elapsed, 3),
        "database": {"driver": url.drivername, "host": url.host, "port": url.port, "name": url.database},
        "code_sha256": code_digest, "coverage": dict(cover), "actual_engine": "PayrollRunService.execute_run_calculation",
        "annual_ctc_result": annual_result,
        "limitations": ["Automatic joining/exit proration is not implemented by this engine; explicit attendance overrides were tested.",
            "Salary revision coverage uses superseded and active persisted compensation rows; approval workflow is separate.",
            "Statutory deductions use configured application rules; this harness does not certify legal correctness.",
            "No external bank settlement or provider payment execution; only persisted payment instructions."]}
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
    return int(counters["employee_evaluations_failed"] > 0 or counters["annual_ctc_cohort_failed"] > 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=36020261114)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--output", default="verification/payroll-stress")
    parsed = parser.parse_args()
    if min(parsed.count, parsed.batch_size, parsed.concurrency, parsed.repeats) < 1:
        parser.error("Count, batch size, concurrency, and repeats must be positive.")
    raise SystemExit(asyncio.run(main(parsed)))
