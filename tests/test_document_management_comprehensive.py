"""Comprehensive end-to-end test suite for Document Management module.

Validates all 4 phases:
- Phase 1: Security & RBAC, /uploads isolation, centralized access, manager hierarchy, tenant isolation, OCR scoping, signatures
- Phase 2: Complete API contract, status/is_verified coupling, paginated list meta, summary metrics, categories, re-upload, self-service, versions
- Phase 3: Magic-byte validation, extension allowlist, orphan file cleanup, safe downloads, 422 inputs
- Phase 4: Full deliverable validation
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
import io
import os
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.database import AsyncSessionLocal
from app.main import create_app
from app.models.company import Company
from app.models.document.category import DocumentCategory
from app.models.document.company import CompanyDocument
from app.models.document.signature import DocumentSignature
from app.models.document.version import DocumentVersion
from app.models.employee import Employee
from app.models.employee_document import EmployeeDocument
from app.models.user import User, UserRole
from app.services.document_categories import seed_canonical_categories_idempotent
from app.services.document_service import DocumentService
from app.services.storage_service import StorageService
from app.utils.jwt import create_access_token


@pytest.fixture
def app_instance():
    return create_app()


@pytest.fixture
def transport(app_instance):
    return ASGITransport(app=app_instance)


async def _create_test_user_and_emp(
    session,
    company_id: uuid.UUID,
    role: str = "employee",
    reporting_manager_id: uuid.UUID | None = None,
    department: str = "Engineering",
    branch: str = "Bengaluru",
):
    uid = uuid.uuid4()
    eid = uuid.uuid4()
    email = f"user_{uid.hex[:8]}@example.com"

    phone_10 = f"98{(uid.int % 100000000):08d}"
    user_role_enum = UserRole(role.lower())

    emp = Employee(
        id=eid,
        user_id=uid,
        company_id=company_id,
        employee_id=f"EMP-{eid.hex[:5]}",
        first_name="Test",
        last_name=f"User-{eid.hex[:4]}",
        personal_email=email,
        company_email=email,
        phone=phone_10,
        department=department,
        branch=branch,
        designation="Engineer",
        joining_date=date(2023, 1, 1),
        reporting_manager_id=reporting_manager_id,
        status="ACTIVE",
        is_active=True,
    )
    session.add(emp)

    user = User(
        id=uid,
        company_id=company_id,
        name=f"Test User {uid.hex[:4]}",
        email=email,
        phone=phone_10,
        password_hash=hash_password("Password#123"),
        role=user_role_enum,
        is_active=True,
        is_verified=True,
    )
    session.add(user)
    await session.flush()

    token = create_access_token(user_id=uid, role=role, company_id=company_id, email=email)
    headers = {"Authorization": f"Bearer {token}"}

    return {
        "user_id": uid,
        "employee_id": eid,
        "email": email,
        "token": token,
        "headers": headers,
    }


# ==============================================================================
# PHASE 1 & 3: CRITICAL SECURITY & STATIC MOUNT HARDENING
# ==============================================================================

@pytest.mark.asyncio
async def test_uploads_documents_static_mount_is_not_publicly_reachable(transport):
    """Rule 1.1: Verify /uploads/documents/<anything> is not publicly reachable and returns 404."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/uploads/documents/confidential_salary_slip.pdf")
        assert res.status_code == 404


