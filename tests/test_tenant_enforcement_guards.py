"""Unit coverage for mandatory tenant predicates before SQL is executed."""

from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import delete, insert, select, text, update

from app.db.base import tenant_id_ctx
from app.db.tenant_enforcement import enforce_statement
from app.models.user import User


TENANT_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
TENANT_B = uuid.UUID("00000000-0000-0000-0000-0000000000b2")


def _state(statement, *, select_statement=False, update_statement=False, delete_statement=False, options=None):
    return SimpleNamespace(
        statement=statement,
        parameters=None,
        execution_options=options or {},
        is_select=select_statement,
        is_update=update_statement,
        is_delete=delete_statement,
    )


def test_tenant_select_gets_company_predicate():
    token = tenant_id_ctx.set(TENANT_A)
    try:
        state = _state(select(User), select_statement=True)
        enforce_statement(state)
    finally:
        tenant_id_ctx.reset(token)

    compiled = str(state.statement)
    assert "users.company_id" in compiled


def test_cross_tenant_insert_is_rejected_before_execution():
    token = tenant_id_ctx.set(TENANT_A)
    try:
        state = _state(insert(User).values(company_id=TENANT_B))
        with pytest.raises(PermissionError, match="Cross-company"):
            enforce_statement(state)
    finally:
        tenant_id_ctx.reset(token)


def test_bulk_update_and_delete_are_scoped_to_active_tenant():
    token = tenant_id_ctx.set(TENANT_A)
    try:
        update_state = _state(update(User).values(is_active=False), update_statement=True)
        enforce_statement(update_state)
        delete_state = _state(delete(User), delete_statement=True)
        enforce_statement(delete_state)
    finally:
        tenant_id_ctx.reset(token)

    assert "users.company_id" in str(update_state.statement)
    assert "users.company_id" in str(delete_state.statement)


def test_raw_sql_requires_explicit_review_marker():
    token = tenant_id_ctx.set(TENANT_A)
    try:
        with pytest.raises(PermissionError, match="scoped ORM SQL"):
            enforce_statement(_state(text("SELECT 1")))
        enforce_statement(_state(text("SELECT 1"), options={"tenant_safe": True}))
    finally:
        tenant_id_ctx.reset(token)
