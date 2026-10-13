"""Idempotent migration helpers for Alembic.

Provides safe DDL operations that work on both fresh and already-migrated databases.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


def get_bind():
    """Get the current connection bind."""
    return op.get_bind()


def get_inspector(bind=None):
    """Get SQLAlchemy inspector for the current bind."""
    if bind is None:
        bind = get_bind()
    return inspect(bind)


def table_exists(table_name: str, schema: str | None = None, bind=None) -> bool:
    """Check if a table exists."""
    inspector = get_inspector(bind)
    return inspector.has_table(table_name, schema=schema)


def column_exists(table_name: str, column_name: str, schema: str | None = None, bind=None) -> bool:
    """Check if a column exists in a table."""
    inspector = get_inspector(bind)
    if not inspector.has_table(table_name, schema=schema):
        return False
    columns = inspector.get_columns(table_name, schema=schema)
    return any(col["name"] == column_name for col in columns)


def index_exists(table_name: str, index_name: str, schema: str | None = None, bind=None) -> bool:
    """Check if an index exists on a table."""
    inspector = get_inspector(bind)
    if not inspector.has_table(table_name, schema=schema):
        return False
    indexes = inspector.get_indexes(table_name, schema=schema)
    return any(idx["name"] == index_name for idx in indexes)


def constraint_exists(table_name: str, constraint_name: str, schema: str | None = None, bind=None) -> bool:
    """Check if a constraint exists on a table."""
    inspector = get_inspector(bind)
    if not inspector.has_table(table_name, schema=schema):
        return False
    constraints = inspector.get_unique_constraints(table_name, schema=schema)
    for c in constraints:
        if c["name"] == constraint_name:
            return True
    constraints = inspector.get_foreign_keys(table_name, schema=schema)
    for c in constraints:
        if c["name"] == constraint_name:
            return True
    constraints = inspector.get_check_constraints(table_name, schema=schema)
    for c in constraints:
        if c["name"] == constraint_name:
            return True
    pk = inspector.get_pk_constraint(table_name, schema=schema)
    if pk and pk.get("name") == constraint_name:
        return True
    return False


def safe_drop_index(index_name: str, table_name: str, schema: str | None = None) -> None:
    """Drop an index if it exists (idempotent)."""
    bind = get_bind()
    if index_exists(table_name, index_name, schema, bind):
        if bind.dialect.name == "postgresql":
            op.execute(sa.text(f'DROP INDEX IF EXISTS {_quote_identifier(index_name)}'))
        else:
            op.drop_index(index_name, table_name=table_name, schema=schema)


def safe_drop_constraint(constraint_name: str, table_name: str, type_: str, schema: str | None = None) -> None:
    """Drop a constraint if it exists (idempotent)."""
    bind = get_bind()
    if constraint_exists(table_name, constraint_name, schema, bind):
        if bind.dialect.name == "postgresql":
            op.execute(sa.text(f'ALTER TABLE {_quote_identifier(table_name)} DROP CONSTRAINT IF EXISTS {_quote_identifier(constraint_name)}'))
        else:
            op.drop_constraint(constraint_name, table_name, type_=type_, schema=schema)


def safe_drop_column(table_name: str, column_name: str, schema: str | None = None) -> None:
    """Drop a column if it exists (idempotent)."""
    bind = get_bind()
    if column_exists(table_name, column_name, schema, bind):
        if bind.dialect.name == "postgresql":
            op.execute(sa.text(f'ALTER TABLE {_quote_identifier(table_name)} DROP COLUMN IF EXISTS {_quote_identifier(column_name)}'))
        else:
            op.drop_column(table_name, column_name, schema=schema)


def safe_drop_table(table_name: str, schema: str | None = None) -> None:
    """Drop a table if it exists (idempotent)."""
    bind = get_bind()
    if table_exists(table_name, schema, bind):
        if bind.dialect.name == "postgresql":
            op.execute(sa.text(f'DROP TABLE IF EXISTS {_quote_identifier(table_name)} CASCADE'))
        else:
            op.drop_table(table_name, schema=schema)


def safe_add_column(table_name: str, column: sa.Column, schema: str | None = None) -> None:
    """Add a column if it doesn't exist (idempotent)."""
    bind = get_bind()
    if not column_exists(table_name, column.name, schema, bind):
        op.add_column(table_name, column, schema=schema)


def safe_create_index(index_name: str, table_name: str, columns: list[str], unique: bool = False, schema: str | None = None, postgresql_where: str | None = None, postgresql_include: list[str] | None = None) -> None:
    """Create an index if it doesn't exist (idempotent)."""
    bind = get_bind()
    if not index_exists(table_name, index_name, schema, bind):
        if bind.dialect.name == "postgresql":
            where_clause = f" WHERE {postgresql_where}" if postgresql_where else ""
            include_clause = f" INCLUDE ({', '.join(_quote_identifier(c) for c in postgresql_include)})" if postgresql_include else ""
            unique_clause = "UNIQUE " if unique else ""
            op.execute(sa.text(
                f'CREATE {unique_clause}INDEX IF NOT EXISTS {_quote_identifier(index_name)} '
                f'ON {_quote_identifier(table_name)} ({", ".join(_quote_identifier(c) for c in columns)})'
                f'{include_clause}{where_clause}'
            ))
        else:
            op.create_index(index_name, table_name, columns, unique=unique, schema=schema)


