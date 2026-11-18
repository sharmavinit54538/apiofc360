"""Security regression matrix. Test records are restricted to the disposable harness."""
import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from app.api.v2 import autopilot
from app.middleware.auth import get_current_user_claims
from app.db.database import get_db_session
from app.db.base import tenant_id_ctx

CID, UID = uuid.uuid4(), uuid.uuid4()
ROUTES = list(autopilot.router.routes)


def example(schema, document):
    if "$ref" in schema:
        return example(document["$defs"][schema["$ref"].split("/")[-1]], document)
    if "default" in schema:
        return schema["default"]
    if "enum" in schema:
        return schema["enum"][0]
    if "anyOf" in schema:
        return example(schema["anyOf"][0], document)
    kind = schema.get("type")
    if kind == "object":
        return {k: example(v, document) for k, v in schema.get("properties", {}).items() if k in schema.get("required", [])}
    if kind == "array":
        return [example(schema["items"], document) for _ in range(schema.get("minItems", 0))]
    if kind in ("integer", "number"):
        return schema.get("minimum", 1)
    if kind == "boolean":
        return True
    if schema.get("format") == "uuid":
        return str(uuid.uuid4())
    if schema.get("format") == "date-time":
        return datetime.now(timezone.utc).isoformat()
    return "test"


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
@pytest.mark.parametrize("role,expected", [(None, 401), ("employee", 403), ("hr_admin", 418)])
async def test_all_autopilot_handlers_authenticate_and_bind_actor(route, role, expected, monkeypatch):
    app = FastAPI()
    app.include_router(autopilot.router)
    async def db():
        yield AsyncMock()
    app.dependency_overrides[get_db_session] = db
    if role:
        app.dependency_overrides[get_current_user_claims] = lambda: {"sub": str(UID), "company_id": str(CID), "role": role}
    def service(db, company_id, actor_id):
        assert company_id == CID and actor_id == UID
        raise HTTPException(418, "Handler reached with verified actor and company")
    monkeypatch.setattr(autopilot, "AutopilotService", service)
    path = route.path
    for param in route.dependant.path_params:
        path = path.replace("{" + param.name + "}", str(uuid.uuid4()))
    body = None
    if route.body_field:
        schema = route.body_field.type_.model_json_schema()
        body = example(schema, schema)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(next(iter(route.methods)), path, json=body)
    assert response.status_code == expected, response.text


async def test_diagnostics_and_private_static_are_not_public():
    from app.main import create_app
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        for path in ("/api/v1/cors-debug", "/uploads/helpdesk/private.txt", "/api/v1/face/recognize", "/api/v1/students"):
            response = await client.get(path, headers={"Authorization": "Bearer credential-marker", "Cookie": "private-cookie-marker"})
            assert response.status_code == 404
            assert "credential-marker" not in response.text and "private-cookie-marker" not in response.text


async def test_context_resets_after_concurrent_failure():
    from app.middleware.tenant_context import TenantContextMiddleware
    async def endpoint(scope, receive, send):
        assert tenant_id_ctx.get() is None
        tenant_id_ctx.set(scope["company"])
        await asyncio.sleep(0)
        assert tenant_id_ctx.get() == scope["company"]
        raise RuntimeError("test failure")
    async def request(company):
        with pytest.raises(RuntimeError):
            await TenantContextMiddleware(endpoint)({"company": company}, None, None)
        assert tenant_id_ctx.get() is None
    await asyncio.gather(request(uuid.uuid4()), request(uuid.uuid4()))


async def test_attachment_cross_tenant_and_unattached_owner(tmp_path, monkeypatch):
    from app.services.helpdesk_service import HelpdeskService
    from app.core.exceptions import ForbiddenException, NotFoundException
    from app.core.config import settings
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    db = AsyncMock()
    service = HelpdeskService(db)
    user = SimpleNamespace(company_id=CID, id=UID)
    with pytest.raises(ForbiddenException):
        await service.download_attachment(uuid.uuid4(), user, uuid.uuid4())
    db.scalar.return_value = SimpleNamespace(ticket_id=None, uploader_id=uuid.uuid4())
    with pytest.raises(ForbiddenException):
        await service.download_attachment(uuid.uuid4(), user, CID)
    db.scalar.return_value = SimpleNamespace(ticket_id=None, uploader_id=UID, file_path=str(tmp_path / "../secret.txt"))
    with pytest.raises(NotFoundException):
        await service.download_attachment(uuid.uuid4(), user, CID)


def test_legacy_hash_cannot_verify_faces():
    from app.services.face_service import generate_embedding
    with pytest.raises(RuntimeError):
        generate_embedding(b"not a face")


async def test_principal_rejects_disabled_and_tenant_changed():
    from app.services.principal_validation import validate_principal
    db = AsyncMock()
    claims = {"sub": str(UID), "company_id": str(CID), "role": "employee"}
    user = SimpleNamespace(id=UID, company_id=CID, role="employee", is_deleted=False,
                           is_active=False, is_verified=True, account_status="SUSPENDED")
    db.scalar.return_value = user
    with pytest.raises(HTTPException) as error:
        await validate_principal(db, claims)
    assert error.value.status_code == 403
    user.company_id = uuid.uuid4()
    with pytest.raises(HTTPException) as error:
        await validate_principal(db, claims)
    assert error.value.status_code == 401
