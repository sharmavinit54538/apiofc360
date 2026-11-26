"""Read-only database integrity, encryption key audit, and safe manager-to-employee sync CLI.

Usage:
    python scripts/audit_and_sync_employees.py --dry-run
    python scripts/audit_and_sync_employees.py --apply-sync --confirm-backup [--company-id <UUID>]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.field_encryption import (  # noqa: E402
    FieldEncryptionError,
    configured_key_ids,
    validate_encryption_configuration,
)
from app.db.database import AsyncSessionLocal, engine  # noqa: E402
from app.repositories.auth_repository import AuthRepository  # noqa: E402
from app.repositories.employee_repository import EmployeeRepository  # noqa: E402
from app.services.email_service import EmailService  # noqa: E402
from app.services.employee_service import EmployeeService  # noqa: E402


def _mask_email(value: str | None) -> str | None:
    if not value:
        return None
    local, sep, domain = value.partition("@")
    if not sep:
        return "***"
    return (local[:1] + "***" if len(local) > 1 else "***") + "@" + domain


async def run_audit() -> dict[str, Any]:
    """Execute a non-destructive read-only integrity, encryption, and manager-sync audit."""
    enc_summary: dict[str, Any]
    configured_ids: set[str] = set()
    try:
        enc_summary = validate_encryption_configuration()
        configured_ids = set(configured_key_ids())
    except FieldEncryptionError as exc:
        enc_summary = {"configured": False, "error": str(exc), "active_key_id": None, "retained_key_ids": []}

    async with AsyncSessionLocal() as session:
        counts_row = (
            await session.execute(
                text(
                    """
                    SELECT
                        COUNT(*) AS total_employees,
                        COUNT(*) FILTER (WHERE COALESCE(is_deleted, false) = false) AS active_employees,
                        COUNT(*) FILTER (WHERE COALESCE(is_deleted, false) = true) AS soft_deleted_employees,
                        COUNT(*) FILTER (WHERE company_id IS NULL) AS null_company_employees
                    FROM employees
                    """
                ).execution_options(tenant_safe=True)
            )
        ).mappings().one()

        integrity_row = (
            await session.execute(
                text(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM employees e LEFT JOIN companies c ON e.company_id = c.id WHERE e.company_id IS NOT NULL AND c.id IS NULL) AS invalid_company_fk,
                        (SELECT COUNT(*) FROM employees e LEFT JOIN users u ON e.user_id = u.id WHERE e.user_id IS NOT NULL AND u.id IS NULL) AS invalid_user_fk,
                        (SELECT COUNT(*) FROM employees e LEFT JOIN departments d ON e.department_id = d.id WHERE e.department_id IS NOT NULL AND d.id IS NULL) AS invalid_dept_fk,
                        (SELECT COUNT(*) FROM employees e LEFT JOIN employees m ON e.reporting_manager_id = m.id WHERE e.reporting_manager_id IS NOT NULL AND m.id IS NULL) AS invalid_manager_fk,
                        (SELECT COUNT(*) FROM employees WHERE reporting_manager_id IS NOT NULL AND reporting_manager_id = id) AS self_reporting_manager,
                        (SELECT COUNT(*) FROM employees e JOIN employees m ON e.reporting_manager_id = m.id WHERE e.company_id IS DISTINCT FROM m.company_id) AS cross_company_reporting_manager,
                        (SELECT COUNT(*) FROM (SELECT user_id FROM employees WHERE user_id IS NOT NULL GROUP BY user_id HAVING COUNT(*) > 1) s) AS dup_user_id_employees,
                        (SELECT COUNT(*) FROM (SELECT LOWER(BTRIM(personal_email)) AS norm_email FROM employees GROUP BY LOWER(BTRIM(personal_email)) HAVING COUNT(*) > 1) s) AS dup_personal_email_ci,
                        (SELECT COUNT(*) FROM employees WHERE personal_email IS NOT NULL AND personal_email <> LOWER(BTRIM(personal_email))) AS non_lowercase_personal_email
                    """
                ).execution_options(tenant_safe=True)
            )
        ).mappings().one()

        blind_row = (
            await session.execute(
                text(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE aadhaar_number IS NOT NULL AND (aadhaar_number_blind_idx IS NULL OR aadhaar_number_blind_idx = '')) AS missing_aadhaar_bidx,
                        COUNT(*) FILTER (WHERE pan_number IS NOT NULL AND (pan_number_blind_idx IS NULL OR pan_number_blind_idx = '')) AS missing_pan_bidx,
                        COUNT(*) FILTER (WHERE uan_number IS NOT NULL AND (uan_number_blind_idx IS NULL OR uan_number_blind_idx = '')) AS missing_uan_bidx,
                        COUNT(*) FILTER (WHERE passport_number IS NOT NULL AND (passport_number_blind_idx IS NULL OR passport_number_blind_idx = '')) AS missing_passport_bidx,
                        COUNT(*) FILTER (WHERE voter_id IS NOT NULL AND (voter_id_blind_idx IS NULL OR voter_id_blind_idx = '')) AS missing_voter_bidx
                    FROM employees
                    """
                ).execution_options(tenant_safe=True)
            )
        ).mappings().one()

        key_usage: dict[str, dict[str, int]] = {}
        missing_key_ids: set[str] = set()
        for tbl, cols in (
            ("employees", ("aadhaar_number", "pan_number", "uan_number", "passport_number", "voter_id")),
            ("employee_bank_accounts", ("account_number", "ifsc_code")),
        ):
            for col in cols:
                res = await session.execute(
                    text(
                        f"SELECT split_part({col}, ':', 3) AS key_id, COUNT(*) AS cnt "
                        f"FROM {tbl} WHERE {col} LIKE 'ofc360:v1:%' "
                        f"GROUP BY split_part({col}, ':', 3)"
                    ).execution_options(tenant_safe=True)
                )
                for row in res.fetchall():
                    key_id, cnt = row[0], int(row[1])
                    if not key_id:
                        continue
                    bucket = key_usage.setdefault(key_id, {"fields": 0, "configured": int(key_id in configured_ids)})
                    bucket["fields"] += cnt
                    if key_id not in configured_ids:
                        missing_key_ids.add(key_id)

        mgr_rows = (
            await session.execute(
                text(
                    """
                    SELECT
                        m.id,
                        m.company_id,
                        m.personal_email,
                        (SELECT e.id FROM employees e WHERE e.company_id = m.company_id AND (e.id = m.id OR LOWER(BTRIM(e.personal_email)) = LOWER(BTRIM(m.personal_email)) OR (m.user_id IS NOT NULL AND e.user_id = m.user_id)) LIMIT 1) AS same_company_emp_id,
                        (SELECT e.company_id FROM employees e WHERE LOWER(BTRIM(e.personal_email)) = LOWER(BTRIM(m.personal_email)) AND e.company_id IS DISTINCT FROM m.company_id LIMIT 1) AS conflict_company_id
                    FROM managers m
                    WHERE COALESCE(m.is_deleted, false) = false
                      AND UPPER(COALESCE(m.status, '')) IN ('ACTIVE', 'INVITED', 'INVITATION_SENT', 'CREATED')
                    ORDER BY m.company_id, m.id
                    """
                ).execution_options(tenant_safe=True)
            )
        ).mappings().all()

    already_synced = 0
    syncable: list[dict[str, Any]] = []
    cross_company_conflicts: list[dict[str, Any]] = []
    for mgr in mgr_rows:
        if mgr["same_company_emp_id"] is not None:
            already_synced += 1
        elif mgr["conflict_company_id"] is not None:
            cross_company_conflicts.append(
                {
                    "manager_id": str(mgr["id"]),
                    "manager_company_id": str(mgr["company_id"]),
                    "conflict_employee_company_id": str(mgr["conflict_company_id"]),
                    "email": _mask_email(mgr["personal_email"]),
                }
            )
        else:
            syncable.append(
                {
                    "manager_id": str(mgr["id"]),
                    "company_id": str(mgr["company_id"]),
                    "email": _mask_email(mgr["personal_email"]),
                }
            )

    return {
        "encryption": enc_summary,
        "encrypted_field_key_ids": key_usage,
        "missing_key_ids": sorted(missing_key_ids),
        "employee_counts": {k: int(v) for k, v in counts_row.items()},
        "integrity_checks": {k: int(v) for k, v in integrity_row.items()},
        "missing_blind_indexes": {k: int(v) for k, v in blind_row.items()},
        "manager_sync": {
            "total_eligible_managers": len(mgr_rows),
            "already_synced": already_synced,
            "pending_safe_sync": len(syncable),
            "cross_company_conflicts": len(cross_company_conflicts),
            "syncable_items": syncable,
            "conflict_items": cross_company_conflicts,
        },
    }


async def run_sync(*, company_id: uuid.UUID | None) -> dict[str, Any]:
    """Run idempotent transactional manager-to-employee synchronization."""
    async with AsyncSessionLocal() as session:
        if company_id is not None:
            company_ids = [company_id]
        else:
            rows = (
                await session.execute(
                    text("SELECT DISTINCT company_id FROM managers WHERE company_id IS NOT NULL AND COALESCE(is_deleted, false) = false")
                    .execution_options(tenant_safe=True)
                )
            ).fetchall()
            company_ids = [row[0] for row in rows if row[0] is not None]

    total_created = 0
    total_updated = 0
    total_skipped = 0
    per_company: dict[str, dict[str, int]] = {}
    email_service = EmailService()
    for cid in company_ids:
        async with AsyncSessionLocal() as session:
            service = EmployeeService(
                session=session,
                employee_repository=EmployeeRepository(session),
                auth_repository=AuthRepository(session),
                email_service=email_service,
            )
            stats = await service.sync_managers_to_employees(cid)
            total_created += int(stats.get("created", 0))
            total_updated += int(stats.get("updated", 0))
            total_skipped += int(stats.get("skipped_conflicts", 0))
            per_company[str(cid)] = stats
    return {
        "companies_processed": len(company_ids),
        "employees_created": total_created,
        "employees_updated": total_updated,
        "skipped_conflicts": total_skipped,
        "per_company": per_company,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description="Audit encryption/DB integrity and safely sync managers to employees.")
    parser.add_argument("--dry-run", action="store_true", help="Read-only audit (default when --apply-sync is omitted).")
    parser.add_argument("--apply-sync", action="store_true", help="Synchronize missing manager employee records.")
    parser.add_argument("--company-id", type=str, default=None, help="Optional single company UUID for --apply-sync.")
    parser.add_argument("--confirm-backup", action="store_true", help="Required acknowledgement before --apply-sync mutates rows.")
    args = parser.parse_args()

    try:
        report = await run_audit()
        if args.apply_sync and not args.dry_run:
            if not args.confirm_backup:
                raise SystemExit("Refusing to mutate database without --confirm-backup.")
            cid = uuid.UUID(args.company_id) if args.company_id else None
            report["sync_applied"] = await run_sync(company_id=cid)
            report["post_sync_audit"] = await run_audit()
        else:
            report["dry_run"] = True

        print(json.dumps(report, indent=2))
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
