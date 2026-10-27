"""Test configuration for root tests directory."""
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from app.core.config import settings

USE_REAL_DB = bool(os.getenv("DATABASE_URL") or getattr(settings, "DATABASE_URL", None))


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset in-memory rate limiter cache before each test."""
    from app.core.rate_limiter import rate_limiter
    rate_limiter.reset()
    yield
    rate_limiter.reset()


@pytest.fixture(scope="session", autouse=True)
def mock_database():
    """Mock database connections for test collection when no real DB is configured."""
    if USE_REAL_DB:
        with patch("app.core.redis_client.redis_client.connect", new_callable=AsyncMock):
            with patch("app.core.redis_client.redis_client.disconnect", new_callable=AsyncMock):
                with patch("app.llm.client.get_llm_client", new_callable=MagicMock):
                    yield None
        return

    with patch("app.db.database.engine", new_callable=MagicMock) as mock_engine:
        mock_engine.connect = AsyncMock()
        mock_engine.begin = AsyncMock()
        mock_engine.dispose = AsyncMock()
        with patch("app.db.database.AsyncSessionLocal", new_callable=MagicMock):
            with patch("app.core.redis_client.redis_client.connect", new_callable=AsyncMock):
                with patch("app.core.redis_client.redis_client.disconnect", new_callable=AsyncMock):
                    with patch("app.llm.client.get_llm_client", new_callable=MagicMock):
                        yield mock_engine


def _create_mock_result(data=None):
    """Create a mock SQLAlchemy result object."""
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = data or []
    mock_scalars.first.return_value = data[0] if data else None
    mock_scalars.scalar.return_value = data[0] if data else 0
    mock_scalars.one_or_none.return_value = data[0] if data else None
    mock_scalars.scalar_one_or_none.return_value = data[0] if data else None
    mock_scalars.scalar_one.return_value = data[0] if data else None
    mock_result.scalars.return_value = mock_scalars
    mock_result.scalar.return_value = data[0] if data else 0
    mock_result.scalar_one_or_none.return_value = data[0] if data else None
    mock_result.scalar_one.return_value = data[0] if data else None
    mock_result.first.return_value = data[0] if data else None
    return mock_result


@pytest.fixture(autouse=True)
def override_db_session():
    """Override get_db_session dependency for all tests when no real DB is configured."""
    if USE_REAL_DB:
        yield
        return

    from app.db.database import get_db_session
    from app.main import app
    
    mock_employee_count_result = _create_mock_result([0])
    mock_policy_docs_result = _create_mock_result([])
    
    async def mock_get_db_session():
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        async def execute_side_effect(stmt):
            stmt_str = str(stmt).lower()
            if "count" in stmt_str and "employee" in stmt_str:
                return mock_employee_count_result
            elif "companypolicydocument" in stmt_str or "policy" in stmt_str:
                return mock_policy_docs_result
            return _create_mock_result([])
        mock_session.execute.side_effect = execute_side_effect
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.refresh = AsyncMock()
        mock_session.delete = AsyncMock()
        yield mock_session
    
    app.dependency_overrides[get_db_session] = mock_get_db_session
    yield
    app.dependency_overrides.clear()