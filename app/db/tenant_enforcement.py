"""Fail-closed tenant checks for ORM reads, bulk writes, inserts and flushes."""
from sqlalchemy import inspect
from sqlalchemy.sql.elements import TextClause
from sqlalchemy.sql.dml import Insert
from sqlalchemy.orm import with_loader_criteria
from app.db.base import Base, tenant_id_ctx


def require_company(value, tenant_id):
    if value is None or str(value) != str(tenant_id):
        raise PermissionError("Cross-company database operation denied")


def enforce_statement(state):
    tenant_id = tenant_id_ctx.get()
    if tenant_id is None:
        return
    stmt = state.statement
    if isinstance(stmt, TextClause):
        # Raw SQL cannot be parsed safely to infer ownership. Only reviewed,
        # explicitly marked infrastructure statements are permitted here.
        if not state.execution_options.get("tenant_safe"):
            raise PermissionError("Tenant requests require scoped ORM SQL")
        return
    table = getattr(stmt, "table", None)
    if isinstance(stmt, Insert) and table is not None and "company_id" in table.c:
        parameters = state.parameters
        rows = parameters if isinstance(parameters, list) else [parameters] if parameters else []
        values = getattr(stmt, "_values", None)
        if values:
            rows.append({getattr(key, "key", key): getattr(value, "value", value) for key, value in values.items()})
        for group in getattr(stmt, "_multi_values", ()):
            rows.extend(group)
        if not rows or getattr(stmt, "select", None) is not None:
            raise PermissionError("Tenant inserts require explicit company values")
        for row in rows:
            require_company(row.get("company_id"), tenant_id)
        conflict = getattr(stmt, "_post_values_clause", None)
        if conflict is not None:
            for key, value in getattr(conflict, "update_values_to_set", []):
                if getattr(key, "key", key) == "company_id":
                    require_company(getattr(value, "value", value), tenant_id)
        return
    if state.is_update or state.is_delete:
        if table is not None and "company_id" in table.c:
            state.statement = stmt.where(table.c.company_id == tenant_id)
            values = getattr(stmt, "_values", None) or {}
            for key, value in values.items():
                if getattr(key, "key", key) == "company_id":
                    require_company(getattr(value, "value", value), tenant_id)
        return
    if state.is_select:
        from app.models.company import Company
        state.statement = stmt.options(with_loader_criteria(Company, Company.id == tenant_id, include_aliases=True))
        for mapper in Base.registry.mappers:
            cls = mapper.class_
            if hasattr(cls, "company_id"):
                state.statement = state.statement.options(with_loader_criteria(
                    cls, cls.company_id == tenant_id, include_aliases=True, propagate_to_loaders=True))


def enforce_flush(session, *_):
    tenant_id = tenant_id_ctx.get()
    if tenant_id is None:
        return
    for obj in session.new | session.dirty | session.deleted:
        if not hasattr(obj, "company_id"):
            continue
        if obj in session.new and obj.company_id is None:
            obj.company_id = tenant_id
        require_company(obj.company_id, tenant_id)
        history = inspect(obj).attrs.company_id.history
        for previous in history.deleted:
            require_company(previous, tenant_id)
