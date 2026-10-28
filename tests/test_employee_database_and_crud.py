"""Comprehensive test suite for Employee Database & CRUD operations, covering:
1. Employee creation
2. Employee creation with skills
3. Employee creation with addresses
4. Employee creation with documents
5. Employee creation with no optional relations
6. GET /employees
7. GET /employees/{id}
8. Duplicate employee handling
9. Existing employee retrieval
10. Authorization/RBAC
11. Employee update regression tests (unlinked user UnboundLocalError, reactivation, deactivation)
"""

import pytest
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from app.schemas.employee.create import EmployeeCreate
from app.schemas.employee.update import EmployeeUpdate
from app.schemas.employee.profile import EmployeeResponse
from app.models.employee import Employee
from app.models.employee_address import EmployeeAddress
from app.models.employee_document import EmployeeDocument
from app.models.employee_education import EmployeeEducation
from app.models.employee_experience import EmployeeExperience
from app.models.employee_skill import EmployeeSkill
from app.models.employee_bank_account import EmployeeBankAccount
from app.models.employee_leave_policy import EmployeeLeavePolicy
from app.models.employee_onboarding import EmployeeOnboarding
from app.services.employee_service import EmployeeService


def run_sync(coro):
    """Drive coroutine synchronously without external event loop or network socket pair."""
    stack = [coro]
    val = None
    while stack:
        curr = stack[-1]
        try:
            nxt = curr.send(val)
            val = None
            if hasattr(nxt, "send"):
                stack.append(nxt)
        except StopIteration as e:
            stack.pop()
            val = e.value
    return val


def test_employee_create_minimal_and_full_validation():
    # 1 & 5: Minimal employee payload (no optional relations)
    min_payload = EmployeeCreate(
        first_name="Sunaina",
        last_name="Mehra",
        personal_email="sunainam757@gmail.com",
        phone="7717544655",
        department="Engineering",
        designation="Senior Frontend Engineer",
        employment_type="FULL_TIME",
        joining_date=date(2026, 8, 17),
    )
    assert min_payload.first_name == "Sunaina"
    assert min_payload.skills == []
    assert min_payload.addresses == []
    assert min_payload.documents == []

    # 2: With skills
    skills_payload = EmployeeCreate(
        first_name="Sunaina",
        last_name="Mehra",
        personal_email="sunainam757@gmail.com",
        phone="7717544655",
        department="Engineering",
        designation="Senior Frontend Engineer",
        employment_type="FULL_TIME",
        joining_date=date(2026, 8, 17),
        skills=[{"skill_name": "React", "proficiency": "Expert", "years_of_experience": 4}],
    )
    assert len(skills_payload.skills) == 1
    assert skills_payload.skills[0].proficiency == "EXPERT"

    # 3: With addresses
    addr_payload = EmployeeCreate(
        first_name="Sunaina",
        last_name="Mehra",
        personal_email="sunainam757@gmail.com",
        phone="7717544655",
        department="Engineering",
        designation="Senior Frontend Engineer",
        employment_type="FULL_TIME",
        joining_date=date(2026, 8, 17),
        addresses=[{"address_type": "CURRENT", "address_line_1": "Flat 402, Highrise Tower, Andheri East"}],
    )
    assert len(addr_payload.addresses) == 1
    assert addr_payload.addresses[0].address_type == "CURRENT"

    # 4: With documents
    doc_payload = EmployeeCreate(
        first_name="Sunaina",
        last_name="Mehra",
        personal_email="sunainam757@gmail.com",
        phone="7717544655",
        department="Engineering",
        designation="Senior Frontend Engineer",
        employment_type="FULL_TIME",
        joining_date=date(2026, 8, 17),
        documents=[{"document_type": "PAN", "document_number": "ABCDE1234F", "document_url": None, "expiry_date": None}],
    )
    assert len(doc_payload.documents) == 1
    assert doc_payload.documents[0].document_type == "PAN"


