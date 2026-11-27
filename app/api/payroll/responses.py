"""Response envelope helpers for Payroll module."""
from __future__ import annotations

from typing import Any, Optional
from app.schemas.auth import APIResponse


def success_response(data: Any, message: str = "Success") -> APIResponse[Any]:
    """Return success APIResponse envelope."""
    return APIResponse[Any](
        success=True,
        message=message,
        data=data,
        errors=None,
    )


def error_response(message: str, errors: Optional[list] = None) -> APIResponse[Any]:
    """Return error APIResponse envelope."""
    return APIResponse[Any](
        success=False,
        message=message,
        data=None,
        errors=errors,
    )
