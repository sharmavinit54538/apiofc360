import base64
import io
import logging
from unittest.mock import patch, MagicMock
import uuid
import numpy as np
import pytest
from PIL import Image
from httpx import AsyncClient, ASGITransport
from datetime import date, datetime, timezone, timedelta

from app.main import create_app
from app.db.database import AsyncSessionLocal
from app.models.company import Company
from app.models.user import User, UserRole
from app.models.employee import Employee
from app.attendance.services.face_service import FaceRecognitionService, MATCH_DISTANCE_THRESHOLD
from app.utils.jwt import create_access_token
from sqlalchemy import insert


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
        with patch.object(FaceRecognitionService, "extract_face_embedding", return_value=(registered_embedding, 0.95)):
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
        with patch.object(FaceRecognitionService, "extract_face_embedding", return_value=(different_embedding, 0.95)):
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

        with patch.object(FaceRecognitionService, "extract_face_embedding", return_value=(matching_embedding, 0.95)):
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


# ─────────────────────────────────────────────────────────────────────────────
# STALE SESSION AUTO-CLOSE & SAME-DAY ACTIVE SESSION TESTS
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_checkin_auto_closes_stale_previous_day_session():
    """
    Test that checking in when a stale open session from yesterday exists
    auto-closes yesterday's session and succeeds with 200/201.
    """
    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncSessionLocal() as session:
        # Create test company
        comp_id = uuid.uuid4()
        company = Company(
            id=comp_id,
            name=f"Stale Session Corp {comp_id.hex[:6]}",
            onboarding_completed=True,
        )
        session.add(company)

        # Create test user
        user_id = uuid.uuid4()
        user_email = f"stale_emp_{user_id.hex[:6]}@example.com"
        user = User(
            id=user_id,
            company_id=comp_id,
            name="Stale Session Employee",
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
            first_name="Stale",
            last_name="Tester",
            personal_email=user_email,
            phone=user.phone,
            department="Engineering",
            designation="Software Engineer",
            status="ACTIVE",
            employment_status="CONFIRMED",
            joining_date=date.today(),
            is_active=True,
            is_face_enrolled=True,
            face_embedding=b"dummy_encrypted_embedding",
        )
        session.add(employee)

        # Create a STALE active session from yesterday (check_out_time = NULL)
        yesterday = date.today() - timedelta(days=1)
        yesterday_utc = datetime.combine(yesterday, datetime.min.time()).replace(tzinfo=timezone.utc)
        stale_session_id = uuid.uuid4()
        await session.execute(
            insert(Attendance).values(
                id=stale_session_id,
                employee_id=emp_id,
                company_id=comp_id,
                date=yesterday,
                check_in_time=yesterday_utc,
                check_out_time=None,  # Active session
                face_image_url="test.jpg",
                captured_face_url="test.jpg",
                status="Present",
                punch_type="IN",
                verified=True,
                punch_verified_by="FACE",
                auto_closed=False,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
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
    matching_embedding = (np.array(registered_embedding) + np.random.normal(0, 0.005, 128))
    matching_embedding /= np.linalg.norm(matching_embedding)
    matching_embedding = matching_embedding.tolist()

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Enroll face first
        with patch.object(FaceRecognitionService, "extract_face_embedding", return_value=(registered_embedding, 0.95)):
            enroll_resp = await client.post(
                "/api/v1/attendance/face-enroll",
                headers=headers,
                json={"image_base64": dummy_image_b64},
            )
            assert enroll_resp.status_code == 200

        # Check-in with matching face - should AUTO-CLOSE stale session and succeed
        with patch.object(FaceRecognitionService, "extract_face_embedding", return_value=(matching_embedding, 0.95)):
            checkin_resp = await client.post(
                "/api/v1/attendance/checkin",
                headers=headers,
                json={
                    "image_base64": dummy_image_b64,
                    "location": {"latitude": 28.6139, "longitude": 77.2090},
                    "notes": "New day checkin",
                },
            )
            # Should succeed (200 or 201) - stale session was auto-closed
            assert checkin_resp.status_code in (200, 201), f"Expected 200/201, got {checkin_resp.status_code}: {checkin_resp.text}"
            checkin_data = checkin_resp.json()
            assert checkin_data["success"] is True
            record = checkin_data["data"]
            assert record["status"] == "Present"
            assert record["punch_type"] == "IN"
            assert record["verified"] is True

            # Verify the new check-in has today's date
            assert record["date"] == date.today().isoformat()

        # Verify the stale session was auto-closed
        async with AsyncSessionLocal() as verify_session:
            from sqlalchemy import select
            from app.attendance.models.attendance import Attendance as FaceAttendance
            stale_check = await verify_session.execute(
                select(FaceAttendance).where(FaceAttendance.id == stale_session_id)
            )
            stale_record = stale_check.scalars().first()
            assert stale_record is not None
            assert stale_record.check_out_time is not None, "Stale session should be auto-closed"
            assert stale_record.auto_closed is True, "Stale session should have auto_closed=True"
            assert "Auto-closed" in (stale_record.notes or ""), "Stale session notes should mention auto-close"


@ pytest.mark.asyncio
async def test_checkin_same_day_active_session_returns_session_details():
    """
    Test that checking in when an active session from TODAY exists
    returns 409 with active_session details for frontend sync.
    """
    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncSessionLocal() as session:
        # Create test company
        comp_id = uuid.uuid4()
        company = Company(
            id=comp_id,
            name=f"SameDay Session Corp {comp_id.hex[:6]}",
            onboarding_completed=True,
        )
        session.add(company)

        # Create test user
        user_id = uuid.uuid4()
        user_email = f"sameday_emp_{user_id.hex[:6]}@example.com"
        user = User(
            id=user_id,
            company_id=comp_id,
            name="Same Day Employee",
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
            first_name="SameDay",
            last_name="Tester",
            personal_email=user_email,
            phone=user.phone,
            department="Engineering",
            designation="Software Engineer",
            status="ACTIVE",
            employment_status="CONFIRMED",
            joining_date=date.today(),
            is_active=True,
            is_face_enrolled=True,
            face_embedding=b"dummy_encrypted_embedding",
        )
        session.add(employee)

        # Create an ACTIVE session from TODAY (check_out_time = NULL)
        today_utc = datetime.now(timezone.utc).replace(microsecond=0)
        active_session_id = uuid.uuid4()
        await session.execute(
            insert(Attendance).values(
                id=active_session_id,
                employee_id=emp_id,
                company_id=comp_id,
                date=date.today(),
                check_in_time=today_utc,
                check_out_time=None,  # Still active
                face_image_url="test.jpg",
                captured_face_url="test.jpg",
                status="Present",
                punch_type="IN",
                verified=True,
                punch_verified_by="FACE",
                shift_name="Morning Shift",
                is_late=False,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        active_session_id_str = str(active_session_id)
        active_checkin_time = today_utc.isoformat()

    token = create_access_token(
        user_id=user_id,
        role="employee",
        company_id=comp_id,
        email=user_email,
    )
    headers = {"Authorization": f"Bearer {token}"}

    dummy_image_b64 = make_dummy_base64_image()
    registered_embedding = generate_unit_vector(128, seed=101)
    matching_embedding = (np.array(registered_embedding) + np.random.normal(0, 0.005, 128))
    matching_embedding /= np.linalg.norm(matching_embedding)
    matching_embedding = matching_embedding.tolist()

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Enroll face first
        with patch.object(FaceRecognitionService, "extract_face_embedding", return_value=(registered_embedding, 0.95)):
            enroll_resp = await client.post(
                "/api/v1/attendance/face-enroll",
                headers=headers,
                json={"image_base64": dummy_image_b64},
            )
            assert enroll_resp.status_code == 200

        # Attempt check-in again - should return 409 with active_session details
        with patch.object(FaceRecognitionService, "extract_face_embedding", return_value=(matching_embedding, 0.95)):
            checkin_resp = await client.post(
                "/api/v1/attendance/checkin",
                headers=headers,
                json={
                    "image_base64": dummy_image_b64,
                    "location": {"latitude": 28.6139, "longitude": 77.2090},
                    "notes": "Duplicate checkin attempt",
                },
            )
            # Should return 409 with active_session details
            assert checkin_resp.status_code == 409, f"Expected 409, got {checkin_resp.status_code}: {checkin_resp.text}"
            err_data = checkin_resp.json()
            
            # Check error detail structure
            detail = err_data.get("detail", {})
            assert detail.get("code") == "ALREADY_CHECKED_IN"
            assert "active_session" in detail, "Response should include active_session for frontend sync"
            
            session_info = detail["active_session"]
            assert session_info["session_id"] == active_session_id_str
            assert session_info["check_in_time"] == active_checkin_time
            assert session_info["status"] == "Present"
            assert session_info["date"] == date.today().isoformat()
            assert session_info["shift_name"] == "Morning Shift"
            assert session_info["is_late"] is False


@pytest.mark.asyncio
async def test_checkin_expired_shift_session_auto_closes():
    """
    Test that a session older than MAX_SHIFT_HOURS (16h) is considered stale
    and auto-closed even if it's from today.
    """
    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncSessionLocal() as session:
        comp_id = uuid.uuid4()
        company = Company(
            id=comp_id,
            name=f"Expired Shift Corp {comp_id.hex[:6]}",
            onboarding_completed=True,
        )
        session.add(company)

        user_id = uuid.uuid4()
        user_email = f"expired_emp_{user_id.hex[:6]}@example.com"
        user = User(
            id=user_id,
            company_id=comp_id,
            name="Expired Shift Employee",
            email=user_email,
            phone=f"98{user_id.int % 100000000:08d}",
            password_hash="dummy_hash",
            role=UserRole.EMPLOYEE,
            account_status="ACTIVE",
            is_active=True,
            is_verified=True,
        )
        session.add(user)

        emp_id = uuid.uuid4()
        employee = Employee(
            id=emp_id,
            user_id=user_id,
            company_id=comp_id,
            employee_id=f"EMP-{user_id.hex[:6].upper()}",
            first_name="Expired",
            last_name="Shift",
            personal_email=user_email,
            phone=user.phone,
            department="Engineering",
            designation="Software Engineer",
            status="ACTIVE",
            employment_status="CONFIRMED",
            joining_date=date.today(),
            is_active=True,
            is_face_enrolled=True,
            face_embedding=b"dummy_encrypted_embedding",
        )
        session.add(employee)

        # Create an active session from 18 hours ago (exceeds 16h max shift)
        eighteen_hours_ago = datetime.now(timezone.utc) - timedelta(hours=18)
        expired_session_id = uuid.uuid4()
        await session.execute(
            insert(Attendance).values(
                id=expired_session_id,
                employee_id=emp_id,
                company_id=comp_id,
                date=date.today(),  # Same day but session is very old
                check_in_time=eighteen_hours_ago,
                check_out_time=None,
                face_image_url="test.jpg",
                captured_face_url="test.jpg",
                status="Present",
                punch_type="IN",
                verified=True,
                punch_verified_by="FACE",
                auto_closed=False,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
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
    matching_embedding = (np.array(registered_embedding) + np.random.normal(0, 0.005, 128))
    matching_embedding /= np.linalg.norm(matching_embedding)
    matching_embedding = matching_embedding.tolist()

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        with patch.object(FaceRecognitionService, "extract_face_embedding", return_value=(registered_embedding, 0.95)):
            await client.post("/api/v1/attendance/face-enroll", headers=headers, json={"image_base64": dummy_image_b64})

        # Check-in should auto-close the expired shift session and succeed
        with patch.object(FaceRecognitionService, "extract_face_embedding", return_value=(matching_embedding, 0.95)):
            checkin_resp = await client.post(
                "/api/v1/attendance/checkin",
                headers=headers,
                json={"image_base64": dummy_image_b64},
            )
            assert checkin_resp.status_code in (200, 201), f"Expected 200/201, got {checkin_resp.status_code}: {checkin_resp.text}"

        # Verify the expired session was auto-closed
        async with AsyncSessionLocal() as verify_session:
            from sqlalchemy import select
            from app.attendance.models.attendance import Attendance as FaceAttendance
            expired_check = await verify_session.execute(
                select(FaceAttendance).where(FaceAttendance.id == expired_session_id)
            )
            expired_record = expired_check.scalars().first()
            assert expired_record is not None
            assert expired_record.check_out_time is not None, "Expired shift session should be auto-closed"
            assert expired_record.auto_closed is True
            assert "Auto-closed" in (expired_record.notes or "")


@pytest.mark.asyncio
async def test_http_exception_not_logged_as_dbapi_error(caplog):
    """
    Test that HTTPException (409 ALREADY_CHECKED_IN) does not trigger
    ERROR level DBAPI/Query exception log in get_db_session.
    """
    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncSessionLocal() as session:
        comp_id = uuid.uuid4()
        company = Company(
            id=comp_id,
            name=f"LogTest Corp {comp_id.hex[:6]}",
            onboarding_completed=True,
        )
        session.add(company)

        user_id = uuid.uuid4()
        user_email = f"logtest_emp_{user_id.hex[:6]}@example.com"
        user = User(
            id=user_id,
            company_id=comp_id,
            name="Log Test Employee",
            email=user_email,
            phone=f"98{user_id.int % 100000000:08d}",
            password_hash="dummy_hash",
            role=UserRole.EMPLOYEE,
            account_status="ACTIVE",
            is_active=True,
            is_verified=True,
        )
        session.add(user)

        emp_id = uuid.uuid4()
        employee = Employee(
            id=emp_id,
            user_id=user_id,
            company_id=comp_id,
            employee_id=f"EMP-{user_id.hex[:6].upper()}",
            first_name="Log",
            last_name="Test",
            personal_email=user_email,
            phone=user.phone,
            department="Engineering",
            designation="Software Engineer",
            status="ACTIVE",
            employment_status="CONFIRMED",
            joining_date=date.today(),
            is_active=True,
            is_face_enrolled=True,
            face_embedding=b"dummy_encrypted_embedding",
        )
        session.add(employee)

        # Active session from today
        today_utc = datetime.now(timezone.utc).replace(microsecond=0)
        active_session_id = uuid.uuid4()
        await session.execute(
            insert(Attendance).values(
                id=active_session_id,
                employee_id=emp_id,
                company_id=comp_id,
                date=date.today(),
                check_in_time=today_utc,
                check_out_time=None,
                face_image_url="test.jpg",
                captured_face_url="test.jpg",
                status="Present",
                punch_type="IN",
                verified=True,
                punch_verified_by="FACE",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
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
    matching_embedding = (np.array(registered_embedding) + np.random.normal(0, 0.005, 128))
    matching_embedding /= np.linalg.norm(matching_embedding)
    matching_embedding = matching_embedding.tolist()

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        with patch.object(FaceRecognitionService, "extract_face_embedding", return_value=(registered_embedding, 0.95)):
            await client.post("/api/v1/attendance/face-enroll", headers=headers, json={"image_base64": dummy_image_b64})

        # Capture logs during the duplicate check-in attempt
        with caplog.at_level(logging.ERROR, logger="app.db.database"):
            with patch.object(FaceRecognitionService, "extract_face_embedding", return_value=(matching_embedding, 0.95)):
                checkin_resp = await client.post(
                    "/api/v1/attendance/checkin",
                    headers=headers,
                    json={"image_base64": dummy_image_b64},
                )
                assert checkin_resp.status_code == 409

        # Verify no ERROR level DBAPI/Query exception was logged
        dbapi_errors = [r for r in caplog.records if "DBAPI/Query exception" in r.getMessage()]
        assert len(dbapi_errors) == 0, f"DBAPI/Query exception should not be logged for HTTPException: {dbapi_errors}"

        # The HTTPException should be raised without database error traceback
        # Check that we don't have ERROR logs from the database lifecycle for this expected error
        error_logs = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(error_logs) == 0, f"Unexpected ERROR logs: {[(r.name, r.getMessage()) for r in error_logs]}"
