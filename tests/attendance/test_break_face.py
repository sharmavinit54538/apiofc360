"""Comprehensive test suite for mandatory face verification on Attendance Break endpoints.

Covers:
1. start_break with valid face (200 OK, status ACTIVE, distance, liveness, image_url returned)
2. start_break without image (400 FACE_QUALITY_LOW)
3. start_break with mismatched face (400 FACE_MISMATCH)
4. start_break without active check-in (400 NO_ACTIVE_CHECKIN)
5. double start_break (409 BREAK_ACTIVE)
6. end_break without active break (400 NO_ACTIVE_BREAK)
7. end_break with valid face (200 OK, status COMPLETED, duration_minutes, record.break_duration updated)
8. checkout auto-ending open break without an image (notes tagged, nullable image preserved)
9. multipart/form-data support for break start and break end
"""

import base64
import io
import uuid
from datetime import date, datetime, timezone
from unittest.mock import patch

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import select

from app.attendance.models.attendance import Attendance
from app.attendance.models.attendance_break import AttendanceBreak
from app.attendance.services.face_service import (
    FaceRecognitionService,
    MATCH_DISTANCE_THRESHOLD,
)
from app.db.database import AsyncSessionLocal
from app.main import create_app
from app.models.company import Company
from app.models.employee import Employee
from app.models.user import User, UserRole
from app.utils.jwt import create_access_token


def make_dummy_image_bytes(color=(0, 128, 255), size=(100, 100)) -> bytes:
    """Create a valid JPEG image as raw bytes."""
    img = Image.new("RGB", size, color=color)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG")
    return buffer.getvalue()


def make_dummy_base64_image(color=(0, 128, 255), size=(100, 100)) -> str:
    """Create a valid JPEG image as base64 string."""
    raw = make_dummy_image_bytes(color=color, size=size)
    return base64.b64encode(raw).decode("utf-8")


def generate_unit_vector(dim=128, seed=None) -> list[float]:
    """Generate a unit-normalized vector of specified dimension."""
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(dim)
    vec /= np.linalg.norm(vec)
    return vec.tolist()


def get_error_code(res_json: dict) -> str:
    """Extract error code from multiple potential response payload shapes."""
    if "code" in res_json:
        return res_json["code"]
    if isinstance(res_json.get("error"), dict) and "code" in res_json["error"]:
        return res_json["error"]["code"]
    if isinstance(res_json.get("detail"), dict) and "code" in res_json["detail"]:
        return res_json["detail"]["code"]
    return ""


def get_error_message(res_json: dict) -> str:
    """Extract error message from multiple potential response payload shapes."""
    if "message" in res_json:
        return res_json["message"]
    if isinstance(res_json.get("error"), dict) and "message" in res_json["error"]:
        return res_json["error"]["message"]
    if isinstance(res_json.get("detail"), dict) and "message" in res_json["detail"]:
        return res_json["detail"]["message"]
    if isinstance(res_json.get("detail"), str):
        return res_json["detail"]
    return ""


async def create_test_employee(
    is_face_enrolled: bool = True,
    registered_embedding: list[float] | None = None,
    checked_in: bool = True,
):
    """Seed test company, user, employee, and optionally an active attendance check-in."""
    comp_id = uuid.uuid4()
    user_id = uuid.uuid4()
    emp_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        company = Company(
            id=comp_id,
            name=f"Break Test Corp {comp_id.hex[:6]}",
            onboarding_completed=True,
        )
        session.add(company)

        user_email = f"emp_break_{user_id.hex[:6]}@example.com"
        user = User(
            id=user_id,
            company_id=comp_id,
            name="Break Tester",
            email=user_email,
            phone=f"97{user_id.int % 100000000:08d}",
            password_hash="dummy_hash",
            role=UserRole.EMPLOYEE,
            account_status="ACTIVE",
            is_active=True,
            is_verified=True,
        )
        session.add(user)

        employee = Employee(
            id=emp_id,
            user_id=user_id,
            company_id=comp_id,
            employee_id=f"BRK-{user_id.hex[:6].upper()}",
            first_name="Break",
            last_name="Tester",
            personal_email=user_email,
            phone=user.phone,
            department="Engineering",
            designation="Software Engineer",
            status="ACTIVE",
            employment_status="CONFIRMED",
            joining_date=date.today(),
            is_active=True,
            is_face_enrolled=is_face_enrolled,
            face_embedding=registered_embedding if is_face_enrolled else None,
        )
        session.add(employee)

        att_record = None
        if checked_in:
            att_id = uuid.uuid4()
            now_utc = datetime.now(timezone.utc)
            att_record = Attendance(
                id=att_id,
                employee_id=emp_id,
                company_id=comp_id,
                date=now_utc.date(),
                check_in_time=now_utc,
                status="Present",
                punch_type="IN",
                verified=True,
                punch_verified_by="FACE",
                captured_face_url="https://example.com/checkin.jpg",
                break_duration=0.0,
            )
            session.add(att_record)

        await session.commit()

    token = create_access_token(
        user_id=user_id,
        role="employee",
        company_id=comp_id,
        email=user_email,
    )
    headers = {"Authorization": f"Bearer {token}"}

    return {
        "company_id": comp_id,
        "user_id": user_id,
        "employee_id": emp_id,
        "headers": headers,
        "token": token,
    }


