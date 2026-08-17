"""OFC360 — Production Database Read-Only Schema Inspection Script.

This script executes ONLY non-destructive, read-only SELECT queries against
the configured PostgreSQL database to determine live schema state before any
Alembic migration is applied.

Usage on Live Server:
    cd /path/to/apiofc360
    python scripts/verify_live_db_schema.py
"""
import asyncio
import json
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.db.database import AsyncSessionLocal


async def run_live_audit():
    report = {
        "server_identity": {},
        "alembic_version": None,
        "refresh_tokens_drift": {},
        "security_tables_drift": {},
        "user_role_enum": [],
        "indexes": [],
        "foreign_keys": [],
        "unique_constraints": [],
        "data_conflict_checks": {},
    }

    async with AsyncSessionLocal() as session:
        # ── 1. Database Server Identity (To distinguish live server from local) ──
        try:
            r = await session.execute(text("""
                SELECT 
                    current_database() as database_name,
                    current_user as connected_user,
                    inet_server_addr()::text as server_ip,
                    inet_server_port() as server_port,
                    version() as pg_version;
            """))
            row = r.mappings().first()
            if row:
                report["server_identity"] = dict(row)
        except Exception as exc:
            report["server_identity"]["error"] = str(exc)

        # ── 2. Current Alembic Version ──────────────────────────────────────
        try:
            r = await session.execute(text("SELECT version_num FROM alembic_version;"))
            report["alembic_version"] = [row[0] for row in r.fetchall()]
        except Exception as exc:
            report["alembic_version"] = f"TABLE NOT FOUND / ERROR: {exc}"

        # ── 3. Check Refresh Token Columns (Target drift columns) ────────────
        try:
            r = await session.execute(text("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'refresh_tokens'
                  AND column_name IN ('family_id', 'parent_token_hash', 'revoked_reason')
                ORDER BY column_name;
            """))
            target_cols = [dict(row) for row in r.mappings().fetchall()]
            
            # Check all columns in refresh_tokens
            r_all = await session.execute(text("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'refresh_tokens'
                ORDER BY ordinal_position;
            """))
            all_cols = [dict(row) for row in r_all.mappings().fetchall()]
            
            report["refresh_tokens_drift"] = {
                "target_columns_present": target_cols,
                "missing_from_db": [
                    c for c in ['family_id', 'parent_token_hash', 'revoked_reason']
                    if c not in [tc['column_name'] for tc in target_cols]
                ],
                "all_existing_columns": all_cols,
            }
        except Exception as exc:
            report["refresh_tokens_drift"]["error"] = str(exc)

        # ── 4. Check Active Security Tables ─────────────────────────────────
        try:
            target_tables = [
                'security_roles',
                'security_policies',
                'user_sessions',
                'ip_whitelist',
                'security_audit_logs',
            ]
            r = await session.execute(text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN ('security_roles', 'security_policies', 'user_sessions', 'ip_whitelist', 'security_audit_logs')
                ORDER BY table_name;
            """))
            existing = [row[0] for row in r.fetchall()]
            report["security_tables_drift"] = {
                "existing_in_db": existing,
                "missing_from_db": [t for t in target_tables if t not in existing],
            }
        except Exception as exc:
            report["security_tables_drift"]["error"] = str(exc)

        # ── 5. Check user_role Enum Values in PostgreSQL ────────────────────
        try:
            r = await session.execute(text("""
                SELECT enumlabel
                FROM pg_enum
                JOIN pg_type ON pg_enum.enumtypid = pg_type.oid
                WHERE typname = 'user_role'
                ORDER BY enumsortorder;
            """))
            report["user_role_enum"] = [row[0] for row in r.fetchall()]
        except Exception as exc:
            report["user_role_enum"] = f"ENUM NOT FOUND / ERROR: {exc}"

        # ── 6. Indexes on Auth & Target Security Tables ──────────────────────
        try:
            r = await session.execute(text("""
                SELECT tablename, indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND tablename IN ('refresh_tokens', 'security_roles', 'security_policies', 'user_sessions', 'ip_whitelist', 'security_audit_logs', 'users')
                ORDER BY tablename, indexname;
            """))
            report["indexes"] = [dict(row) for row in r.mappings().fetchall()]
        except Exception as exc:
            report["indexes"] = str(exc)

        # ── 7. Foreign Keys on Target Tables ────────────────────────────────
        try:
            r = await session.execute(text("""
                SELECT
                    tc.table_name, 
                    kcu.column_name, 
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name,
                    rc.delete_rule
                FROM information_schema.table_constraints AS tc 
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                  AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage AS ccu
                  ON ccu.constraint_name = tc.constraint_name
                  AND ccu.table_schema = tc.table_schema
                JOIN information_schema.referential_constraints AS rc
                  ON rc.constraint_name = tc.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = 'public'
                  AND tc.table_name IN ('refresh_tokens', 'security_roles', 'security_policies', 'user_sessions', 'ip_whitelist', 'security_audit_logs')
                ORDER BY tc.table_name, kcu.column_name;
            """))
            report["foreign_keys"] = [dict(row) for row in r.mappings().fetchall()]
        except Exception as exc:
            report["foreign_keys"] = str(exc)

        # ── 8. Unique Constraints on Target Tables ──────────────────────────
        try:
            r = await session.execute(text("""
                SELECT tc.table_name, kcu.column_name, tc.constraint_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                  AND tc.table_schema = kcu.table_schema
                WHERE tc.constraint_type = 'UNIQUE'
                  AND tc.table_schema = 'public'
                  AND tc.table_name IN ('refresh_tokens', 'security_roles', 'security_policies', 'user_sessions', 'ip_whitelist', 'security_audit_logs', 'users')
                ORDER BY tc.table_name, kcu.column_name;
            """))
            report["unique_constraints"] = [dict(row) for row in r.mappings().fetchall()]
        except Exception as exc:
            report["unique_constraints"] = str(exc)

        # ── 9. Data Conflict Checks ─────────────────────────────────────────
        # 9a. Total rows in refresh_tokens
        try:
            r = await session.execute(text("SELECT COUNT(*) FROM refresh_tokens;"))
            report["data_conflict_checks"]["refresh_tokens_row_count"] = r.scalar()
        except Exception as exc:
            report["data_conflict_checks"]["refresh_tokens_row_count"] = str(exc)

        # 9b. Existing security_roles rows (check for duplicate role_code)
        if "security_roles" in report.get("security_tables_drift", {}).get("existing_in_db", []):
            try:
                r = await session.execute(text("""
                    SELECT role_code, COUNT(*) 
                    FROM security_roles 
                    GROUP BY role_code 
                    HAVING COUNT(*) > 1;
                """))
                report["data_conflict_checks"]["duplicate_role_codes"] = [dict(row) for row in r.mappings().fetchall()]
            except Exception as exc:
                report["data_conflict_checks"]["duplicate_role_codes"] = str(exc)

        # 9c. User role distribution in DB
        try:
            r = await session.execute(text("SELECT role::text, COUNT(*) FROM users GROUP BY role ORDER BY count DESC;"))
            report["data_conflict_checks"]["users_by_role"] = [dict(row) for row in r.mappings().fetchall()]
        except Exception as exc:
            report["data_conflict_checks"]["users_by_role"] = str(exc)

    # ── Output Report ────────────────────────────────────────────────────────
    print("=" * 80)
    print("OFC360 LIVE DATABASE READ-ONLY INSPECTION REPORT")
    print("=" * 80)
    print(json.dumps(report, indent=2, default=str))
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_live_audit())
