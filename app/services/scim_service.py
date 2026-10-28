"""SCIM 2.0 user/group provisioning with immediate tenant deprovisioning."""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.redis_client import redis_client
from app.core.security import hash_password
from app.middleware.auth import invalidate_auth_active_cache
from app.models.enterprise_auth import ExternalIdentity, SCIMGroup, SCIMGroupMember, SCIMToken
from app.models.user import User
from app.repositories.auth_repository import AuthRepository

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class SCIMService:
    USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
    GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
    LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_token(self, *, company_id: uuid.UUID, name: str, scopes: list[str], created_by: uuid.UUID, expires_at: datetime | None = None) -> tuple[SCIMToken, str]:
        normalized = sorted(set(scopes))
        if not normalized or any(scope not in {"scim:users", "scim:groups", "scim:*"} for scope in normalized):
            raise ValueError("Invalid SCIM token scopes.")
        prefix = secrets.token_hex(4)
        raw = f"scim_{prefix}_{secrets.token_urlsafe(32)}"
        token = SCIMToken(
            id=uuid.uuid4(), company_id=company_id, name=name.strip(), prefix=prefix,
            token_hash=_hash(raw), scopes=normalized, created_by=created_by, expires_at=expires_at,
        )
        self.session.add(token)
        await self.session.commit()
        return token, raw

    async def authenticate(self, raw_token: str | None, scope: str) -> SCIMToken:
        if not raw_token:
            raise PermissionError("SCIM bearer token is required.")
        token = (await self.session.execute(select(SCIMToken).where(SCIMToken.token_hash == _hash(raw_token)))).scalar_one_or_none()
        if (
            token is None or not token.is_active or token.revoked_at is not None
            or (token.expires_at and _as_utc(token.expires_at) <= _now())
            or ("scim:*" not in token.scopes and scope not in token.scopes)
        ):
            raise PermissionError("Invalid, expired, revoked, or insufficiently scoped SCIM token.")
        token.last_used_at = _now()
        await self.session.commit()
        return token

    async def revoke_token(self, token_id: uuid.UUID, *, company_id: uuid.UUID) -> SCIMToken:
        token = (await self.session.execute(select(SCIMToken).where(
            SCIMToken.id == token_id, SCIMToken.company_id == company_id,
        ))).scalar_one_or_none()
        if token is None:
            raise LookupError("SCIM token not found.")
        token.is_active = False
        token.revoked_at = _now()
        await self.session.commit()
        return token

    async def _user(self, user_id: uuid.UUID, company_id: uuid.UUID) -> User:
        user = (await self.session.execute(select(User).where(
            User.id == user_id, User.company_id == company_id,
        ))).scalar_one_or_none()
        if user is None:
            raise LookupError("SCIM user not found.")
        return user

    @staticmethod
    def user_resource(user: User, base_url: str = "/scim/v2") -> dict[str, Any]:
        name_parts = (user.name or "").split(" ", 1)
        return {
            "schemas": [SCIMService.USER_SCHEMA], "id": str(user.id), "userName": user.email,
            "name": {"formatted": user.name, "givenName": name_parts[0] if name_parts else "", "familyName": name_parts[1] if len(name_parts) > 1 else ""},
            "displayName": user.name, "active": bool(user.is_active and not user.is_deleted),
            "emails": [{"value": user.email, "type": "work", "primary": True}],
            "meta": {"resourceType": "User", "location": f"{base_url}/Users/{user.id}"},
        }

    @staticmethod
    def group_resource(group: SCIMGroup, base_url: str = "/scim/v2") -> dict[str, Any]:
        return {
            "schemas": [SCIMService.GROUP_SCHEMA], "id": str(group.id), "displayName": group.display_name,
            "externalId": group.external_id,
            "members": [{"value": str(member.user_id), "$ref": f"{base_url}/Users/{member.user_id}"} for member in group.members],
            "meta": {"resourceType": "Group", "location": f"{base_url}/Groups/{group.id}"},
        }

    async def list_users(self, *, company_id: uuid.UUID, start_index: int = 1, count: int = 100, filter_text: str | None = None) -> dict:
        start_index, count = max(1, start_index), max(0, min(count, 500))
        stmt = select(User).where(User.company_id == company_id)
        count_stmt = select(func.count(User.id)).where(User.company_id == company_id)
        if filter_text:
            match = re.fullmatch(r'\s*userName\s+eq\s+"([^"]+)"\s*', filter_text, re.IGNORECASE)
            if not match:
                raise ValueError("Only userName eq SCIM filters are supported.")
            email = match.group(1).lower()
            stmt = stmt.where(User.email == email)
            count_stmt = count_stmt.where(User.email == email)
        total = (await self.session.execute(count_stmt)).scalar_one()
        users = (await self.session.execute(stmt.order_by(User.created_at).offset(start_index - 1).limit(count))).scalars().all() if count else []
        return {"schemas": [self.LIST_SCHEMA], "totalResults": total, "startIndex": start_index, "itemsPerPage": len(users), "Resources": [self.user_resource(user) for user in users]}

    async def create_user(self, *, company_id: uuid.UUID, payload: dict) -> User:
        email = str(payload.get("userName") or "").strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ValueError("SCIM userName must be a valid work email.")
        existing = (await self.session.execute(select(User).where(User.email == email).execution_options(bypass_tenant=True))).scalar_one_or_none()
        if existing:
            if existing.company_id != company_id:
                raise PermissionError("Email is already registered to another tenant.")
            raise ValueError("SCIM user already exists.")
        name = payload.get("name") if isinstance(payload.get("name"), dict) else {}
        display_name = str(payload.get("displayName") or name.get("formatted") or " ".join(filter(None, [name.get("givenName"), name.get("familyName")])) or email.split("@")[0])[:100]
        active = bool(payload.get("active", True))
        user = User(
            id=uuid.uuid4(), company_id=company_id, email=email, name=display_name,
            phone=str(uuid.uuid4().int)[:10], password_hash=hash_password(secrets.token_urlsafe(32)),
            role="employee", is_active=active, is_verified=True,
            account_status="ACTIVE" if active else "DEACTIVATED", onboarding_completed=False,
        )
        self.session.add(user)
        await self.session.flush()
        if payload.get("externalId"):
            self.session.add(ExternalIdentity(
                id=uuid.uuid4(), company_id=company_id, user_id=user.id,
                provider_type="SCIM", external_id=str(payload["externalId"]),
                attributes_json={"externalId": str(payload["externalId"])},
            ))
        await self.session.commit()
        return user

    async def get_user(self, user_id: uuid.UUID, *, company_id: uuid.UUID) -> User:
        return await self._user(user_id, company_id)

    async def _set_active(self, user: User, active: bool) -> None:
        previous = bool(user.is_active)
        user.is_active = active
        user.account_status = "ACTIVE" if active else "DEACTIVATED"
        user.is_verified = True
        if previous and not active:
            user.token_version += 1
            await AuthRepository(self.session).revoke_all_user_refresh_tokens(user.id, reason="SCIM_DEPROVISIONING")
            try:
                await redis_client.revoke_user_tokens(user.id)
                await invalidate_auth_active_cache(user.id, user.company_id)
            except Exception as exc:
                logger.warning("SCIM session cache revocation fallback for user %s: %s", user.id, exc)

    async def replace_user(self, user_id: uuid.UUID, *, company_id: uuid.UUID, payload: dict) -> User:
        user = await self._user(user_id, company_id)
        email = str(payload.get("userName") or user.email).strip().lower()
        if email != user.email:
            other = (await self.session.execute(select(User).where(User.email == email).execution_options(bypass_tenant=True))).scalar_one_or_none()
            if other:
                raise ValueError("New userName is already in use.")
            user.email = email
        user.name = str(payload.get("displayName") or user.name)[:100]
        await self._set_active(user, bool(payload.get("active", True)))
        await self.session.commit()
        return user

    async def patch_user(self, user_id: uuid.UUID, *, company_id: uuid.UUID, payload: dict) -> User:
        user = await self._user(user_id, company_id)
        operations = payload.get("Operations")
        if not isinstance(operations, list) or not operations:
            raise ValueError("SCIM PatchOp Operations are required.")
        for operation in operations:
            op = str(operation.get("op") or "").lower()
            if op not in {"replace", "add"}:
                raise ValueError("Only add and replace SCIM user operations are supported.")
            path = str(operation.get("path") or "").lower()
            value = operation.get("value")
            if path == "active":
                await self._set_active(user, bool(value))
            elif path in {"displayname", "name.formatted"}:
                user.name = str(value)[:100]
            elif path == "username":
                raise ValueError("Use PUT to change a SCIM userName safely.")
            elif not path and isinstance(value, dict):
                if "active" in value:
                    await self._set_active(user, bool(value["active"]))
                if "displayName" in value:
                    user.name = str(value["displayName"])[:100]
            else:
                raise ValueError(f"Unsupported SCIM user patch path: {path}")
        await self.session.commit()
        return user

    async def deprovision_user(self, user_id: uuid.UUID, *, company_id: uuid.UUID) -> None:
        user = await self._user(user_id, company_id)
        await self._set_active(user, False)
        await self.session.commit()

    async def _group(self, group_id: uuid.UUID, company_id: uuid.UUID) -> SCIMGroup:
        group = (await self.session.execute(select(SCIMGroup).options(selectinload(SCIMGroup.members)).where(
            SCIMGroup.id == group_id, SCIMGroup.company_id == company_id,
        ))).scalar_one_or_none()
        if group is None:
            raise LookupError("SCIM group not found.")
        return group

    async def list_groups(self, *, company_id: uuid.UUID, start_index: int = 1, count: int = 100) -> dict:
        start_index, count = max(1, start_index), max(0, min(count, 500))
        total = (await self.session.execute(select(func.count(SCIMGroup.id)).where(SCIMGroup.company_id == company_id))).scalar_one()
        groups = (await self.session.execute(select(SCIMGroup).options(selectinload(SCIMGroup.members)).where(
            SCIMGroup.company_id == company_id,
        ).order_by(SCIMGroup.display_name).offset(start_index - 1).limit(count))).scalars().all() if count else []
        return {"schemas": [self.LIST_SCHEMA], "totalResults": total, "startIndex": start_index, "itemsPerPage": len(groups), "Resources": [self.group_resource(group) for group in groups]}

    async def create_group(self, *, company_id: uuid.UUID, payload: dict) -> SCIMGroup:
        display_name = str(payload.get("displayName") or "").strip()
        if not display_name:
            raise ValueError("SCIM group displayName is required.")
        group = SCIMGroup(
            id=uuid.uuid4(), company_id=company_id, display_name=display_name,
            external_id=str(payload["externalId"]) if payload.get("externalId") else None,
        )
        self.session.add(group)
        await self.session.flush()
        await self._replace_members(group, payload.get("members") or [])
        await self.session.commit()
        return await self._group(group.id, company_id)

    async def get_group(self, group_id: uuid.UUID, *, company_id: uuid.UUID) -> SCIMGroup:
        return await self._group(group_id, company_id)

    async def _replace_members(self, group: SCIMGroup, members: list[dict]) -> None:
        user_ids = []
        for member in members:
            try:
                user_ids.append(uuid.UUID(str(member.get("value"))))
            except (ValueError, TypeError) as exc:
                raise ValueError("SCIM group member value must be a user UUID.") from exc
        if user_ids:
            users = (await self.session.execute(select(User.id).where(
                User.company_id == group.company_id, User.id.in_(user_ids),
            ))).scalars().all()
            if set(users) != set(user_ids):
                raise ValueError("SCIM group members must belong to the same tenant.")
        existing = (await self.session.execute(select(SCIMGroupMember).where(SCIMGroupMember.group_id == group.id))).scalars().all()
        for member in existing:
            await self.session.delete(member)
        await self.session.flush()
        for user_id in dict.fromkeys(user_ids):
            self.session.add(SCIMGroupMember(
                id=uuid.uuid4(), company_id=group.company_id, group_id=group.id, user_id=user_id, added_at=_now(),
            ))
        await self.session.flush()

    async def replace_group(self, group_id: uuid.UUID, *, company_id: uuid.UUID, payload: dict) -> SCIMGroup:
        group = await self._group(group_id, company_id)
        group.display_name = str(payload.get("displayName") or group.display_name).strip()
        if "members" in payload:
            await self._replace_members(group, payload["members"] or [])
        await self.session.commit()
        return await self._group(group.id, company_id)

    async def patch_group(self, group_id: uuid.UUID, *, company_id: uuid.UUID, payload: dict) -> SCIMGroup:
        group = await self._group(group_id, company_id)
        for operation in payload.get("Operations") or []:
            op = str(operation.get("op") or "").lower()
            path = str(operation.get("path") or "").lower()
            value = operation.get("value")
            if path == "displayname" and op in {"replace", "add"}:
                group.display_name = str(value).strip()
            elif path == "members" and op == "replace":
                await self._replace_members(group, value or [])
            elif path == "members" and op == "add":
                current = [{"value": str(member.user_id)} for member in group.members]
                by_id = {member["value"]: member for member in current}
                for member in value or []:
                    by_id[str(member.get("value"))] = member
                await self._replace_members(group, list(by_id.values()))
            elif path == "members" and op == "remove":
                remove_ids = {str(member.get("value")) for member in value or []}
                await self._replace_members(group, [{"value": str(member.user_id)} for member in group.members if str(member.user_id) not in remove_ids])
            else:
                raise ValueError("Unsupported SCIM group patch operation.")
        await self.session.commit()
        return await self._group(group.id, company_id)

    async def delete_group(self, group_id: uuid.UUID, *, company_id: uuid.UUID) -> None:
        group = await self._group(group_id, company_id)
        await self.session.delete(group)
        await self.session.commit()
