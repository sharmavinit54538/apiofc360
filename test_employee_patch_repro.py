import asyncio
import sys
import os
import uuid
import traceback

sys.path.insert(0, os.getcwd())

from app.db.database import AsyncSessionLocal
from app.models.employee import Employee
from app.schemas.employee.update import EmployeeUpdate
from app.services.employee_service import EmployeeService
from app.repositories.employee_repository import EmployeeRepository
from app.repositories.auth_repository import AuthRepository
from app.services.email_service import EmailService
from app.core.exceptions import AppException, NotFoundException, ConflictException
from sqlalchemy import select

payload_dict = {
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

async def main():
    company_id = uuid.UUID("c749fc92-0bcc-48dd-9404-2a23ac8d6b2a")
    admin_id = uuid.uuid4()
    target_uuid = uuid.UUID("e7f1f422-2dab-40a1-8101-16102b9c2e65")

    print("--- 1. Testing EmployeeUpdate Pydantic Schema Parsing ---")
    try:
        update_schema = EmployeeUpdate(**payload_dict)
        print("EmployeeUpdate Pydantic model dump:")
        print(update_schema.model_dump(exclude_unset=True))
    except Exception as e:
        print("Schema validation failed!")
        traceback.print_exc()

    async with AsyncSessionLocal() as session:
        repo = EmployeeRepository(session)
        auth_repo = AuthRepository(session)
        email_svc = EmailService()
        service = EmployeeService(
            session=session,
            employee_repository=repo,
            auth_repository=auth_repo,
            email_service=email_svc,
        )
        
        # Test non-existent employee update
        print("\n--- 2. Testing Update on Non-Existent Employee ID ---")
        try:
            res = await service.update_employee(
                admin_id=admin_id,
                company_id=company_id,
                employee_uuid=target_uuid,
                payload=EmployeeUpdate(**payload_dict)
            )
            print("Result:", res)
        except Exception as e:
            print(f"Caught exception on non-existent employee: {type(e).__name__}: {e}")
            traceback.print_exc()

        # Check existing employee 43be8db8-9c72-4409-9c4e-1bf54e0a3eba
        existing_emp_id = uuid.UUID("43be8db8-9c72-4409-9c4e-1bf54e0a3eba")
        emp_res = await session.execute(select(Employee).where(Employee.id == existing_emp_id))
        emp = emp_res.scalar_one_or_none()
        print("\nExisting employee:", emp.__dict__ if emp else None)
        
        if emp:
            # Set company_id on existing employee if None so service won't reject company check
            if emp.company_id is None:
                emp.company_id = company_id
                await session.commit()
            
            print("\n--- 3. Testing Update on Existing Employee ID ---")
            try:
                res = await service.update_employee(
                    admin_id=admin_id,
                    company_id=company_id,
                    employee_uuid=existing_emp_id,
                    payload=EmployeeUpdate(**payload_dict)
                )
                print("Result success:", res)
            except Exception as e:
                print(f"Caught exception on existing employee: {type(e).__name__}: {e}")
                traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
