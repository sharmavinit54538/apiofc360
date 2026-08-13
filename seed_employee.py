import asyncio
import sys
import os
import uuid
from datetime import date

sys.path.insert(0, os.getcwd())

from app.db.database import AsyncSessionLocal
from app.models.employee import Employee
from app.models.company import Company
from app.models.user import User
from sqlalchemy import select

async def seed():
    target_id = uuid.UUID("e7f1f422-2dab-40a1-8101-16102b9c2e65")
    async with AsyncSessionLocal() as session:
        # Get or create company
        res_comp = await session.execute(select(Company))
        comp = res_comp.scalars().first()
        if not comp:
            comp = Company(id=uuid.uuid4(), name="Default Company")
            session.add(comp)
            await session.commit()
            await session.refresh(comp)
        
        company_id = comp.id

        # Check if target employee exists
        res = await session.execute(select(Employee).where(Employee.id == target_id))
        emp = res.scalar_one_or_none()
        if not emp:
            print(f"Seeding employee {target_id} in company {company_id}...")
            emp = Employee(
                id=target_id,
                company_id=company_id,
                employee_id="EMP-TEST-001",
                first_name="Rubel",
                last_name="Singh",
                personal_email="rubel_test_seed@gmail.com",
                company_email="rubel_test_seed_co@gmail.com",
                phone="08580625000",
                department="Engineering",
                designation="Software Engineer",
                role="employee",
                employment_type="FULL_TIME",
                employment_status="PROBATION",
                joining_date=date(2026, 8, 1),
                status="ACTIVE",
                is_active=True,
                is_deleted=False,
            )
            session.add(emp)
            await session.commit()
            print(f"Employee {target_id} seeded successfully.")
        else:
            print(f"Employee {target_id} already exists.")

if __name__ == "__main__":
    asyncio.run(seed())