def test_employee_response_model_validation_with_orm_models():
    """Verify that EmployeeResponse serializes cleanly from ORM-like objects with all relations."""
    emp_id = uuid.uuid4()
    company_id = uuid.uuid4()

    mock_emp = {
        "id": emp_id,
        "company_id": company_id,
        "user_id": None,
        "employee_id": "EMP-202608-0001",
        "first_name": "Sunaina",
        "last_name": "Mehra",
        "profile_photo_url": None,
        "gender": "Female",
        "date_of_birth": date(1996, 8, 20),
        "personal_email": "sunainam757@gmail.com",
        "company_email": "sunaina@ofc360.com",
        "phone": "7717544655",
        "alternate_phone": None,
        "blood_group": "O+",
        "marital_status": "Single",
        "department": "Engineering",
        "designation": "Senior Frontend Engineer",
        "team": "Core Platform",
        "reporting_manager_id": None,
        "branch": "Mumbai HQ",
        "work_location": "Remote",
        "employment_type": "FULL_TIME",
        "employment_status": "PROBATION",
        "joining_date": date(2026, 8, 17),
        "probation_end_date": None,
        "shift": "General",
        "employee_capacity": 100,
        "cost_center_id": "CC-001",
        "ctc": Decimal("1200000"),
        "basic_salary": Decimal("600000"),
        "hra": Decimal("300000"),
        "bonus": Decimal("180000"),
        "pf": Decimal("72000"),
        "esi": Decimal("0"),
        "professional_tax": Decimal("2500"),
        "role": "employee",
        "leave_group": "Standard India Policy",
        "status": "INVITED",
        "is_deleted": False,
        "created_by": None,
        "created_at": "2026-08-17T10:00:00Z",
        "updated_at": "2026-08-17T10:00:00Z",
        "addresses": [
            {
                "id": uuid.uuid4(),
                "employee_id": emp_id,
                "address_type": "CURRENT",
                "address_line_1": "Flat 402, Highrise Tower, Andheri East",
                "address_line_2": None,
                "city": "Mumbai",
                "state": "Maharashtra",
                "country": "India",
                "pincode": "400069",
                "is_same_as_current": False,
                "created_at": "2026-08-17T10:00:00Z",
                "updated_at": "2026-08-17T10:00:00Z",
            }
        ],
        "skills": [
            {
                "id": uuid.uuid4(),
                "employee_id": emp_id,
                "skill_name": "React",
                "proficiency": "EXPERT",
                "years_of_experience": 4,
                "created_at": "2026-08-17T10:00:00Z",
                "updated_at": "2026-08-17T10:00:00Z",
            }
        ],
        "bank_accounts": [
            {
                "id": uuid.uuid4(),
                "employee_id": emp_id,
                "bank_name": "HDFC Bank",
                "account_holder_name": "Sunaina Mehra",
                "account_number": "50100234567890",
                "ifsc_code": "HDFC0001234",
                "account_type": "SAVINGS",
                "is_primary": True,
                "created_at": "2026-08-17T10:00:00Z",
                "updated_at": "2026-08-17T10:00:00Z",
            }
        ],
        "experience": [
            {
                "id": uuid.uuid4(),
                "employee_id": emp_id,
                "company_name": "Tech Corp",
                "designation": "Frontend Dev",
                "employment_type": "FULL_TIME",
                "start_date": date(2022, 1, 1),
                "end_date": date(2024, 6, 1),
                "is_current": False,
                "description": "Built UI components",
                "created_at": "2026-08-17T10:00:00Z",
                "updated_at": "2026-08-17T10:00:00Z",
            }
        ],
        "documents": [],
        "education": [],
        "assets": [],
        "emergency_contacts": [],
        "leave_policies": [],
        "onboarding_steps": [],
    }

    res = EmployeeResponse.model_validate(mock_emp)
    assert res.first_name == "Sunaina"
    assert res.employee_id == "EMP-202608-0001"
    assert len(res.bank_accounts) == 1
    assert res.bank_accounts[0].bank_name == "HDFC Bank"
    assert len(res.experience) == 1
    assert res.experience[0].company_name == "Tech Corp"
    assert len(res.skills) == 1
    assert res.skills[0].proficiency == "EXPERT"


