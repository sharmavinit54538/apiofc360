from datetime import date, datetime

from pydantic import BaseModel


class AttendanceRecordIn(BaseModel):
    student_id: str
    status: str  # present|absent|late|excused
    remarks: str | None = None


class BulkAttendanceIn(BaseModel):
    date: date
    class_name: str
    section: str | None = None
    records: list[AttendanceRecordIn]


class AttendanceOut(BaseModel):
    id: str
    tenant_id: str
    school_id: str
    student_id: str
    date: date
    class_name: str
    section: str | None
    status: str
    source: str
    confidence: float | None
    remarks: str | None
    marked_by: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class AttendanceReportRow(BaseModel):
    student_id: str
    student_name: str
    class_name: str
    section: str | None
    present: int
    absent: int
    late: int
    excused: int
    total: int
    attendance_rate: float
