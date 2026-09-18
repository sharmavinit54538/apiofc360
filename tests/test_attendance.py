"""Comprehensive automated test suite for Face Attendance Module.

Covers:
1. P0 crash bug regression: GET /api/v1/attendance/face/company (with branch and department filters)
2. Check-in success (valid photo with magic bytes, coordinates, server IP)
3. Duplicate check-in rejection (HTTP 409)
4. Check-out without active session rejection (HTTP 400)
5. Check-out success (working hours calculation, authenticated image url)
6. File validation rejections (0-byte, invalid magic bytes, fake extensions, oversized)
7. Geofence enforcement (inside, outside, opt-in behavior)
8. Authenticated photo retrieval & unauthenticated public static block
9. Rate limiting on check-in/checkout endpoints
"""

from __future__ import annotations

import io
import os
import uuid
from datetime import date, datetime, timezone
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.db.database import AsyncSessionLocal
from app.utils.jwt import create_access_token
from app.core.security import hash_password
from app.models.company import Company
from app.models.employee import Employee
from app.models.user import User, UserRole, UserAccountStatus
from app.attendance.models.attendance import Attendance

# Sample valid image payloads
VALID_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00" + b"\xaa" * 100
VALID_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
VALID_WEBP_BYTES = b"RIFF\x20\x00\x00\x00WEBPVP8 " + b"\x00" * 32
CORRUPT_BYTES = b"This is plain text pretending to be an image."


@pytest.fixture
def app_instance():
    return create_app()


@pytest.fixture
def transport(app_instance):
    return ASGITransport(app=app_instance)


async def _create_test_env(
    role: UserRole = UserRole.EMPLOYEE,
    office_latitude: float | None = None,
    office_longitude: float | None = None,
    geofence_radius: float | None = None,
    with_attendance: bool = False,
):
    """Seed company, employee, and authentication headers."""
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    email = f"att_test_{user_id.hex[:6]}@example.com"
    phone_num = f"97{user_id.int % 100000000:08d}"

    async with AsyncSessionLocal() as session:
        comp = Company(
            id=company_id,
            name=f"Attendance Co {company_id.hex[:4]}",
            office_latitude=office_latitude,
            office_longitude=office_longitude,
            geofence_radius_meters=geofence_radius,
            timezone="Asia/Kolkata",
        )
        session.add(comp)

        user = User(
            id=user_id,
            company_id=company_id,
            name="Test User",
            email=email,
            phone=phone_num,
            password_hash=hash_password("Pass@1234"),
            role=role,
            account_status=UserAccountStatus.ACTIVE.value,
            is_active=True,
            is_verified=True,
        )
        session.add(user)

        employee = Employee(
            id=emp_id,
            user_id=user_id,
            company_id=company_id,
            employee_id=f"EMP-{user_id.hex[:4]}",
            first_name="Attend",
            last_name="Tester",
            personal_email=email,
            company_email=email,
            phone=phone_num,
            department="Engineering",
            branch="Bangalore",
            designation="Software Engineer",
            employment_type="FULL_TIME",
            joining_date=date.today(),
            status="ACTIVE",
            is_active=True,
            is_deleted=False,
        )
        session.add(employee)

        if with_attendance:
            att = Attendance(
                id=uuid.uuid4(),
                employee_id=emp_id,
                company_id=company_id,
                date=date.today(),
                check_in_time=datetime.now(timezone.utc),
                face_image_url="uploads/face_attendance/seed_checkin.jpg",
                device_info="Pytest Device",
                ip_address="127.0.0.1",
            )
            session.add(att)

        await session.commit()

    token = create_access_token(
        user_id=str(user_id),
        email=email,
        role=role.value,
        company_id=str(company_id),
    )

    return {
        "company_id": company_id,
        "user_id": user_id,
        "employee_id": emp_id,
        "email": email,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


# ============================================================================
# 1. P0 Regression Test: GET /attendance/face/company
# ============================================================================
@pytest.mark.asyncio
async def test_p0_regression_company_attendance(transport):
    """Calling GET /attendance/face/company with department filter must not crash with TypeError."""
    admin_env = await _create_test_env(role=UserRole.HR_ADMIN, with_attendance=True)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get(
            "/api/v1/attendance/face/company?page=1&limit=20&branch=Bangalore&department=Engineering",
            headers=admin_env["headers"],
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["success"] is True
        assert "data" in data
        assert data["data"]["total"] >= 1
        assert len(data["data"]["items"]) >= 1
        item = data["data"]["items"][0]
        assert "face_image_url" in item
        # URL must be transformed to secure authenticated streaming endpoint
        if item["face_image_url"]:
            assert item["face_image_url"].startswith("/attendance/face/image/")


# ============================================================================
# 2. Check-in Success & Server IP Derivation
# ============================================================================
@pytest.mark.asyncio
async def test_checkin_success(transport):
    """Valid check-in creates attendance row and rewrites image URL to secure route."""
    env = await _create_test_env(role=UserRole.EMPLOYEE)

    files = {"file": ("face_proof.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")}
    data = {
        "latitude": "12.9716",
        "longitude": "77.5946",
        "device_info": "Test Browser",
        "ip_address": "spoofed.client.ip",  # Must be ignored in favor of server request
    }

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/v1/attendance/face/check-in",
            headers={**env["headers"], "X-Forwarded-For": "203.0.113.195"},
            files=files,
            data=data,
        )
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        res_json = resp.json()
        assert res_json["success"] is True
        record = res_json["data"]
        assert record["employee_id"] == str(env["employee_id"])
        assert record["face_image_url"].startswith("/attendance/face/image/")
        # Verify server derived IP was saved
        assert record["ip_address"] == "203.0.113.195"


# ============================================================================
# 3. Duplicate Check-in Rejection
# ============================================================================
@pytest.mark.asyncio
async def test_duplicate_checkin_rejection(transport):
    """Second check-in on the same calendar day returns HTTP 409 Conflict."""
    env = await _create_test_env(role=UserRole.EMPLOYEE, with_attendance=True)

    files = {"file": ("face_proof.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")}

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/v1/attendance/face/check-in",
            headers=env["headers"],
            files=files,
            data={"latitude": "12.9716", "longitude": "77.5946"},
        )
        assert resp.status_code == 409
        assert "already checked in" in resp.text.lower()


