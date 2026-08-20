import asyncio
import asyncpg

async def check():
    conn = await asyncpg.connect(user='postgres', password='Bindu@134366', host='127.0.0.1', port=5432, database='equnixsphere_prod')
    enum_vals = await conn.fetch("SELECT enumlabel FROM pg_enum JOIN pg_type ON pg_enum.enumtypid = pg_type.oid WHERE pg_type.typname = 'user_role'")
    print("user_role enum values:", [e['enumlabel'] for e in enum_vals])
    
    # Also check existing distinct roles in users table
    distinct_roles = await conn.fetch("SELECT DISTINCT role FROM users")
    print("distinct user roles in users table:", [r['role'] for r in distinct_roles])
    await conn.close()

if __name__ == '__main__':
    asyncio.run(check())
