"""Tests for Super Admin platform monitoring, RBAC, and seed CLI."""

from unittest.mock import AsyncMock, MagicMock
import uuid

from fastapi import HTTPException
import pytest

from app.core.rbac import require_super_admin, ROLE_SUPER_ADMIN, ROLE_HR_ADMIN, ROLE_EMPLOYEE
from app.models.user import User, UserRole, UserAccountStatus
from seed_super_admin import seed_super_admin


@pytest.mark.asyncio
async def test_require_super_admin_rbac():
    """Test RBAC dependency strictly permits super_admin with superadmin@ofc360.com and rejects other roles/emails."""
    # Allowed
    claims_super = {"sub": str(uuid.uuid4()), "role": "super_admin", "email": "superadmin@ofc360.com"}
    assert await require_super_admin(claims_super) == claims_super

    # Rejected emails
    claims_wrong_email = {"sub": str(uuid.uuid4()), "role": "super_admin", "email": "hacker@test.com"}
    with pytest.raises(HTTPException) as exc_info:
        await require_super_admin(claims_wrong_email)
    assert exc_info.value.status_code == 403

    # Rejected roles
    for role in ["hr_admin", "employee", "manager", "executive", "it_admin", "guest"]:
        claims = {"sub": str(uuid.uuid4()), "role": role}
        with pytest.raises(HTTPException) as exc_info:
            await require_super_admin(claims)
        assert exc_info.value.status_code == 403
        assert "Super Admin access required" in exc_info.value.detail


@pytest.mark.asyncio
async def test_seed_super_admin_creates_platform_account():
    """Test seed_super_admin script logic creating a platform-level Super Admin."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    # User does not exist
    mock_exec_res = MagicMock()
    mock_exec_res.scalars.return_value.first.return_value = None
    mock_session.execute.return_value = mock_exec_res

    with pytest.MonkeyPatch.context() as mp:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = None
        mp.setattr("seed_super_admin.AsyncSessionLocal", lambda: mock_ctx)

        await seed_super_admin(
            email="superadmin@ofc360.com",
            password="SuperPassword@123",
            name="Platform Super Admin",
            phone="9999999999",
        )

    added_objects = [c.args[0] for c in mock_session.add.call_args_list]
    assert len(added_objects) == 1
    sa_user = added_objects[0]
    assert isinstance(sa_user, User)
    assert sa_user.email == "superadmin@ofc360.com"
    assert sa_user.role == UserRole.SUPER_ADMIN
    assert sa_user.company_id is None  # Platform level
    assert sa_user.is_active is True
    assert sa_user.is_verified is True
    assert sa_user.account_status == "ACTIVE"
    assert sa_user.must_change_password is False