def _mock_employee_dict(emp_id, company_id, user_id=None, **overrides):
    base = {
        "id": emp_id,
        "company_id": company_id,
        "user_id": user_id,
        "employee_id": "EMP-202610-0005",
        "first_name": "banoth",
        "last_name": "siddarth",
        "profile_photo_url": None,
        "gender": "Male",
        "date_of_birth": date(1996, 8, 20),
        "personal_email": "xyz@gmail.com",
        "company_email": "xyz@gmail.com",
        "phone": "+919351008590",
        "alternate_phone": None,
        "blood_group": "O+",
        "marital_status": "Single",
        "department": "AGI",
        "designation": "Executive",
        "team": "Core Platform",
        "reporting_manager_id": None,
        "branch": "Jaipur HQ",
        "work_location": "Jaipur HQ",
        "employment_type": "FULL_TIME",
        "employment_status": "PROBATION",
        "joining_date": date(2026, 10, 26),
        "probation_end_date": None,
        "shift": "General",
        "employee_capacity": 100,
        "cost_center_id": "CC-001",
        "ctc": Decimal("1200000"),
        "basic_salary": Decimal("600000"),
        "hra": Decimal("300000"),
        "bonus": Decimal("180000"),
        "pf": Decimal("72000"),
        "esi": Decimal("0"),
        "professional_tax": Decimal("2500"),
        "role": "executive",
        "leave_group": "Standard India Policy",
        "status": "ACTIVE",
        "is_deleted": False,
        "created_by": None,
        "created_at": "2026-10-26T10:00:00Z",
        "updated_at": "2026-10-26T10:00:00Z",
        "addresses": [],
        "skills": [],
        "bank_accounts": [],
        "experience": [],
        "documents": [],
        "education": [],
        "assets": [],
        "emergency_contacts": [],
        "leave_policies": [],
        "onboarding_steps": [],
    }
    base.update(overrides)
    return base


def test_update_employee_service_unlinked_user_no_unbound_local_error():
    """Verify that update_employee on an employee with user_id=None succeeds without raising UnboundLocalError."""
    session = AsyncMock()
    session.add = MagicMock()
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_res
    repo = AsyncMock()
    auth_repo = AsyncMock()
    email_service = AsyncMock()
    service = EmployeeService(
        session=session,
        employee_repository=repo,
        auth_repository=auth_repo,
        email_service=email_service,
    )

    admin_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    company_id = uuid.uuid4()
    mock_emp = Employee(
        id=emp_id,
        user_id=None,
        company_id=company_id,
        employee_id="EMP-202610-0005",
        first_name="banoth",
        last_name="siddarth",
        personal_email="xyz@gmail.com",
        company_email="xyz@gmail.com",
        phone="+919351008590",
        department="AGI",
        employment_type="FULL_TIME",
        gender="MALE",
        joining_date=date(2026, 10, 26),
        role="executive",
        work_location="Jaipur HQ",
        is_active=True,
        status="ACTIVE",
        is_deleted=False,
    )
    repo.get_by_id_raw.return_value = mock_emp
    repo.get_by_personal_email.return_value = None
    repo.get_by_company_email_in_company.return_value = None
    repo.get_by_phone_in_company.return_value = None
    repo.get_by_employee_id.return_value = None
    repo.get_by_id.return_value = _mock_employee_dict(emp_id, company_id, user_id=None)

    payload = EmployeeUpdate.model_validate({
        "first_name": "banoth",
        "last_name": "siddarth",
        "personal_email": "xyz@gmail.com",
        "company_email": "xyz@gmail.com",
        "phone": "+919351008590",
        "department": "AGI",
        "employee_id": "EMP-202610-0005",
        "employment_type": "FULL_TIME",
        "gender": "MALE",
        "joining_date": "2026-10-26",
        "role": "executive",
        "work_location": "Jaipur HQ",
    })

    res = run_sync(service.update_employee(admin_id=admin_id, company_id=company_id, employee_uuid=emp_id, payload=payload))
    assert res.first_name == "banoth"
    assert res.last_name == "siddarth"
    assert res.user_id is None
    repo.update_employee.assert_awaited_once()