def safe_create_unique_constraint(constraint_name: str, table_name: str, columns: list[str], schema: str | None = None, postgresql_nulls_not_distinct: bool = False) -> None:
    """Create a unique constraint if it doesn't exist (idempotent)."""
    bind = get_bind()
    if not constraint_exists(table_name, constraint_name, schema, bind):
        if bind.dialect.name == "postgresql":
            nulls_clause = " NULLS NOT DISTINCT" if postgresql_nulls_not_distinct else ""
            op.execute(sa.text(
                f'ALTER TABLE {_quote_identifier(table_name)} '
                f'ADD CONSTRAINT {_quote_identifier(constraint_name)} '
                f'UNIQUE ({", ".join(_quote_identifier(c) for c in columns)}){nulls_clause}'
            ))
        else:
            op.create_unique_constraint(constraint_name, table_name, columns, schema=schema)


def safe_create_foreign_key(constraint_name: str, source_table: str, referent_table: str, local_cols: list[str], remote_cols: list[str], schema: str | None = None, referent_schema: str | None = None, ondelete: str | None = None, onupdate: str | None = None) -> None:
    """Create a foreign key if it doesn't exist (idempotent)."""
    bind = get_bind()
    if not constraint_exists(source_table, constraint_name, schema, bind):
        if bind.dialect.name == "postgresql":
            ondelete_clause = f" ON DELETE {ondelete}" if ondelete else ""
            onupdate_clause = f" ON UPDATE {onupdate}" if onupdate else ""
            op.execute(sa.text(
                f'ALTER TABLE {_quote_identifier(source_table)} '
                f'ADD CONSTRAINT {_quote_identifier(constraint_name)} '
                f'FOREIGN KEY ({", ".join(_quote_identifier(c) for c in local_cols)}) '
                f'REFERENCES {_quote_identifier(referent_table)} ({", ".join(_quote_identifier(c) for c in remote_cols)})'
                f'{ondelete_clause}{onupdate_clause}'
            ))
        else:
            op.create_foreign_key(constraint_name, source_table, referent_table, local_cols, remote_cols,
                                  schema=schema, referent_schema=referent_schema, ondelete=ondelete, onupdate=onupdate)


def safe_create_table(table_name: str, columns: list[sa.Column], schema: str | None = None, **kwargs) -> None:
    """Create a table if it doesn't exist (idempotent)."""
    bind = get_bind()
    if not table_exists(table_name, schema, bind):
        op.create_table(table_name, *columns, schema=schema, **kwargs)


def _quote_identifier(name: str) -> str:
    """Quote a PostgreSQL identifier."""
    return f'"{name}"'


def enum_type_exists(enum_name: str, bind=None) -> bool:
    """Check if a PostgreSQL ENUM type exists."""
    if bind is None:
        bind = get_bind()
    if bind.dialect.name != "postgresql":
        return False
    result = bind.execute(sa.text(
        "SELECT 1 FROM pg_type WHERE typname = :name"
    ), {"name": enum_name}).scalar()
    return result is not None


def safe_create_enum(enum_name: str, values: list[str], bind=None) -> None:
    """Create a PostgreSQL ENUM type if it doesn't exist."""
    if bind is None:
        bind = get_bind()
    if bind.dialect.name != "postgresql":
        return
    if not enum_type_exists(enum_name, bind):
        values_str = ", ".join(f"'{v}'" for v in values)
        op.execute(sa.text(f"CREATE TYPE {_quote_identifier(enum_name)} AS ENUM ({values_str})"))


def safe_drop_enum(enum_name: str, bind=None) -> None:
    """Drop a PostgreSQL ENUM type if it exists."""
    if bind is None:
        bind = get_bind()
    if bind.dialect.name != "postgresql":
        return
    if enum_type_exists(enum_name, bind):
        op.execute(sa.text(f"DROP TYPE IF EXISTS {_quote_identifier(enum_name)}"))


def safe_alter_column_type(table_name: str, column_name: str, new_type: sa.TypeEngine, schema: str | None = None,
                           existing_type: sa.TypeEngine | None = None, existing_nullable: bool | None = None,
                           existing_server_default: sa.TextClause | str | None = None,
                           server_default: sa.TextClause | str | None = None, nullable: bool | None = None) -> None:
    """Alter column type if the column exists (idempotent)."""
    bind = get_bind()
    if column_exists(table_name, column_name, schema, bind):
        op.alter_column(
            table_name, column_name,
            type_=new_type,
            existing_type=existing_type,
            existing_nullable=existing_nullable,
            existing_server_default=existing_server_default,
            server_default=server_default,
            nullable=nullable,
            schema=schema
        )