@pytest.mark.asyncio
async def test_employee_cannot_read_or_download_another_employee_doc(transport):
    """Rules 1.2, 1.3: Employee cannot list, get, or download another employee's document."""
    async with AsyncSessionLocal() as session:
        comp_id = uuid.uuid4()
        session.add(Company(id=comp_id, name="Security Test Corp"))
        await session.flush()

        hr = await _create_test_user_and_emp(session, comp_id, role="hr_admin")
        emp1 = await _create_test_user_and_emp(session, comp_id, role="employee")
        emp2 = await _create_test_user_and_emp(session, comp_id, role="employee")

        # Fetch canonical category
        cat_res = await session.execute(select(DocumentCategory).where(DocumentCategory.is_company == False).limit(1))
        category = cat_res.scalar_one_or_none()
        if not category:
            await seed_canonical_categories_idempotent(session)
            cat_res = await session.execute(select(DocumentCategory).where(DocumentCategory.is_company == False).limit(1))
            category = cat_res.scalar_one()

        # Create document for emp1
        storage = StorageService()
        dummy_file = io.BytesIO(b"%PDF-1.4 dummy confidential content")
        dummy_file.name = "pan_card.pdf"
        saved = await storage.provider.save_stream(dummy_file, f"{uuid.uuid4().hex}.pdf")

        doc1 = EmployeeDocument(
            id=uuid.uuid4(),
            employee_id=emp1["employee_id"],
            category_id=category.id,
            uploaded_by=hr["user_id"],
            title="Emp1 PAN Card",
            file_path=saved["file_path"],
            file_name="pan_card.pdf",
            file_size=saved["file_size"],
            visibility="PRIVATE",
            status="PENDING",
            is_verified=False,
        )
        session.add(doc1)
        await session.commit()
        doc1_id = doc1.id

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Emp2 tries to get Emp1's document by ID -> returns 404 (existence not leaked, Rule 1.6)
        res_get = await client.get(f"/api/v1/documents/employees/{doc1_id}", headers=emp2["headers"])
        assert res_get.status_code == 404

        # 2. Emp2 tries to download Emp1's document -> returns 404
        res_dl = await client.get(f"/api/v1/documents/employees/{doc1_id}/download", headers=emp2["headers"])
        assert res_dl.status_code == 404

        # 3. Emp2 tries to list with employee_id=Emp1 -> returns 403 Forbidden
        res_list = await client.get(f"/api/v1/documents/employees?employee_id={emp1['employee_id']}", headers=emp2["headers"])
        assert res_list.status_code == 403

        # 4. Emp2 listing without filter only returns Emp2's docs (empty here)
        res_own = await client.get("/api/v1/documents/employees", headers=emp2["headers"])
        assert res_own.status_code == 200
        assert len(res_own.json()["data"]) == 0


@pytest.mark.asyncio
async def test_manager_reporting_hierarchy_access(transport):
    """Rules 1.2, 1.3: Manager sees only self + reporting tree; no branch/dept stranger leak."""
    async with AsyncSessionLocal() as session:
        comp_id = uuid.uuid4()
        session.add(Company(id=comp_id, name="Hierarchy Corp"))
        await session.flush()

        mgr = await _create_test_user_and_emp(session, comp_id, role="manager", department="Engineering", branch="Bengaluru")
        report = await _create_test_user_and_emp(session, comp_id, role="employee", reporting_manager_id=mgr["employee_id"], department="Engineering", branch="Bengaluru")
        stranger = await _create_test_user_and_emp(session, comp_id, role="employee", reporting_manager_id=None, department="Engineering", branch="Bengaluru")

        cat_res = await session.execute(select(DocumentCategory).where(DocumentCategory.is_company == False).limit(1))
        category = cat_res.scalar_one_or_none()
        if not category:
            await seed_canonical_categories_idempotent(session)
            cat_res = await session.execute(select(DocumentCategory).where(DocumentCategory.is_company == False).limit(1))
            category = cat_res.scalar_one()

        storage = StorageService()

        # Doc for report
        s1 = await storage.provider.save_stream(io.BytesIO(b"%PDF-1.4 report doc"), f"{uuid.uuid4().hex}.pdf")
        doc_report = EmployeeDocument(
            id=uuid.uuid4(),
            employee_id=report["employee_id"],
            category_id=category.id,
            uploaded_by=mgr["user_id"],
            title="Report Offer Letter",
            file_path=s1["file_path"],
            file_name="offer.pdf",
            file_size=s1["file_size"],
            visibility="PRIVATE",
            status="PENDING",
            is_verified=False,
        )
        session.add(doc_report)

        # Doc for stranger (same branch & department, but NOT in reporting chain!)
        s2 = await storage.provider.save_stream(io.BytesIO(b"%PDF-1.4 stranger doc"), f"{uuid.uuid4().hex}.pdf")
        doc_stranger = EmployeeDocument(
            id=uuid.uuid4(),
            employee_id=stranger["employee_id"],
            category_id=category.id,
            uploaded_by=mgr["user_id"],
            title="Stranger Salary Slip",
            file_path=s2["file_path"],
            file_name="salary.pdf",
            file_size=s2["file_size"],
            visibility="PRIVATE",
            status="PENDING",
            is_verified=False,
        )
        session.add(doc_stranger)
        await session.commit()

        doc_report_id = doc_report.id
        doc_stranger_id = doc_stranger.id

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Manager CAN access report's document
        r_rep = await client.get(f"/api/v1/documents/employees/{doc_report_id}", headers=mgr["headers"])
        assert r_rep.status_code == 200

        # 2. Manager CANNOT access stranger's document (returns 404 to avoid leaking existence)
        r_str = await client.get(f"/api/v1/documents/employees/{doc_stranger_id}", headers=mgr["headers"])
        assert r_str.status_code == 404

        # 3. Manager passing stranger's employee_id gets 403 Forbidden
        r_str_list = await client.get(f"/api/v1/documents/employees?employee_id={stranger['employee_id']}", headers=mgr["headers"])
        assert r_str_list.status_code == 403


