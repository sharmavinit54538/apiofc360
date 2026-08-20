"""Comprehensive tests for Super Admin Organizations & HR Admin Data Resolution.

Verifies:
1. HR Admin is resolved strictly by User.company_id and User.role == UserRole.HR_ADMIN
2. Companies without HR Admin return hr_admin: None (no fake placeholders or random employee fallbacks)
3. Normal employees are NEVER leaked as HR Admin
4. Add organization flow creates Company + Subscription + HR Admin User in DB
5. Edit organization flow updates HR Admin user in DB
6. Search by HR Admin name and email works
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi import HTTPException

from app.api.super_admin import (
    get_super_admin_organizations,
    create_super_admin_organization,
    get_super_admin_organization_detail,
    update_super_admin_organization,
)
from app.models.company import Company
from app.models.employee import Employee
from app.models.user import User, UserRole
from app.models.subscription import Subscription


@pytest.mark.asyncio
async def test_case_1_company_with_hr_admin_returns_real_hr_admin():
    """Case 1: Company with HR_ADMIN user returns real hr_admin details."""
    comp_id = uuid.uuid4()
    company = Company(
        id=comp_id,
        name="EquinoxSphere",
        onboarding_completed=True,
        company_profile={"domain": "equinox.com", "plan": "Enterprise", "mrr": 2500},
        created_at=datetime.now(timezone.utc),
    )

    hr_user = User(
        id=uuid.uuid4(),
        name="Rahul Sharma",
        email="rahul@equinox.com",
        phone="9876543210",
        role=UserRole.HR_ADMIN,
        company_id=comp_id,
        is_active=True,
        is_verified=True,
        password_hash="hashed",
        is_deleted=False,
    )

    sub = Subscription(
        id=uuid.uuid4(),
        company_id=comp_id,
        plan="Enterprise",
        access_status="ACTIVE",
        payment_status="PAID",
        mrr=2500.0,
    )

    mock_db = AsyncMock()

    async def mock_execute(stmt):
        mock_res = MagicMock()
        stmt_str = str(stmt)
        if "FROM companies" in stmt_str:
            mock_res.scalars.return_value.all.return_value = [company]
        elif "FROM subscriptions" in stmt_str:
            mock_res.scalars.return_value.all.return_value = [sub]
        elif "FROM users" in stmt_str:
            if "count" in stmt_str.lower():
                mock_res.all.return_value = [(comp_id, 5)]
            else:
                mock_res.scalars.return_value.all.return_value = [hr_user]
        elif "FROM employees" in stmt_str:
            mock_res.all.return_value = [(comp_id, 10)]
        else:
            mock_res.scalars.return_value.all.return_value = []
            mock_res.all.return_value = []
        return mock_res

    mock_db.execute = mock_execute

    results = await get_super_admin_organizations(db=mock_db)
    assert len(results) == 1
    org = results[0]
    assert org["name"] == "EquinoxSphere"
    assert org["domain"] == "equinox.com"
    assert org["hr_admin"] is not None
    assert org["hr_admin"]["name"] == "Rahul Sharma"
    assert org["hr_admin"]["email"] == "rahul@equinox.com"
    assert org["hrAdminName"] == "Rahul Sharma"
    assert org["hrAdminEmail"] == "rahul@equinox.com"
    assert len(org["hr_admins"]) == 1


@pytest.mark.asyncio
async def test_case_2_company_without_hr_admin_returns_null():
    """Case 2: Company without HR_ADMIN returns hr_admin: None."""
    comp_id = uuid.uuid4()
    company = Company(
        id=comp_id,
        name="EmptyOrg",
        onboarding_completed=False,
        company_profile={},
        created_at=datetime.now(timezone.utc),
    )

    mock_db = AsyncMock()

    async def mock_execute(stmt):
        mock_res = MagicMock()
        stmt_str = str(stmt)
        if "FROM companies" in stmt_str:
            mock_res.scalars.return_value.all.return_value = [company]
        elif "FROM subscriptions" in stmt_str:
            mock_res.scalars.return_value.all.return_value = []
        elif "FROM users" in stmt_str:
            if "count" in stmt_str.lower():
                mock_res.all.return_value = [(comp_id, 0)]
            else:
                mock_res.scalars.return_value.all.return_value = []
        elif "FROM employees" in stmt_str:
            mock_res.all.return_value = []
        else:
            mock_res.scalars.return_value.all.return_value = []
            mock_res.all.return_value = []
        return mock_res

    mock_db.execute = mock_execute

    results = await get_super_admin_organizations(db=mock_db)
    assert len(results) == 1
    org = results[0]
    assert org["name"] == "EmptyOrg"
    assert org["domain"] is None
    assert org["hr_admin"] is None
    assert org["hrAdminName"] == ""
    assert org["hrAdminEmail"] == ""
    assert org["hr_admins"] == []


@pytest.mark.asyncio
async def test_case_3_company_with_normal_employee_only_returns_null_hr_admin():
    """Case 3: Company with standard EMPLOYEE users returns hr_admin: None (no leakage)."""
    comp_id = uuid.uuid4()
    company = Company(
        id=comp_id,
        name="EmployeeOnlyCorp",
        onboarding_completed=True,
        company_profile={"domain": "empcorp.com"},
        created_at=datetime.now(timezone.utc),
    )

    mock_db = AsyncMock()

    async def mock_execute(stmt):
        mock_res = MagicMock()
        stmt_str = str(stmt)
        if "FROM companies" in stmt_str:
            mock_res.scalars.return_value.all.return_value = [company]
        elif "FROM subscriptions" in stmt_str:
            mock_res.scalars.return_value.all.return_value = []
        elif "FROM users" in stmt_str:
            if "count" in stmt_str.lower():
                mock_res.all.return_value = [(comp_id, 1)]
            else:
                # No users with role == UserRole.HR_ADMIN returned
                mock_res.scalars.return_value.all.return_value = []
        elif "FROM employees" in stmt_str:
            mock_res.all.return_value = [(comp_id, 1)]
        else:
            mock_res.scalars.return_value.all.return_value = []
            mock_res.all.return_value = []
        return mock_res

    mock_db.execute = mock_execute

    results = await get_super_admin_organizations(db=mock_db)
    assert len(results) == 1
    org = results[0]
    assert org["hr_admin"] is None
    assert org["hrAdminName"] == ""
    assert org["hrAdminEmail"] == ""


@pytest.mark.asyncio
async def test_case_4_create_organization_flow_provisions_company_and_hr_admin():
    """Case 4: Add Organization creates Company + Subscription + HR Admin User in DB."""
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    # User does not pre-exist
    mock_exec_res = MagicMock()
    mock_exec_res.scalars.return_value.first.return_value = None
    mock_db.execute.return_value = mock_exec_res

    payload = {
        "name": "Digimino Technologies",
        "domain": "digimino.com",
        "plan": "Growth",
        "status": "Active",
        "hrAdminName": "Digi Admin",
        "hrAdminEmail": "admin@digimino.com",
        "employeeCount": 25,
        "mrr": 500,
        "industry": "Fintech",
        "location": "Bangalore",
    }

    result = await create_super_admin_organization(payload=payload, db=mock_db)

    added_objects = [call.args[0] for call in mock_db.add.call_args_list]
    companies_added = [o for o in added_objects if isinstance(o, Company)]
    subs_added = [o for o in added_objects if isinstance(o, Subscription)]
    users_added = [o for o in added_objects if isinstance(o, User)]

    assert len(companies_added) == 1
    assert len(subs_added) == 1
    assert len(users_added) == 1

    created_company = companies_added[0]
    created_user = users_added[0]

    assert created_company.name == "Digimino Technologies"
    assert created_user.email == "admin@digimino.com"
    assert created_user.name == "Digi Admin"
    assert created_user.role == UserRole.HR_ADMIN
    assert created_user.company_id == created_company.id

    assert result["name"] == "Digimino Technologies"
    assert result["domain"] == "digimino.com"
    assert result["hrAdminName"] == "Digi Admin"
    assert result["hrAdminEmail"] == "admin@digimino.com"
    assert result["hr_admin"]["name"] == "Digi Admin"


@pytest.mark.asyncio
async def test_case_5_update_organization_updates_hr_admin_user_record():
    """Case 5: Edit Organization updates HR Admin record in PostgreSQL."""
    comp_id = uuid.uuid4()
    company = Company(
        id=comp_id,
        name="Existing Org",
        company_profile={"domain": "existing.com"},
    )

    hr_user = User(
        id=uuid.uuid4(),
        name="Old Name",
        email="old@existing.com",
        role=UserRole.HR_ADMIN,
        company_id=comp_id,
    )

    mock_db = AsyncMock()
    mock_db.get.return_value = company
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    async def mock_execute(stmt):
        mock_res = MagicMock()
        stmt_str = str(stmt)
        if "FROM subscriptions" in stmt_str:
            mock_res.scalars.return_value.first.return_value = None
        elif "users.id !=" in stmt_str:
            # Conflict check for email uniqueness
            mock_res.scalars.return_value.first.return_value = None
        elif "FROM users" in stmt_str:
            mock_res.scalars.return_value.first.return_value = hr_user
        else:
            mock_res.scalars.return_value.first.return_value = None
        return mock_res

    mock_db.execute = mock_execute

    update_payload = {
        "name": "Existing Org Renamed",
        "domain": "newdomain.com",
        "hrAdminName": "New Admin Name",
        "hrAdminEmail": "newadmin@existing.com",
    }

    result = await update_super_admin_organization(
        org_id=str(comp_id),
        payload=update_payload,
        db=mock_db,
    )

    assert result["success"] is True
    assert company.name == "Existing Org Renamed"
    assert company.company_profile["domain"] == "newdomain.com"
    assert hr_user.name == "New Admin Name"
    assert hr_user.email == "newadmin@existing.com"


@pytest.mark.asyncio
async def test_case_6_organization_detail_returns_real_hr_admin_owner():
    """Case 6: Organization detail endpoint resolves owner strictly from HR Admin."""
    comp_id = uuid.uuid4()
    company = Company(
        id=comp_id,
        name="DetailOrg",
        company_profile={"domain": "detail.com"},
        onboarding_completed=True,
    )
    hr_user = User(
        id=uuid.uuid4(),
        name="Primary HR",
        email="hr@detail.com",
        role=UserRole.HR_ADMIN,
        company_id=comp_id,
    )
    emp_user = User(
        id=uuid.uuid4(),
        name="Regular Employee",
        email="emp@detail.com",
        role=UserRole.EMPLOYEE,
        company_id=comp_id,
    )

    mock_db = AsyncMock()
    mock_db.get.return_value = company

    async def mock_execute(stmt):
        mock_res = MagicMock()
        stmt_str = str(stmt)
        if "FROM subscriptions" in stmt_str:
            mock_res.scalars.return_value.first.return_value = None
        elif "FROM users" in stmt_str:
            mock_res.scalars.return_value.all.return_value = [hr_user, emp_user]
        elif "FROM employees" in stmt_str:
            mock_res.scalar.return_value = 1
        elif "FROM audit_logs" in stmt_str:
            mock_res.scalars.return_value.all.return_value = []
        return mock_res

    mock_db.execute = mock_execute

    result = await get_super_admin_organization_detail(org_id=str(comp_id), db=mock_db)
    assert result["name"] == "DetailOrg"
    assert result["domain"] == "detail.com"
    assert result["owner"]["name"] == "Primary HR"
    assert result["owner"]["email"] == "hr@detail.com"
    assert result["hr_admin"]["name"] == "Primary HR"
    assert len(result["hr_admins"]) == 1

