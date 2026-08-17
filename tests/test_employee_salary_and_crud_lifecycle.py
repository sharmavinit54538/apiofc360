"""Comprehensive regression and lifecycle test suite for OFC360 Employee Salary & CRUD operations.

Tests:
1. Partial employee update preserving CTC.
2. Partial employee update preserving HRA.
3. HRA > CTC rejection (Schema & Service).
4. Basic salary > CTC rejection (Schema & Service).
5. Updating CTC with existing HRA.
6. Updating non-salary fields without changing salary.
7. Full salary update with valid compensation breakup.
8. Create -> Read -> Update -> Read -> Delete lifecycle with soft-delete verification.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest
from pydantic import ValidationError

from app.core.exceptions import AppException, ConflictException, NotFoundException
from app.models.employee import Employee
from app.models.company import Company
from app.models.user import User
from app.schemas.employee.create import EmployeeCreate
from app.schemas.employee.update import EmployeeUpdate
from app.schemas.employee.profile import EmployeeResponse
from app.services.employee_service import EmployeeService


def _create_mock_employee(
    emp_id: uuid.UUID,
    company_id: uuid.UUID,
    *,
    ctc: Decimal = Decimal("1200000"),
    basic_salary: Decimal = Decimal("600000"),
    hra: Decimal = Decimal("300000"),
    bonus: Decimal = Decimal("180000"),
    designation: str = "Senior Frontend Engineer",
    is_deleted: bool = False,
) -> Employee:
    emp = Employee(
        id=emp_id,
        company_id=company_id,
        user_id=None,
        employee_id="EMP-202608-0008",
        first_name="Sunaina",
        last_name="Mehra",
        personal_email="sunaina.mehra@example.com",
        company_email="sunaina.mehra@ofc360.com",
        phone="9876543210",
        department="Engineering",
        designation=designation,
        employment_type="FULL_TIME",
        employment_status="CONFIRMED",
        joining_date=date(2026, 8, 17),
        ctc=ctc,
        basic_salary=basic_salary,
        hra=hra,
        bonus=bonus,
        pf=Decimal("72000"),
        esi=Decimal("0"),
        professional_tax=Decimal("2500"),
        role="employee",
        status="ACTIVE",
        is_deleted=is_deleted,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    # Populate empty relation lists to satisfy ORM serializer
    emp.addresses = []
    emp.documents = []
    emp.education = []
    emp.experience = []
    emp.skills = []
    emp.assets = []
    emp.emergency_contacts = []
    emp.bank_accounts = []
    emp.leave_policies = []
    emp.onboarding_steps = []
    return emp


# ==============================================================================
# 1. Partial employee update preserving CTC
# ==============================================================================
@pytest.mark.asyncio
async def test_partial_employee_update_preserves_ctc():
    """Updating only designation must preserve existing DB CTC (1200000) and other salary fields."""
    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    emp_id = uuid.uuid4()

    mock_emp = _create_mock_employee(emp_id, company_id, ctc=Decimal("1200000"), designation="Frontend Engineer")

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=MagicMock(id=admin_id))))
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    mock_repo = MagicMock()
    mock_repo.get_by_id_raw = AsyncMock(return_value=mock_emp)
    mock_repo.get_by_id = AsyncMock(return_value=mock_emp)
    mock_repo.update_employee = AsyncMock()

    service = EmployeeService(
        session=mock_session,
        employee_repository=mock_repo,
        auth_repository=MagicMock(),
        email_service=MagicMock(),
    )

    update_payload = EmployeeUpdate(designation="Senior Frontend Engineer")
    result = await service.update_employee(
        admin_id=admin_id,
        company_id=company_id,
        employee_uuid=emp_id,
        payload=update_payload,
    )

    # Verify update_employee call arguments did NOT contain 'ctc'
    called_kwargs = mock_repo.update_employee.call_args[1]
    assert "ctc" not in called_kwargs
    assert called_kwargs.get("designation") == "Senior Frontend Engineer"

    # Verify response retains existing salary values
    assert result.ctc == Decimal("1200000")
    assert result.basic_salary == Decimal("600000")
    assert result.hra == Decimal("300000")
    assert result.bonus == Decimal("180000")


# ==============================================================================
# 2. Partial employee update preserving HRA
# ==============================================================================
@pytest.mark.asyncio
async def test_partial_employee_update_preserves_hra():
    """Updating CTC evaluates against existing HRA (300000) and preserves HRA."""
    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    emp_id = uuid.uuid4()

    mock_emp = _create_mock_employee(emp_id, company_id, ctc=Decimal("1200000"), hra=Decimal("300000"), basic_salary=Decimal("600000"))

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=MagicMock(id=admin_id))))
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    mock_repo = MagicMock()
    mock_repo.get_by_id_raw = AsyncMock(return_value=mock_emp)
    mock_repo.get_by_id = AsyncMock(return_value=mock_emp)
    mock_repo.update_employee = AsyncMock()

    service = EmployeeService(
        session=mock_session,
        employee_repository=mock_repo,
        auth_repository=MagicMock(),
        email_service=MagicMock(),
    )

    # Valid CTC increase
    update_payload = EmployeeUpdate(ctc=Decimal("1500000"))
    result = await service.update_employee(
        admin_id=admin_id,
        company_id=company_id,
        employee_uuid=emp_id,
        payload=update_payload,
    )

    called_kwargs = mock_repo.update_employee.call_args[1]
    assert called_kwargs.get("ctc") == Decimal("1500000")
    assert "hra" not in called_kwargs


# ==============================================================================
# 3. HRA > CTC rejection
# ==============================================================================
@pytest.mark.asyncio
async def test_hra_exceeds_ctc_rejection():
    """HRA > CTC must fail both in Pydantic schema validation and in service layer against existing DB CTC."""
    # 3a. Schema level rejection
    with pytest.raises(ValidationError) as exc_info:
        EmployeeCreate(
            first_name="Sunaina",
            last_name="Mehra",
            personal_email="sunaina@example.com",
            phone="9876543210",
            department="Engineering",
            designation="Senior Frontend Engineer",
            employment_type="FULL_TIME",
            joining_date=date(2026, 8, 17),
            ctc=Decimal("200000"),
            hra=Decimal("300000"),
        )
    assert "hra (300000) cannot exceed ctc (200000)" in str(exc_info.value)

    # 3b. Service level rejection against existing DB CTC=200000
    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    emp_id = uuid.uuid4()

    mock_emp = _create_mock_employee(emp_id, company_id, ctc=Decimal("200000"), hra=Decimal("50000"), basic_salary=Decimal("100000"), bonus=Decimal("20000"))

    mock_session = AsyncMock()
    mock_repo = MagicMock()
    mock_repo.get_by_id_raw = AsyncMock(return_value=mock_emp)

    service = EmployeeService(
        session=mock_session,
        employee_repository=mock_repo,
        auth_repository=MagicMock(),
        email_service=MagicMock(),
    )

    # Try to partially update HRA to 300000 (which exceeds existing DB CTC 200000)
    update_payload = EmployeeUpdate(hra=Decimal("300000"))
    with pytest.raises(AppException) as app_exc:
        await service.update_employee(
            admin_id=admin_id,
            company_id=company_id,
            employee_uuid=emp_id,
            payload=update_payload,
        )
    assert app_exc.value.status_code == 400
    assert "hra (300000) cannot exceed ctc (200000)" in app_exc.value.message


# ==============================================================================
# 4. Basic salary > CTC rejection
# ==============================================================================
@pytest.mark.asyncio
async def test_basic_salary_exceeds_ctc_rejection():
    """Basic salary > CTC must be rejected."""
    # 4a. Schema level
    with pytest.raises(ValidationError) as exc_info:
        EmployeeCreate(
            first_name="Sunaina",
            last_name="Mehra",
            personal_email="sunaina@example.com",
            phone="9876543210",
            department="Engineering",
            designation="Senior Frontend Engineer",
            employment_type="FULL_TIME",
            joining_date=date(2026, 8, 17),
            ctc=Decimal("500000"),
            basic_salary=Decimal("600000"),
        )
    assert "basic_salary (600000) cannot exceed ctc (500000)" in str(exc_info.value)

    # 4b. Service level
    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    emp_id = uuid.uuid4()

    mock_emp = _create_mock_employee(emp_id, company_id, ctc=Decimal("500000"), basic_salary=Decimal("250000"), hra=Decimal("100000"), bonus=Decimal("50000"))

    mock_session = AsyncMock()
    mock_repo = MagicMock()
    mock_repo.get_by_id_raw = AsyncMock(return_value=mock_emp)

    service = EmployeeService(
        session=mock_session,
        employee_repository=mock_repo,
        auth_repository=MagicMock(),
        email_service=MagicMock(),
    )

    update_payload = EmployeeUpdate(basic_salary=Decimal("600000"))
    with pytest.raises(AppException) as app_exc:
        await service.update_employee(
            admin_id=admin_id,
            company_id=company_id,
            employee_uuid=emp_id,
            payload=update_payload,
        )
    assert app_exc.value.status_code == 400
    assert "basic_salary (600000) cannot exceed ctc (500000)" in app_exc.value.message


# ==============================================================================
# 5. Updating CTC with existing HRA & basic salary
# ==============================================================================
@pytest.mark.asyncio
async def test_updating_ctc_evaluates_against_existing_salary():
    """Decreasing CTC below existing DB HRA or basic_salary must be rejected."""
    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    emp_id = uuid.uuid4()

    # Existing: basic=600k, hra=300k, bonus=180k, ctc=1.2M
    mock_emp = _create_mock_employee(emp_id, company_id, ctc=Decimal("1200000"), basic_salary=Decimal("600000"), hra=Decimal("300000"), bonus=Decimal("180000"))

    mock_session = AsyncMock()
    mock_repo = MagicMock()
    mock_repo.get_by_id_raw = AsyncMock(return_value=mock_emp)

    service = EmployeeService(
        session=mock_session,
        employee_repository=mock_repo,
        auth_repository=MagicMock(),
        email_service=MagicMock(),
    )

    # Change CTC to 500000 while basic_salary is 600000 in DB
    update_payload = EmployeeUpdate(ctc=Decimal("500000"))
    with pytest.raises(AppException) as app_exc:
        await service.update_employee(
            admin_id=admin_id,
            company_id=company_id,
            employee_uuid=emp_id,
            payload=update_payload,
        )
    assert app_exc.value.status_code == 400
    assert "basic_salary (600000) cannot exceed ctc (500000)" in app_exc.value.message


# ==============================================================================
# 6. Updating non-salary fields without changing salary
# ==============================================================================
@pytest.mark.asyncio
async def test_updating_non_salary_fields_preserves_salary():
    """Updating first_name, phone, branch, shift, team does not alter salary fields."""
    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    emp_id = uuid.uuid4()

    mock_emp = _create_mock_employee(emp_id, company_id)

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=MagicMock(id=admin_id))))
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    mock_repo = MagicMock()
    mock_repo.get_by_id_raw = AsyncMock(return_value=mock_emp)
    mock_repo.get_by_id = AsyncMock(return_value=mock_emp)
    mock_repo.get_by_phone_in_company = AsyncMock(return_value=None)
    mock_repo.update_employee = AsyncMock()

    service = EmployeeService(
        session=mock_session,
        employee_repository=mock_repo,
        auth_repository=MagicMock(),
        email_service=MagicMock(),
    )

    update_payload = EmployeeUpdate(
        first_name="Sunaina Updated",
        phone="9876543299",
        branch="Bengaluru Office",
        shift="Evening",
    )
    result = await service.update_employee(
        admin_id=admin_id,
        company_id=company_id,
        employee_uuid=emp_id,
        payload=update_payload,
    )

    called_kwargs = mock_repo.update_employee.call_args[1]
    assert "ctc" not in called_kwargs
    assert "hra" not in called_kwargs
    assert "basic_salary" not in called_kwargs
    assert called_kwargs.get("first_name") == "Sunaina Updated"
    assert called_kwargs.get("phone") == "9876543299"
    assert result.ctc == Decimal("1200000")


# ==============================================================================
# 7. Full salary update with valid compensation breakup
# ==============================================================================
@pytest.mark.asyncio
async def test_full_salary_update_with_valid_breakup():
    """Updating all salary fields simultaneously with a valid compensation structure succeeds."""
    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    emp_id = uuid.uuid4()

    mock_emp = _create_mock_employee(emp_id, company_id)

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=MagicMock(id=admin_id))))
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    mock_repo = MagicMock()
    mock_repo.get_by_id_raw = AsyncMock(return_value=mock_emp)
    mock_repo.get_by_id = AsyncMock(return_value=mock_emp)
    mock_repo.update_employee = AsyncMock()

    service = EmployeeService(
        session=mock_session,
        employee_repository=mock_repo,
        auth_repository=MagicMock(),
        email_service=MagicMock(),
    )

    update_payload = EmployeeUpdate(
        ctc=Decimal("1800000"),
        basic_salary=Decimal("900000"),
        hra=Decimal("450000"),
        bonus=Decimal("250000"),
        pf=Decimal("108000"),
        esi=Decimal("0"),
        professional_tax=Decimal("2500"),
    )
    result = await service.update_employee(
        admin_id=admin_id,
        company_id=company_id,
        employee_uuid=emp_id,
        payload=update_payload,
    )

    called_kwargs = mock_repo.update_employee.call_args[1]
    assert called_kwargs.get("ctc") == Decimal("1800000")
    assert called_kwargs.get("basic_salary") == Decimal("900000")
    assert called_kwargs.get("hra") == Decimal("450000")
    assert called_kwargs.get("bonus") == Decimal("250000")


# ==============================================================================
# 8. Complete CRUD Lifecycle (Create -> Read -> Update -> Read -> Delete -> Read)
# ==============================================================================
@pytest.mark.asyncio
async def test_complete_crud_lifecycle_and_soft_delete():
    """Verify entire CRUD lifecycle preserves salary integrity and implements soft-delete correctly."""
    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    emp_id = uuid.uuid4()

    mock_emp = _create_mock_employee(emp_id, company_id)

    mock_session = AsyncMock()
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    mock_repo = MagicMock()
    mock_repo.get_by_personal_email = AsyncMock(return_value=None)
    mock_repo.get_by_company_email_in_company = AsyncMock(return_value=None)
    mock_repo.get_by_employee_id = AsyncMock(return_value=None)
    mock_repo.create_employee = AsyncMock(return_value=mock_emp)
    mock_repo.create_onboarding_steps = AsyncMock()
    mock_repo.get_by_id = AsyncMock(return_value=mock_emp)
    mock_repo.get_by_id_raw = AsyncMock(return_value=mock_emp)
    mock_repo.update_employee = AsyncMock()
    mock_repo.soft_delete = AsyncMock()

    mock_auth_repo = MagicMock()
    mock_auth_repo.revoke_all_user_refresh_tokens = AsyncMock()

    mock_email = MagicMock()
    mock_email.send_employee_onboarding_invite = AsyncMock()

    service = EmployeeService(
        session=mock_session,
        employee_repository=mock_repo,
        auth_repository=mock_auth_repo,
        email_service=mock_email,
    )

    # 1. CREATE
    create_payload = EmployeeCreate(
        employee_id="EMP-202608-0008",
        first_name="Sunaina",
        last_name="Mehra",
        personal_email="sunaina.mehra@example.com",
        company_email="sunaina.mehra@ofc360.com",
        phone="9876543210",
        department="Engineering",
        designation="Senior Frontend Engineer",
        employment_type="FULL_TIME",
        joining_date=date(2026, 8, 17),
        ctc=Decimal("1200000"),
        basic_salary=Decimal("600000"),
        hra=Decimal("300000"),
        bonus=Decimal("180000"),
    )
    created_emp = await service.create_employee(admin_id=admin_id, company_id=company_id, payload=create_payload)
    assert created_emp.first_name == "Sunaina"
    assert created_emp.ctc == Decimal("1200000")
    assert created_emp.hra == Decimal("300000")

    # 2. READ
    read_emp = await service.get_employee(employee_uuid=emp_id, company_id=company_id)
    assert read_emp.ctc == Decimal("1200000")
    assert read_emp.basic_salary == Decimal("600000")

    # 3. UPDATE (Non-salary field only)
    update_payload = EmployeeUpdate(designation="Lead Frontend Engineer")
    updated_emp = await service.update_employee(admin_id=admin_id, company_id=company_id, employee_uuid=emp_id, payload=update_payload)
    assert updated_emp.ctc == Decimal("1200000")

    # 4. READ AGAIN
    read_again = await service.get_employee(employee_uuid=emp_id, company_id=company_id)
    assert read_again.ctc == Decimal("1200000")

    # 5. DELETE (Soft delete)
    await service.delete_employee(admin_id=admin_id, company_id=company_id, employee_uuid=emp_id)
    mock_repo.soft_delete.assert_called_once_with(emp_id, deleted_by=admin_id)

    # 6. READ AFTER DELETE (get_by_id returns None for deleted)
    mock_repo.get_by_id = AsyncMock(return_value=None)
    with pytest.raises(AppException) as not_found_exc:
        await service.get_employee(employee_uuid=emp_id, company_id=company_id)
    assert not_found_exc.value.status_code == 404


# ==============================================================================
# 9. EmployeeListItem serialization includes CTC & Salary for table views
# ==============================================================================
def test_employee_list_item_serialization_includes_ctc_and_salary():
    """Verify EmployeeListItem serializes CTC, basic_salary, and salary aliases for table rendering."""
    from app.schemas.employee.update import EmployeeListItem

    emp_id = uuid.uuid4()
    mock_emp = {
        "id": emp_id,
        "employee_id": "EMP-202608-0008",
        "first_name": "Sunaina",
        "last_name": "Mehra",
        "personal_email": "sunaina.mehra@example.com",
        "phone": "9876543210",
        "department": "Engineering",
        "designation": "Senior Frontend Engineer",
        "employment_type": "FULL_TIME",
        "status": "ACTIVE",
        "joining_date": date(2026, 8, 17),
        "created_at": datetime.now(timezone.utc),
        "ctc": Decimal("1200000"),
        "basic_salary": Decimal("600000"),
        "hra": Decimal("300000"),
        "bonus": Decimal("180000"),
    }

    item = EmployeeListItem.model_validate(mock_emp)
    assert item.ctc == Decimal("1200000")
    assert item.salary == Decimal("1200000")
    assert item.annual_ctc == Decimal("1200000")
    assert item.basic_salary == Decimal("600000")
    assert item.hra == Decimal("300000")

    # Serialized dump for JSON API response
    data = item.model_dump()
    assert data["ctc"] == Decimal("1200000")
    assert data["salary"] == Decimal("1200000")
    assert data["annual_ctc"] == Decimal("1200000")