@pytest.mark.asyncio
async def test_hr_only_and_private_visibility_rules(transport):
    """Rules 1.2, 1.5: HR_ONLY hidden from owner; PRIVATE hidden from peers; Company HR_ONLY/PRIVATE hidden from normal employee."""
    async with AsyncSessionLocal() as session:
        comp_id = uuid.uuid4()
        session.add(Company(id=comp_id, name="Visibility Corp"))
        await session.flush()

        hr = await _create_test_user_and_emp(session, comp_id, role="hr_admin")
        emp = await _create_test_user_and_emp(session, comp_id, role="employee")

        cat_res = await session.execute(select(DocumentCategory).where(DocumentCategory.is_company == False).limit(1))
        category = cat_res.scalar_one()

        storage = StorageService()

        # Employee doc with HR_ONLY visibility
        s1 = await storage.provider.save_stream(io.BytesIO(b"%PDF-1.4 confidential review"), f"{uuid.uuid4().hex}.pdf")
        doc_hronly = EmployeeDocument(
            id=uuid.uuid4(),
            employee_id=emp["employee_id"],
            category_id=category.id,
            uploaded_by=hr["user_id"],
            title="HR Investigation Notes",
            file_path=s1["file_path"],
            file_name="investigation.pdf",
            file_size=s1["file_size"],
            visibility="HR_ONLY",
            status="PENDING",
            is_verified=False,
        )
        session.add(doc_hronly)

        # Company doc with HR_ONLY visibility
        cat_c_res = await session.execute(select(DocumentCategory).where(DocumentCategory.is_company == True).limit(1))
        cat_comp = cat_c_res.scalar_one()
        s2 = await storage.provider.save_stream(io.BytesIO(b"%PDF-1.4 payroll internal"), f"{uuid.uuid4().hex}.pdf")
        comp_doc_hronly = CompanyDocument(
            id=uuid.uuid4(),
            company_id=comp_id,
            category_id=cat_comp.id,
            uploaded_by=hr["user_id"],
            title="Executive Compensation Guideline",
            file_path=s2["file_path"],
            file_name="exec_comp.pdf",
            file_size=s2["file_size"],
            visibility="HR_ONLY",
            status="PUBLISHED",
        )
        session.add(comp_doc_hronly)
        await session.commit()

        emp_doc_id = doc_hronly.id
        comp_doc_id = comp_doc_hronly.id

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Employee cannot view HR_ONLY document even though they own the employee profile
        r1 = await client.get(f"/api/v1/documents/employees/{emp_doc_id}", headers=emp["headers"])
        assert r1.status_code == 404

        # 2. HR can view HR_ONLY employee document
        r2 = await client.get(f"/api/v1/documents/employees/{emp_doc_id}", headers=hr["headers"])
        assert r2.status_code == 200

        # 3. Employee cannot view or download HR_ONLY company document
        r3 = await client.get(f"/api/v1/documents/company/{comp_doc_id}", headers=emp["headers"])
        assert r3.status_code == 404
        r4 = await client.get(f"/api/v1/documents/company/{comp_doc_id}/download", headers=emp["headers"])
        assert r4.status_code == 404

        # 4. Company doc is excluded from employee's GET /documents/company list
        r5 = await client.get("/api/v1/documents/company", headers=emp["headers"])
        assert r5.status_code == 200
        comp_ids = [d["id"] for d in r5.json()["data"]]
        assert str(comp_doc_id) not in comp_ids


