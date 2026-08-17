import asyncio
import os
import sys
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.database import AsyncSessionLocal

async def audit_calls_schema():
    print("=== CONNECT CALLS SCHEMA & DB AUDIT ===")
    try:
        async with AsyncSessionLocal() as session:
            # 1. DB Info
            r = await session.execute(text("SELECT current_database(), current_user, inet_server_addr()::text, version();"))
            db_info = r.fetchone()
            print(f"Connected DB: {db_info[0]} as {db_info[1]} | Server: {db_info[2]}")

            # 2. Check alembic version
            try:
                r = await session.execute(text("SELECT version_num FROM alembic_version;"))
                print(f"Alembic Version: {[row[0] for row in r.fetchall()]}")
            except Exception as e:
                print(f"Alembic version error: {e}")

            # 3. Check connect_call_logs columns
            r = await session.execute(text("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'connect_call_logs'
                ORDER BY ordinal_position;
            """))
            cols = r.fetchall()
            print(f"\nconnect_call_logs columns ({len(cols)} found):")
            for col in cols:
                print(f"  - {col[0]}: {col[1]} (nullable={col[2]}, default={col[3]})")

            # 4. Check connect_user_sound_settings columns
            r = await session.execute(text("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'connect_user_sound_settings'
                ORDER BY ordinal_position;
            """))
            cols = r.fetchall()
            print(f"\nconnect_user_sound_settings columns ({len(cols)} found):")
            for col in cols:
                print(f"  - {col[0]}: {col[1]} (nullable={col[2]}, default={col[3]})")

            # 5. Check connect_notifications columns
            r = await session.execute(text("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'connect_notifications'
                ORDER BY ordinal_position;
            """))
            cols = r.fetchall()
            print(f"\nconnect_notifications columns ({len(cols)} found):")
            for col in cols:
                print(f"  - {col[0]}: {col[1]} (nullable={col[2]}, default={col[3]})")

            # 6. Check connect_user_presence columns
            r = await session.execute(text("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'connect_user_presence'
                ORDER BY ordinal_position;
            """))
            cols = r.fetchall()
            print(f"\nconnect_user_presence columns ({len(cols)} found):")
            for col in cols:
                print(f"  - {col[0]}: {col[1]} (nullable={col[2]}, default={col[3]})")

    except Exception as exc:
        print(f"Database connection error: {exc}")

if __name__ == "__main__":
    asyncio.run(audit_calls_schema())
