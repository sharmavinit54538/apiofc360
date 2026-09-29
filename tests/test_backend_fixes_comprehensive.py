"""
Comprehensive Tests for Backend Fixes:
- Issue 1: POST & GET /api/v1/onboarding/company, validation & error handling
- Issue 2: Registration does not auto-create 3 departments and default leave policies
- Issue 3: Asset cross-tenant isolation (list, get, update return 404/exclude cross-tenant assets)
- Issue 4: _resolve_admin_context does not silently auto-create "% Organization" when company_id is missing
"""

from __future__ import annotations
import secrets
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.main import app
from app.models.asset import Asset
from app.models.company import Company
from app.models.department import Department
from app.models.employee import Employee
from app.models.employee_leave_policy import EmployeeLeavePolicy
from app.models.user import User
from app.utils.jwt import create_access_token


@pytest.fixture
def unique_suffix():
    return secrets.token_hex(4)


async def register_and_login_admin(client: AsyncClient, suffix: str, comp_prefix: str = "TestCorp") -> tuple[dict, str, uuid.UUID]:
    """Helper to register, verify, login an HR Admin, and return (credentials, token, company_id)."""
    rand_phone = f"97{secrets.randbelow(90000000) + 10000000}"
    company_name = f"{comp_prefix} {suffix}"
    letters = "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(6)).capitalize()
    admin_data = {
        "name": f"Admin {letters}",
        "email": f"hr_{suffix}@testcorp.com",
        "phone": rand_phone,
        "password": "SecurePassword@123",
        "company_name": company_name,
    }

    reg_resp = await client.post("/api/v1/auth/register", json=admin_data)
    assert reg_resp.status_code == 201, f"Registration failed: {reg_resp.text}"

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == admin_data["email"]))).scalar_one()
        user.is_verified = True
        user.is_active = True
        user.account_status = "ACTIVE"
        await db.commit()
        company_id = user.company_id

    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": admin_data["email"], "password": admin_data["password"]},
    )
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    token_data = login_resp.json()
    token = token_data.get("access_token") or (token_data.get("data") or {}).get("access_token")
    return admin_data, token, company_id


# ==============================================================================
# Issue 1: POST /api/v1/onboarding/company & GET validation
# ==============================================================================

@pytest.mark.asyncio
async def test_issue_1_onboarding_company_post_get_and_length_validation(unique_suffix):
    """Test Issue 1: POST onboarding company succeeds with 200, GET returns same name, length > 100 returns 422."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        _, token, comp_id = await register_and_login_admin(client, unique_suffix)
        headers = {"Authorization": f"Bearer {token}"}

        # 1. POST valid payload
        new_company_name = f"Updated Enterprise {unique_suffix}"
        post_payload = {
            "company_name": new_company_name,
            "company_logo": None,
            "industry": "Technology",
            "company_size": "1–10",
            "country": "India",
            "city": "Bengaluru",
            "state": "Karnataka",
            "timezone": "Asia/Kolkata",
            "currency": "INR",
        }

        post_resp = await client.post("/api/v1/onboarding/company", json=post_payload, headers=headers)
        assert post_resp.status_code == 200, f"POST /onboarding/company failed: {post_resp.text}"
        post_json = post_resp.json()
        assert post_json.get("success") is True

        # 2. GET returns same name
        get_resp = await client.get("/api/v1/onboarding/company", headers=headers)
        assert get_resp.status_code == 200, f"GET /onboarding/company failed: {get_resp.text}"
        get_json = get_resp.json()
        org_data = get_json.get("data") or {}
        assert (org_data.get("company_name") or org_data.get("name")) == new_company_name

        # 3. POST with company_name > 100 characters must return 422
        long_name = "X" * 105
        invalid_payload = dict(post_payload)
        invalid_payload["company_name"] = long_name
        invalid_resp = await client.post("/api/v1/onboarding/company", json=invalid_payload, headers=headers)
        assert invalid_resp.status_code == 422, f"Expected 422 for name > 100, got: {invalid_resp.status_code}"


# ==============================================================================
# Issue 2: Register does NOT auto-create 3 departments and default leave policies
# ==============================================================================

@pytest.mark.asyncio
async def test_issue_2_register_no_autocreated_departments_or_leave_policies(unique_suffix):
    """Test Issue 2: Registering a user does NOT create default departments or leave policies."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        _, _, comp_id = await register_and_login_admin(client, unique_suffix)

    async with AsyncSessionLocal() as db:
        # Check departments
        dept_res = await db.execute(select(Department).where(Department.company_id == comp_id))
        departments = dept_res.scalars().all()
        assert len(departments) == 0, f"Expected 0 auto-created departments, found: {[d.department_name for d in departments]}"

        # Check default leave policies for company's employee
        emp_res = await db.execute(select(Employee).where(Employee.company_id == comp_id))
        emp = emp_res.scalar_one_or_none()
        assert emp is not None, "Registered admin employee not found."

        leave_res = await db.execute(select(EmployeeLeavePolicy).where(EmployeeLeavePolicy.employee_id == emp.id))
        leave_policies = leave_res.scalars().all()
        assert len(leave_policies) == 0, f"Expected 0 auto-created leave policies, found: {len(leave_policies)}"


