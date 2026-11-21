"""Regression coverage for the explicit platform-owner CLI workflow."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts import seed_super_admin as provisioning


class _ScalarRows:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


def _session_factory(session):
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=context)


def _session() -> AsyncMock:
    session = AsyncMock()
    # SQLAlchemy's Session.add is synchronous even when the session is async.
    session.add = MagicMock()
    return session


@pytest.mark.asyncio
async def test_initial_provisioning_creates_owner_and_audit(monkeypatch):
    session = _session()
    session.scalars.return_value = _ScalarRows([])
    session.scalar.return_value = None
    monkeypatch.setattr(provisioning, "AsyncSessionLocal", _session_factory(session))
    monkeypatch.setattr(provisioning, "hash_password", lambda _: "hashed")

    await provisioning.seed_super_admin(
        "superadmin@ofc360.com", "a-secure-password", "Platform Owner", "9876543210", "ops-42"
    )

    assert session.commit.await_count == 1
    created_owner, audit = [call.args[0] for call in session.add.call_args_list]
    assert created_owner.email == "superadmin@ofc360.com"
    assert created_owner.company_id is None
    assert created_owner.must_change_password is True
    assert audit.action == "PLATFORM_OWNER_PROVISIONED"
    assert audit.actor_id == "ops-42"


@pytest.mark.asyncio
async def test_existing_owner_is_unchanged_without_recovery(monkeypatch):
    owner = SimpleNamespace(email="superadmin@ofc360.com", company_id=None)
    session = _session()
    session.scalars.return_value = _ScalarRows([owner])
    session.scalar.return_value = owner
    monkeypatch.setattr(provisioning, "AsyncSessionLocal", _session_factory(session))

    with pytest.raises(RuntimeError, match="--recover"):
        await provisioning.seed_super_admin(
            "superadmin@ofc360.com", "a-secure-password", None, None, "ops-42"
        )

    session.add.assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_recovery_is_audited(monkeypatch):
    owner = SimpleNamespace(
        id="owner-id",
        email="superadmin@ofc360.com",
        company_id=None,
        password_hash="old",
        is_active=False,
        is_verified=False,
        account_status="SUSPENDED",
        must_change_password=False,
    )
    session = _session()
    session.scalars.return_value = _ScalarRows([owner])
    session.scalar.return_value = owner
    monkeypatch.setattr(provisioning, "AsyncSessionLocal", _session_factory(session))
    monkeypatch.setattr(provisioning, "hash_password", lambda _: "new-hash")

    await provisioning.seed_super_admin(
        "superadmin@ofc360.com", "a-secure-password", None, None, "incident-17", recover=True
    )

    assert owner.password_hash == "new-hash"
    assert owner.is_active is True
    assert owner.must_change_password is True
    audit = session.add.call_args.args[0]
    assert audit.action == "PLATFORM_OWNER_RECOVERED"
    assert audit.actor_id == "incident-17"
    assert session.commit.await_count == 1