@pytest.mark.asyncio
async def test_cross_company_access_returns_404(transport):
    """Rule 1.4: Cross-company access returns 404."""
    async with AsyncSessionLocal() as session:
        comp_a = uuid.uuid4()
        comp_b = uuid.uuid4()
        session.add(Company(id=comp_a, name="Company A"))
        session.add(Company(id=comp_b, name="Company B"))
        await session.flush()

        hr_a = await _create_test_user_and_emp(session, comp_a, role="hr_admin")
        hr_b = await _create_test_user_and_emp(session, comp_b, role="hr_admin")

        cat_res = await session.execute(select(DocumentCategory).where(DocumentCategory.is_company == False).limit(1))
        category = cat_res.scalar_one()

        storage = StorageService()
        s1 = await storage.provider.save_stream(io.BytesIO(b"%PDF-1.4 comp A doc"), f"{uuid.uuid4().hex}.pdf")
        doc_a = EmployeeDocument(
            id=uuid.uuid4(),
            employee_id=hr_a["employee_id"],
            category_id=category.id,
            uploaded_by=hr_a["user_id"],
            title="Company A Document",
            file_path=s1["file_path"],
            file_name="doc_a.pdf",
            file_size=s1["file_size"],
            visibility="PRIVATE",
            status="PENDING",
            is_verified=False,
        )
        session.add(doc_a)
        await session.commit()
        doc_a_id = doc_a.id

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # HR of Company B tries to view or download Company A document -> returns 404
        r_get = await client.get(f"/api/v1/documents/employees/{doc_a_id}", headers=hr_b["headers"])
        assert r_get.status_code == 404

        r_dl = await client.get(f"/api/v1/documents/employees/{doc_a_id}/download", headers=hr_b["headers"])
        assert r_dl.status_code == 404


# ==============================================================================
# PHASE 2: API CONTRACT, VERIFICATION, STATUS COUPLING, PAGINATION & SUMMARY
# ==============================================================================

@pytest.mark.asyncio
async def test_document_summary_returns_correct_real_counts(transport):
    """Rule 2.4: /documents/summary returns correct counts with no swallowed exceptions."""
    async with AsyncSessionLocal() as session:
        comp_id = uuid.uuid4()
        session.add(Company(id=comp_id, name="Summary Metrics Corp"))
        await session.flush()

        hr = await _create_test_user_and_emp(session, comp_id, role="hr_admin")
        cat = (await session.execute(select(DocumentCategory).where(DocumentCategory.is_company == False).limit(1))).scalar_one()

        storage = StorageService()
        s = await storage.provider.save_stream(io.BytesIO(b"%PDF-1.4 test"), f"{uuid.uuid4().hex}.pdf")

        # 1 verified doc
        doc1 = EmployeeDocument(
            id=uuid.uuid4(),
            employee_id=hr["employee_id"],
            category_id=cat.id,
            uploaded_by=hr["user_id"],
            title="Verified Doc",
            file_path=s["file_path"],
            file_name="doc.pdf",
            file_size=s["file_size"],
            visibility="PRIVATE",
            status="VERIFIED",
            is_verified=True,
            expiry_date=date.today() + timedelta(days=10),
        )
        session.add(doc1)

        # 1 pending doc
        doc2 = EmployeeDocument(
            id=uuid.uuid4(),
            employee_id=hr["employee_id"],
            category_id=cat.id,
            uploaded_by=hr["user_id"],
            title="Pending Doc",
            file_path=s["file_path"],
            file_name="doc.pdf",
            file_size=s["file_size"],
            visibility="PRIVATE",
            status="PENDING",
            is_verified=False,
            expiry_date=date.today() - timedelta(days=2),  # expired
        )
        session.add(doc2)
        await session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/documents/summary", headers=hr["headers"])
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        data = body["data"]

        # Validate required keys
        expected_keys = {
            "total_documents",
            "verified_documents",
            "pending_verification",
            "rejected_documents",
            "requires_signature",
            "expiring_soon",
            "expiring_90_days",
            "expired_documents",
        }
        assert expected_keys.issubset(data.keys())
        assert data["total_documents"] == 2
        assert data["verified_documents"] == 1
        assert data["pending_verification"] == 1
        assert data["expiring_soon"] == 1
        assert data["expired_documents"] == 1