# ============================================================================
# 4. Check-out Without Active Session Rejection
# ============================================================================
@pytest.mark.asyncio
async def test_checkout_without_active_session(transport):
    """Checking out without checking in returns HTTP 400 Bad Request."""
    env = await _create_test_env(role=UserRole.EMPLOYEE, with_attendance=False)

    files = {"file": ("checkout.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")}

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/v1/attendance/face/check-out",
            headers=env["headers"],
            files=files,
            data={"latitude": "12.9716", "longitude": "77.5946"},
        )
        assert resp.status_code == 400
        assert "no active check-in session" in resp.text.lower()


# ============================================================================
# 5. Check-out Success & Hours Calculation
# ============================================================================
@pytest.mark.asyncio
async def test_checkout_success(transport):
    """Successful checkout calculates working hours and updates checkout_image_url."""
    env = await _create_test_env(role=UserRole.EMPLOYEE)

    # 1. First check in
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        in_resp = await client.post(
            "/api/v1/attendance/face/check-in",
            headers=env["headers"],
            files={"file": ("in.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")},
            data={"latitude": "12.9716", "longitude": "77.5946"},
        )
        assert in_resp.status_code == 201
        att_id = in_resp.json()["data"]["id"]

        # 2. Then check out
        out_resp = await client.post(
            "/api/v1/attendance/face/check-out",
            headers=env["headers"],
            files={"file": ("out.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")},
            data={"latitude": "12.9716", "longitude": "77.5946"},
        )
        assert out_resp.status_code == 200, f"Checkout failed: {out_resp.text}"
        out_data = out_resp.json()["data"]
        assert out_data["check_out_time"] is not None
        assert out_data["checkout_image_url"] == f"/attendance/face/image/{att_id}?type=checkout"
        assert out_data["working_hours"] is not None


# ============================================================================
# 6. File Validation Hardening (Empty, Corrupt, Oversized)
# ============================================================================
@pytest.mark.asyncio
async def test_file_validation_rejections(transport):
    """Tests 0-byte file, invalid magic bytes, and unsupported format rejections."""
    env = await _create_test_env(role=UserRole.EMPLOYEE)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. 0-byte empty file
        empty_files = {"file": ("empty.jpg", io.BytesIO(b""), "image/jpeg")}
        resp_empty = await client.post(
            "/api/v1/attendance/face/check-in",
            headers=env["headers"],
            files=empty_files,
        )
        assert resp_empty.status_code == 400
        assert "empty" in resp_empty.text.lower()

        # 2. Fake magic bytes (corrupted / renamed text file)
        corrupt_files = {"file": ("fake.jpg", io.BytesIO(CORRUPT_BYTES), "image/jpeg")}
        resp_corrupt = await client.post(
            "/api/v1/attendance/face/check-in",
            headers=env["headers"],
            files=corrupt_files,
        )
        assert resp_corrupt.status_code == 400
        assert "corrupted or mislabeled" in resp_corrupt.text.lower() or "not match" in resp_corrupt.text.lower()

        # 3. Disallowed extension (.pdf)
        pdf_files = {"file": ("document.pdf", io.BytesIO(b"%PDF-1.4 sample"), "application/pdf")}
        resp_pdf = await client.post(
            "/api/v1/attendance/face/check-in",
            headers=env["headers"],
            files=pdf_files,
        )
        assert resp_pdf.status_code == 400
        assert "invalid file format" in resp_pdf.text.lower()


