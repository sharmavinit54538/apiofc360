"""Run feature-audit checks in a private PostgreSQL cluster, never the app DB."""
from pathlib import Path
import payroll_disposable_pg as harness

harness.STATE = Path(__file__).resolve().parents[1] / "scratch" / "audit-verification-20261122"
harness.PORT = 55444
harness.DATABASES = (
    "payroll_verify_audit", "payroll_verify_billing",
    "payroll_verify_attendance", "payroll_verify_auth",
)

if __name__ == "__main__":
    raise SystemExit(harness.main())
