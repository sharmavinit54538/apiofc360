import asyncio
import sys
import os

sys.path.insert(0, os.getcwd())

from app.db.database import AsyncSessionLocal
from app.api.super_admin import (
    get_super_admin_statistics,
    get_super_admin_organizations,
    get_super_admin_users,
    get_super_admin_subscriptions,
    get_super_admin_system_health,
    get_super_admin_security,
)

async def test():
    async with AsyncSessionLocal() as session:
        stats = await get_super_admin_statistics(db=session)
        print("Dashboard stats successfully computed from DB:")
        print("  Total Orgs:", stats["kpis"]["total_organizations"])
        print("  Active Orgs:", stats["kpis"]["active_organizations"])
        print("  Total Users:", stats["kpis"]["total_users"])
        print("  Workforce:", stats["kpis"]["total_workforce_managed"])
        print("  MRR:", stats["financials"]["mrr"])
        print("  ARR:", stats["financials"]["arr"])
        print("  Total Revenue:", stats["financials"]["total_revenue"])
        
        orgs = await get_super_admin_organizations(page=1, page_size=5, db=session)
        print(f"\nFetched {len(orgs)} organizations from DB. First org sample:")
        if orgs:
            print("  Org Name:", orgs[0]["name"], "| Plan:", orgs[0]["plan"], "| Users:", orgs[0]["user_count"])
            
        users = await get_super_admin_users(page=1, page_size=5, db=session)
        print(f"\nFetched {len(users)} users from DB. First user sample:")
        if users:
            print("  User Name:", users[0]["name"], "| Email:", users[0]["email"], "| Role:", users[0]["role"])
            
        subs = await get_super_admin_subscriptions(db=session)
        print(f"\nFetched {len(subs)} subscriptions from DB.")
        
        health = await get_super_admin_system_health(db=session)
        print("\nSystem health status:", health["status"])
        for s in health["services"]:
            print(f"  Service: {s['name']} -> {s['status']} ({s['response_time']})")
            
        sec = await get_super_admin_security(db=session)
        print("\nSecurity Score:", sec["security_score"], "| Active sessions:", sec["active_sessions_count"])

if __name__ == "__main__":
    asyncio.run(test())
