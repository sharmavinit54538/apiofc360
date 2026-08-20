import asyncio
import asyncpg

async def check():
    conn = await asyncpg.connect(user='postgres', password='Bindu@134366', host='127.0.0.1', port=5432, database='equnixsphere_prod')
    for tbl in ['companies', 'users', 'employees', 'audit_logs', 'refresh_tokens', 'payroll_runs', 'plans', 'subscriptions']:
        try:
            cnt = await conn.fetchval(f"SELECT COUNT(*) FROM {tbl}")
            print(f"Table {tbl}: {cnt} rows")
        except Exception as e:
            print(f"Table {tbl}: {e}")
            
    # Sample company and user
    companies = await conn.fetch("SELECT id, name, onboarding_completed, company_profile, hr_settings FROM companies LIMIT 5")
    for c in companies:
        print("Company:", c['id'], c['name'], c['onboarding_completed'])
        
    users = await conn.fetch("SELECT id, name, email, role, is_active FROM users LIMIT 5")
    for u in users:
        print("User:", u['id'], u['name'], u['email'], u['role'], u['is_active'])
        
    await conn.close()

if __name__ == '__main__':
    asyncio.run(check())