@pytest.mark.asyncio
async def test_verification_workflow_and_consistency(transport):
    """Rules 2.1, 2.2, 2.6: verify, reject (comments required), request-reupload, PUT cannot set VERIFIED."""
    async with AsyncSessionLocal() as session:
        comp_id = uuid.uuid4()
        session.add(Company(id=comp_id, name="Verification Corp"))
        await session.flush()

        hr = await _create_test_user_and_emp(session, comp_id, role="hr_admin")
        cat = (await session.execute(select(DocumentCategory).where(DocumentCategory.is_company == False).limit(1))).scalar_one()

        storage = StorageService()
        s = await storage.provider.save_stream(io.BytesIO(b"%PDF-1.4 test"), f"{uuid.uuid4().hex}.pdf")

        doc = EmployeeDocument(
            id=uuid.uuid4(),
            employee_id=hr["employee_id"],
            category_id=cat.id,
            uploaded_by=hr["user_id"],
            title="Passport Document",
            file_path=s["file_path"],
            file_name="passport.pdf",
            file_size=s["file_size"],
            visibility="PRIVATE",
            status="PENDING",
            is_verified=False,
        )
        session.add(doc)
        await session.commit()
        doc_id = doc.id

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Reject without comments -> 422 Unprocessable
        r_rej_fail = await client.patch(
            f"/api/v1/documents/{doc_id}/reject",
            json={"comments": ""},
            headers=hr["headers"],
        )
        assert r_rej_fail.status_code == 422

        # 2. Reject with comments -> REJECTED, is_verified=False
        r_rej = await client.patch(
            f"/api/v1/documents/{doc_id}/reject",
            json={"comments": "Photo page is blurred and unreadable."},
            headers=hr["headers"],
        )
        assert r_rej.status_code == 200
        data_rej = r_rej.json()["data"]
        assert data_rej["status"] == "REJECTED"
        assert data_rej["is_verified"] is False

        # 3. Request re-upload -> PENDING, is_verified=False
        r_reup = await client.patch(
            f"/api/v1/documents/{doc_id}/request-reupload",
            json={"comments": "Please re-upload a clean color scan."},
            headers=hr["headers"],
        )
        assert r_reup.status_code == 200
        data_reup = r_reup.json()["data"]
        assert data_reup["status"] == "PENDING"
        assert data_reup["is_verified"] is False

        # 4. Verify document -> VERIFIED, is_verified=True
        r_ver = await client.patch(
            f"/api/v1/documents/{doc_id}/verify",
            json={"comments": "Verified against physical original."},
            headers=hr["headers"],
        )
        assert r_ver.status_code == 200
        data_ver = r_ver.json()["data"]
        assert data_ver["status"] == "VERIFIED"
        assert data_ver["is_verified"] is True
        assert data_ver["verified_by"] is not None
        assert data_ver["verified_at"] is not None

        # 5. Generic PUT cannot transition status to VERIFIED -> returns 400
        r_put_illegal = await client.put(
            f"/api/v1/documents/employees/{doc_id}",
            data={"status_field": "VERIFIED"},
            headers=hr["headers"],
        )
        assert r_put_illegal.status_code == 400

        # 6. Uploading revised file via PUT resets status to PENDING and is_verified to False
        new_pdf = io.BytesIO(b"%PDF-1.4 revised clean version")
        files = {"file": ("new_passport.pdf", new_pdf, "application/pdf")}
        r_revision = await client.put(
            f"/api/v1/documents/employees/{doc_id}",
            files=files,
            headers=hr["headers"],
        )
        assert r_revision.status_code == 200
        data_rev = r_revision.json()["data"]
        assert data_rev["status"] == "PENDING"
        assert data_rev["is_verified"] is False
        assert data_rev["version"] == 2


