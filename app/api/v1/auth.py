import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import invalid_credentials, invalid_token, school_not_found, school_suspended, user_inactive
from app.core.security import create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from app.db.dependencies import CurrentUser, get_current_user
from app.db.session import get_db
from app.models.refresh_token import RefreshToken
from app.models.school import School
from app.models.user import User
from app.schemas.auth import AuthResponse, LoginRequest, ProfileUpdateRequest, RefreshRequest, SessionUserOut, TenantOut, TokenPairOut
from app.services.audit_service import log_action

router = APIRouter(prefix="/auth", tags=["Auth"])
logger = logging.getLogger("ofc360.auth")

COOKIE_NAMES = [settings.COOKIE_NAME, "ofc360_refresh_token", "refresh_token", "eduflow_refresh_token"]


def _set_refresh_cookie(response: Response, token: str):
    is_prod = settings.ENVIRONMENT != "development"
    secure = settings.COOKIE_SECURE if settings.COOKIE_SECURE is not None else is_prod
    response.set_cookie(
        key=settings.COOKIE_NAME,
        value=token,
        httponly=True,
        secure=secure,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        path="/",
    )


def _clear_refresh_cookies(response: Response):
    for c_name in set(COOKIE_NAMES):
        response.delete_cookie(key=c_name, path="/", domain=settings.COOKIE_DOMAIN)
        if settings.COOKIE_DOMAIN:
            response.delete_cookie(key=c_name, path="/")


def _tenant_out(school: School) -> TenantOut:
    return TenantOut(tenant_id=school.id, school_id=school.id, school_code=school.school_code, school_name=school.school_name, status=school.status)


def _user_out(user: User, school: School) -> SessionUserOut:
    return SessionUserOut(
        id=user.id, name=user.name, email=user.email, role=user.role, avatar=user.avatar, status=user.status,
        tenant_id=user.tenant_id, school_id=user.school_id, school_code=school.school_code,
        school_name=school.school_name, permissions=user.permissions_list(),
    )


@router.post("/login", response_model=AuthResponse, summary="Login with school code + email + password")
async def login(payload: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    school = (await db.execute(select(School).where(School.school_code == payload.school_code))).scalar_one_or_none()
    if not school:
        raise school_not_found()
    if school.status != "active":
        raise school_suspended()

    user = (
        await db.execute(select(User).where(User.tenant_id == school.id, User.email == payload.email))
    ).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise invalid_credentials()
    if user.status != "active":
        raise user_inactive()

    user.school = school
    access, access_exp = create_access_token(user)
    refresh, refresh_exp, jti = create_refresh_token(user)

    db.add(RefreshToken(jti=jti, user_id=user.id, tenant_id=user.tenant_id, expires_at=datetime.fromtimestamp(refresh_exp / 1000, tz=timezone.utc)))
    user.last_login_at = datetime.now(timezone.utc)
    await log_action(db, request, school.id, user.id, "login", "user", user.id)
    await db.commit()

    _set_refresh_cookie(response, refresh)
    return AuthResponse(
        access_token=access, refresh_token=refresh, access_expires_at=access_exp, refresh_expires_at=refresh_exp,
        user=_user_out(user, school), tenant=_tenant_out(school),
    )


@router.post("/refresh", response_model=TokenPairOut, summary="Rotate refresh token, issue new access token")
async def refresh(payload: RefreshRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    token = None
    if payload.refresh_token and payload.refresh_token.strip():
        token = payload.refresh_token.strip()
    elif payload.refreshToken and payload.refreshToken.strip():
        token = payload.refreshToken.strip()
    else:
        for c_name in COOKIE_NAMES:
            c_val = request.cookies.get(c_name)
            if c_val and c_val.strip():
                token = c_val.strip()
                break

    if not token:
        logger.warning("AUTH_REFRESH_TOKEN_MISSING: No refresh token in payload or cookies")
        raise invalid_token()

    claims = decode_token(token)
    if not claims or claims.get("type") != "refresh":
        logger.warning("AUTH_REFRESH_TOKEN_INVALID: Claims invalid or token type is not 'refresh'")
        raise invalid_token()

    row = (await db.execute(select(RefreshToken).where(RefreshToken.jti == claims.get("jti")))).scalar_one_or_none()
    if not row:
        logger.warning("AUTH_REFRESH_FAILED: Refresh token jti not found in database")
        raise invalid_token()
    if row.revoked:
        logger.warning("AUTH_REFRESH_FAILED: Refresh token already revoked (jti=%s)", claims.get("jti"))
        raise invalid_token()
    if row.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        logger.warning("AUTH_REFRESH_TOKEN_EXPIRED: Token expired at %s", row.expires_at)
        raise invalid_token()

    user = await db.get(User, claims.get("user_id"))
    if not user or str(user.tenant_id) != str(claims.get("tenant_id")):
        logger.warning("AUTH_REFRESH_FAILED: User not found or tenant mismatch")
        raise invalid_token()
    if user.status != "active":
        logger.warning("AUTH_REFRESH_FAILED: User is not active (status=%s)", user.status)
        raise user_inactive()
    school = await db.get(School, user.tenant_id)
    if not school or school.status != "active":
        logger.warning("AUTH_REFRESH_FAILED: School is not active")
        raise school_suspended()
    user.school = school

    # rotate: revoke old, issue new
    row.revoked = True
    access, access_exp = create_access_token(user)
    new_refresh, refresh_exp, new_jti = create_refresh_token(user)
    db.add(RefreshToken(jti=new_jti, user_id=user.id, tenant_id=user.tenant_id, expires_at=datetime.fromtimestamp(refresh_exp / 1000, tz=timezone.utc)))
    await db.commit()

    _set_refresh_cookie(response, new_refresh)
    logger.info("AUTH_REFRESH_SUCCESS: Rotated token for user_id=%s tenant_id=%s", user.id, user.tenant_id)
    return TokenPairOut(access_token=access, refresh_token=new_refresh, access_expires_at=access_exp, refresh_expires_at=refresh_exp)


@router.post("/logout", summary="Revoke refresh token and clear cookie")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    token = None
    for c_name in COOKIE_NAMES:
        c_val = request.cookies.get(c_name)
        if c_val and c_val.strip():
            token = c_val.strip()
            break

    claims = decode_token(token) if token else None
    if claims and claims.get("type") == "refresh":
        row = (await db.execute(select(RefreshToken).where(RefreshToken.jti == claims.get("jti")))).scalar_one_or_none()
        if row:
            row.revoked = True
            await db.commit()
    _clear_refresh_cookies(response)
    return {"success": True}


@router.get("/me", response_model=SessionUserOut, summary="Current authenticated user")
async def me(current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    user = await db.get(User, current.id)
    school = await db.get(School, current.tenant_id)
    return _user_out(user, school)


@router.put("/profile", response_model=SessionUserOut, summary="Update own profile (name/avatar/password)")
async def update_profile(payload: ProfileUpdateRequest, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    user = await db.get(User, current.id)
    if payload.name is not None:
        user.name = payload.name
    if payload.avatar is not None:
        user.avatar = payload.avatar
    if payload.password:
        user.password_hash = hash_password(payload.password)
    await db.commit()
    school = await db.get(School, current.tenant_id)
    return _user_out(user, school)
