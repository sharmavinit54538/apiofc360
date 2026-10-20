import asyncio
from app.db.database import get_asyncpg_connection

async def diagnose():
    conn = await get_asyncpg_connection()
    try:
        # 1. Alembic version
        ver = await conn.fetch("SELECT * FROM alembic_version")
        print("=== ALEMBIC VERSION ===")
        for r in ver:
            print(dict(r))

        # 2. Check payroll_periods columns
        pp_cols = await conn.fetch("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'payroll_periods'
            ORDER BY ordinal_position
        """)
        print(f"\n=== PAYROLL_PERIODS COLUMNS ({len(pp_cols)}) ===")
        for r in pp_cols:
            print(r['column_name'], r['data_type'], "NULLABLE" if r['is_nullable'] == 'YES' else "NOT NULL")

        # 3. Check constraints on payroll_periods
        pp_cons = await conn.fetch("""
            SELECT conname, contype, pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            WHERE t.relname = 'payroll_periods'
        """)
        print("\n=== PAYROLL_PERIODS CONSTRAINTS ===")
        for r in pp_cons:
            print(dict(r))

        # 4. Check pay_cycles table
        pc_exists = await conn.fetchval("SELECT to_regclass('public.pay_cycles')")
        print(f"\n=== PAY_CYCLES EXISTS: {pc_exists} ===")
        if pc_exists:
            pc_count = await conn.fetchval("SELECT COUNT(*) FROM pay_cycles")
            print(f"Total pay_cycles rows: {pc_count}")
            pc_dups = await conn.fetch("""
                SELECT company_id, period_month, period_year, COUNT(*) as cnt
                FROM pay_cycles
                GROUP BY company_id, period_month, period_year
                HAVING COUNT(*) > 1
            """)
            print(f"Duplicate (company_id, period_month, period_year) in pay_cycles: {len(pc_dups)}")
            for r in pc_dups[:10]:
                print(dict(r))

            null_check = await conn.fetch("""
                SELECT 
                    COUNT(*) FILTER (WHERE company_id IS NULL) as null_company,
                    COUNT(*) FILTER (WHERE period_month IS NULL) as null_month,
                    COUNT(*) FILTER (WHERE period_year IS NULL) as null_year
                FROM pay_cycles
            """)
            print("Null checks in pay_cycles:", [dict(r) for r in null_check])

        # 5. Check payroll_periods rows
        pp_exists = await conn.fetchval("SELECT to_regclass('public.payroll_periods')")
        if pp_exists:
            pp_count = await conn.fetchval("SELECT COUNT(*) FROM payroll_periods")
            print(f"\nTotal payroll_periods rows: {pp_count}")
            pp_dups = await conn.fetch("""
                SELECT company_id, period_month, period_year, COUNT(*) as cnt
                FROM payroll_periods
                GROUP BY company_id, period_month, period_year
                HAVING COUNT(*) > 1
            """)
            print(f"Duplicate (company_id, period_month, period_year) in payroll_periods: {len(pp_dups)}")
            for r in pp_dups[:10]:
                print(dict(r))

        # 6. Check if pc.id exists in payroll_periods
        if pc_exists and pp_exists:
            overlap = await conn.fetchval("""
                SELECT COUNT(*) FROM pay_cycles pc
                JOIN payroll_periods pp ON pc.id = pp.id
            """)
            print(f"Overlapping IDs between pay_cycles and payroll_periods: {overlap}")

            comb_overlap = await conn.fetchval("""
                SELECT COUNT(*) FROM pay_cycles pc
                JOIN payroll_periods pp ON pc.company_id = pp.company_id 
                    AND pc.period_month = pp.period_month 
                    AND pc.period_year = pp.period_year
            """)
            print(f"Overlapping (company_id, month, year) between pay_cycles and payroll_periods: {comb_overlap}")

        # 7. Check ai_messages columns
        ai_cols = await conn.fetch("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'ai_messages'
        """)
        print("\n=== AI_MESSAGES COLUMNS ===")
        for r in ai_cols:
            print(r['column_name'], r['data_type'])

    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(diagnose())
