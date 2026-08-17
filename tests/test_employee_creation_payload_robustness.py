"""Unit tests verifying Employee & Manager create payload robustness and proficiency validation."""

import pytest
from pydantic import ValidationError
from app.schemas.employee.create import EmployeeCreate
from app.schemas.employee.skill import EmployeeSkillCreate
from app.schemas.manager import ManagerCreate, ManagerSkillCreate


def test_proficiency_variations():
    """Verify that proficiency accepts synonyms, whitespace, case differences, and None/empty."""
    # Standard values
    assert EmployeeSkillCreate(skill_name="Python", proficiency="BEGINNER").proficiency == "BEGINNER"
    assert EmployeeSkillCreate(skill_name="Python", proficiency="INTERMEDIATE").proficiency == "INTERMEDIATE"
    assert EmployeeSkillCreate(skill_name="Python", proficiency="ADVANCED").proficiency == "ADVANCED"
    assert EmployeeSkillCreate(skill_name="Python", proficiency="EXPERT").proficiency == "EXPERT"

    # Case & Whitespace
    assert EmployeeSkillCreate(skill_name="Python", proficiency=" expert ").proficiency == "EXPERT"
    assert EmployeeSkillCreate(skill_name="Python", proficiency="advanced").proficiency == "ADVANCED"
    assert EmployeeSkillCreate(skill_name="Python", proficiency="intermediate ").proficiency == "INTERMEDIATE"
    assert EmployeeSkillCreate(skill_name="Python", proficiency="beginner").proficiency == "BEGINNER"

    # Synonyms
    assert EmployeeSkillCreate(skill_name="Python", proficiency="basic").proficiency == "BEGINNER"
    assert EmployeeSkillCreate(skill_name="Python", proficiency="novice").proficiency == "BEGINNER"
    assert EmployeeSkillCreate(skill_name="Python", proficiency="master").proficiency == "EXPERT"
    assert EmployeeSkillCreate(skill_name="Python", proficiency="lead").proficiency == "EXPERT"

    # Empty & None
    assert EmployeeSkillCreate(skill_name="Python", proficiency="").proficiency is None
    assert EmployeeSkillCreate(skill_name="Python", proficiency=None).proficiency is None


def test_full_employee_create_with_flexible_payload():
    """Test full EmployeeCreate with nested objects having whitespace, aliases, and empty rows."""
    payload = {
        "first_name": "Sunaina",
        "last_name": "Mehra",
        "personal_email": "sunainam757@gmail.com",
        "phone": "7717544655",
        "department": "Engineering",
        "designation": "Senior Frontend Engineer",
        "employment_type": "FULL_TIME",
        "joining_date": "2026-08-17",
        "basic_salary": 600000,
        "blood_group": "O+",
        "bonus": 180000,
        "branch": "Mumbai HQ",
        "company_email": "sunaina@ofc360.com",
        "cost_center_id": "CC-001",
        "ctc": 1200000,
        "date_of_birth": "1996-08-20",
        "employee_capacity": 100,
        "esi": 0,
        "gender": "Male",
        "hra": 300000,
        "leave_group": "Standard India Policy",
        "marital_status": "Single",
        "pf": 72000,
        "probation_period_months": 3,
        "professional_tax": 2500,
        "role": "employee",
        "shift": "General",
        "team": "Core Platform",
        "work_location": "Remote",
        "documents": [
            {"document_type": "PAN", "document_number": "ABCDE1234F", "document_url": None, "expiry_date": None},
            {"document_type": "", "document_number": ""}
        ],
        "emergency_contacts": [
            {"name": "Ramesh Sharma", "relation": "Parent", "phone": "+91 9876543210", "alternate_phone": "", "email": "", "address": ""}
        ],
        "skills": [
            {"skill_name": "React", "proficiency": "Expert", "years_of_experience": 4},
            {"name": "TypeScript", "proficiency": "Advanced", "years_of_experience": "3"},
            {"skill_name": "Node.js", "proficiency": "Intermediate "},
            {"skill_name": "Docker", "proficiency": ""},
            {"skill_name": "", "proficiency": ""}
        ],
        "addresses": [
            {"address_type": "CURRENT", "address_line_1": "Flat 402, Highrise Tower, Andheri East", "address_line_2": ""},
            {"address_type": "", "address_line_1": ""}
        ],
        "education": [
            {"degree": "B.Tech", "institution": "Mumbai University", "start_year": "2014-06-01", "end_year": "2018", "grade": ""}
        ],
        "bank_accounts": [
            {"bank_name": "HDFC Bank", "account_number": "123456789012", "ifsc_code": "hdfc0001234", "account_type": "savings", "account_holder_name": ""}
        ]
    }

    emp = EmployeeCreate(**payload)
    assert emp.first_name == "Sunaina"
    assert len(emp.skills) == 4
    assert emp.skills[0].proficiency == "EXPERT"
    assert emp.skills[1].skill_name == "TypeScript"
    assert emp.skills[1].proficiency == "ADVANCED"
    assert emp.skills[1].years_of_experience == 3
    assert emp.skills[2].proficiency == "INTERMEDIATE"
    assert emp.skills[3].proficiency is None

    assert len(emp.documents) == 1
    assert len(emp.addresses) == 1
    assert emp.emergency_contacts[0].email is None
    assert emp.education[0].start_year == 2014
    assert emp.education[0].end_year == 2018
    assert emp.bank_accounts[0].ifsc_code == "HDFC0001234"
    assert emp.bank_accounts[0].account_type == "SAVINGS"
