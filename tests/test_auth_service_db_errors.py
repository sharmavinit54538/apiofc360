"""Unit test verifying that database errors during login return 500, not 401."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import status
from sqlalchemy.exc import ProgrammingError, SQLAlchemyError

from app.core.exceptions import AppException
from app.schemas.auth import LoginRequest
from app.services.auth_service import AuthService


@pytest.mark.asyncio
async def test_login_programming_error_returns_500():
    """Verify ProgrammingError raises 500 and not 401."""
    session = AsyncMock()
    repo = AsyncMock()
    email_service = AsyncMock()

    orig_exc = Exception("column companies.status does not exist")
    repo.get_user_by_identifier.side_effect = ProgrammingError(
        statement="SELECT ...",
        params={},
        orig=orig_exc,
    )

    service = AuthService(session=session, auth_repository=repo, email_service=email_service)
    payload = LoginRequest(identifier="user@example.com", password="password123")

    with pytest.raises(AppException) as exc_info:
        await service.login(payload)

    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert "database error" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_login_sqlalchemy_error_returns_500():
    """Verify general SQLAlchemyError raises 500 and not 401."""
    session = AsyncMock()
    repo = AsyncMock()
    email_service = AsyncMock()

    repo.get_user_by_identifier.side_effect = SQLAlchemyError("Connection failed")

    service = AuthService(session=session, auth_repository=repo, email_service=email_service)
    payload = LoginRequest(identifier="user@example.com", password="password123")

    with pytest.raises(AppException) as exc_info:
        await service.login(payload)

    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


@pytest.mark.asyncio
async def test_login_wrong_credentials_returns_401():
    """Verify non-existent user returns 401."""
    session = AsyncMock()
    repo = AsyncMock()
    email_service = AsyncMock()

    repo.get_user_by_identifier.return_value = None

    service = AuthService(session=session, auth_repository=repo, email_service=email_service)
    payload = LoginRequest(identifier="nonexistent@example.com", password="wrongpassword")

    with pytest.raises(AppException) as exc_info:
        await service.login(payload)

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.message == "Invalid email or password."
