from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import conflict, not_found, permission_denied, validation_error
from app.core.security import hash_password
from app.db.dependencies import CurrentUser, get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import Page
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.services.audit_service import log_action

router = APIRouter(prefix="/users", tags=["Users"])


def _require_admin(current: CurrentUser):
    if current.role != "admin":
        raise permission_denied()


@router.get("", response_model=Page[UserOut])
async def list_users(search: str | None = None, role: str | None = None, status: str | None = None,
                      page: int = 1, page_size: int = 20,
                      current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _require_admin(current)
    q = select(User).where(User.tenant_id == current.tenant_id)
    if search:
        like = f"%{search}%"
        q = q.where(or_(User.name.ilike(like), User.email.ilike(like)))
    if role:
        q = q.where(User.role == role)
    if status:
        q = q.where(User.status == status)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    q = q.order_by(User.name).offset((page - 1) * page_size).limit(page_size)
    items = (await db.execute(q)).scalars().all()
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: str, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _require_admin(current)
    u = await db.get(User, user_id)
    if not u or u.tenant_id != current.tenant_id:
        raise not_found("User")
    return u


@router.post("", response_model=UserOut, status_code=201)
async def create_user(payload: UserCreate, request: Request, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _require_admin(current)
    existing = (await db.execute(select(User).where(User.tenant_id == current.tenant_id, User.email == payload.email))).scalar_one_or_none()
    if existing:
        raise conflict("A user with this email already exists", "DUPLICATE_EMAIL")
    u = User(
        tenant_id=current.tenant_id, school_id=current.school_id, name=payload.name, email=payload.email,
        password_hash=hash_password(payload.password), role=payload.role, phone=payload.phone, avatar=payload.avatar,
    )
    db.add(u)
    await db.flush()
    await log_action(db, request, current.tenant_id, current.id, "create", "user", u.id)
    await db.commit()
    await db.refresh(u)
    return u


@router.put("/{user_id}", response_model=UserOut)
async def update_user(user_id: str, payload: UserUpdate, request: Request, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _require_admin(current)
    u = await db.get(User, user_id)
    if not u or u.tenant_id != current.tenant_id:
        raise not_found("User")
    if payload.role and payload.role != u.role and u.id == current.id:
        raise validation_error("You cannot change your own role")
    data = payload.model_dump(exclude_unset=True)
    if "password" in data:
        pw = data.pop("password")
        if pw:
            u.password_hash = hash_password(pw)
    for field, value in data.items():
        setattr(u, field, value)
    await log_action(db, request, current.tenant_id, current.id, "update", "user", u.id)
    await db.commit()
    await db.refresh(u)
    return u


@router.delete("/{user_id}", status_code=204)
async def delete_user(user_id: str, request: Request, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _require_admin(current)
    u = await db.get(User, user_id)
    if not u or u.tenant_id != current.tenant_id:
        raise not_found("User")
    if u.id == current.id:
        raise validation_error("You cannot delete your own account")
    u.status = "inactive"
    await log_action(db, request, current.tenant_id, current.id, "delete", "user", u.id)
    await db.commit()
    return None
