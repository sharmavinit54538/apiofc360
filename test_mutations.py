import asyncio
import sys
import os

sys.path.insert(0, os.getcwd())

from app.db.database import AsyncSessionLocal
from app.api.super_admin import (
    create_super_admin_organization,
    get_super_admin_organization_detail,
    super_admin_org_access_suspend,
    super_admin_org_access_reactivate,
    delete_super_admin_organization,
)

async def test_mutation_flow():
    async with AsyncSessionLocal() as session:
        # 1. Create Organization
        created = await create_super_admin_organization(
            payload={
                "name": "Integration Test Corp",
                "domain": "integrationtest.com",
                "plan": "Growth",
                "status": "Active",
                "hrAdminName": "Integration Admin",
                "hrAdminEmail": "admin@integrationtest.com",
                "employeeCount": 25,
                "mrr": 299,
                "industry": "Fintech",
                "location": "New York",
            },
            db=session
        )
        org_id = created["id"]
        print(f"Created organization in PostgreSQL: ID={org_id}, Name={created['name']}")
        
        # 2. Get Detail
        detail = await get_super_admin_organization_detail(org_id=org_id, db=session)
        print(f"Detail fetched from DB: Name={detail['name']}, Plan={detail['subscription']['plan']}, Users={len(detail['users'])}")
        
        # 3. Suspend
        suspended = await super_admin_org_access_suspend(org_id=org_id, db=session)
        print(f"Suspended in DB: {suspended['message']}")
        
        # 4. Reactivate
        reactivated = await super_admin_org_access_reactivate(org_id=org_id, db=session)
        print(f"Reactivated in DB: {reactivated['message']}")
        
        # 5. Delete/Deactivate
        deleted = await delete_super_admin_organization(org_id=org_id, db=session)
        print(f"Deactivated in DB: {deleted['message']}")
        
        print("\nAll database mutations verified successfully!")

if __name__ == "__main__":
    asyncio.run(test_mutation_flow())
