from datetime import datetime

from pydantic import BaseModel


class NotificationCreate(BaseModel):
    recipient_id: str
    type: str = "in-app"
    title: str
    message: str


class NotificationOut(BaseModel):
    id: str
    recipient_id: str
    type: str
    title: str
    message: str
    read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentOut(BaseModel):
    id: str
    document_type: str
    student_id: str | None
    admission_id: str | None
    file_name: str
    mime_type: str
    size: int
    uploaded_by: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class CameraCreate(BaseModel):
    camera_name: str
    location: str | None = None
    stream_url: str


class CameraUpdate(BaseModel):
    camera_name: str | None = None
    location: str | None = None
    stream_url: str | None = None
    status: str | None = None


class CameraOut(BaseModel):
    id: str
    camera_name: str
    location: str | None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class FaceEnrollResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    student_id: str
    enrolled: bool
    sample_count: int
    model_name: str


class FaceRecognizeResponse(BaseModel):
    recognized: bool
    student_id: str | None = None
    student_name: str | None = None
    confidence: float
    attendance_marked: bool


class RecognitionLogOut(BaseModel):
    id: str
    student_id: str | None
    recognition_time: datetime
    confidence: float
    source: str
    camera_id: str | None
    attendance_marked: bool

    class Config:
        from_attributes = True