@pytest.mark.asyncio
async def test_break_start_without_image_returns_400():
    """Start break without image must fail fast with HTTP 400 and code FACE_QUALITY_LOW."""
    app = create_app()
    transport = ASGITransport(app=app)
    registered_embedding = generate_unit_vector(128, seed=11)
    data = await create_test_employee(is_face_enrolled=True, registered_embedding=registered_embedding, checked_in=True)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Missing image_base64
        resp = await client.post(
            "/api/v1/attendance/break/start",
            headers=data["headers"],
            json={"notes": "No image sent"},
        )
        assert resp.status_code == 400
        res_json = resp.json()
        assert get_error_code(res_json) == "FACE_QUALITY_LOW"
        assert "Face image is required" in get_error_message(res_json)

        # 2. Empty string image_base64
        resp_empty = await client.post(
            "/api/v1/attendance/break/start",
            headers=data["headers"],
            json={"image_base64": "", "notes": "Empty image string"},
        )
        assert resp_empty.status_code == 400
        res_json_empty = resp_empty.json()
        assert get_error_code(res_json_empty) == "FACE_QUALITY_LOW"


@pytest.mark.asyncio
async def test_break_start_without_checkin_returns_400():
    """Start break before checking in must fail fast with 400 NO_ACTIVE_CHECKIN before face matching."""
    app = create_app()
    transport = ASGITransport(app=app)
    registered_embedding = generate_unit_vector(128, seed=12)
    data = await create_test_employee(is_face_enrolled=True, registered_embedding=registered_embedding, checked_in=False)

    dummy_b64 = make_dummy_base64_image()

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/v1/attendance/break/start",
            headers=data["headers"],
            json={"image_base64": dummy_b64, "notes": "Break before checkin"},
        )
        assert resp.status_code == 400
        res_json = resp.json()
        assert get_error_code(res_json) == "NO_ACTIVE_CHECKIN"


@pytest.mark.asyncio
async def test_break_start_with_mismatched_face_returns_400():
    """Start break with mismatched face embedding must return 400 FACE_MISMATCH."""
    app = create_app()
    transport = ASGITransport(app=app)
    registered_embedding = generate_unit_vector(128, seed=13)
    data = await create_test_employee(is_face_enrolled=True, registered_embedding=registered_embedding, checked_in=True)

    dummy_b64 = make_dummy_base64_image()
    different_embedding = generate_unit_vector(128, seed=999)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        with patch.object(FaceRecognitionService, "extract_face_embedding", return_value=(different_embedding, 0.95)):
            resp = await client.post(
                "/api/v1/attendance/break/start",
                headers=data["headers"],
                json={"image_base64": dummy_b64, "notes": "Imposter break"},
            )
            assert resp.status_code == 400
            res_json = resp.json()
            assert get_error_code(res_json) == "FACE_MISMATCH"


