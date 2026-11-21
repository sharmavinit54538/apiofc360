"""Reconcile retained execution evidence; never converts failures into passes."""
from __future__ import annotations

from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "verification" / "payroll-pg-20261115"
BASELINE = ROOT / "verification" / "full-backend-post-statutory-20261115-rerun.xml"


def classify(module, name, message):
    if "ConnectionRefusedError" in message:
        return "environment", "PostgreSQL connection refused before application assertion; original run had no usable test DB.", "original JUnit traceback"
    if "PermissionError" in message:
        return "environment", "Windows fixture temporary-directory access denied during setup/teardown.", "original JUnit error traceback"
    if name in {"test_auth_login_comprehensive_suite", "test_login_unknown_email_returns_401_not_500"}:
        return "environment", "Login converted the unavailable database exception into HTTP 500; rerun with PostgreSQL reached the expected 401.", "suite-20261116/results.xml"
    if "'NoneType' object can't be awaited" in message:
        return "application", "invalidate_auth_active_cache awaited the synchronous cache_delete result; now deletes Redis asynchronously and local cache synchronously.", "app/middleware/auth.py"
    if "'created_by' is an invalid keyword argument for User" in message:
        return "application", "HRAdminService passed nonexistent User.created_by; creator attribution belongs to Employee and audit records.", "app/services/hr_admin_service.py"
    if module.endswith("test_payments_razorpay") or (module.endswith("test_settings_and_billing_comprehensive") and name != "test_preserved_existing_endpoints"):
        return "application", "Implemented settings/billing/payments routers were omitted from the /api/v1 router assembly; registered them.", "app/api/v1/router.py"
    if name == "test_require_employee_or_above_dependency":
        return "application", "Unknown roles silently normalized to employee in authorization; strict parsing now rejects them.", "app/core/rbac.py; app/models/user/role.py"
    if name == "test_it_admin_sidebar_permissions":
        return "application", "Sidebar omitted itadmin and tech_admin aliases that canonical RoleEnum accepts.", "app/api/sidebar.py; app/models/user/role.py"
    if name == "test_cto_dashboard_endpoint_requires_auth":
        return "application", "Legacy CTO router exists but is not registered. It also contains unscoped queries and fabricated fallback metrics; mounting it only to satisfy this assertion is unsafe and outside the payroll repair.", "app/api/cto/dashboard.py; app/api/v1/router.py"

    fixtures = {
        "test_expense_migration": "Fixture asserted a historical exact Alembic head instead of checking one head and expense ancestry.",
        "test_ai_chat_assistant_routes": "Test parses a streaming SSE response with response.json(); its JWT company/user IDs are also not persisted.",
        "test_ai_face_attendance": "Fixture referenced Attendance without importing it; later Core inserts also needed ORM FK targets flushed first.",
        "test_ai_resume_parser_comprehensive": "Mock UploadFile.read returned the same bytes indefinitely, never EOF, correctly triggering the file-size limit.",
        "test_alembic_single_head": "Fixture enforced the old 28-character version limit even after migration 902a widens alembic_version to 128.",
        "test_api_500_404_fixes": "Fixture requests legacy /v2/payroll URL, while the unified route contract uses /api/v2; 404 occurs before authentication.",
        "test_auth_endpoints_comprehensive": "Mocks/payloads use the old four-value login return and token-only password reset instead of current five-value/OTP contracts.",
        "test_auth_hierarchy": "Tests expect four-value login and a 403 for unverified email; service returns five values or an OTP verification challenge.",
        "test_brute_force_and_rate_limiting": "Fixture patches synchronous verify_password, but login invokes verify_password_async.",
        "test_company_logo_upload": "MagicMock Company has no SQLAlchemy state for flag_modified; company=None helper substitutes a company; missing-tenant expected status is stale.",
        "test_employee_salary_and_crud_lifecycle": "Fixture accesses EmployeeListItem.ctc, which is absent from the current response schema.",
        "test_leave_management_module": "AsyncMock returns coroutine instead of synchronous SQLAlchemy Result; fixed historical dates violate lookback and three-type assertion predates fourth leave type.",
        "test_lifecycle_synchronization": "Login fixture patches the old password verifier, so authentication fails before the deactivated-user status assertion.",
        "test_operational_security_and_hygiene": "ResetPasswordRequest fixture supplies obsolete token fields; current schema requires email and OTP.",
        "test_production_assistant": "Shared app dependency overrides leaked from earlier failed tests; isolated unauthorized health request is checked separately.",
        "test_rbac_and_role_enum_standardization": "Fixture asserts seven enum entries although deployed legacy roles are intentionally retained alongside the seven canonical roles.",
        "test_registration_comprehensive": "Fixture expects removed department auto-seeding and omits APIResponse.meta from the serialized contract.",
        "test_screening_production_hardening": "Mock query results/order predate current tenant-scoped screening queries; one AsyncMock side-effect sequence is exhausted.",
        "test_settings_and_billing_comprehensive": "Fixture expects legacy company response name; competing settings route has a different response contract.",
        "test_super_admin_organizations_hr_admin": "SQL-string mock treats any query containing count as aggregation, including User.account_status in a normal User SELECT.",
        "test_super_admin_security_lock": "Mocks target synchronous password verifier and old provisioning call shape rather than current async implementation.",
        "test_super_admin_suite": "Fixture patches missing root seed_super_admin module rather than scripts.seed_super_admin.",
        "test_token_revocation_and_rotation": "Password mock targets obsolete verifier; refresh-token assertion rejects the newly supplied revocation metadata.",
    }
    for suffix, reason in fixtures.items():
        if suffix in module:
            return "test_fixture_or_contract", reason, module.replace(".", "/") + ".py"
    raise ValueError(f"Unclassified baseline failure: {module}::{name}: {message}")


