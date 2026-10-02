"""
Orphan and Unassigned Assets Management Script.

By default, runs in DRY-RUN mode.
Lists assets that have no assigned employee (orphans), or whose company_id needs review.

Usage:
    # Dry run (list only)
    python scripts/orphan_assets_report.py

    # Reassign orphan assets to a specific company
    python scripts/orphan_assets_report.py --reassign-company <COMPANY_UUID> --execute

    # Delete orphan assets (ONLY with explicit confirmation)
    python scripts/orphan_assets_report.py --delete-orphans --execute
"""

from __future__ import annotations
import argparse
import asyncio
import sys
import uuid
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, func
from app.db.database import AsyncSessionLocal
from app.models.asset import Asset
from app.models.company import Company
from app.models.employee import Employee


async def main():
    parser = argparse.ArgumentParser(description="Report and manage orphan/unassigned assets.")
    parser.add_argument("--execute", action="store_true", help="Execute changes. Without this flag, script runs in DRY-RUN mode.")
    parser.add_argument("--reassign-company", type=str, default=None, help="Company UUID to reassign unassigned/orphan assets to.")
    parser.add_argument("--delete-orphans", action="store_true", help="Delete unassigned orphan assets (Requires --execute).")

    args = parser.parse_args()
    is_dry_run = not args.execute

    print("=" * 80)
    print(f"ASSET TENANCY & ORPHAN REPORT ({'DRY-RUN MODE' if is_dry_run else 'EXECUTE MODE'})")
    print("=" * 80)

    async with AsyncSessionLocal() as session:
        # 1. Total assets count
        total_assets = (await session.execute(select(func.count(Asset.id)))).scalar_one()
        print(f"Total Assets in Database: {total_assets}")

        # 2. Assets without employee (unassigned / potentially orphan)
        stmt = select(Asset).where(Asset.employee_id.is_(None)).order_by(Asset.created_at.asc())
        res = await session.execute(stmt)
        unassigned_assets = res.scalars().all()
        print(f"Unassigned / Standalone Assets (employee_id is NULL): {len(unassigned_assets)}")

        if unassigned_assets:
            print("\nList of Unassigned Assets:")
            for a in unassigned_assets:
                print(f"  - ID: {a.id} | Tag: {a.tag} | Name: {a.name} | Category: {a.category} | Company ID: {a.company_id} | Status: {a.status}")

        # 3. Check for any tenant mismatch between asset and assigned employee
        stmt_mismatch = (
            select(Asset, Employee)
            .join(Employee, Asset.employee_id == Employee.id)
            .where(Asset.company_id != Employee.company_id)
        )
        mismatched = (await session.execute(stmt_mismatch)).all()
        if mismatched:
            print(f"\nWARNING: Found {len(mismatched)} assets with company_id mismatched from assigned employee:")
            for asset, emp in mismatched:
                print(f"  - Asset {asset.tag} (Company: {asset.company_id}) assigned to Employee {emp.first_name} {emp.last_name} (Company: {emp.company_id})")
        else:
            print("\nAll assigned assets match their assigned employee's company_id.")

        # 4. Action: Reassign
        if args.reassign_company:
            try:
                target_company_id = uuid.UUID(args.reassign_company)
            except ValueError:
                print(f"\nError: Invalid UUID '{args.reassign_company}'.")
                return

            comp = (await session.execute(select(Company).where(Company.id == target_company_id))).scalar_one_or_none()
            if not comp:
                print(f"\nError: Company with ID {target_company_id} not found.")
                return

            print(f"\nTarget Company for Reassignment: {comp.name} ({comp.id})")
            if is_dry_run:
                print(f"[DRY-RUN] Would reassign {len(unassigned_assets)} assets to company '{comp.name}'. No changes made.")
            else:
                for a in unassigned_assets:
                    a.company_id = target_company_id
                await session.commit()
                print(f"[SUCCESS] Reassigned {len(unassigned_assets)} assets to company '{comp.name}'.")

        # 5. Action: Delete Orphans
        elif args.delete_orphans:
            if is_dry_run:
                print(f"\n[DRY-RUN] Would delete {len(unassigned_assets)} orphan assets. No changes made.")
            else:
                for a in unassigned_assets:
                    await session.delete(a)
                await session.commit()
                print(f"\n[SUCCESS] Deleted {len(unassigned_assets)} orphan assets from database.")

    print("\n" + "=" * 80)
    if is_dry_run:
        print("Dry run completed. To apply changes, re-run with --execute and appropriate options.")
    else:
        print("Execution completed.")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
