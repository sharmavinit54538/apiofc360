import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.core.security import hash_password
from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.models.school import School
from app.models.user import User

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False}, poolclass=__import__("sqlalchemy").pool.StaticPool)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_sessionmaker(engine):
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    db_session.AsyncSessionLocal = maker  # patch module-level session factory used by get_db

    async def override_get_db():
        async with maker() as s:
            yield s

    app.dependency_overrides[db_session.get_db] = override_get_db
    yield maker
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(db_sessionmaker):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def seeded_school(db_sessionmaker):
    async with db_sessionmaker() as db:
        school = School(school_code="SCH001", school_name="Test School", status="active")
        db.add(school)
        await db.flush()
        admin = User(tenant_id=school.id, school_id=school.id, name="Admin", email="admin@test.com", role="admin", password_hash=hash_password("Password@123"), status="active")
        db.add(admin)
        await db.commit()
        return {"school_id": school.id, "school_code": school.school_code, "admin_email": admin.email}


@pytest_asyncio.fixture
async def second_school(db_sessionmaker):
    async with db_sessionmaker() as db:
        school = School(school_code="SCH002", school_name="Second School", status="active")
        db.add(school)
        await db.flush()
        admin = User(tenant_id=school.id, school_id=school.id, name="Admin2", email="admin2@test.com", role="admin", password_hash=hash_password("Password@123"), status="active")
        db.add(admin)
        await db.commit()
        return {"school_id": school.id, "school_code": school.school_code, "admin_email": admin.email}


async def login(client: AsyncClient, school_code: str, email: str, password: str = "Password@123") -> str:
    r = await client.post("/api/v1/auth/login", json={"school_code": school_code, "email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]
