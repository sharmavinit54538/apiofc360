"""Alembic migration environment.

Configured for robust remote PostgreSQL migrations:
- Dedicated migration connection with NullPool
- Explicit asyncpg timeouts (connect, command, statement)
- Proper connection lifecycle management
- Transactional DDL where supported
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config, AsyncEngine

from app.core.config import settings
from app.db.base import Base
import app.models

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Escape % for alembic config parsing
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))

target_metadata = Base.metadata


def my_compare_server_default(context, inspected_column, metadata_column, inspected_default, metadata_default, rendered_metadata_default):
    from sqlalchemy.sql.sqltypes import JSON, Enum
    if isinstance(metadata_column.type, JSON):
        return False
    if isinstance(metadata_column.type, Enum) or 'enum' in str(metadata_column.type).lower() or metadata_column.name == 'role':
        return False
    return None


def run_migrations_offline() -> None:
    """Run migrations without creating an Engine."""

    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=my_compare_server_default,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations with a synchronous connection facade."""

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=my_compare_server_default,
    )

    with context.begin_transaction():
        context.run_migrations()


async def create_migration_engine() -> AsyncEngine:
    """Create a dedicated async engine for migrations with robust timeouts.
    
    Uses NullPool to avoid connection pooling issues during migrations.
    Configures asyncpg timeouts for remote PostgreSQL reliability.
    """
    from app.db.database import get_asyncpg_connection
    
    # Create engine with NullPool (no pooling for migrations)
    engine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        async_creator=get_asyncpg_connection,
    )
    
    return engine


async def run_async_migrations() -> None:
    """Run migrations through SQLAlchemy's async engine with robust connection handling."""
    engine = await create_migration_engine()
    
    try:
        # Use a single connection for all migrations with explicit transaction
        async with engine.begin() as connection:
            # Set PostgreSQL session timeouts for this connection
            await connection.execute(text("SET statement_timeout = '300s'"))
            await connection.execute(text("SET lock_timeout = '120s'"))
            await connection.execute(text("SET idle_in_transaction_session_timeout = '600s'"))
            
            # Run migrations on this connection
            await connection.run_sync(do_run_migrations)
            
    finally:
        # Ensure engine is properly disposed
        await engine.dispose()


def run_migrations_online() -> None:
    """Run migrations online."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()