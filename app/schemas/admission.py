from datetime import date, datetime

from pydantic import BaseModel


class AdmissionBase(BaseModel):
    student_name: str
    dob: date | None = None
    gender: str | None = None
    class_applying_for: str
    parent_name: str | None = None
    parent_occupation: str | None = None
    contact: str | None = None
    email: str | None = None
    address: str | None = None
    previous_school: str | None = None
    blood_group: str | None = None
    aadhaar: str | None = None
    emergency_contact: str | None = None
    religion: str | None = None
    nationality: str | None = None
    category: str | None = None
    transport_required: bool = False
    hostel_required: bool = False
    photo: str | None = None


class AdmissionCreate(AdmissionBase):
    pass


class AdmissionUpdate(BaseModel):
    student_name: str | None = None
    dob: date | None = None
    gender: str | None = None
    class_applying_for: str | None = None
    parent_name: str | None = None
    parent_occupation: str | None = None
    contact: str | None = None
    email: str | None = None
    address: str | None = None
    previous_school: str | None = None
    blood_group: str | None = None
    aadhaar: str | None = None
    emergency_contact: str | None = None
    religion: str | None = None
    nationality: str | None = None
    category: str | None = None
    transport_required: bool | None = None
    hostel_required: bool | None = None
    photo: str | None = None


class AdmissionStatusUpdate(BaseModel):
    status: str  # verified | approved | rejected
    remarks: str | None = None


class AdmissionOut(AdmissionBase):
    id: str
    tenant_id: str
    school_id: str
    form_number: str
    status: str
    created_by: str | None
    verified_by: str | None
    approved_by: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
