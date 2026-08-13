import asyncio
import sys
import os
import uuid
from datetime import date
from decimal import Decimal
import traceback

sys.path.insert(0, os.getcwd())

from app.db.database import AsyncSessionLocal
from app.models.employee import Employee
from app.models.company import Company
from app.models.user import User
from app.schemas.employee.update import EmployeeUpdate
from app.services.employee_service import EmployeeService
from app.repositories.employee_repository import EmployeeRepository
from app.repositories.auth_repository import AuthRepository
from app.services.email_service import EmailService
from app.core.exceptions import AppException, ConflictException, NotFoundException
from sqlalchemy import select

target_payload = {
  "first_name": "Rubel",
  "last_name": "SIngh Thakur",
  "personal_email": "rubelthakur614@gmail.com",
  "company_email": "rubelthakur614@gmail.com",
  "phone": "08580625010",
  "date_of_birth": "1995-05-15",
  "gender": "Male",
  "blood_group": "O+",
  "marital_status": "Single",
  "joining_date": "2026-08-04",
  "department": "Engineering",
  "designation": "Junior Developer",
  "role": "junior developer",
  "employment_type": "FULL_TIME",
  "branch": "Mumbai HQ",
  "work_location": "Onsite",
  "shift": "Morning",
  "leave_group": "Standard India Policy",
  "cost_center_id": "CC-ENG-01",
  "ctc": 7200000,
  "bonus": 180000,
  "hra": 300000
}

async def run_tests():
    target_id = uuid.UUID("e7f1f422-2dab-40a1-8101-16102b9c2e65")

    async with AsyncSessionLocal() as session:
        # Get company_id
        comp_res = await session.execute(select(Company))
        comp = comp_res.scalars().first()
        assert comp is not None, "Company must exist"
        company_id = comp.id

        # Get or create admin user for audit log
        user_res = await session.execute(select(User).where(User.company_id == company_id))
        admin_user = user_res.scalars().first()
        if not admin_user:
            admin_user = User(
                id=uuid.uuid4(),
                email="admin_test@ofc360.com",
                hashed_password="hashed_pwd",
                role="ADMIN",
                company_id=company_id
            )
            session.add(admin_user)
            await session.commit()
            await session.refresh(admin_user)

        admin_id = admin_user.id

        repo = EmployeeRepository(session)
        auth_repo = AuthRepository(session)
        email_svc = EmailService()
        service = EmployeeService(
            session=session,
            employee_repository=repo,
            auth_repository=auth_repo,
            email_service=email_svc,
        )

        print("==================================================")
        print("TEST 1: Update target employee e7f1f422-2dab-40a1-8101-16102b9c2e65 with full payload")
        print("==================================================")
        update_schema = EmployeeUpdate(**target_payload)
        res = await service.update_employee(
            admin_id=admin_id,
            company_id=company_id,
            employee_uuid=target_id,
            payload=update_schema
        )
        print(f"SUCCESS! Updated Employee Response ID: {res.id}, Name: {res.first_name} {res.last_name}")
        assert str(res.id) == str(target_id)
        assert res.first_name == "Rubel"
        assert res.last_name == "SIngh Thakur"
        assert res.personal_email == "rubelthakur614@gmail.com"
        assert res.company_email == "rubelthakur614@gmail.com"
        assert res.phone == "08580625010"
        assert res.department == "Engineering"
        assert res.designation == "Junior Developer"
        assert res.employment_type == "FULL_TIME"
        assert res.cost_center_id == "CC-ENG-01"

        print("\n==================================================")
        print("TEST 2: Partial PATCH with only 1 field (first_name='RubelUpdated')")
        print("==================================================")
        partial_schema = EmployeeUpdate(first_name="RubelUpdated")
        res_partial = await service.update_employee(
            admin_id=admin_id,
            company_id=company_id,
            employee_uuid=target_id,
            payload=partial_schema
        )
        print(f"SUCCESS! First Name updated to: {res_partial.first_name}")
        assert res_partial.first_name == "RubelUpdated"
        # Verify other fields remain unchanged!
        assert res_partial.last_name == "SIngh Thakur"
        assert res_partial.personal_email == "rubelthakur614@gmail.com"
        assert res_partial.phone == "08580625010"

        print("\n==================================================")
        print("TEST 3: Empty PATCH payload")
        print("==================================================")
        empty_schema = EmployeeUpdate()
        res_empty = await service.update_employee(
            admin_id=admin_id,
            company_id=company_id,
            employee_uuid=target_id,
            payload=empty_schema
        )
        print(f"SUCCESS! Empty payload returned employee ID: {res_empty.id}")
        assert res_empty.first_name == "RubelUpdated"

        print("\n==================================================")
        print("TEST 4: Non-existent employee UUID")
        print("==================================================")
        fake_uuid = uuid.uuid4()
        try:
            await service.update_employee(
                admin_id=admin_id,
                company_id=company_id,
                employee_uuid=fake_uuid,
                payload=EmployeeUpdate(first_name="Test")
            )
            print("FAILED: Should have raised AppException 404")
        except AppException as e:
            print(f"SUCCESS! Caught 404 exception: {e.message} (status: {e.status_code})")
            assert e.status_code == 404

        print("\n==================================================")
        print("TEST 5: Duplicate Personal Email")
        print("==================================================")
        # Create second employee
        emp2_id = uuid.uuid4()
        emp2_code = f"EMP-TEST-{uuid.uuid4().hex[:6]}"
        emp2_email = f"other_unique_{uuid.uuid4().hex[:6]}@gmail.com"
        emp2_phone = f"09{uuid.uuid4().int % 1000000009:09d}"
        emp2 = Employee(
            id=emp2_id,
            company_id=company_id,
            employee_id=emp2_code,
            first_name="Other",
            last_name="User",
            personal_email=emp2_email,
            phone=emp2_phone,
            department="Sales",
            designation="Manager",
            joining_date=date(2026, 1, 1),
            status="ACTIVE"
        )
        session.add(emp2)
        await session.commit()

        try:
            await service.update_employee(
                admin_id=admin_id,
                company_id=company_id,
                employee_uuid=target_id,
                payload=EmployeeUpdate(personal_email=emp2_email)
            )
            print("FAILED: Should have raised ConflictException for duplicate personal email")
        except ConflictException as e:
            print(f"SUCCESS! Caught duplicate personal email exception: {e.message} (field: {e.field})")
            assert e.field == "personal_email"

        print("\n==================================================")
        print("TEST 6: Duplicate Phone Number")
        print("==================================================")
        try:
            await service.update_employee(
                admin_id=admin_id,
                company_id=company_id,
                employee_uuid=target_id,
                payload=EmployeeUpdate(phone=emp2_phone)
            )
            print("FAILED: Should have raised ConflictException for duplicate phone")
        except ConflictException as e:
            print(f"SUCCESS! Caught duplicate phone exception: {e.message} (field: {e.field})")
            assert e.field == "phone"

        print("\n==================================================")
        print("TEST 7: Invalid reporting manager")
        print("==================================================")
        try:
            await service.update_employee(
                admin_id=admin_id,
                company_id=company_id,
                employee_uuid=target_id,
                payload=EmployeeUpdate(reporting_manager_id=uuid.uuid4())
            )
            print("FAILED: Should have raised 400 for invalid reporting manager")
        except AppException as e:
            print(f"SUCCESS! Caught invalid manager exception: {e.message} (status: {e.status_code})")
            assert e.status_code == 400

        print("\n==================================================")
        print("ALL TESTS PASSED SUCCESSFULLY!")
        print("==================================================")

if __name__ == "__main__":
    asyncio.run(run_tests())
