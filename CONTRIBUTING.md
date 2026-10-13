# Contributing to apiofc360

## Database Migration Rules

To maintain database schema consistency across development, staging, and production environments, please follow these migration standards:

1. **No Manual Schema Modifications**:
   - Never alter tables, columns, indexes, or relations directly via SQL clients or pgAdmin.
   - Never use `Base.metadata.create_all()` in dev or tests. Every schema change must exist as an Alembic migration.

2. **Generating Migrations**:
   - Update your SQLAlchemy models in `app/models/`.
   - Autogenerate a revision:
     ```bash
     alembic revision --autogenerate -m "add_feature_table"
     ```
   - Carefully review the generated file in `alembic/versions/`. Ensure both `upgrade()` and `downgrade()` are complete, clean, and idempotent.

3. **Idempotent Operations (Required)**:
   - **Drops**: Always use `IF EXISTS` semantics. Use helpers from `alembic/helpers.py`:
     - `safe_drop_index()`, `safe_drop_table()`, `safe_drop_column()`, `safe_drop_constraint()`
   - **Creates**: Always check existence before creating. Use helpers:
     - `safe_create_index()`, `safe_create_table()`, `safe_add_column()`, `safe_create_unique_constraint()`, `safe_create_foreign_key()`
   - Never hand-write `op.drop_index()`, `op.drop_column()`, `op.drop_table()`, `op.drop_constraint()` without guards.

4. **Verifying on a Clean Database**:
   - Run migrations against a fresh PostgreSQL database instance:
     ```bash
     alembic upgrade head
     alembic check
     ```
   - Ensure `alembic check` returns `No new upgrade operations detected.`
   - Test full rollback and replay:
     ```bash
     alembic downgrade base && alembic upgrade head
     ```

5. **Single Head Policy**:
   - The migration graph must have exactly ONE head at all times.
   - If `alembic heads` shows multiple heads, create a merge migration:
     ```bash
     alembic merge heads -m "merge_heads"
     ```
   - Never push with multiple heads.

6. **Pre-commit / Make Verification**:
   - Run `make db-check` (or `pytest tests/test_alembic_single_head.py && alembic check`) before committing.
   - Pre-commit hooks automatically check for single migration heads and zero schema drift.
   - CI validates: single head, complete parent chain, fresh DB upgrade + check, downgrade/upgrade cycle.

### Workflow Summary for Schema Changes
> **Golden Rule**: Change a model => run `alembic revision --autogenerate -m ...`, review the file (add idempotent guards using `alembic/helpers.py`), run `alembic upgrade head && alembic check` on a fresh DB before pushing. Never edit DB by hand, never use Base.metadata.create_all, never add ad-hoc scripts like add_missing_columns.py; if two heads appear, `alembic merge`.