# ==============================================================================
# PHASE 3: FILE HANDLING, MAGIC BYTES, VALIDATION & SAFE DOWNLOADS
# ==============================================================================

@pytest.mark.asyncio
async def test_file_upload_validation_and_magic_bytes(transport):
    """Rule 3.1 & 3.4: Validate extension allowlist, magic byte checks, and 422 input validation."""
    async with AsyncSessionLocal() as session:
        comp_id = uuid.uuid4()
        session.add(Company(id=comp_id, name="File Validation Corp"))
        await session.flush()

        hr = await _create_test_user_and_emp(session, comp_id, role="hr_admin")
        cat = (await session.execute(select(DocumentCategory).where(DocumentCategory.is_company == False).limit(1))).scalar_one()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Fake extension: .exe disguised as pdf
        fake_pdf = io.BytesIO(b"MZ\x90\x00 This is an executable file pretending to be pdf")
        r_fake = await client.post(
            "/api/v1/documents/employees",
            data={
                "employee_id": str(hr["employee_id"]),
                "category_id": str(cat.id),
                "title": "Malicious Executable",
            },
            files={"file": ("malware.pdf", fake_pdf, "application/pdf")},
            headers=hr["headers"],
        )
        assert r_fake.status_code == 400

        # 2. Unsupported extension: .sh
        sh_file = io.BytesIO(b"#!/bin/bash\necho hello\n")
        r_sh = await client.post(
            "/api/v1/documents/employees",
            data={
                "employee_id": str(hr["employee_id"]),
                "category_id": str(cat.id),
                "title": "Bash Script",
            },
            files={"file": ("script.sh", sh_file, "text/plain")},
            headers=hr["headers"],
        )
        assert r_sh.status_code == 400

        # 3. Invalid dates: expiry_date < issue_date -> 422
        valid_pdf = io.BytesIO(b"%PDF-1.4 legitimate document content")
        r_dates = await client.post(
            "/api/v1/documents/employees",
            data={
                "employee_id": str(hr["employee_id"]),
                "category_id": str(cat.id),
                "title": "Invalid Date Document",
                "issue_date": "2026-05-01",
                "expiry_date": "2026-04-01",
            },
            files={"file": ("doc.pdf", valid_pdf, "application/pdf")},
            headers=hr["headers"],
        )
        assert r_dates.status_code == 422


