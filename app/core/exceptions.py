"""Application exceptions and common error response handlers."""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

ErrorList = list[dict[str, str | None]]


class AppException(Exception):
    """Base application exception rendered through the common response envelope."""

    def __init__(
        self,
        *,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        code: str | None = None,
        errors: ErrorList | None = None,
        field: str | None = None,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.code = code
        self.errors = errors
        self.field = field
        super().__init__(message)


class ValidationException(AppException):
    """Business validation failure."""

    def __init__(self, *, message: str = "Validation failed.", code: str = "VALIDATION_FAILED", errors: ErrorList | None = None, field: str | None = None) -> None:
        super().__init__(message=message, status_code=status.HTTP_400_BAD_REQUEST, code=code, errors=errors, field=field)


class ConflictException(AppException):
    """Resource conflict failure."""

    def __init__(self, *, message: str, code: str = "CONFLICT", errors: ErrorList | None = None, field: str | None = None) -> None:
        super().__init__(message=message, status_code=status.HTTP_409_CONFLICT, code=code, errors=errors, field=field)


class DatabaseException(AppException):
    """Database operation failure."""

    def __init__(self, *, message: str = "Internal server error.", code: str = "DATABASE_ERROR") -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code=code,
            errors=[{"field": None, "message": message}],
        )


class NotFoundException(AppException):
    """Resource not found failure."""

    def __init__(self, message: str = "Resource not found.", code: str = "NOT_FOUND", errors: ErrorList | None = None) -> None:
        super().__init__(message=message, status_code=status.HTTP_404_NOT_FOUND, code=code, errors=errors)


class BadRequestException(AppException):
    """Bad request exception."""

    def __init__(self, message: str, code: str = "BAD_REQUEST", errors: ErrorList | None = None) -> None:
        super().__init__(message=message, status_code=status.HTTP_400_BAD_REQUEST, code=code, errors=errors)


class ForbiddenException(AppException):
    """Forbidden access failure."""

    def __init__(self, message: str = "Access forbidden.", code: str = "FORBIDDEN", errors: ErrorList | None = None) -> None:
        super().__init__(message=message, status_code=status.HTTP_403_FORBIDDEN, code=code, errors=errors)


class UnauthorizedException(AppException):
    """Authentication required failure."""

    def __init__(self, message: str = "Authentication required.", code: str = "UNAUTHORIZED", errors: ErrorList | None = None) -> None:
        super().__init__(message=message, status_code=status.HTTP_401_UNAUTHORIZED, code=code, errors=errors)


def add_cors_headers(request: Request, response: JSONResponse) -> JSONResponse:
    """Inject CORS headers manually for exception responses."""
    import re
    from app.core.config import settings

    origin = request.headers.get("origin")
    if origin:
        is_allowed = False
        allowed_origins = [
            "https://www.ofc360.com",
            "https://ofc360.com",
            "https://api.ofc360.com",
        ] + list(settings.ALLOWED_ORIGINS) + list(settings.BACKEND_CORS_ORIGINS) + list(settings.DEV_CORS_ORIGINS)
        if origin in allowed_origins:
            is_allowed = True
        else:
            allowed_regex = r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+)(:\d+)?"
            if re.match(allowed_regex, origin):
                is_allowed = True

        if is_allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Expose-Headers"] = "Authorization"
            response.headers["Vary"] = "Origin"

    return response


