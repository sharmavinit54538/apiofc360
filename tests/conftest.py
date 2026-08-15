import pytest
import pytest_asyncio
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.db.database import engine

@pytest_asyncio.fixture(scope="session", autouse=True)
async def db_engine_lifecycle():
    """Ensure the DB engine is correctly disposed after all tests run."""
    yield
    await engine.dispose()

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
