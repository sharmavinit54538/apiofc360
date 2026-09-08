from pydantic import BaseModel


class DashboardSummary(BaseModel):
    totalStudents: int
    totalTeachers: int
    attendanceRate: float
    absentToday: int


class AttendanceTrendPoint(BaseModel):
    day: str
    rate: float


class ClassAttendancePoint(BaseModel):
    name: str
    attendance: float
