import asyncio
import logging
import socket
import ssl
from collections.abc import AsyncGenerator
from typing import Any

import asyncpg
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

logger = logging.getLogger(__name__)


def should_force_ipv4(host: str) -> bool:
    """
    Determine whether to force manual IPv4 resolution for database hostname.

    - Automatically SKIPPED for Render internal hosts (starts with 'dpg-' or contains '.render.com' / '.internal')
      or when running in Render environment.
    - Only enabled if settings.FORCE_IPV4_DB is explicitly set to True (opt-in fallback for legacy
      Supabase-style direct connections with IPv6 routing issues).
    """
    is_render_host = host.startswith("dpg-") or ".render.com" in host or host.endswith(".internal")
    is_render_env = settings.ENVIRONMENT.lower() in ("render", "production", "staging")

    if is_render_host or is_render_env:
        return False

    return bool(getattr(settings, "FORCE_IPV4_DB", False))


async def get_asyncpg_connection() -> asyncpg.Connection:
    """
    Custom asynchronous creator for SQLAlchemy's create_async_engine.

    Render internal networking (e.g. hostnames matching dpg-xxxxx-a) uses standard IPv4/dual-stack routing
    and does not require manual IP resolution. Manual IPv4 resolution using raw IP addresses breaks TLS/SNI
    handshakes ('No SNI information found') when SSL is enabled.

    This function uses direct hostname connections by default, while retaining an opt-in IPv4 forcing workaround
    (via FORCE_IPV4_DB=True) for legacy providers (e.g. Supabase direct connections with IPv6 issues).
    """
    db_url = make_url(settings.DATABASE_URL)
    host = db_url.host or "localhost"
    port = db_url.port or 5432

    # Handle SSL configuration from URL query parameters
    ssl_mode = db_url.query.get("sslmode")
    ssl_param = db_url.query.get("ssl")
    ssl_setting: Any = None

    if ssl_mode:
        if ssl_mode.lower() in ("disable", "off", "0", "false"):
            ssl_setting = False
        elif ssl_mode.lower() in ("require", "verify-ca", "verify-full", "prefer", "allow"):
            ssl_setting = "require"
    elif ssl_param:
        if ssl_param.lower() in ("false", "disable", "off", "0"):
            ssl_setting = False
        elif ssl_param.lower() in ("true", "require", "on", "1"):
            ssl_setting = True
        else:
            ssl_setting = ssl_param

    # Determine if IPv4 forcing workaround should be used
    use_ipv4_workaround = should_force_ipv4(host)

    if not use_ipv4_workaround:
        logger.info("Using direct connection (no IPv4 workaround) for database host: %s", host)
        kwargs: dict[str, Any] = {
            "host": host,
            "port": port,
            "user": db_url.username,
            "password": db_url.password,
            "database": db_url.database,
        }
        if ssl_setting is not None:
            kwargs["ssl"] = ssl_setting

        if "timeout" in db_url.query:
            kwargs["timeout"] = float(db_url.query["timeout"])
        elif "connect_timeout" in db_url.query:
            kwargs["timeout"] = float(db_url.query["connect_timeout"])

        return await asyncpg.connect(**kwargs)

    # Legacy IPv4-forcing workaround (for direct IPv6-only resolution issues e.g. Supabase)
    logger.info("Using IPv4-forced connection with SNI-preserving SSL context for database host: %s", host)
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

    ipv4_address = addr_info[0][4][0]

    kwargs = {
        "host": ipv4_address,
        "port": port,
        "user": db_url.username,
        "password": db_url.password,
        "database": db_url.database,
    }

    if ssl_setting is not None and ssl_setting is not False:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        kwargs["ssl"] = ssl_ctx
    elif ssl_setting is False:
        kwargs["ssl"] = False

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

