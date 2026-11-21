"""Regression tests for platform-owner mutations in the Super Admin API."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api import super_admin


@pytest.mark.asyncio
async def test_generic_console_cannot_create_another_platform_owner():
    with pytest.raises(HTTPException) as error:
        await super_admin.create_super_admin_user({"name": "Owner", "email": "owner@example.com", "role": "super_admin"})
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_generic_console_cannot_modify_platform_owner():
    owner = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        email="superadmin@ofc360.com",
        role="super_admin",
        is_deleted=False,
    )
    db = AsyncMock()
    db.get.return_value = owner

    with pytest.raises(HTTPException) as error:
        await super_admin.update_super_admin_user(str(owner.id), {"name": "Changed"}, db)

    assert error.value.status_code == 403
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_generic_console_rejects_placeholder_credentials(monkeypatch):
    db = AsyncMock()
    query_result = MagicMock()
    query_result.scalars.return_value.first.return_value = None
    db.execute.return_value = query_result
    company_id = "00000000-0000-0000-0000-000000000010"
    with pytest.raises(HTTPException) as error:
        await super_admin.create_super_admin_user(
            {
                "name": "Tenant Admin",
                "email": "admin@example.com",
                "role": "hr_admin",
                "phone": "9876543210",
                "companyId": company_id,
            },
            db,
        )

    assert error.value.status_code == 422
    db.execute.assert_awaited_once()
    db.commit.assert_not_awaited()