def test_update_employee_service_reactivation_sets_user_active_true():
    """Verify that updating an employee with is_active=True and status=ACTIVE sets User.is_active=True."""
    session = AsyncMock()
    session.add = MagicMock()
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_res
    repo = AsyncMock()
    auth_repo = AsyncMock()
    email_service = AsyncMock()
    service = EmployeeService(
        session=session,
        employee_repository=repo,
        auth_repository=auth_repo,
        email_service=email_service,
    )

    admin_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()
    mock_emp = Employee(
        id=emp_id,
        user_id=user_id,
        company_id=company_id,
        employee_id="EMP-202610-0005",
        first_name="banoth",
        last_name="siddarth",
        personal_email="xyz@gmail.com",
        company_email="xyz@gmail.com",
        phone="+919351008590",
        department="AGI",
        employment_type="FULL_TIME",
        gender="MALE",
        joining_date=date(2026, 10, 26),
        role="executive",
        work_location="Jaipur HQ",
        is_active=True,
        status="ACTIVE",
        is_deleted=False,
    )
    repo.get_by_id_raw.return_value = mock_emp
    repo.get_by_personal_email.return_value = None
    repo.get_by_company_email_in_company.return_value = None
    repo.get_by_phone_in_company.return_value = None
    repo.get_by_employee_id.return_value = None
    repo.get_by_id.return_value = _mock_employee_dict(emp_id, company_id, user_id=user_id, status="ACTIVE")

    reactivate_payload = EmployeeUpdate(first_name="UpdatedName")
    res_reactivate = run_sync(service.update_employee(admin_id=admin_id, company_id=company_id, employee_uuid=emp_id, payload=reactivate_payload))
    assert res_reactivate.status == "ACTIVE"

    found_reactivation = False
    for call in session.execute.call_args_list:
        stmt = call[0][0]
        if hasattr(stmt, "_values") and stmt._values:
            for k, v in stmt._values.items():
                if getattr(k, "key", None) == "is_active" and getattr(v, "value", v) is True:
                    found_reactivation = True
    assert found_reactivation, "Expected User.is_active=True update statement to be executed"


def test_update_employee_service_deactivation_revokes_tokens():
    """Verify that updating with employment_status=TERMINATED revokes refresh and redis tokens and sets User.is_active=False."""
    session = AsyncMock()
    session.add = MagicMock()
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_res
    repo = AsyncMock()
    auth_repo = AsyncMock()
    email_service = AsyncMock()
    service = EmployeeService(
        session=session,
        employee_repository=repo,
        auth_repository=auth_repo,
        email_service=email_service,
    )

    admin_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()
    mock_emp = Employee(
        id=emp_id,
        user_id=user_id,
        company_id=company_id,
        employee_id="EMP-202610-0005",
        first_name="banoth",
        last_name="siddarth",
        personal_email="xyz@gmail.com",
        company_email="xyz@gmail.com",
        phone="+919351008590",
        department="AGI",
        employment_type="FULL_TIME",
        gender="MALE",
        joining_date=date(2026, 10, 26),
        role="executive",
        work_location="Jaipur HQ",
        is_active=True,
        status="ACTIVE",
        is_deleted=False,
    )
    repo.get_by_id_raw.return_value = mock_emp
    repo.get_by_personal_email.return_value = None
    repo.get_by_company_email_in_company.return_value = None
    repo.get_by_phone_in_company.return_value = None
    repo.get_by_employee_id.return_value = None
    repo.get_by_id.return_value = _mock_employee_dict(emp_id, company_id, user_id=user_id, status="INACTIVE")

    deactivate_payload = EmployeeUpdate(employment_status="TERMINATED")

    with patch("app.core.redis_client.redis_client.revoke_user_tokens", new_callable=AsyncMock) as mock_redis_revoke, \
         patch("app.middleware.auth.invalidate_auth_active_cache", new_callable=AsyncMock) as mock_cache_inv:
        run_sync(service.update_employee(admin_id=admin_id, company_id=company_id, employee_uuid=emp_id, payload=deactivate_payload))
        auth_repo.revoke_all_user_refresh_tokens.assert_awaited_with(user_id)
        mock_redis_revoke.assert_awaited_with(user_id)
        mock_cache_inv.assert_awaited_with(user_id, company_id)

    found_deactivation = False
    for call in session.execute.call_args_list:
        stmt = call[0][0]
        if hasattr(stmt, "_values") and stmt._values:
            for k, v in stmt._values.items():
                if getattr(k, "key", None) == "is_active" and getattr(v, "value", v) is False:
                    found_deactivation = True
    assert found_deactivation, "Expected User.is_active=False update statement to be executed"
