from datetime import datetime

from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str
    phone: str | None = None
    avatar: str | None = None


class UserUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    avatar: str | None = None
    status: str | None = None
    role: str | None = None
    password: str | None = None


class UserOut(BaseModel):
    id: str
    tenant_id: str
    school_id: str
    name: str
    email: str
    role: str
    avatar: str | None
    status: str
    phone: str | None
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
