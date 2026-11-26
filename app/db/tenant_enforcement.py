"""Fail-closed tenant checks for ORM reads, bulk writes, inserts and flushes."""
from __future__ import annotations

from functools import lru_cache
from typing import Iterable

from sqlalchemy import inspect
from sqlalchemy.orm import configure_mappers, with_loader_criteria
from sqlalchemy.sql.dml import Insert
from sqlalchemy.sql.elements import TextClause
from sqlalchemy.sql.selectable import FromClause

from app.db.base import Base, tenant_id_ctx


def require_company(value, tenant_id):
    if value is None or str(value) != str(tenant_id):
        raise PermissionError("Cross-company database operation denied")


@lru_cache(maxsize=1)
def _tenant_registry_index() -> tuple[
    tuple[type, ...],
    dict[FromClause, tuple[type, ...]],
    dict[type, tuple[type, ...]],
]:
    """Build cached lookup tables for tenant-scoped ORM classes without per-query mapper loops."""
    configure_mappers()
    from app.models.company import Company

    all_classes: list[type] = []
    table_to_classes: dict[FromClause, list[type]] = {}
    seen_cls: set[type] = set()

    for mapper in Base.registry.mappers:
        cls = mapper.class_
        is_tenant = cls is Company or hasattr(cls, "company_id")
        if is_tenant and cls not in seen_cls:
            seen_cls.add(cls)
            all_classes.append(cls)
        for selectable in (mapper.local_table, mapper.persist_selectable):
            if selectable is not None and is_tenant:
                table_to_classes.setdefault(selectable, []).append(cls)

    reachable_cache: dict[type, tuple[type, ...]] = {}
    _EAGER_LOADERS = {"joined", "selectin", "subquery", "immediate"}

    for mapper in Base.registry.mappers:
        root_cls = mapper.class_
        visited_mappers = set()
        queue = [mapper]
        collected: list[type] = []
        collected_set: set[type] = set()
        while queue:
            cur = queue.pop(0)
            if cur in visited_mappers:
                continue
            visited_mappers.add(cur)
            cur_cls = cur.class_
            if (cur_cls is Company or hasattr(cur_cls, "company_id")) and cur_cls not in collected_set:
                collected_set.add(cur_cls)
                collected.append(cur_cls)
            # Never fan out through Company/hub reverse relationships (200+ models) unless eager-loaded on root
            if cur is not mapper and cur_cls is Company:
                continue
            for rel in cur.relationships:
                if getattr(rel, "lazy", None) not in _EAGER_LOADERS:
                    continue
                target_mapper = rel.mapper
                if target_mapper not in visited_mappers:
                    queue.append(target_mapper)
        reachable_cache[root_cls] = tuple(collected)

    return (
        tuple(all_classes),
        {tbl: tuple(dict.fromkeys(clss)) for tbl, clss in table_to_classes.items()},
        reachable_cache,
    )


def warm_tenant_enforcement_cache() -> int:
    """Pre-warm ORM mapper and tenant enforcement caches at application startup."""
    all_classes, _, _ = _tenant_registry_index()
    return len(all_classes)


def _extract_target_classes(stmt, table_to_classes: dict[FromClause, tuple[type, ...]], reachable_cache: dict[type, tuple[type, ...]]) -> tuple[type, ...] | None:
    """Resolve tenant-scoped ORM classes referenced by ``stmt`` or reachable via loaders."""
    roots: list[type] = []

    def _add_entity(entity) -> None:
        if entity is None:
            return
        if isinstance(entity, type):
            roots.append(entity)
            return
        parent = getattr(entity, "parent", None)
        if parent is not None and hasattr(parent, "class_"):
            roots.append(parent.class_)
            return
        entity_cls = getattr(entity, "entity", None)
        if isinstance(entity_cls, type):
            roots.append(entity_cls)

    for desc in getattr(stmt, "column_descriptions", ()) or ():
        _add_entity(desc.get("entity"))
        expr = desc.get("expr")
        if expr is not None:
            _add_entity(getattr(expr, "class_", None))

    for from_obj in getattr(stmt, "get_final_froms", lambda: ())() or ():
        for cls in table_to_classes.get(from_obj, ()):
            roots.append(cls)

    for opt in getattr(stmt, "_with_options", ()) or ():
        for path_item in getattr(opt, "path", ()) or ():
            if hasattr(path_item, "class_"):
                roots.append(path_item.class_)
            elif hasattr(path_item, "mapper") and hasattr(path_item.mapper, "class_"):
                roots.append(path_item.mapper.class_)

    if not roots:
        return None

    from app.models.company import Company

    resolved: list[type] = []
    seen: set[type] = set()
    for root in roots:
        for candidate in reachable_cache.get(root, (root,) if hasattr(root, "company_id") or root is Company else ()):
            if candidate not in seen:
                seen.add(candidate)
                resolved.append(candidate)
    return tuple(resolved)


def _criteria_for_classes(classes: tuple[type, ...], raw_tenant_id: Any) -> tuple:
    from app.models.company import Company

    criteria = []
    for cls in classes:
        if cls is Company:
            criteria.append(with_loader_criteria(Company, Company.id == raw_tenant_id, include_aliases=True))
        elif hasattr(cls, "company_id"):
            criteria.append(
                with_loader_criteria(
                    cls,
                    cls.company_id == raw_tenant_id,
                    include_aliases=True,
                    propagate_to_loaders=True,
                )
            )
    return tuple(criteria)


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
        all_classes, table_to_classes, reachable_cache = _tenant_registry_index()
        # Preserve global safety for explicit subqueries/WHERE clauses when non-trivial expressions appear
        where_criteria = getattr(stmt, "_where_criteria", ()) or ()
        target_classes: tuple[type, ...] | None = None
        if not where_criteria and not getattr(stmt, "_setup_joins", ()):
            target_classes = _extract_target_classes(stmt, table_to_classes, reachable_cache)
        else:
            # Walk statement tables to include any joined/subquery models cleanly
            extracted = _extract_target_classes(stmt, table_to_classes, reachable_cache)
            if extracted is not None:
                from sqlalchemy.sql import visitors
                sub_tables = {
                    node
                    for node in visitors.iterate(stmt)
                    if isinstance(node, FromClause) and node in table_to_classes
                }
                if sub_tables:
                    extra = []
                    seen_e = set(extracted)
                    for tbl in sub_tables:
                        for root in table_to_classes[tbl]:
                            for cand in reachable_cache.get(root, (root,)):
                                if cand not in seen_e:
                                    seen_e.add(cand)
                                    extra.append(cand)
                    target_classes = extracted + tuple(extra)
                else:
                    target_classes = extracted
        if not target_classes:
            target_classes = all_classes
        criteria = _criteria_for_classes(target_classes, tenant_id)
        if criteria:
            state.statement = stmt.options(*criteria)


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
