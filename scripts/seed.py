"""
Development seed script.

Usage:
    python -m scripts.seed

Creates one demo school/tenant and one user per role. Passwords come from
environment variables (see .env.example) — never hardcode credentials for
anything beyond local development.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.school import School  # noqa: E402
from app.models.user import User  # noqa: E402

SCHOOL_CODE = "EDU001"
SCHOOL_NAME = "EduFlow Demo School"

SEED_USERS = [
    ("School Admin", "admin@eduflow.demo", "admin", settings.SEED_ADMIN_PASSWORD),
    ("Demo Teacher", "teacher@eduflow.demo", "teacher", settings.SEED_TEACHER_PASSWORD),
    ("Demo Student", "student@eduflow.demo", "student", settings.SEED_STUDENT_PASSWORD),
    ("Demo Parent", "parent@eduflow.demo", "parent", settings.SEED_PARENT_PASSWORD),
    ("Demo Accountant", "accountant@eduflow.demo", "accountant", settings.SEED_ACCOUNTANT_PASSWORD),
]


async def seed():
    async with AsyncSessionLocal() as db:
        school = (await db.execute(select(School).where(School.school_code == SCHOOL_CODE))).scalar_one_or_none()
        if not school:
            school = School(school_code=SCHOOL_CODE, school_name=SCHOOL_NAME, status="active")
            db.add(school)
            await db.flush()
            print(f"Created school: {SCHOOL_NAME} ({SCHOOL_CODE})")
        else:
            print(f"School already exists: {SCHOOL_NAME} ({SCHOOL_CODE})")

        for name, email, role, password in SEED_USERS:
            existing = (await db.execute(select(User).where(User.tenant_id == school.id, User.email == email))).scalar_one_or_none()
            if existing:
                print(f"  - {role}: {email} (already exists)")
                continue
            db.add(User(tenant_id=school.id, school_id=school.id, name=name, email=email, role=role, password_hash=hash_password(password), status="active"))
            print(f"  - {role}: {email} / {password}")

        await db.commit()
    print("\nSeed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
