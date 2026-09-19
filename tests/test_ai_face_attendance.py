"""Comprehensive test suite for AI Face Recognition Attendance and Mandatory Enrollment."""

import base64
import io
from unittest.mock import patch
import uuid
import numpy as np
import pytest
from PIL import Image
from httpx import AsyncClient, ASGITransport
from datetime import date, datetime, timezone

from app.main import create_app
from app.db.database import AsyncSessionLocal
from app.models.company import Company
from app.models.user import User, UserRole
from app.models.employee import Employee
from app.attendance.services.face_service import FaceRecognitionService, MATCH_DISTANCE_THRESHOLD
from app.utils.jwt import create_access_token


def make_dummy_base64_image(color=(255, 0, 0), size=(100, 100)) -> str:
    """Create a valid PNG image as base64 string."""
    img = Image.new("RGB", size, color=color)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def generate_unit_vector(dim=128, seed=None) -> list[float]:
    """Generate a unit-normalized vector of specified dimension."""
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(dim)
    vec /= np.linalg.norm(vec)
    return vec.tolist()


# ─────────────────────────────────────────────────────────────────────────────
# UNIT TESTS: FaceRecognitionService
# ─────────────────────────────────────────────────────────────────────────────

def test_face_service_decode_base64():
    """Verify base64 image decoding handles raw base64 and data-URIs."""
    raw_b64 = make_dummy_base64_image()
    rgb = FaceRecognitionService.decode_base64_image(raw_b64)
    assert isinstance(rgb, np.ndarray)
    assert rgb.shape == (100, 100, 3)

    data_uri = f"data:image/jpeg;base64,{raw_b64}"
    rgb_uri = FaceRecognitionService.decode_base64_image(data_uri)
    assert rgb_uri.shape == (100, 100, 3)


def test_face_service_decode_invalid_base64():
    """Verify invalid base64 throws 400."""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        FaceRecognitionService.decode_base64_image("invalid_not_base64_!@#$%")
    assert exc_info.value.status_code == 400


def test_face_service_no_face_detected():
    """Verify solid color image with 0 faces triggers 400 NO FACE DETECTED."""
    from fastapi import HTTPException
    solid_img = np.zeros((100, 100, 3), dtype=np.uint8)
    with pytest.raises(HTTPException) as exc_info:
        FaceRecognitionService.extract_face_embedding(solid_img)
    assert exc_info.value.status_code == 400
    assert "No face detected" in str(exc_info.value.detail)


