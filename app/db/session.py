"""Compatibility exports for the single HRMS database lifecycle."""
from app.db.database import engine, AsyncSessionLocal, get_db_session
get_db = get_db_session
