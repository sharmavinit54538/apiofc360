import asyncio
import os
import sys
import uuid
import pytest
from decimal import Decimal
from pydantic import ValidationError

sys.path.insert(0, os.getcwd())

from app.schemas.employee.create import EmployeeCreate
from app.schemas.employee.update import EmployeeUpdate
from app.main import create_app
import httpx
from httpx import ASGITransport
from sqlalchemy import select
from app.db.database import AsyncSessionLocal
from app.models.user import User
from app.models.company import Company
from app.core.security import create_access_token


def test_individual_field_exceeds_ctc():
    """hra > ctc should raise ValidationError."""
    try:
        EmployeeUpdate(ctc=Decimal("190000"), hra=Decimal("300000"))
        assert False, "Should have raised ValidationError"
    except ValidationError as e:
        err_msg = str(e)
        print("Caught expected ValidationError for hra > ctc:\n", err_msg)
        assert "hra (300000) cannot exceed ctc (190000)" in err_msg


def test_combined_breakup_exceeds_ctc():
    """basic_salary + hra + bonus > ctc * 1.01 should raise ValidationError."""
    try:
        EmployeeUpdate(
            ctc=Decimal("100000"),
            basic_salary=Decimal("60000"),
            hra=Decimal("30000"),
            bonus=Decimal("20000"),
        )
        assert False, "Should have raised ValidationError"
    except ValidationError as e:
        err_msg = str(e)
        print("Caught expected ValidationError for combined breakup:\n", err_msg)
        assert "basic_salary + hra + bonus exceeds ctc" in err_msg


def test_null_ctc_skips_validation():
    """When ctc is None, non-null hra should not trigger validation error."""
    update = EmployeeUpdate(ctc=None, hra=Decimal("300000"))
    assert update.hra == Decimal("300000")
    assert update.ctc is None


def test_valid_salary_breakup():
    """Valid salary breakup within ctc should pass."""
    update = EmployeeUpdate(
        ctc=Decimal("7200000"),
        basic_salary=Decimal("3600000"),
        hra=Decimal("1800000"),
        bonus=Decimal("1000000"),
        pf=Decimal("432000"),
        esi=Decimal("0"),
        professional_tax=Decimal("2500"),
    )
    assert update.ctc == Decimal("7200000")


async def test_api_endpoint_returns_422_on_invalid_salary():
    """Submitting hra=300000, ctc=190000 to PATCH /api/v1/employees/{id} must return 422 Unprocessable Entity."""
    app = create_app()

    async with AsyncSessionLocal() as session:
        comp_res = await session.execute(select(Company))
        comp = comp_res.scalars().first()
        user_res = await session.execute(select(User).where(User.company_id == comp.id))
        admin_user = user_res.scalars().first()
        if not admin_user:
            admin_user = User(
                id=uuid.uuid4(),
                email="admin_test_sal@ofc360.com",
                hashed_password="pwd",
                role="ADMIN",
                company_id=comp.id,
            )
            session.add(admin_user)
            await session.commit()
            await session.refresh(admin_user)

        token = create_access_token(
            subject=str(admin_user.id),
            claims={"type": "access", "role": admin_user.role, "company_id": str(comp.id)},
        )

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    target_id = "e7f1f422-2dab-40a1-8101-16102b9c2e65"

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        invalid_payload = {
            "ctc": 190000,
            "hra": 300000,
        }
        res = await client.patch(f"/api/v1/employees/{target_id}", json=invalid_payload, headers=headers)
        print(f"PATCH API Response status: {res.status_code}")
        print(f"PATCH API Response body: {res.json()}")
        assert res.status_code == 422, f"Expected 422 validation error, got {res.status_code}"
        detail = str(res.json())
        assert "hra (300000) cannot exceed ctc (190000)" in detail or "hra" in detail


def run_all_tests():
    print("--- Running Schema Unit Tests ---")
    test_individual_field_exceeds_ctc()
    test_combined_breakup_exceeds_ctc()
    test_null_ctc_skips_validation()
    test_valid_salary_breakup()
    print("--- Schema Unit Tests Passed! ---")

    print("\n--- Running API Integration Test ---")
    asyncio.run(test_api_endpoint_returns_422_on_invalid_salary())
    print("--- API Integration Test Passed! ---")


if __name__ == "__main__":
    run_all_tests()
