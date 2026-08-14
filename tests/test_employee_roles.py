import pytest
from pydantic import ValidationError

from app.schemas.employee.create import EmployeeCreate
from app.schemas.employee.constants import ROLE_VALUES
from app.schemas.manager import ManagerCreate


def test_allowed_roles_in_constants():
    """Assert that ROLE_VALUES contains exactly the 6 system roles."""
    expected_roles = {"super_admin", "hr_admin", "manager", "employee", "executive", "it_admin"}
    assert ROLE_VALUES == expected_roles


@pytest.mark.parametrize("valid_role", [
    "super_admin",
    "hr_admin",
    "manager",
    "employee",
    "executive",
    "it_admin",
])
def test_valid_roles_accepted_in_employee_create(valid_role):
    """Assert that all 6 system roles pass EmployeeCreate validation."""
    data = {
        "employee_id": "EMP-001",
        "first_name": "John",
        "last_name": "Doe",
        "personal_email": "john.doe@example.com",
        "phone": "9876543210",
        "department": "Engineering",
        "designation": "Software Engineer",
        "joining_date": "2026-01-01",
        "role": valid_role,
    }
    emp = EmployeeCreate(**data)
    assert emp.role == valid_role


@pytest.mark.parametrize("invalid_role", [
    "ceo",
    "admin",
    "junior developer",
    "cfo",
    "cto",
    "coo",
    "cmo",
    "clo",
    "ciso",
    "cio",
    "superadmin",
])
def test_invalid_roles_rejected_in_employee_create(invalid_role):
    """Assert that any non-system role returns 422 validation error with exact message."""
    data = {
        "employee_id": "EMP-001",
        "first_name": "Jane",
        "last_name": "Doe",
        "personal_email": "jane.doe@example.com",
        "phone": "9876543210",
        "department": "Engineering",
        "designation": "Software Engineer",
        "joining_date": "2026-01-01",
        "role": invalid_role,
    }
    with pytest.raises(ValidationError) as exc_info:
        EmployeeCreate(**data)
    
    error_msg = str(exc_info.value)
    assert "role must be one of: super_admin, hr_admin, manager, employee, executive, it_admin" in error_msg


@pytest.mark.parametrize("invalid_role", [
    "ceo",
    "admin",
    "junior developer",
])
def test_invalid_roles_rejected_in_manager_create(invalid_role):
    """Assert that ManagerCreate schema also rejects old and non-system roles."""
    data = {
        "employee_id": "MGR-001",
        "first_name": "Manager",
        "last_name": "Test",
        "personal_email": "mgr.test@example.com",
        "phone": "9876543210",
        "department": "Management",
        "designation": "Engineering Manager",
        "joining_date": "2026-01-01",
        "role": invalid_role,
    }
    with pytest.raises(ValidationError) as exc_info:
        ManagerCreate(**data)
    
    error_msg = str(exc_info.value)
    assert "role must be one of: super_admin, hr_admin, manager, employee, executive, it_admin" in error_msg
