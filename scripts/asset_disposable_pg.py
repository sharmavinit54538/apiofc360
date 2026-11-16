"""Asset verification in a dedicated loopback-only PostgreSQL cluster.

Uses the existing PostgreSQL verification runner; never loads .env credentials.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import payroll_disposable_pg as runner

runner.STATE = runner.ROOT / "scratch" / "asset-verification-20261116"
runner.PORT = 55442
runner.DATABASES = ("asset_verify_suite", "asset_verify_migration", "asset_verify_regression")
original_environment = runner.environment


def environment(database):
    env = original_environment(database)
    env["ASSET_TEST_DISPOSABLE"] = "1"
    return env


runner.environment = environment

if __name__ == "__main__":
    raise SystemExit(runner.main())