def error_response_content(
    *,
    message: str,
    code: str | None = None,
    errors: ErrorList | None = None,
    field: str | None = None,
) -> dict[str, Any]:
    """Build a common error response payload."""

    response_data: dict[str, Any] = {
        "success": False,
        "message": message,
        "data": None,
        "errors": errors or [{"field": field, "message": message}],
    }
    if code is not None:
        response_data["code"] = code
        response_data["error"] = {"code": code, "message": message}
    if field is not None:
        response_data["field"] = field
    return response_data


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Render known application exceptions."""

    user_id = None
    role = None
    if hasattr(request.state, "user_claims"):
        claims = request.state.user_claims
        user_id = claims.get("sub")
        role = claims.get("role")

    log_msg = f"AppException on {request.method} {request.url.path} | User: {user_id} | Role: {role} | Status: {exc.status_code} | Msg: {exc.message}"
    if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        logger.error(log_msg)
    elif exc.status_code in (401, 403, 404):
        logger.info(log_msg)
    else:
        logger.warning(log_msg)

    response = JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder(
            error_response_content(
                message=exc.message,
                code=getattr(exc, "code", None),
                errors=exc.errors,
                field=getattr(exc, "field", None),
            )
        ),
    )
    return add_cors_headers(request, response)


async def request_validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Render Pydantic v2 request validation errors with human-readable messages.

    Improvements over the default FastAPI handler:
    - Logs the raw request body for debugging 422s
    - Converts Pydantic v2 error types into plain-English messages
    - Returns the first error's field at the top level for simple frontends
    - Includes all errors in the `errors` list
    """

    # ── Extract user identity from claims if available ──────────────────────
    user_id: str | None = None
    role: str | None = None
    if hasattr(request.state, "user_claims"):
        claims = request.state.user_claims
        user_id = claims.get("sub")
        role = claims.get("role")

    # ── Capture request body for logging (best-effort) ──────────────────────
    body_preview: str = "<unreadable>"
    try:
        raw_body = await request.body()
        body_preview = raw_body.decode("utf-8", errors="replace")[:500]
    except Exception:
        pass

    # ── Build human-readable error list ─────────────────────────────────────
    _FRIENDLY: dict[str, str] = {
        "missing":          "is required.",
        "string_too_short": "is too short.",
        "string_too_long":  "is too long.",
        "int_parsing":      "must be a valid integer.",
        "float_parsing":    "must be a valid number.",
        "uuid_parsing":     "must be a valid UUID (e.g. 3fa85f64-5717-4562-b3fc-2c963f66afa6).",
        "uuid_type":        "must be a valid UUID string.",
        "enum":             "has an invalid value.",
        "literal_error":    "has an invalid value.",
        "bool_parsing":     "must be true or false.",
        "value_error":      "",  # use the custom msg from the validator
        "json_invalid":     "Request body must be valid JSON.",
        "json_type":        "Request body must be a JSON object.",
    }

    errors: ErrorList = []
    for error in exc.errors():
        location = error.get("loc", ())
        # Strip FastAPI's internal location prefixes (body, query, path)
        field_parts = [str(p) for p in location if p not in {"body", "query", "path"}]
        field = ".".join(field_parts) if field_parts else None

        error_type = error.get("type", "")
        raw_msg = str(error.get("msg", "Invalid input")).removeprefix("Value error, ")

        # Build a friendly, field-specific message
        if error_type == "missing" and field:
            msg = f"{field} is required."
        elif error_type in ("uuid_parsing", "uuid_type") and field:
            msg = f"{field} must be a valid UUID (e.g. 3fa85f64-5717-4562-b3fc-2c963f66afa6)."
        elif error_type in ("literal_error", "enum") and field:
            # Extract the allowed values from the Pydantic context
            ctx = error.get("ctx", {})
            expected = ctx.get("expected", "")
            if expected:
                msg = f"{field} must be one of: {expected}."
            else:
                msg = f"{field} has an invalid value. {raw_msg}"
        elif error_type == "string_too_short" and field:
            ctx = error.get("ctx", {})
            min_len = ctx.get("min_length", 1)
            msg = f"{field} must be at least {min_len} character(s) long."
        elif error_type == "string_too_long" and field:
            ctx = error.get("ctx", {})
            max_len = ctx.get("max_length", "")
            msg = f"{field} must be at most {max_len} characters long."
        elif error_type in ("int_parsing", "int_type") and field:
            msg = f"{field} must be a valid integer."
        elif error_type in ("float_parsing", "float_type", "decimal_parsing") and field:
            msg = f"{field} must be a valid number."
        elif error_type == "greater_than_equal" and field:
            ctx = error.get("ctx", {})
            msg = f"{field} must be greater than or equal to {ctx.get('ge', '')}."
        elif error_type == "less_than_equal" and field:
            ctx = error.get("ctx", {})
            msg = f"{field} must be less than or equal to {ctx.get('le', '')}."
        elif error_type in ("json_invalid", "json_type"):
            msg = "Request body must be valid JSON."
            field = None
        else:
            friendly = _FRIENDLY.get(error_type, "")
            msg = f"{field} {friendly}".strip() if (field and friendly) else raw_msg

        errors.append({"field": field, "message": msg})

    # Use the first error as the top-level message for simple frontend consumption
    first = errors[0] if errors else {"field": None, "message": "Validation failed."}
    top_message = first["message"]

    logger.warning(
        "422 Validation error | %s %s | user=%s | role=%s | errors=%d | body=%s | details=%s",
        request.method,
        request.url.path,
        user_id,
        role,
        len(errors),
        body_preview,
        str(errors),
    )

    response_body = {
        "success": False,
        "message": top_message,
        "field": first.get("field"),
        "data": None,
        "errors": errors,
    }

    response = JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=jsonable_encoder(response_body),
    )
    return add_cors_headers(request, response)




async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Render HTTP exceptions with the common response envelope."""

    status_code = exc.status_code
    message = str(exc.detail) if exc.detail else "Request failed."

    user_id = None
    role = None
    if hasattr(request.state, "user_claims"):
        claims = request.state.user_claims
        user_id = claims.get("sub")
        role = claims.get("role")

    log_msg = f"HTTPException on {request.method} {request.url.path} | User: {user_id} | Role: {role} | Status: {status_code} | Msg: {message}"
    if status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        logger.error(log_msg)
    elif status_code in (401, 403, 404):
        logger.info(log_msg)
    else:
        logger.warning(log_msg)
    response = JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(error_response_content(message=message)),
    )
    return add_cors_headers(request, response)


async def database_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """Render uncaught database exceptions without leaking internals."""

    user_id = None
    role = None
    if hasattr(request.state, "user_claims"):
        claims = request.state.user_claims
        user_id = claims.get("sub")
        role = claims.get("role")

    logger.exception(
        "Database error on %s %s | User: %s | Role: %s", 
        request.method, 
        request.url.path, 
        user_id, 
        role, 
        exc_info=exc
    )
    response = JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=jsonable_encoder(error_response_content(message="Internal server error.")),
    )
    return add_cors_headers(request, response)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render uncaught exceptions without leaking internals."""

    user_id = None
    role = None
    if hasattr(request.state, "user_claims"):
        claims = request.state.user_claims
        user_id = claims.get("sub")
        role = claims.get("role")

    logger.exception(
        "Unhandled error on %s %s | User: %s | Role: %s", 
        request.method, 
        request.url.path, 
        user_id, 
        role, 
        exc_info=exc
    )
    response = JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=jsonable_encoder(error_response_content(message="Internal server error.")),
    )
    return add_cors_headers(request, response)


from pydantic import ValidationError, BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


async def pydantic_validation_exception_handler(request: Request, exc: ValidationError) -> JSONResponse:
    """Map manual Pydantic ValidationError instances to standard 422 Unprocessable Entity response."""
    return await request_validation_exception_handler(request, RequestValidationError(exc.errors()))


def install_exception_handlers(app: FastAPI) -> None:
    """Register global exception handlers on a FastAPI app."""

    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    app.add_exception_handler(ValidationError, pydantic_validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(SQLAlchemyError, database_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