def test_face_service_compare_embeddings():
    """Verify distance comparison and threshold <= 0.50 behavior."""
    v1 = generate_unit_vector(128, seed=42)
    # Similar vector (distance small)
    v2_arr = np.array(v1) + np.random.normal(0, 0.02, 128)
    v2_arr /= np.linalg.norm(v2_arr)
    v2 = v2_arr.tolist()

    # Distant vector
    v3 = generate_unit_vector(128, seed=999)

    # 1. Matching pair
    is_match, dist = FaceRecognitionService.compare_embeddings(v1, v2, threshold=MATCH_DISTANCE_THRESHOLD)
    assert is_match is True
    assert dist <= MATCH_DISTANCE_THRESHOLD

    # 2. Mismatched pair
    is_match_diff, dist_diff = FaceRecognitionService.compare_embeddings(v1, v3, threshold=MATCH_DISTANCE_THRESHOLD)
    assert is_match_diff is False
    assert dist_diff > MATCH_DISTANCE_THRESHOLD


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRATION TESTS: End-to-end API Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_face_attendance_full_lifecycle():
    """Full lifecycle test for AI Face Recognition Attendance:
    1. Employee check-in before face enrollment fails with 403 FACE_NOT_ENROLLED.
    2. Face status check returns is_enrolled=False.
    3. Face enrollment with blank image (0 faces) fails with 400.
    4. Face enrollment with valid face succeeds and sets is_face_enrolled=True.
    5. Face status check now returns is_enrolled=True.
    6. Check-in with non-matching face returns 400 FACE_MISMATCH.
    7. Check-in with matching face succeeds, records attendance status='Present', punch_type='IN', verified=True.
    """
    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncSessionLocal() as session:
        # Create test company
        comp_id = uuid.uuid4()
        company = Company(
            id=comp_id,
            name=f"Face AI Corp {comp_id.hex[:6]}",
            onboarding_completed=True,
        )
        session.add(company)

        # Create test user
        user_id = uuid.uuid4()
        user_email = f"face_emp_{user_id.hex[:6]}@example.com"
        user = User(
            id=user_id,
            company_id=comp_id,
            name="Face Attendance Employee",
            email=user_email,
            phone=f"98{user_id.int % 100000000:08d}",
            password_hash="dummy_hash",
            role=UserRole.EMPLOYEE,
            account_status="ACTIVE",
            is_active=True,
            is_verified=True,
        )
        session.add(user)

        # Create test employee linked to user
        emp_id = uuid.uuid4()
        employee = Employee(
            id=emp_id,
            user_id=user_id,
            company_id=comp_id,
            employee_id=f"EMP-{user_id.hex[:6].upper()}",
            first_name="Face",
            last_name="Tester",
            personal_email=user_email,
            phone=user.phone,
            department="Engineering",
            designation="Software Engineer",
            status="ACTIVE",
            employment_status="CONFIRMED",
            joining_date=date.today(),
            is_active=True,
            is_face_enrolled=False,
            face_embedding=None,
        )
        session.add(employee)
        await session.commit()

    token = create_access_token(
        user_id=user_id,
        role="employee",
        company_id=comp_id,
        email=user_email,
    )
    headers = {"Authorization": f"Bearer {token}"}

    dummy_image_b64 = make_dummy_base64_image()
    registered_embedding = generate_unit_vector(128, seed=101)
    different_embedding = generate_unit_vector(128, seed=202)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Step 1: Check face status before enrollment -> is_enrolled = False
        status_resp = await client.get("/api/v1/attendance/face-status", headers=headers)
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["is_enrolled"] is False
        assert status_data["enrolled_at"] is None

        # Step 2: Attempt check-in before enrollment -> Expect 403 FACE_NOT_ENROLLED
        checkin_before_resp = await client.post(
            "/api/v1/attendance/checkin",
            headers=headers,
            json={"image_base64": dummy_image_b64, "notes": "Early checkin attempt"},
        )
        assert checkin_before_resp.status_code == 403
        err_json = checkin_before_resp.json()
        assert err_json.get("code") == "FACE_NOT_ENROLLED" or (isinstance(err_json.get("detail"), dict) and err_json["detail"].get("code") == "FACE_NOT_ENROLLED")

        # Step 3: Attempt enrollment with solid image (0 faces detected) -> Expect 400
        enroll_fail_resp = await client.post(
            "/api/v1/attendance/face-enroll",
            headers=headers,
            json={"image_base64": dummy_image_b64},
        )
        # Should fail with 400 No face detected
        assert enroll_fail_resp.status_code == 400

        # Step 4: Enroll face using valid face embedding
        with patch.object(FaceRecognitionService, "extract_face_embedding", return_value=registered_embedding):
            enroll_success_resp = await client.post(
                "/api/v1/attendance/face-enroll",
                headers=headers,
                json={"image_base64": dummy_image_b64},
            )
            assert enroll_success_resp.status_code == 200
            enroll_result = enroll_success_resp.json()
            assert enroll_result["success"] is True
            assert "enrolled successfully" in enroll_result["message"].lower()

        # Step 5: Check face status after enrollment -> is_enrolled = True
        status_after_resp = await client.get("/api/v1/attendance/face-status", headers=headers)
        assert status_after_resp.status_code == 200
        status_after_data = status_after_resp.json()
        assert status_after_data["is_enrolled"] is True
        assert status_after_data["enrolled_at"] is not None

        # Step 6: Check-in with mismatched face embedding -> Expect 400 FACE_MISMATCH
        with patch.object(FaceRecognitionService, "extract_face_embedding", return_value=different_embedding):
            mismatch_resp = await client.post(
                "/api/v1/attendance/checkin",
                headers=headers,
                json={"image_base64": dummy_image_b64},
            )
            assert mismatch_resp.status_code == 400
            mismatch_data = mismatch_resp.json()
            assert mismatch_data.get("code") == "FACE_MISMATCH" or (isinstance(mismatch_data.get("detail"), dict) and mismatch_data["detail"].get("code") == "FACE_MISMATCH")

        # Step 7: Check-in with matching face embedding -> Expect 200 OK
        # Generate matching embedding (distance ~ 0.05 <= 0.50)
        matching_embedding = (np.array(registered_embedding) + np.random.normal(0, 0.005, 128))
        matching_embedding /= np.linalg.norm(matching_embedding)
        matching_embedding = matching_embedding.tolist()

        with patch.object(FaceRecognitionService, "extract_face_embedding", return_value=matching_embedding):
            match_resp = await client.post(
                "/api/v1/attendance/checkin",
                headers=headers,
                json={
                    "image_base64": dummy_image_b64,
                    "location": {"latitude": 28.6139, "longitude": 77.2090},
                    "notes": "Verified morning checkin",
                },
            )
            assert match_resp.status_code == 200
            match_data = match_resp.json()
            assert match_data["success"] is True
            record = match_data["data"]
            assert record["status"] == "Present"
            assert record["punch_type"] == "IN"
            assert record["verified"] is True
            assert record["punch_verified_by"] == "FACE"
            assert record["captured_face_url"] is not None
            assert record["latitude"] == 28.6139
            assert record["longitude"] == 77.2090
            assert record["notes"] == "Verified morning checkin"
