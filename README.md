# apiofc360 Backend

FastAPI enterprise platform with async SQLAlchemy (asyncpg) and Alembic on PostgreSQL.

## Database Migrations & Schema Guidelines

To prevent schema drift, broken migration branches, and CI failures, all developers must adhere to the following rules:

### 1. Never Edit the Database Manually or Use `Base.metadata.create_all`
- **Never** modify database tables, columns, constraints, or indexes manually in development, staging, or production.
- **Never** call `Base.metadata.create_all()` in application runtime or test harnesses. The database schema must be driven strictly through Alembic migrations.

### 2. Always Generate and Review Migrations
- Whenever you make changes to SQLAlchemy models in `app/models/`, generate a migration using:
  ```bash
  alembic revision --autogenerate -m "describe_your_changes"
  ```
- **Inspect the generated migration file** before committing:
  - Check that all created/altered tables, columns, constraints, and indexes match your expectations.
  - Remove any unwanted detected changes or unintentional drops.
  - Ensure operations are idempotent where appropriate (e.g. inspector checks `sa.inspect(op.get_bind())` or `IF EXISTS` / `IF NOT EXISTS`).
  - Ensure the `downgrade()` function accurately and cleanly reverts every change made in `upgrade()`.

### 3. Test on a Fresh Database Locally
- Always verify your migration locally against an empty PostgreSQL database before pushing:
  ```bash
  alembic upgrade head
  alembic check
  alembic downgrade base
  alembic upgrade head
  ```
- `alembic check` must report: `No new upgrade operations detected.`

### 4. Resolving Multiple Heads
- If two developers create migrations concurrently or git branches diverge, Alembic will detect multiple heads (`alembic heads | wc -l > 1`).
- To merge them into a single head:
  ```bash
  alembic merge heads -m "merge_heads"
  ```
- Verify that `alembic heads` shows exactly one head revision.