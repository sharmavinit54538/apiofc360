import asyncio
import asyncpg

async def check():
    conn = await asyncpg.connect(user='postgres', password='Bindu@134366', host='127.0.0.1', port=5432, database='equnixsphere_prod')
    for tbl in ['companies', 'users', 'employees', 'subscriptions', 'audit_logs', 'refresh_tokens']:
        cols = await conn.fetch(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{tbl}' ORDER BY ordinal_position")
        print(f"\n--- Columns in {tbl} ---")
        for c in cols:
            print(f"  {c['column_name']} ({c['data_type']})")
    
    # Check sample subscription rows if any
    subs = await conn.fetch("SELECT * FROM subscriptions LIMIT 5")
    print(f"\nSample subscriptions ({len(subs)}):", [dict(s) for s in subs])
    await conn.close()

if __name__ == '__main__':
    asyncio.run(check())