@pytest.mark.asyncio
async def test_break_start_and_end_lifecycle_success():
    """Full successful break flow:
    1. Start break with valid matching face -> 200 ACTIVE, face_distance, liveness_score, image_url.
    2. Attempt second start -> 409 BREAK_ACTIVE.
    3. End break without image -> 400 FACE_QUALITY_LOW.
    4. End break with valid face -> 200 COMPLETED, face_distance, duration_minutes, updates Attendance.break_duration.
    5. Attempt second end -> 400 NO_ACTIVE_BREAK.
    """
    app = create_app()
    transport = ASGITransport(app=app)
    registered_embedding = generate_unit_vector(128, seed=14)
    data = await create_test_employee(is_face_enrolled=True, registered_embedding=registered_embedding, checked_in=True)

    dummy_b64 = make_dummy_base64_image()
    matching_embedding = (np.array(registered_embedding) + np.random.normal(0, 0.005, 128))
    matching_embedding /= np.linalg.norm(matching_embedding)
    matching_embedding = matching_embedding.tolist()

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Start break with valid face
        with patch.object(FaceRecognitionService, "extract_face_embedding", return_value=(matching_embedding, 0.95)):
            start_resp = await client.post(
                "/api/v1/attendance/break/start",
                headers=data["headers"],
                json={
                    "image_base64": dummy_b64,
                    "location": {"latitude": 28.6139, "longitude": 77.2090, "accuracy": 5.0},
                    "notes": "Coffee break",
                },
            )
            assert start_resp.status_code == 200
            start_data = start_resp.json()
            assert start_data["success"] is True
            record = start_data["data"]
            assert record["status"] == "ACTIVE"
            assert record["notes"] == "Coffee break"
            assert record["face_distance"] is not None
            assert record["face_distance"] <= MATCH_DISTANCE_THRESHOLD
            assert record["liveness_score"] is not None
            assert record["image_url"] is not None
            assert record["start_image_url"] is not None
            break_id = uuid.UUID(record["id"])

        # Verify DB values for start
        async with AsyncSessionLocal() as session:
            db_break = await session.get(AttendanceBreak, break_id)
            assert db_break is not None
            assert db_break.status == "ACTIVE"
            assert db_break.start_face_distance is not None
            assert db_break.start_face_distance <= MATCH_DISTANCE_THRESHOLD
            assert db_break.start_liveness_score is not None
            assert db_break.start_image_url is not None
            assert db_break.start_latitude == 28.6139
            assert db_break.start_longitude == 77.2090

        # 2. Attempt double start -> 409 BREAK_ACTIVE
        with patch.object(FaceRecognitionService, "extract_face_embedding", return_value=(matching_embedding, 0.95)):
            double_resp = await client.post(
                "/api/v1/attendance/break/start",
                headers=data["headers"],
                json={"image_base64": dummy_b64, "notes": "Double start"},
            )
            assert double_resp.status_code == 409
            assert get_error_code(double_resp.json()) == "BREAK_ACTIVE"

        # 3. Attempt end break without image -> 400 FACE_QUALITY_LOW
        end_no_img = await client.post(
            "/api/v1/attendance/break/end",
            headers=data["headers"],
            json={},
        )
        assert end_no_img.status_code == 400
        assert get_error_code(end_no_img.json()) == "FACE_QUALITY_LOW"

        # 4. End break with valid face -> 200 COMPLETED
        with patch.object(FaceRecognitionService, "extract_face_embedding", return_value=(matching_embedding, 0.95)):
            end_resp = await client.post(
                "/api/v1/attendance/break/end",
                headers=data["headers"],
                json={
                    "image_base64": dummy_b64,
                    "location": {"latitude": 28.6140, "longitude": 77.2091},
                },
            )
            assert end_resp.status_code == 200
            end_data = end_resp.json()
            assert end_data["success"] is True
            ended_record = end_data["data"]
            assert ended_record["status"] == "COMPLETED"
            assert ended_record["duration_minutes"] is not None
            assert ended_record["face_distance"] is not None
            assert ended_record["liveness_score"] is not None
            assert ended_record["image_url"] is not None
            assert ended_record["end_image_url"] is not None

        # Verify DB values for end and parent Attendance
        async with AsyncSessionLocal() as session:
            db_break = await session.get(AttendanceBreak, break_id)
            assert db_break.status == "COMPLETED"
            assert db_break.end_face_distance is not None
            assert db_break.end_liveness_score is not None
            assert db_break.end_image_url is not None
            assert db_break.end_latitude == 28.6140
            assert db_break.end_longitude == 77.2091

            att_stmt = select(Attendance).where(Attendance.employee_id == data["employee_id"])
            att_res = await session.execute(att_stmt)
            att_row = att_res.scalar_one()
            # break_duration is recorded in hours
            assert att_row.break_duration is not None
            assert att_row.break_duration >= 0.0

        # 5. Attempt second end without active break -> 400 NO_ACTIVE_BREAK
        with patch.object(FaceRecognitionService, "extract_face_embedding", return_value=(matching_embedding, 0.95)):
            second_end_resp = await client.post(
                "/api/v1/attendance/break/end",
                headers=data["headers"],
                json={"image_base64": dummy_b64},
            )
            assert second_end_resp.status_code == 400
            assert get_error_code(second_end_resp.json()) == "NO_ACTIVE_BREAK"