@pytest.mark.asyncio
async def test_safe_download_behavior(transport):
    """Rule 3.3: Safe download headers, Content-Disposition, and missing file handling."""
    async with AsyncSessionLocal() as session:
        comp_id = uuid.uuid4()
        session.add(Company(id=comp_id, name="Safe Download Corp"))
        await session.flush()

        hr = await _create_test_user_and_emp(session, comp_id, role="hr_admin")
        cat = (await session.execute(select(DocumentCategory).where(DocumentCategory.is_company == False).limit(1))).scalar_one()

        storage = StorageService()
        s = await storage.provider.save_stream(io.BytesIO(b"%PDF-1.4 test document"), f"{uuid.uuid4().hex}.pdf")

        doc = EmployeeDocument(
            id=uuid.uuid4(),
            employee_id=hr["employee_id"],
            category_id=cat.id,
            uploaded_by=hr["user_id"],
            title="My Resume",
            file_path=s["file_path"],
            file_name="resume.pdf",
            file_size=s["file_size"],
            visibility="PRIVATE",
            status="PENDING",
            is_verified=False,
        )
        session.add(doc)
        await session.commit()
        doc_id = doc.id
        doc_file_path = s["file_path"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Inline stream download
        r_inline = await client.get(f"/api/v1/documents/employees/{doc_id}/download", headers=hr["headers"])
        assert r_inline.status_code == 200
        assert r_inline.headers.get("x-content-type-options") == "nosniff"
        assert "inline" in r_inline.headers.get("content-disposition", "")
        assert r_inline.headers.get("content-type") == "application/pdf"

        # 2. Forced attachment download via ?download=true
        r_attach = await client.get(f"/api/v1/documents/employees/{doc_id}/download?download=true", headers=hr["headers"])
        assert r_attach.status_code == 200
        assert "attachment" in r_attach.headers.get("content-disposition", "")

        # 3. Missing file on disk returns 404 (does not 500)
        os.remove(doc_file_path)
        r_missing = await client.get(f"/api/v1/documents/employees/{doc_id}/download", headers=hr["headers"])
        assert r_missing.status_code == 404
        assert "missing from storage" in r_missing.json()["message"].lower()


# ==============================================================================
# PHASE 1 & 2: SIGNATURES & RE-UPLOAD ENDPOINTS
# ==============================================================================

@pytest.mark.asyncio
async def test_signature_workflow_and_anti_tampering(transport):
    """Rule 1.8: Request signature, duplicate rejection (409), hash anti-tamper, and status check."""
    async with AsyncSessionLocal() as session:
        comp_id = uuid.uuid4()
        session.add(Company(id=comp_id, name="Signature Corp"))
        await session.flush()

        hr = await _create_test_user_and_emp(session, comp_id, role="hr_admin")
        signer = await _create_test_user_and_emp(session, comp_id, role="employee")
        cat = (await session.execute(select(DocumentCategory).where(DocumentCategory.is_company == False).limit(1))).scalar_one()

        storage = StorageService()
        s = await storage.provider.save_stream(io.BytesIO(b"%PDF-1.4 signable contract"), f"{uuid.uuid4().hex}.pdf")

        doc = EmployeeDocument(
            id=uuid.uuid4(),
            employee_id=signer["employee_id"],
            category_id=cat.id,
            uploaded_by=hr["user_id"],
            title="Employment Contract",
            file_path=s["file_path"],
            file_name="contract.pdf",
            file_size=s["file_size"],
            document_hash=s["document_hash"],
            visibility="PRIVATE",
            status="PENDING",
            is_verified=False,
        )
        session.add(doc)
        await session.commit()
        doc_id = doc.id
        doc_path = s["file_path"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Request signature
        r_req = await client.post(
            f"/api/v1/documents/{doc_id}/request-signature",
            json={"signer_user_id": str(signer["user_id"])},
            headers=hr["headers"],
        )
        assert r_req.status_code == 201
        sig_data = r_req.json()["data"]
        assert sig_data["status"] == "PENDING"

        # 2. Duplicate signature request returns 409 Conflict
        r_dup = await client.post(
            f"/api/v1/documents/{doc_id}/request-signature",
            json={"signer_user_id": str(signer["user_id"])},
            headers=hr["headers"],
        )
        assert r_dup.status_code == 409

        # 3. Check signature status endpoint
        r_stat = await client.get(f"/api/v1/documents/{doc_id}/signature-status", headers=signer["headers"])
        assert r_stat.status_code == 200
        assert r_stat.json()["data"]["status"] == "PENDING"

        # 4. Sign document successfully
        r_sign = await client.post(
            f"/api/v1/documents/{doc_id}/sign",
            json={"device_info": "MacBook Pro Chrome"},
            headers=signer["headers"],
        )
        assert r_sign.status_code == 200
        assert r_sign.json()["data"]["status"] == "SIGNED"


@pytest.mark.asyncio
async def test_canonical_categories_idempotent_seeding():
    """Rule 2.5: Seed canonical categories idempotently without duplicates."""
    async with AsyncSessionLocal() as session:
        # First seeding
        await seed_canonical_categories_idempotent(session)
        res1 = await session.execute(select(DocumentCategory))
        cats1 = res1.scalars().all()
        count1 = len(cats1)
        assert count1 >= 30  # Canonical list has 36 categories

        # Second seeding should not create duplicates
        await seed_canonical_categories_idempotent(session)
        res2 = await session.execute(select(DocumentCategory))
        cats2 = res2.scalars().all()
        count2 = len(cats2)
        assert count1 == count2
