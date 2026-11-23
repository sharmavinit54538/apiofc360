"""Real PostgreSQL + signed JWT integration fixtures for the expense workflow.

Only an explicitly selected loopback test database is accepted. Each test uses
its own disposable schema; no application connection or authentication is mocked.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from jose import jwt
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.base import Base, tenant_id_ctx
from app.db.database import get_db_session
import app.models  # noqa: F401 - load all referenced ORM mappings
from app.models.company import Company
from app.models.employee import Employee
from app.models.user import User
from app.utils.jwt import _get_algorithm, _get_signing_key


@dataclass
class Identity:
    user: User
    employee: Employee | None

    def headers(self, permissions=None, **overrides):
        now = datetime.now(timezone.utc)
        role = getattr(self.user.role, "value", self.user.role)
        payload = {
            "sub": str(self.user.id), "role": role, "type": "access",
            "company_id": str(self.user.company_id) if self.user.company_id else None,
            "email": self.user.email,
            "iat": int(now.timestamp()), "exp": int((now + timedelta(minutes=10)).timestamp()),
            "jti": str(uuid.uuid4()),
        }
        if permissions is not None:
            payload["permissions"] = permissions
        payload.update(overrides)
        token = jwt.encode(payload, _get_signing_key(), algorithm=_get_algorithm())
        return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def expense_db():
    raw_url = os.getenv("EXPENSES_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("Set EXPENSES_TEST_DATABASE_URL to an isolated local PostgreSQL test database")
    url = make_url(raw_url)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or not (url.database or "").startswith("ofc360_expenses_test")
    ):
        pytest.fail("Expense tests require a loopback PostgreSQL database named ofc360_expenses_test*")
    schema = f"expense_test_{uuid.uuid4().hex}"
    admin = create_async_engine(raw_url)
    async with admin.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(raw_url, connect_args={"server_settings": {"search_path": schema}})
    wanted = {
        "companies", "users", "employees", "managers", "reimbursement_claims",
        "payroll_audit_logs", "security_roles", "security_permissions", "role_permissions",
    }
    todo = list(wanted)
    while todo:
        for fk in Base.metadata.tables[todo.pop()].foreign_keys:
            if fk.column.table.name not in wanted:
                wanted.add(fk.column.table.name)
                todo.append(fk.column.table.name)
    tables = [table for table in Base.metadata.sorted_tables if table.name in wanted]
    token = tenant_id_ctx.set(None)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield factory
    finally:
        tenant_id_ctx.reset(token)
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


@pytest_asyncio.fixture
async def actors(expense_db):
    async with expense_db() as db:
        alpha = Company(id=uuid.uuid4(), name="Expense test organization A", status="ACTIVE")
        beta = Company(id=uuid.uuid4(), name="Expense test organization B", status="ACTIVE")
        db.add_all([alpha, beta])
        await db.flush()

        async def actor(name, role="employee", company=alpha, manager=None, employee=True):
            suffix = uuid.uuid4().hex[:12]
            user = User(
                id=uuid.uuid4(), company_id=company.id if company else None,
                name=name, email=f"{suffix}@expense-test.example", phone=str(uuid.uuid4().int)[:10],
                password_hash="integration-only-no-login", role=role, is_active=True,
                is_verified=True, account_status="ACTIVE",
            )
            db.add(user)
            await db.flush()
            profile = None
            if employee:
                profile = Employee(
                    id=uuid.uuid4(), company_id=company.id, user_id=user.id,
                    employee_id=f"ET-{suffix}", first_name=name, last_name="Test",
                    personal_email=user.email, phone=user.phone, department="Engineering",
                    designation="Engineer", joining_date=date(2025, 1, 1),
                    status="ACTIVE", is_active=True, is_deleted=False, employment_status="ACTIVE",
                    manager_id=manager.employee.id if manager else None,
                )
                db.add(profile)
                await db.flush()
            return Identity(user, profile)

        manager = await actor("Manager", "manager")
        result = {
            "company": alpha, "other_company": beta,
            "manager": manager,
            "employee": await actor("Employee", manager=manager),
            "peer": await actor("Peer", manager=manager),
            "outsider": await actor("Outside team"),
            "foreign": await actor("Other tenant", company=beta),
            "hr": await actor("HR", "hr_admin"),
            "finance": await actor("Finance", "hr_admin", employee=False),
            "it": await actor("IT", "it_admin"),
            "executive": await actor("Executive", "executive"),
            "super": await actor("Platform", "super_admin", company=None, employee=False),
            "no_employee": await actor("No employee profile", employee=False),
        }
        await db.commit()
        return result


@pytest_asyncio.fixture
async def api(expense_db, actors):
    from app.main import app

    async def test_session():
        async with expense_db() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_db_session] = test_session
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.fixture
def expense_payload():
    return {
        "category": "travel", "amount": "2500.00", "currency": "INR",
        "expense_date": "2026-11-10", "description": "Client meeting travel",
        "merchant": "Uber", "receipt_url": None, "project_id": None,
    }
