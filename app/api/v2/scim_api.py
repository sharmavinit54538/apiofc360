"""SCIM 2.0 endpoints and tenant-scoped SCIM bearer-token administration."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v2.enterprise_dependencies import Claims, Session, company_id, ok, require_admin, translate, user_id
from app.db.database import get_db_session
from app.models.enterprise_auth import SCIMToken
from app.services.scim_service import SCIMService


class SCIMResponse(JSONResponse):
    media_type = "application/scim+json"


router = APIRouter(prefix="/scim/v2", tags=["SCIM 2.0"], default_response_class=SCIMResponse)
admin_router = APIRouter(prefix="/scim", tags=["SCIM Administration v2"])


async def _bearer_token(authorization: Annotated[str | None, Header()] = None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise PermissionError("SCIM bearer token is required.")
    return authorization.split(" ", 1)[1].strip()


async def users_token(
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db_session),
) -> SCIMToken:
    try:
        raw = await _bearer_token(authorization)
        return await SCIMService(db).authenticate(raw, "scim:users")
    except PermissionError as exc:
        translate(exc)


async def groups_token(
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db_session),
) -> SCIMToken:
    try:
        raw = await _bearer_token(authorization)
        return await SCIMService(db).authenticate(raw, "scim:groups")
    except PermissionError as exc:
        translate(exc)


class TokenRequest(BaseModel):
    name: str
    scopes: list[str] = Field(default_factory=lambda: ["scim:users", "scim:groups"])
    expires_at: datetime | None = None


class UserRequest(BaseModel):
    schemas: list[str] | None = None
    userName: str
    displayName: str | None = None
    name: dict[str, Any] | None = None
    active: bool = True
    externalId: str | None = None
    emails: list[dict] | None = None


class PatchRequest(BaseModel):
    schemas: list[str] | None = None
    Operations: list[dict[str, Any]]


class GroupRequest(BaseModel):
    schemas: list[str] | None = None
    displayName: str
    externalId: str | None = None
    members: list[dict[str, Any]] = Field(default_factory=list)


@admin_router.post("/tokens", status_code=201)
async def create_scim_token(body: TokenRequest, claims: Claims, db: Session):
    require_admin(claims)
    try:
        token, raw = await SCIMService(db).create_token(
            company_id=company_id(claims), created_by=user_id(claims), **body.model_dump(),
        )
        return ok({"id": str(token.id), "prefix": token.prefix, "scopes": token.scopes, "token": raw}, "SCIM token created; copy it now")
    except ValueError as exc:
        translate(exc)


@admin_router.delete("/tokens/{token_id}")
async def revoke_scim_token(token_id: uuid.UUID, claims: Claims, db: Session):
    require_admin(claims)
    try:
        token = await SCIMService(db).revoke_token(token_id, company_id=company_id(claims))
        return ok({"id": str(token.id), "is_active": token.is_active})
    except LookupError as exc:
        translate(exc)


@router.get("/Users")
async def list_users(
    token: Annotated[SCIMToken, Depends(users_token)], db: Session,
    startIndex: int = Query(1, ge=1), count: int = Query(100, ge=0, le=500), filter: str | None = None,
):
    try:
        return await SCIMService(db).list_users(company_id=token.company_id, start_index=startIndex, count=count, filter_text=filter)
    except ValueError as exc:
        translate(exc)


@router.post("/Users", status_code=201)
async def create_user(body: UserRequest, token: Annotated[SCIMToken, Depends(users_token)], db: Session):
    try:
        user = await SCIMService(db).create_user(company_id=token.company_id, payload=body.model_dump(exclude_none=True))
        return SCIMService.user_resource(user)
    except (ValueError, PermissionError) as exc:
        translate(exc)


@router.get("/Users/{user_id}")
async def get_user(user_id: uuid.UUID, token: Annotated[SCIMToken, Depends(users_token)], db: Session):
    try:
        return SCIMService.user_resource(await SCIMService(db).get_user(user_id, company_id=token.company_id))
    except LookupError as exc:
        translate(exc)


@router.put("/Users/{user_id}")
async def replace_user(user_id: uuid.UUID, body: UserRequest, token: Annotated[SCIMToken, Depends(users_token)], db: Session):
    try:
        return SCIMService.user_resource(await SCIMService(db).replace_user(user_id, company_id=token.company_id, payload=body.model_dump(exclude_none=True)))
    except (ValueError, LookupError) as exc:
        translate(exc)


@router.patch("/Users/{user_id}")
async def patch_user(user_id: uuid.UUID, body: PatchRequest, token: Annotated[SCIMToken, Depends(users_token)], db: Session):
    try:
        return SCIMService.user_resource(await SCIMService(db).patch_user(user_id, company_id=token.company_id, payload=body.model_dump()))
    except (ValueError, LookupError) as exc:
        translate(exc)


@router.delete("/Users/{user_id}", status_code=204)
async def deprovision_user(user_id: uuid.UUID, token: Annotated[SCIMToken, Depends(users_token)], db: Session):
    try:
        await SCIMService(db).deprovision_user(user_id, company_id=token.company_id)
        return Response(status_code=204)
    except LookupError as exc:
        translate(exc)


@router.get("/Groups")
async def list_groups(
    token: Annotated[SCIMToken, Depends(groups_token)], db: Session,
    startIndex: int = Query(1, ge=1), count: int = Query(100, ge=0, le=500),
):
    return await SCIMService(db).list_groups(company_id=token.company_id, start_index=startIndex, count=count)


@router.post("/Groups", status_code=201)
async def create_group(body: GroupRequest, token: Annotated[SCIMToken, Depends(groups_token)], db: Session):
    try:
        group = await SCIMService(db).create_group(company_id=token.company_id, payload=body.model_dump(exclude_none=True))
        return SCIMService.group_resource(group)
    except ValueError as exc:
        translate(exc)


@router.get("/Groups/{group_id}")
async def get_group(group_id: uuid.UUID, token: Annotated[SCIMToken, Depends(groups_token)], db: Session):
    try:
        return SCIMService.group_resource(await SCIMService(db).get_group(group_id, company_id=token.company_id))
    except LookupError as exc:
        translate(exc)


@router.put("/Groups/{group_id}")
async def replace_group(group_id: uuid.UUID, body: GroupRequest, token: Annotated[SCIMToken, Depends(groups_token)], db: Session):
    try:
        return SCIMService.group_resource(await SCIMService(db).replace_group(group_id, company_id=token.company_id, payload=body.model_dump(exclude_none=True)))
    except (ValueError, LookupError) as exc:
        translate(exc)


@router.patch("/Groups/{group_id}")
async def patch_group(group_id: uuid.UUID, body: PatchRequest, token: Annotated[SCIMToken, Depends(groups_token)], db: Session):
    try:
        return SCIMService.group_resource(await SCIMService(db).patch_group(group_id, company_id=token.company_id, payload=body.model_dump()))
    except (ValueError, LookupError) as exc:
        translate(exc)


@router.delete("/Groups/{group_id}", status_code=204)
async def delete_group(group_id: uuid.UUID, token: Annotated[SCIMToken, Depends(groups_token)], db: Session):
    try:
        await SCIMService(db).delete_group(group_id, company_id=token.company_id)
        return Response(status_code=204)
    except LookupError as exc:
        translate(exc)
