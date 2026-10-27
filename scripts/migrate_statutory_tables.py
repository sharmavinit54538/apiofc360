import asyncio
from sqlalchemy import text
from app.db.database import engine

async def run_migration():
    async with engine.begin() as conn:
        res = await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'payroll_periods'"))
        cols = [r[0] for r in res.fetchall()]
        print("Existing columns in payroll_periods:", cols)
        for col_name, col_type in [
            ("processing_date", "DATE"),
            ("payment_date", "DATE"),
            ("is_locked", "BOOLEAN DEFAULT FALSE"),
            ("locked_by", "UUID"),
            ("locked_at", "TIMESTAMP WITH TIME ZONE"),
        ]:
            if col_name not in cols:
                print(f"Adding column to payroll_periods: {col_name}")
        await conn.execute(text("ALTER TABLE payroll_compliance_due_dates ALTER COLUMN compliance_id DROP NOT NULL"))
        await conn.execute(text("ALTER TABLE payroll_compliance_challans ALTER COLUMN compliance_id DROP NOT NULL"))

        print("Ensuring payroll_compliance_challans columns...")
        challan_cols = [
            ("company_id", "UUID REFERENCES companies(id) ON DELETE CASCADE"),
            ("period_id", "UUID REFERENCES payroll_periods(id) ON DELETE SET NULL"),
            ("compliance_id", "UUID"),
            ("challan_type", "VARCHAR(50) NOT NULL DEFAULT 'EPFO_ECR'"),
            ("period_month", "INTEGER NOT NULL DEFAULT 1"),
            ("period_year", "INTEGER NOT NULL DEFAULT 2026"),
            ("total_amount", "NUMERIC(14, 2) NOT NULL DEFAULT 0"),
            ("employee_count", "INTEGER NOT NULL DEFAULT 0"),
            ("trrn_number", "VARCHAR(100)"),
            ("challan_generation_date", "DATE"),
            ("payment_date", "DATE"),
            ("utr_number", "VARCHAR(100)"),
            ("challan_file_path", "VARCHAR(500)"),
            ("challan_file_url", "VARCHAR(500)"),
            ("payment_receipt_path", "VARCHAR(500)"),
            ("payment_receipt_url", "VARCHAR(500)"),
            ("epf_employee_amount", "NUMERIC(14, 2) NOT NULL DEFAULT 0"),
            ("epf_employer_amount", "NUMERIC(14, 2) NOT NULL DEFAULT 0"),
            ("eps_amount", "NUMERIC(14, 2) NOT NULL DEFAULT 0"),
            ("edli_amount", "NUMERIC(14, 2) NOT NULL DEFAULT 0"),
            ("admin_charges", "NUMERIC(14, 2) NOT NULL DEFAULT 0"),
            ("status", "VARCHAR(30) NOT NULL DEFAULT 'GENERATED'"),
            ("file_payload", "TEXT"),
            ("created_at", "TIMESTAMP WITH TIME ZONE DEFAULT NOW()"),
            ("updated_at", "TIMESTAMP WITH TIME ZONE DEFAULT NOW()"),
        ]
        for cname, ctype in challan_cols:
            await conn.execute(text(f"ALTER TABLE payroll_compliance_challans ADD COLUMN IF NOT EXISTS {cname} {ctype}"))

        print("Ensuring payroll_compliance_due_dates columns...")
        due_cols = [
            ("company_id", "UUID REFERENCES companies(id) ON DELETE CASCADE"),
            ("compliance_id", "UUID"),
            ("challan_id", "UUID REFERENCES payroll_compliance_challans(id) ON DELETE SET NULL"),
            ("period_id", "UUID REFERENCES payroll_periods(id) ON DELETE SET NULL"),
            ("title", "VARCHAR(100) NOT NULL DEFAULT 'EPFO PF Monthly Remittance'"),
            ("due_date", "DATE NOT NULL DEFAULT '2026-06-15'"),
            ("period", "VARCHAR(50) NOT NULL DEFAULT 'May 2026'"),
            ("period_month", "INTEGER NOT NULL DEFAULT 1"),
            ("period_year", "INTEGER NOT NULL DEFAULT 2026"),
            ("status", "VARCHAR(30) NOT NULL DEFAULT 'PENDING'"),
            ("challan_number", "VARCHAR(100)"),
            ("trrn_number", "VARCHAR(100)"),
            ("payment_date", "DATE"),
            ("utr_number", "VARCHAR(100)"),
            ("amount_paid", "NUMERIC(14, 2)"),
            ("is_overdue", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("overdue_days", "INTEGER NOT NULL DEFAULT 0"),
            ("interest_7q_amount", "NUMERIC(14, 2) NOT NULL DEFAULT 0"),
            ("damages_14b_amount", "NUMERIC(14, 2) NOT NULL DEFAULT 0"),
            ("created_at", "TIMESTAMP WITH TIME ZONE DEFAULT NOW()"),
            ("updated_at", "TIMESTAMP WITH TIME ZONE DEFAULT NOW()"),
        ]
        for cname, ctype in due_cols:
            await conn.execute(text(f"ALTER TABLE payroll_compliance_due_dates ADD COLUMN IF NOT EXISTS {cname} {ctype}"))


        emp_cols_res = await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'employees'"))
        emp_cols = [r[0] for r in emp_cols_res.fetchall()]
        print("Checking employee columns...")
        for col_name, col_type in [
            ("is_pf_eligible", "BOOLEAN DEFAULT TRUE"),
            ("is_international_worker", "BOOLEAN DEFAULT FALSE"),
            ("pf_wage_ceiling_applicable", "BOOLEAN DEFAULT TRUE"),
        ]:
            if col_name not in emp_cols:
                print(f"Adding column to employees: {col_name}")
                await conn.execute(text(f"ALTER TABLE employees ADD COLUMN IF NOT EXISTS {col_name} {col_type}"))

        print("Migration complete!")

if __name__ == "__main__":
    asyncio.run(run_migration())
