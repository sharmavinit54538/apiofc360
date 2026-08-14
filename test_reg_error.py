import asyncio
import traceback
import sys
import os

sys.path.insert(0, os.getcwd())

from app.db.database import AsyncSessionLocal
from sqlalchemy import text
from app.services.auth_service import AuthService
from app.repositories.auth_repository import AuthRepository
from app.services.email_service import EmailService
from app.services.token_service import TokenService
from app.schemas.auth import RegisterRequest

async def inspect():
    async with AsyncSessionLocal() as session:
        print("--- USERS TABLE COLUMNS ---")
        res = await session.execute(text("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'users'
            ORDER BY ordinal_position;
        """))
        for row in res.fetchall():
            print(dict(row._mapping))

        print("\n--- USERS CONSTRAINTS ---")
        res = await session.execute(text("""
            SELECT conname, contype, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'users'::regclass;
        """))
        for row in res.fetchall():
            print(dict(row._mapping))

        print("\n--- USERS INDEXES ---")
        res = await session.execute(text("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = 'users';
        """))
        for row in res.fetchall():
            print(dict(row._mapping))

        print("\n--- ALEMBIC VERSION ---")
        try:
            res = await session.execute(text("SELECT version_num FROM alembic_version;"))
            print(res.fetchall())
        except Exception as e:
            print("Alembic version error:", e)

async def test_register():
    print("\n--- TESTING REGISTER CALL ---")
    payload_data = {
        "first_name": "vinit",
        "last_name": "sharma",
        "name": "vinit sharma",
        "full_name": "vinit sharma",
        "company_name": "EquinoxSphere",
        "email": "sharmavinit7348@gmail.com",
        "password": "StrongPassword@123",
        "phone": "9351608590"
    }
    
    try:
        req = RegisterRequest.model_validate(payload_data)
        print("Validated payload:", req.model_dump())
    except Exception as e:
        print("Pydantic validation failed:")
        traceback.print_exc()
        return

    async with AsyncSessionLocal() as session:
        auth_repo = AuthRepository(session)
        email_svc = EmailService()
        token_svc = TokenService(session=session, auth_repository=auth_repo)
        auth_svc = AuthService(
            session=session,
            auth_repository=auth_repo,
            email_service=email_svc,
            token_service=token_svc,
        )
        try:
            await auth_svc.register_user(req)
            print("Register succeeded!")
        except Exception as e:
            print("Register threw exception:")
            traceback.print_exc()

async def main():
    await inspect()
    await test_register()

if __name__ == "__main__":
    asyncio.run(main())