@pytest.mark.asyncio
async def test_checkout_auto_ends_open_break_without_break_image():
    """Checkout step 7 must auto-complete open break without requiring face image for the break.
    Verifies that the auto-ended break notes are marked and nullable biometrics remain valid.
    """
    app = create_app()
    transport = ASGITransport(app=app)
    registered_embedding = generate_unit_vector(128, seed=15)
    data = await create_test_employee(is_face_enrolled=True, registered_embedding=registered_embedding, checked_in=True)

    dummy_b64 = make_dummy_base64_image()
    matching_embedding = (np.array(registered_embedding) + np.random.normal(0, 0.005, 128))
    matching_embedding /= np.linalg.norm(matching_embedding)
    matching_embedding = matching_embedding.tolist()

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Start break with face
        with patch.object(FaceRecognitionService, "extract_face_embedding", return_value=(matching_embedding, 0.95)):
            start_resp = await client.post(
                "/api/v1/attendance/break/start",
                headers=data["headers"],
                json={"image_base64": dummy_b64, "notes": "Lunch before checkout"},
            )
            assert start_resp.status_code == 200
            break_id = uuid.UUID(start_resp.json()["data"]["id"])

        # 2. Perform checkout (only provides checkout face, NOT break face)
        with patch.object(FaceRecognitionService, "extract_face_embedding", return_value=(matching_embedding, 0.95)):
            checkout_resp = await client.post(
                "/api/v1/attendance/checkout",
                headers=data["headers"],
                json={
                    "image_base64": dummy_b64,
                    "location": {"latitude": 28.6139, "longitude": 77.2090},
                    "notes": "Leaving office",
                },
            )
            assert checkout_resp.status_code == 200
            checkout_data = checkout_resp.json()
            assert checkout_data["success"] is True

        # 3. Verify DB: break was auto-completed gracefully
        async with AsyncSessionLocal() as session:
            db_break = await session.get(AttendanceBreak, break_id)
            assert db_break.status == "COMPLETED"
            assert "Auto-ended at checkout" in (db_break.notes or "")
            assert db_break.end_image_url is None
            assert db_break.end_face_distance is None
            assert db_break.duration_minutes is not None


@pytest.mark.asyncio
async def test_break_multipart_form_data_support():
    """Verify POST /attendance/break/start and /break/end accept multipart/form-data."""
    app = create_app()
    transport = ASGITransport(app=app)
    registered_embedding = generate_unit_vector(128, seed=16)
    data = await create_test_employee(is_face_enrolled=True, registered_embedding=registered_embedding, checked_in=True)

    img_bytes = make_dummy_image_bytes()
    matching_embedding = (np.array(registered_embedding) + np.random.normal(0, 0.005, 128))
    matching_embedding /= np.linalg.norm(matching_embedding)
    matching_embedding = matching_embedding.tolist()

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Multipart break start
        with patch.object(FaceRecognitionService, "extract_face_embedding", return_value=(matching_embedding, 0.95)):
            files = {"file": ("face_start.jpg", img_bytes, "image/jpeg")}
            form_data = {
                "notes": "Multipart start test",
                "latitude": "28.6139",
                "longitude": "77.2090",
                "accuracy": "8.5",
            }
            start_resp = await client.post(
                "/api/v1/attendance/break/start",
                headers=data["headers"],
                files=files,
                data=form_data,
            )
            assert start_resp.status_code == 200
            start_data = start_resp.json()
            assert start_data["success"] is True
            assert start_data["data"]["status"] == "ACTIVE"
            assert start_data["data"]["face_distance"] <= MATCH_DISTANCE_THRESHOLD
            assert start_data["data"]["notes"] == "Multipart start test"

        # 2. Multipart break end
        with patch.object(FaceRecognitionService, "extract_face_embedding", return_value=(matching_embedding, 0.95)):
            files = {"file": ("face_end.jpg", img_bytes, "image/jpeg")}
            form_data = {
                "latitude": "28.6141",
                "longitude": "77.2092",
            }
            end_resp = await client.post(
                "/api/v1/attendance/break/end",
                headers=data["headers"],
                files=files,
                data=form_data,
            )
            assert end_resp.status_code == 200
            end_data = end_resp.json()
            assert end_data["success"] is True
            assert end_data["data"]["status"] == "COMPLETED"
            assert end_data["data"]["duration_minutes"] is not None
            assert end_data["data"]["face_distance"] <= MATCH_DISTANCE_THRESHOLD