# ==============================================================================
# Issue 3: Cross-tenant Asset Leakage Prevention
# ==============================================================================

@pytest.mark.asyncio
async def test_issue_3_asset_cross_tenant_isolation(unique_suffix):
    """Test Issue 3: Company A's assets are NOT visible to Company B's HR admin in list, get, and update."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Setup Company A and Company B
        _, token_a, comp_id_a = await register_and_login_admin(client, f"a_{unique_suffix}", "CompanyA")
        _, token_b, comp_id_b = await register_and_login_admin(client, f"b_{unique_suffix}", "CompanyB")

        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # 1. Company A creates an asset
        tag_a = f"ASSET-A-{unique_suffix}"
        create_payload = {
            "tag": tag_a,
            "name": f"Dell Precision {unique_suffix}",
            "category": "laptop",
            "brand": "Dell",
            "model": "5570",
        }
        create_resp = await client.post("/api/v1/assets", json=create_payload, headers=headers_a)
        assert create_resp.status_code == 201, f"Failed to create asset: {create_resp.text}"
        asset_a_data = create_resp.json()["data"]
        asset_a_id = asset_a_data["id"]

        # Verify asset was created with company_id == comp_id_a
        async with AsyncSessionLocal() as db:
            db_asset = await db.get(Asset, uuid.UUID(asset_a_id))
            assert db_asset is not None
            assert db_asset.company_id == comp_id_a

        # 2. Company B lists assets -> Asset A must NOT appear
        list_resp_b = await client.get("/api/v1/assets", headers=headers_b)
        assert list_resp_b.status_code == 200
        items_b = list_resp_b.json()["data"]["items"]
        b_tags = [item["tag"] for item in items_b]
        assert tag_a not in b_tags, f"Leak detected! Asset {tag_a} of Company A visible to Company B."

        # 3. Company B gets Asset A by UUID -> must return 404
        get_resp_b = await client.get(f"/api/v1/assets/{asset_a_id}", headers=headers_b)
        assert get_resp_b.status_code == 404, f"Expected 404 when Company B accesses Company A's asset, got: {get_resp_b.status_code}"

        # 4. Company B tries to update Asset A -> must return 404
        update_resp_b = await client.put(
            f"/api/v1/assets/{asset_a_id}",
            json={"name": "Hacked Asset Name"},
            headers=headers_b
        )
        assert update_resp_b.status_code == 404, f"Expected 404 when Company B modifies Company A's asset, got: {update_resp_b.status_code}"

        # 5. Core modules misc list_assets also isolates
        misc_resp_b = await client.get("/api/v1/core/assets", headers=headers_b)
        if misc_resp_b.status_code == 200:
            misc_items = misc_resp_b.json().get("data", [])
            misc_tags = [item["tag"] for item in misc_items]
            assert tag_a not in misc_tags


# ==============================================================================
# Issue 4: _resolve_admin_context does NOT auto-create "% Organization"
# ==============================================================================

@pytest.mark.asyncio
async def test_issue_4_no_silent_organization_creation_when_company_id_missing(unique_suffix):
    """Test Issue 4: Missing company_id returns 400 error and does NOT silently provision '% Organization'."""
    transport = ASGITransport(app=app)

    async with AsyncSessionLocal() as db:
        # Create an orphan user with NO company_id
        orphan_user_id = uuid.uuid4()
        orphan_email = f"orphan_{unique_suffix}@example.com"
        orphan_letters = "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(6)).capitalize()
        orphan_name = f"Ghost Admin {orphan_letters}"
        orphan_user = User(
            id=orphan_user_id,
            email=orphan_email,
            password_hash="dummy_hash",
            name=orphan_name,
            role="hr_admin",
            company_id=None,
            is_active=True,
            is_verified=True,
            account_status="ACTIVE",
        )
        db.add(orphan_user)
        await db.commit()

    # Generate token with NO company_id
    token_without_comp = create_access_token(
        data={"sub": str(orphan_user_id), "role": "hr_admin", "company_id": None}
    )

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get(
            "/api/v1/onboarding/company",
            headers={"Authorization": f"Bearer {token_without_comp}"}
        )
        # Must return 400 Bad Request
        assert resp.status_code == 400, f"Expected 400 for user with no company_id, got: {resp.status_code}, {resp.text}"

    # Verify NO Company named '% Organization' was created
    async with AsyncSessionLocal() as db:
        ghost_comp_name = f"{orphan_name} Organization"
        check_comp = await db.execute(select(Company).where(Company.name == ghost_comp_name))
        assert check_comp.scalar_one_or_none() is None, "Silent auto-provision created a company!"
