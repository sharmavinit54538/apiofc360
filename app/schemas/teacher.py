from datetime import date, datetime

from pydantic import BaseModel


class TeacherBase(BaseModel):
    employee_id: str
    name: str
    email: str
    phone: str | None = None
    subject: str | None = None
    qualification: str | None = None
    joining_date: date | None = None
    class_assignments: list[str] | None = None
    photo: str | None = None


class TeacherCreate(TeacherBase):
    pass


class TeacherUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    subject: str | None = None
    qualification: str | None = None
    joining_date: date | None = None
    class_assignments: list[str] | None = None
    photo: str | None = None
    status: str | None = None


class TeacherOut(BaseModel):
    id: str
    tenant_id: str
    school_id: str
    employee_id: str
    name: str
    email: str
    phone: str | None
    subject: str | None
    qualification: str | None
    joining_date: date | None
    class_assignments: list[str] | None = None
    photo: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
