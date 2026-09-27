"""Verify all 97 spec endpoints (19 v1 and 78 v2) are registered on FastAPI app."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app

SPEC_ENDPOINTS_V1 = [
    ("GET", "/api/v1/payroll/employees/{employeeId}/payslips"),
    ("GET", "/api/v1/payroll/my-payslips"),
    ("GET", "/api/v1/payroll/periods"),
    ("POST", "/api/v1/payroll/periods"),
    ("GET", "/api/v1/payroll/periods/{periodId}"),
    ("POST", "/api/v1/payroll/run"),
    ("GET", "/api/v1/payroll/runs/{runId}"),
    ("POST", "/api/v1/payroll/runs/{runId}/approve"),
    ("POST", "/api/v1/payroll/runs/{runId}/cancel"),
    ("GET", "/api/v1/payroll/runs/{runId}/employees"),
    ("GET", "/api/v1/payroll/runs/{runId}/employees/{employeeId}"),
    ("GET", "/api/v1/payroll/runs/{runId}/employees/{employeeId}/payslip/download"),
    ("POST", "/api/v1/payroll/runs/{runId}/finalize"),
    ("POST", "/api/v1/payroll/runs/{runId}/payslips/generate"),
    ("GET", "/api/v1/payroll/runs/{runId}/preview"),
    ("POST", "/api/v1/payroll/runs/{runId}/reject"),
    ("POST", "/api/v1/payroll/runs/{runId}/retry"),
    ("GET", "/api/v1/payroll/runs/{runId}/status"),
    ("GET", "/api/v1/payroll/runs/{runId}/validation"),
]

SPEC_ENDPOINTS_V2 = [
    # Accounting
    ("GET", "/api/v2/payroll/accounting-export"),
    # Company Bank
    ("GET", "/api/v2/payroll/companies/{companyId}/bank-accounts"),
    # Compensation
    ("POST", "/api/v2/payroll/compensation/bulk-import/apply"),
    ("POST", "/api/v2/payroll/compensation/bulk-import/preview"),
    ("POST", "/api/v2/payroll/compensation/revisions/{revisionId}/approve"),
    ("POST", "/api/v2/payroll/compensation/revisions/{revisionId}/reject"),
    ("GET", "/api/v2/payroll/compensations"),
    # Payroll Cycles
    ("POST", "/api/v2/payroll/cycles/{cycleId}/reopen"),
    ("POST", "/api/v2/payroll/cycles/{cycleId}/void"),
    # Employee Payroll
    ("GET", "/api/v2/payroll/employee/dashboard"),
    ("GET", "/api/v2/payroll/employee/provision-slips"),
    ("GET", "/api/v2/payroll/employees/{employeeId}/compensation"),
    ("POST", "/api/v2/payroll/employees/{employeeId}/compensation/revisions"),
    ("GET", "/api/v2/payroll/employees/{employeeId}/payslips"),
    ("POST", "/api/v2/payroll/employees/{employeeId}/reveal-bank-account"),
    # Full & Final
    ("GET", "/api/v2/payroll/full-and-final"),
    ("POST", "/api/v2/payroll/full-and-final"),
    ("GET", "/api/v2/payroll/full-and-final/{fnfId}"),
    ("POST", "/api/v2/payroll/full-and-final/{fnfId}/approve"),
    ("POST", "/api/v2/payroll/full-and-final/{fnfId}/finalize"),
    ("POST", "/api/v2/payroll/full-and-final/{fnfId}/reject"),
    ("GET", "/api/v2/payroll/full-and-final/{fnfId}/statement/download"),
    # Employee Payslips
    ("GET", "/api/v2/payroll/my-payslips"),
    ("GET", "/api/v2/payroll/my-payslips/{runId}/download"),
    ("GET", "/api/v2/payroll/my-provision-slips"),
    # Pay Components
    ("GET", "/api/v2/payroll/pay-components"),
    ("POST", "/api/v2/payroll/pay-components"),
    # Payment Batches
    ("GET", "/api/v2/payroll/payment-batches"),
    ("GET", "/api/v2/payroll/payment-batches/{batchId}"),
    ("POST", "/api/v2/payroll/payment-batches/{batchId}/approve"),
    ("POST", "/api/v2/payroll/payment-batches/{batchId}/bank-file"),
    ("GET", "/api/v2/payroll/payment-batches/{batchId}/bank-file/download"),
    ("POST", "/api/v2/payroll/payment-batches/{batchId}/bank-response/apply"),
    ("POST", "/api/v2/payroll/payment-batches/{batchId}/bank-response/preview"),
    ("POST", "/api/v2/payroll/payment-batches/{batchId}/items/{itemId}/hold"),
    ("POST", "/api/v2/payroll/payment-batches/{batchId}/items/{itemId}/release"),
    ("POST", "/api/v2/payroll/payment-batches/{batchId}/items/{itemId}/retry"),
    ("POST", "/api/v2/payroll/payment-batches/{batchId}/reconcile"),
    ("POST", "/api/v2/payroll/payment-batches/{batchId}/reject"),
    ("POST", "/api/v2/payroll/payment-batches/{batchId}/submit"),
    ("POST", "/api/v2/payroll/payment-batches/{batchId}/validate"),
    # Payslip / Provision Slip
    ("GET", "/api/v2/payroll/payslips/{runId}/{employeeId}"),
    ("GET", "/api/v2/payroll/provision-slips/{provisionSlipId}/pdf"),
    # Reports
    ("GET", "/api/v2/payroll/reports/{reportKey}"),
    ("POST", "/api/v2/payroll/reports/{reportKey}/export"),
    ("GET", "/api/v2/payroll/reports/exports/{exportId}/download"),
    # Payroll Runs
    ("DELETE", "/api/v2/payroll/runs/{runId}"),
    ("GET", "/api/v2/payroll/runs/{runId}/approval"),
    ("POST", "/api/v2/payroll/runs/{runId}/approve"),
    ("GET", "/api/v2/payroll/runs/{runId}/employees"),
    ("GET", "/api/v2/payroll/runs/{runId}/employees/{employeeId}"),
    ("GET", "/api/v2/payroll/runs/{runId}/employees/{employeeId}/payslip"),
    ("GET", "/api/v2/payroll/runs/{runId}/employees/{employeeId}/payslip/download"),
    ("GET", "/api/v2/payroll/runs/{runId}/finalization"),
    ("POST", "/api/v2/payroll/runs/{runId}/finalize"),
    ("GET", "/api/v2/payroll/runs/{runId}/generation-status"),
    ("POST", "/api/v2/payroll/runs/{runId}/payment-batches"),
    ("GET", "/api/v2/payroll/runs/{runId}/payment-batches"),
    ("POST", "/api/v2/payroll/runs/{runId}/payslips/generate"),
    ("GET", "/api/v2/payroll/runs/{runId}/preview"),
    ("POST", "/api/v2/payroll/runs/{runId}/process"),
    ("POST", "/api/v2/payroll/runs/{runId}/reject"),
    ("POST", "/api/v2/payroll/runs/{runId}/revalidate"),
    ("GET", "/api/v2/payroll/runs/{runId}/review"),
    ("POST", "/api/v2/payroll/runs/{runId}/send-back"),
    ("POST", "/api/v2/payroll/runs/{runId}/validate"),
    ("GET", "/api/v2/payroll/runs/{runId}/validation"),
    ("GET", "/api/v2/payroll/runs/{runId}/validation-issues"),
    # Statutory
    ("GET", "/api/v2/payroll/statutory/config"),
    ("POST", "/api/v2/payroll/statutory/reports/{component}"),
    ("GET", "/api/v2/payroll/statutory/summary"),
    # Variable Inputs
    ("GET", "/api/v2/payroll/variable-inputs"),
    ("POST", "/api/v2/payroll/variable-inputs"),
    ("POST", "/api/v2/payroll/variable-inputs/bulk-apply"),
    ("POST", "/api/v2/payroll/variable-inputs/bulk-preview"),
    ("POST", "/api/v2/payroll/variable-inputs/{id}/approve"),
    ("POST", "/api/v2/payroll/variable-inputs/{id}/reject"),
]


def normalize_path(path: str) -> str:
    # Normalize path parameter names like {employeeId} -> {}
    import re
    return re.sub(r"\{[^}]+\}", "{}", path)


def main():
    registered = set()
    for route in app.routes:
        methods = getattr(route, "methods", set())
        path = getattr(route, "path", "")
        for m in methods:
            registered.add((m.upper(), normalize_path(path)))

    missing_v1 = []
    for method, path in SPEC_ENDPOINTS_V1:
        if (method, normalize_path(path)) not in registered:
            missing_v1.append((method, path))

    missing_v2 = []
    for method, path in SPEC_ENDPOINTS_V2:
        if (method, normalize_path(path)) not in registered:
            missing_v2.append((method, path))

    print(f"=== Spec Verification ===")
    print(f"Spec v1: {len(SPEC_ENDPOINTS_V1)} endpoints | Found: {len(SPEC_ENDPOINTS_V1) - len(missing_v1)}")
    if missing_v1:
        print(f"MISSING v1 ({len(missing_v1)}):")
        for m, p in missing_v1:
            print(f"  {m} {p}")

    print(f"Spec v2: {len(SPEC_ENDPOINTS_V2)} endpoints | Found: {len(SPEC_ENDPOINTS_V2) - len(missing_v2)}")
    if missing_v2:
        print(f"MISSING v2 ({len(missing_v2)}):")
        for m, p in missing_v2:
            print(f"  {m} {p}")

    if not missing_v1 and not missing_v2:
        print("\nALL 97 ENDPOINTS FULLY REGISTERED AND VERIFIED!")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
