import asyncio
import os
import sys

sys.path.insert(0, os.getcwd())

from app.db.database import AsyncSessionLocal
from app.repositories.auth_repository import AuthRepository
from app.services.auth_service import AuthService
from app.services.email_service import EmailService
from app.services.token_service import TokenService
from app.schemas.auth import ForgotPasswordRequest

async def test_local_forgot():
    async with AsyncSessionLocal() as session:
        auth_repo = AuthRepository(session)
        email_svc = EmailService()
        token_svc = TokenService(session, auth_repo)
        auth_svc = AuthService(session, auth_repo, email_svc, token_svc)
        
        req = ForgotPasswordRequest(email="sharmavinit7348@gmail.com")
        try:
            print("Checking if user exists...")
            user = await auth_repo.get_user_by_email("sharmavinit7348@gmail.com")
            print(f"User in DB: {user}")
            if user:
                print(f"User details: id={user.id}, role={user.role}, is_deleted={user.is_deleted}")
            
            print("Calling auth_svc.forgot_password...")
            await auth_svc.forgot_password(req)
            print("SUCCESS: forgot_password completed!")
        except Exception as e:
            print(f"FAILED: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_local_forgot())
