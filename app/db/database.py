"""Async SQLAlchemy engine and session dependency."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings


engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
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

