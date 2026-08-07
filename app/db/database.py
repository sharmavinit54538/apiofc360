"""Async SQLAlchemy engine and session dependency."""

import asyncio
import socket
from collections.abc import AsyncGenerator
from typing import Any

import asyncpg
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings


async def get_asyncpg_connection() -> asyncpg.Connection:
    """
    Custom asynchronous creator for SQLAlchemy's create_async_engine.

    Render internal networking (e.g. hostnames matching dpg-xxxxx-a) uses a dual-stack
    DNS setup. However, the internal container network environment on Render only routes
    IPv4 traffic. Default socket resolution in Python's asyncio / asyncpg resolves and
    attempts an IPv6 (AF_INET6) connection first, producing:
        OSError: [Errno 101] Network is unreachable

    To prevent this, we explicitly resolve the database hostname to IPv4 (AF_INET) via
    socket.getaddrinfo() before initiating the connection with asyncpg.connect().
    """
    db_url = make_url(settings.DATABASE_URL)
    host = db_url.host or "localhost"
    port = db_url.port or 5432

    # Manually resolve the hostname using socket.AF_INET to force IPv4
    loop = asyncio.get_running_loop()
    try:
        addr_info = await loop.getaddrinfo(
            host,
            port,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Failed to resolve IPv4 address for database host '{host}': {exc}"
        ) from exc

    if not addr_info:
        raise RuntimeError(f"No IPv4 address could be resolved for database host '{host}'.")

    # Select the first IPv4 address returned
    ipv4_address = addr_info[0][4][0]

    # Preserve all connection settings: user, password, database, port, ssl, timeout
    kwargs: dict[str, Any] = {
        "host": ipv4_address,
        "port": port,
        "user": db_url.username,
        "password": db_url.password,
        "database": db_url.database,
    }

    # Handle SSL configuration from URL query parameters
    ssl_mode = db_url.query.get("sslmode")
    ssl_param = db_url.query.get("ssl")
    if ssl_mode:
        if ssl_mode.lower() == "disable":
            kwargs["ssl"] = False
        elif ssl_mode.lower() in ("require", "verify-ca", "verify-full", "prefer", "allow"):
            kwargs["ssl"] = "require"
    elif ssl_param:
        if ssl_param.lower() in ("false", "disable", "off", "0"):
            kwargs["ssl"] = False
        elif ssl_param.lower() in ("true", "require", "on", "1"):
            kwargs["ssl"] = True
        else:
            kwargs["ssl"] = ssl_param

    # Handle timeout parameter if specified
    if "timeout" in db_url.query:
        kwargs["timeout"] = float(db_url.query["timeout"])
    elif "connect_timeout" in db_url.query:
        kwargs["timeout"] = float(db_url.query["connect_timeout"])

    return await asyncpg.connect(**kwargs)


engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    async_creator=get_asyncpg_connection,
    echo=settings.DB_ECHO,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=settings.DB_POOL_RECYCLE,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session for request-scoped dependency injection."""

    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria
from app.db.base import tenant_id_ctx, Base

# Cache: set of ORM classes that have a company_id column (built lazily once)
_tenant_classes: set | None = None


def _get_tenant_classes() -> set:
    """Lazily build and cache the set of ORM classes with company_id."""
    global _tenant_classes
    if _tenant_classes is None:
        _tenant_classes = set()
        for mapper in list(Base.registry.mappers):
            cls = mapper.class_
            if hasattr(cls, "company_id"):
                _tenant_classes.add(cls)
    return _tenant_classes


@event.listens_for(Session, "do_orm_execute")
def _do_orm_execute(orm_execute_state):
    tenant_id = tenant_id_ctx.get()
    if tenant_id and not orm_execute_state.execution_options.get("bypass_tenant", False):
        for cls in _get_tenant_classes():
            orm_execute_state.statement = orm_execute_state.statement.options(
                with_loader_criteria(
                    cls,
                    lambda target_cls: target_cls.company_id == tenant_id,
                    include_aliases=True,
                    propagate_to_loaders=True,
                    track_closure_variables=False
                )
            )

@event.listens_for(Session, "before_flush")
def _before_flush(session, flush_context, instances):
    tenant_id = tenant_id_ctx.get()
    if tenant_id:
        for obj in session.new:
            if hasattr(obj, "company_id") and getattr(obj, "company_id") is None:
                obj.company_id = tenant_id

