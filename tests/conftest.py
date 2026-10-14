"""Test configuration for root tests directory."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Mock the database engine and session before importing app.main
# This prevents the lifespan from trying to connect to a real database during test collection

@pytest.fixture(scope="session", autouse=True)
def mock_database():
    """Mock database connections for test collection."""
    with patch("app.db.database.engine", new_callable=MagicMock) as mock_engine:
        mock_engine.connect = AsyncMock()
        mock_engine.begin = AsyncMock()
        mock_engine.dispose = AsyncMock()
        with patch("app.db.database.AsyncSessionLocal", new_callable=MagicMock):
            with patch("app.core.redis_client.redis_client.connect", new_callable=AsyncMock):
                with patch("app.core.redis_client.redis_client.disconnect", new_callable=AsyncMock):
                    with patch("app.llm.client.get_llm_client", new_callable=MagicMock):
                        yield mock_engine