def cases(path):
    return list(ET.parse(path).iter("testcase"))


def status(case):
    return next((tag for tag in ("failure", "error", "skipped") if case.find(tag) is not None), "passed")


def audit_baseline():
    latest_path = EVIDENCE / "suite-snapshot-20261117" / "results.xml"
    latest = {(c.get("classname"), c.get("name")): status(c) for c in cases(latest_path)} if latest_path.exists() else {}
    rows = []
    for case in cases(BASELINE):
        module, name = case.get("classname"), case.get("name")
        for phase in ("failure", "error"):
            for node in case.findall(phase):
                message = node.get("message", "")
                category, reason, reference = classify(module, name, message)
                rows.append(dict(test=f"{module}::{name}", original_outcome=phase, category=category,
                                 root_cause=reason, source_reference=reference,
                                 snapshot_result=latest.get((module, name), "not_yet_reported"), original_message=message))
    assert len(rows) == 209
    assert Counter(r["original_outcome"] for r in rows) == {"failure": 202, "error": 7}
    with (EVIDENCE / "original-209-classification.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {"baseline": {"passed": 951, "failed": 202, "errors": 7, "skipped": 22},
               "categories": dict(Counter(r["category"] for r in rows)),
               "snapshot_outcomes_for_original_209": dict(Counter(r["snapshot_result"] for r in rows)),
               "note": "Category records the original failure cause, not a pass or release waiver; subsequent independent defects can still fail the same test."}
    (EVIDENCE / "original-209-classification-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def audit_financial():
    directory = EVIDENCE / "stress-10000-isolated-20261116" / "financial"
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    totals, scenarios = Counter(), Counter()
    fingerprints = {}
    count = 0
    with (directory / "results.jsonl").open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            assert row["gross_paise"] - row["deductions_paise"] == row["net_paise"]
            assert row["net_paise"] == row["payment_amount_paise"]
            assert row["variance_paise"] == row["settlement_adjustment_paise"] == 0
            assert row["code_sha256"] == summary["code_sha256"]
            for key in ("gross_paise", "deductions_paise", "net_paise", "payment_amount_paise"):
                totals[key] += row[key]
            fingerprint = tuple(row[k] for k in ("gross_paise", "deductions_paise", "net_paise", "payment_amount_paise"))
            if row["scenario"] in fingerprints:
                assert fingerprints[row["scenario"]] == fingerprint
            fingerprints[row["scenario"]] = fingerprint
            scenarios[row["scenario"]] += 1
            count += 1
    assert count == 20000 and len(scenarios) == 10000 and set(scenarios.values()) == {2}
    assert not (directory / "failures.jsonl").read_text(encoding="utf-8").strip()
    assert sum(r["gross_paise"] for r in summary["annual_ctc_result"]["monthly_runs"]) == 10000007
    files = ("app/services/payroll/run_service.py", "app/services/payroll/statutory_service.py", "app/services/payroll/money.py")
    source = ROOT / "scratch" / "payroll-verification-20261115" / "source-20261117-a"
    snapshot_digest = hashlib.sha256(b"".join((source / p).read_bytes() for p in files)).hexdigest()
    result = {"seed": summary["seed"], "logical_scenarios": len(scenarios), "evaluations": count,
              "repeats": 2, "all_rows_reconciled": True, "totals_both_repeats_paise": dict(totals),
              "payroll_variance_paise": 0, "payment_variance_paise": 0, "annual_ctc_paise": 10000007,
              "annual_ctc_variance_paise": 0, "stress_code_sha256": summary["code_sha256"],
              "snapshot_payroll_code_sha256": snapshot_digest, "snapshot_matches_tested_payroll_code": snapshot_digest == summary["code_sha256"],
              "files_sha256": {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                               for name in ("inputs.jsonl", "results.jsonl", "summary.json", "failures.jsonl")}}
    (EVIDENCE / "financial-independent-reconciliation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps({"baseline": audit_baseline(), "financial": audit_financial()}, indent=2))
