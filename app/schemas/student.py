from datetime import date, datetime

from pydantic import BaseModel


class StudentBase(BaseModel):
    admission_number: str
    roll_number: str | None = None
    first_name: str
    last_name: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    class_name: str
    section: str | None = None
    parent_name: str | None = None
    parent_phone: str | None = None
    parent_email: str | None = None
    address: str | None = None
    blood_group: str | None = None
    aadhaar: str | None = None
    nationality: str | None = None
    category: str | None = None
    religion: str | None = None
    emergency_contact: str | None = None
    photo: str | None = None


class StudentCreate(StudentBase):
    pass


class StudentUpdate(BaseModel):
    roll_number: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    class_name: str | None = None
    section: str | None = None
    parent_name: str | None = None
    parent_phone: str | None = None
    parent_email: str | None = None
    address: str | None = None
    blood_group: str | None = None
    aadhaar: str | None = None
    nationality: str | None = None
    category: str | None = None
    religion: str | None = None
    emergency_contact: str | None = None
    photo: str | None = None
    status: str | None = None


class StudentOut(StudentBase):
    id: str
    tenant_id: str
    school_id: str
    full_name: str
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
