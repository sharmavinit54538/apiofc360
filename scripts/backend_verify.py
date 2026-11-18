"""Isolated backend verification; never uses configured application credentials."""
from pathlib import Path
import asyncio
import json
import sys
import payroll_disposable_pg as harness

harness.STATE = Path(__file__).resolve().parents[1] / "scratch" / "backend-verification-20261118"
harness.PORT = 55443
harness.DATABASES = ("payroll_verify_backend", "payroll_verify_backend_suite")

if __name__ == "__main__":
    if sys.argv[1:] == ["start-and-provision"]:
        harness.execute([harness.BIN / "pg_ctl.exe", "-D", harness.STATE / "pgdata",
                         "-l", harness.STATE / "postgres.log", "-w", "start"])
        asyncio.run(harness.provision(json.loads((harness.STATE / "credentials.json").read_text())))
        raise SystemExit(0)
    raise SystemExit(harness.main())
