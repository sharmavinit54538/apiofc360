"""End-to-end database lifecycle test for Super Admin Company Headcount.

Validates the full PostgreSQL -> FastAPI -> API Response pipeline:
1. Provisions a test organization with 0 employees.
2. Verifies GET /api/v1/super-admin/organizations returns employee_count = 0.
3. Creates new active employees associated with company_id.
4. Verifies headcount increases dynamically with each added employee.
5. Soft-deletes / terminates employees and verifies headcount decreases accordingly.
6. Cleans up test fixtures in PostgreSQL.
"""

import sys
import os
sys.path.insert(0, os.getcwd())

import uuid
from datetime import date, datetime, timezone
import pytest
from sqlalchemy import select, delete

from app.db.database import AsyncSessionLocal
from app.models.company import Company
from app.models.employee import Employee
from app.models.user import User, UserRole
from app.models.subscription import Subscription
from app.api.super_admin import get_super_admin_organizations, get_super_admin_organization_detail


@pytest.mark.asyncio
async def test_live_company_headcount_add_and_terminate_lifecycle():
    async with AsyncSessionLocal() as session:
        test_company_id = uuid.uuid4()
        test_company_name = f"Headcount Test Corp {uuid.uuid4().hex[:6]}"

        # 1. Create test company
        test_company = Company(
            id=test_company_id,
            name=test_company_name,
            onboarding_completed=True,
            company_profile={"domain": "headcount-test.com", "plan": "Enterprise", "mrr": 500.0},
            created_at=datetime.now(timezone.utc),
        )
        test_sub = Subscription(
            id=uuid.uuid4(),
            company_id=test_company_id,
            plan="Enterprise",
            access_status="ACTIVE",
            payment_status="PAID",
            mrr=500.0,
            created_at=datetime.now(timezone.utc),
        )
        session.add(test_company)
        session.add(test_sub)
        await session.commit()

        try:
            # 2. Verify initial headcount is 0
            res = await get_super_admin_organizations(search=test_company_name, db=session)
            matching = [o for o in res if o["id"] == str(test_company_id)]
            assert len(matching) == 1, "Expected test organization in API response"
            assert matching[0]["employee_count"] == 0
            assert matching[0]["employeeCount"] == 0

            # Check detail endpoint as well
            detail = await get_super_admin_organization_detail(org_id=str(test_company_id), db=session)
            assert detail["stats"]["employee_count"] == 0
            assert detail["stats"]["employeeCount"] == 0

            # 3. Add Employee 1 (INVITED status, active=True, is_deleted=False)
            emp_1_id = uuid.uuid4()
            emp_1 = Employee(
                id=emp_1_id,
                company_id=test_company_id,
                employee_id=f"EMP-{uuid.uuid4().hex[:6].upper()}",
                first_name="Alice",
                last_name="Tester",
                personal_email=f"alice_{uuid.uuid4().hex[:6]}@example.com",
                company_email=f"alice_{uuid.uuid4().hex[:6]}@headcount-test.com",
                phone="9876540001",
                department="Engineering",
                designation="Software Engineer",
                joining_date=date.today(),
                employment_type="FULL_TIME",
                employment_status="PROBATION",
                role="employee",
                status="INVITED",
                is_active=True,
                is_deleted=False,
            )
            session.add(emp_1)
            await session.commit()

            # Verify headcount increased to 1
            res_after_1 = await get_super_admin_organizations(search=test_company_name, db=session)
            matching_1 = [o for o in res_after_1 if o["id"] == str(test_company_id)][0]
            assert matching_1["employee_count"] == 1
            assert matching_1["employeeCount"] == 1

            detail_1 = await get_super_admin_organization_detail(org_id=str(test_company_id), db=session)
            assert detail_1["stats"]["employee_count"] == 1
            assert detail_1["stats"]["employeeCount"] == 1

            # 4. Add Employee 2 (ACTIVE status)
            emp_2_id = uuid.uuid4()
            emp_2 = Employee(
                id=emp_2_id,
                company_id=test_company_id,
                employee_id=f"EMP-{uuid.uuid4().hex[:6].upper()}",
                first_name="Bob",
                last_name="Builder",
                personal_email=f"bob_{uuid.uuid4().hex[:6]}@example.com",
                company_email=f"bob_{uuid.uuid4().hex[:6]}@headcount-test.com",
                phone="9876540002",
                department="Design",
                designation="Product Designer",
                joining_date=date.today(),
                employment_type="FULL_TIME",
                employment_status="CONFIRMED",
                role="employee",
                status="ACTIVE",
                is_active=True,
                is_deleted=False,
            )
            session.add(emp_2)
            await session.commit()

            # Verify headcount increased to 2
            res_after_2 = await get_super_admin_organizations(search=test_company_name, db=session)
            matching_2 = [o for o in res_after_2 if o["id"] == str(test_company_id)][0]
            assert matching_2["employee_count"] == 2
            assert matching_2["employeeCount"] == 2

            detail_2 = await get_super_admin_organization_detail(org_id=str(test_company_id), db=session)
            assert detail_2["stats"]["employee_count"] == 2
            assert detail_2["stats"]["employeeCount"] == 2

            # 5. Terminate Employee 1 (status = "TERMINATED", is_active = False)
            emp_1.status = "TERMINATED"
            emp_1.is_active = False
            emp_1.employment_status = "TERMINATED"
            session.add(emp_1)
            await session.commit()

            # Verify headcount decreased to 1
            res_after_term = await get_super_admin_organizations(search=test_company_name, db=session)
            matching_term = [o for o in res_after_term if o["id"] == str(test_company_id)][0]
            assert matching_term["employee_count"] == 1
            assert matching_term["employeeCount"] == 1

            detail_term = await get_super_admin_organization_detail(org_id=str(test_company_id), db=session)
            assert detail_term["stats"]["employee_count"] == 1
            assert detail_term["stats"]["employeeCount"] == 1

            # 6. Soft-delete Employee 2 (is_deleted = True, status = "DELETED")
            emp_2.is_deleted = True
            emp_2.status = "DELETED"
            session.add(emp_2)
            await session.commit()

            # Verify headcount decreased to 0
            res_after_del = await get_super_admin_organizations(search=test_company_name, db=session)
            matching_del = [o for o in res_after_del if o["id"] == str(test_company_id)][0]
            assert matching_del["employee_count"] == 0
            assert matching_del["employeeCount"] == 0

            detail_del = await get_super_admin_organization_detail(org_id=str(test_company_id), db=session)
            assert detail_del["stats"]["employee_count"] == 0
            assert detail_del["stats"]["employeeCount"] == 0

        finally:
            # Cleanup test fixtures
            await session.execute(delete(Employee).where(Employee.company_id == test_company_id))
            await session.execute(delete(Subscription).where(Subscription.company_id == test_company_id))
            await session.execute(delete(Company).where(Company.id == test_company_id))
            await session.commit()
