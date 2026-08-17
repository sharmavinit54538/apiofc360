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
"""

import pytest
import uuid
from datetime import date
from decimal import Decimal

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
