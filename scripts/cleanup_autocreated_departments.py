"""Cleanup script for auto-created departments in incomplete onboarding companies.

Usage:
    Dry-run mode (default, safe, lists matching records):
        python scripts/cleanup_autocreated_departments.py

    Execution mode (deletes only when explicitly confirmed):
        python scripts/cleanup_autocreated_departments.py --execute
"""

import argparse
import asyncio
import os
import sys

# Ensure app is in python path
sys.path.insert(0, os.path.abspath("."))

from sqlalchemy import func, select, delete
from app.db.database import AsyncSessionLocal
from app.models.company import Company
from app.models.department import Department
from app.models.employee import Employee


async def cleanup(execute: bool = False):
    print("=" * 80)
    print("CLEANUP AUTO-CREATED DEPARTMENTS SCRIPT")
    print(f"Mode: {'EXECUTE (DELETION)' if execute else 'DRY-RUN (LIST ONLY - SAFE)'}")
    print("=" * 80)

    async with AsyncSessionLocal() as session:
        # Find auto-created departments (MGMT, ENG, HR) in companies with onboarding_completed=False
        # where NO employees are assigned (count(Employee.id) == 0)
        query = (
            select(Department, Company)
            .join(Company, Company.id == Department.company_id)
            .outerjoin(Employee, (Employee.department_id == Department.id) & (Employee.is_deleted.is_(False)))
            .where(
                Company.onboarding_completed.is_(False),
                Department.department_code.in_(["MGMT", "ENG", "HR"]),
                Department.department_name.in_(["Management", "Engineering", "Human Resources"]),
            )
            .group_by(Department.id, Company.id)
            .having(func.count(Employee.id) == 0)
            .order_by(Company.name, Department.department_name)
        )

        res = await session.execute(query)
        matching_rows = res.all()

        print(f"\nFound {len(matching_rows)} unassigned auto-created department(s) across incomplete companies:\n")

        dept_ids_to_delete = []
        for dept, comp in matching_rows:
            dept_ids_to_delete.append(dept.id)
            print(f" - Company: {comp.name:<30} (ID: {comp.id})")
            print(f"   Dept: [{dept.department_code}] {dept.department_name:<20} (ID: {dept.id})")

        if not matching_rows:
            print("No auto-created unassigned departments found matching criteria.")
            return

        if execute:
            print("\nExecuting deletion of identified departments...")
            delete_stmt = delete(Department).where(Department.id.in_(dept_ids_to_delete))
            result = await session.execute(delete_stmt)
            await session.commit()
            print(f"Successfully deleted {result.rowcount} departments.")
        else:
            print("\n[DRY RUN COMPLETE] No records were modified or deleted.")
            print("To delete these departments, run the script with: python scripts/cleanup_autocreated_departments.py --execute")


def main():
    parser = argparse.ArgumentParser(description="Cleanup auto-created departments for incomplete companies.")
    parser.add_argument("--execute", action="store_true", help="Execute deletion (default is dry-run list only).")
    args = parser.parse_args()
    asyncio.run(cleanup(execute=args.execute))


if __name__ == "__main__":
    main()
