"""FastAPI Dependency type aliases for Payroll module."""
from __future__ import annotations

from typing import Annotated
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims, get_current_user_claims_optional

DB = Annotated[AsyncSession, Depends(get_db_session)]
Claims = Annotated[dict, Depends(get_current_user_claims)]
OptionalClaims = Annotated[dict | None, Depends(get_current_user_claims_optional)]
