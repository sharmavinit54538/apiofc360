import asyncio
import sys
from pathlib import Path

REPO_ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, REPO_ROOT)

from app.db.database import AsyncSessionLocal, engine
from sqlalchemy import text

async def check():
    print(f"DATABASE HOST: {engine.url.host}")
    print(f"DATABASE NAME: {engine.url.database}")
    print(f"DATABASE PORT: {engine.url.port}")
    
    target_email = "sharmavinit7348@gmail.com"
    
    async with AsyncSessionLocal() as session:
        # Check users columns
        sample_u = await session.execute(text("SELECT * FROM users LIMIT 1"))
        u_cols = list(sample_u.keys())
        print(f"\nUsers table columns: {u_cols}")
        
        # Check exact match in users
        print(f"\n--- Checking 'users' table for: {target_email} ---")
        u = await session.execute(text("SELECT * FROM users WHERE LOWER(email) = LOWER(:email)"), {"email": target_email})
        rows = u.fetchall()
        if rows:
            print(f"FOUND in users table ({len(rows)} record(s)):")
            for r in rows:
                print(dict(zip(u_cols, r)))
        else:
            print(f"NOT FOUND in users table with exact email: {target_email}")
            
        # Check similar emails in users table
        print("\n--- Checking 'users' table for similar emails (%sharma% / %vinit% / %7348%) ---")
        similar_u = await session.execute(text("SELECT id, email, role, is_active FROM users WHERE email ILIKE '%sharma%' OR email ILIKE '%vinit%' OR email ILIKE '%7348%'"))
        similar_rows = similar_u.fetchall()
        if similar_rows:
            print(f"Similar users found ({len(similar_rows)}):")
            for r in similar_rows:
                print(dict(zip(["id", "email", "role", "is_active"], r)))
        else:
            print("No similar users found.")

        # Check all users in DB
        all_u = await session.execute(text("SELECT id, email, role, is_active FROM users"))
        all_users = all_u.fetchall()
        print(f"\nAll registered users in DB ({len(all_users)}):")
        for r in all_users:
            print(f"  - Email: {r[1]} | Role: {r[2]} | Active: {r[3]} | ID: {r[0]}")

        # Check employees columns & records
        sample_e = await session.execute(text("SELECT * FROM employees LIMIT 1"))
        e_cols = list(sample_e.keys())
        print(f"\nEmployees table columns: {e_cols}")
        
        print(f"\n--- Checking 'employees' table for: {target_email} or similar ---")
        e = await session.execute(text("SELECT id, user_id, first_name, last_name, company_email, personal_email FROM employees WHERE company_email ILIKE '%sharma%' OR personal_email ILIKE '%sharma%' OR company_email ILIKE '%vinit%' OR personal_email ILIKE '%vinit%' OR company_email ILIKE '%7348%' OR personal_email ILIKE '%7348%'"))
        erows = e.fetchall()
        if erows:
            print(f"FOUND matching employee(s) ({len(erows)}):")
            for r in erows:
                print(dict(zip(["id", "user_id", "first_name", "last_name", "company_email", "personal_email"], r)))
        else:
            print("No matching employees found.")

if __name__ == "__main__":
    asyncio.run(check())
