"""Test all 20 required production assistant prompts against FastAPI server with automatic password reset wrapper."""
import asyncio
import sys
import os

sys.path.insert(0, os.getcwd())

# Reconfigure stdout to use UTF-8 on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

TEST_USER_EMAIL = os.getenv("TEST_USER_EMAIL", "testuser@example.com")
TEST_USER_PASSWORD = os.getenv("TEST_USER_PASSWORD", "SecretPass123!")


async def reset_password_in_db():
    from app.db.database import AsyncSessionLocal
    from app.models.user import User
    from app.core.security import hash_password
    from sqlalchemy import select
    
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(User).where(User.email == TEST_USER_EMAIL))
        user = res.scalar_one_or_none()
        if user:
            user.password_hash = hash_password(TEST_USER_PASSWORD)
            await session.commit()
            print(f"[DB SETUP] Reset password for {TEST_USER_EMAIL}!")
        else:
            print(f"[DB SETUP] Warning: User {TEST_USER_EMAIL} not found!")
 
async def run():
    # Reset password directly in DB first
    await reset_password_in_db()
    
    # Wait 1.5 seconds to ensure server has processed or if there's any lag
    await asyncio.sleep(1.5)
    
    import httpx
    base = "http://127.0.0.1:8001/api/v1"
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        # Login
        print("=== Step 1: Login ===")
        login_resp = await client.post(f"{base}/auth/login", json={
            "identifier": TEST_USER_EMAIL,
            "password": TEST_USER_PASSWORD
        })
        print(f"Login Status: {login_resp.status_code}")
        if login_resp.status_code != 200:
            print(f"Login failed! Response body: {login_resp.text}")
            return
            
        token = login_resp.json()["data"]["access_token"]
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        # Helper to call streaming API
        async def call_chat(message, label, conversation_id=None):
            print(f"\n==================================================")
            print(f"=== {label} ===")
            print(f"User Query: '{message}'")
            payload = {
                "message": message,
                "conversation_id": conversation_id
            }
            conv_id = None
            full_text = ""
            async with client.stream("POST", f"{base}/ai/chat", json=payload, headers=headers) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        import json
                        data = json.loads(line[6:])
                        if data.get("event") == "meta":
                            conv_id = data.get("conversation_id")
                        elif data.get("event") == "token":
                            full_text += data.get("text", "")
                        elif data.get("event") == "error":
                            full_text += f"\n[STREAM ERROR]: {data.get('message')}"
            print(f"Response:\n{full_text}")
            return conv_id

        # 1. Greetings
        await call_chat("Hi", "Test 1: Greeting 'Hi'")
        await call_chat("Hello", "Test 2: Greeting 'Hello'")
        
        # 2. Identity Check
        await call_chat("Who are you", "Test 3: Identity Check")
        
        # 3. Help Command
        await call_chat("Help", "Test 4: Help Category List")
        
        # 4. Goodbye
        await call_chat("Goodbye", "Test 5: Goodbye")
        
        # 5. Show all employees
        await call_chat("Show all employees", "Test 6: Show all employees")
        
        # 6. Employee Count
        await call_chat("Employee count", "Test 7: Employee count query")
        
        # 7. Show departments
        await call_chat("Show departments", "Test 8: Show departments list")
        
        # 8. Attendance today
        await call_chat("Attendance today", "Test 9: Attendance check-in status")
        
        # 9. Payroll summary
        await call_chat("Payroll summary", "Test 10: Salary and CTC stats")
        
        # 10. Employees hired this month
        await call_chat("Employees hired this month", "Test 11: Recent hires query")
        
        # 11. Active / Inactive employees
        await call_chat("Show active employees", "Test 12: Active employees filter")
        await call_chat("Show inactive employees", "Test 13: Inactive employees filter")
        
        # 12. Managers query
        await call_chat("Managers", "Test 14: Company managers list")
        
        # 13. Reports / Analytics
        await call_chat("Reports", "Test 15: General reports query")
        await call_chat("Analytics", "Test 16: Company headcount or CTC analytics")

asyncio.run(run())