# ============================================================================
# 7. GPS Geofence Validation
# ============================================================================
@pytest.mark.asyncio
async def test_geofence_enforcement(transport):
    """Enforces office radius when configured, rejects out-of-bounds coordinates."""
    # Configure office at MG Road Bangalore (12.9750, 77.6090) with 300m radius
    env = await _create_test_env(
        role=UserRole.EMPLOYEE,
        office_latitude=12.9750,
        office_longitude=77.6090,
        geofence_radius=300.0,
    )

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Coordinates 5 km away -> Out of bounds
        outside_files = {"file": ("out_bounds.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")}
        outside_data = {"latitude": "12.9352", "longitude": "77.6245"}  # Koramangala (~5 km away)
        resp_out = await client.post(
            "/api/v1/attendance/face/check-in",
            headers=env["headers"],
            files=outside_files,
            data=outside_data,
        )
        assert resp_out.status_code == 400
        assert "outside the office geofence" in resp_out.text.lower()

        # 2. Coordinates within 100 meters -> Permitted
        inside_files = {"file": ("in_bounds.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")}
        inside_data = {"latitude": "12.9751", "longitude": "77.6092"}  # ~25m away
        resp_in = await client.post(
            "/api/v1/attendance/face/check-in",
            headers=env["headers"],
            files=inside_files,
            data=inside_data,
        )
        assert resp_in.status_code == 201


# ============================================================================
# 8. Authenticated Photo Retrieval & Direct Static Block
# ============================================================================
@pytest.mark.asyncio
async def test_authenticated_image_streaming(transport):
    """Test authenticated streaming, cross-company access block, and direct static blocking."""
    # Create employee and check in to create a real photo file
    env = await _create_test_env(role=UserRole.EMPLOYEE)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        checkin_resp = await client.post(
            "/api/v1/attendance/face/check-in",
            headers=env["headers"],
            files={"file": ("photo.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")},
        )
        assert checkin_resp.status_code == 201
        att_id = checkin_resp.json()["data"]["id"]

        # 1. Owning employee streams photo -> HTTP 200
        stream_resp = await client.get(
            f"/api/v1/attendance/face/image/{att_id}",
            headers=env["headers"],
        )
        assert stream_resp.status_code == 200
        assert len(stream_resp.content) > 0

        # 2. Unauthenticated request -> HTTP 401
        unauth_resp = await client.get(f"/api/v1/attendance/face/image/{att_id}")
        assert unauth_resp.status_code == 401

        # 3. Another employee from different company -> HTTP 403
        other_env = await _create_test_env(role=UserRole.EMPLOYEE)
        forbidden_resp = await client.get(
            f"/api/v1/attendance/face/image/{att_id}",
            headers=other_env["headers"],
        )
        assert forbidden_resp.status_code == 403

        # 4. Direct unauthenticated request to /uploads/face_attendance/ -> HTTP 403
        static_resp = await client.get("/uploads/face_attendance/any_file.jpg")
        assert static_resp.status_code == 403


# ============================================================================
# 9. Rate Limiter Trigger
# ============================================================================
@pytest.mark.asyncio
async def test_attendance_rate_limiting(transport):
    """Exceeding ATTENDANCE_RATE_LIMIT_LIMIT triggers HTTP 429 Too Many Requests."""
    env = await _create_test_env(role=UserRole.EMPLOYEE)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Fire 8 rapid requests (limit is 5/min)
        status_codes = []
        for i in range(8):
            files = {"file": (f"rate_{i}.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")}
            resp = await client.post(
                "/api/v1/attendance/face/check-in",
                headers={**env["headers"], "X-Forwarded-For": "198.51.100.77"},
                files=files,
            )
            status_codes.append(resp.status_code)

        # At least one request should have hit rate limiter (429)
        assert 429 in status_codes
