import asyncio
import os
import sys

sys.path.insert(0, os.getcwd())
from app.db.database import AsyncSessionLocal
from app.services.auth_service import AuthService
from app.repositories.auth_repository import AuthRepository
from app.services.email_service import EmailService
from app.services.token_service import TokenService
from app.schemas.auth import LoginRequest

async def test_auth():
    async with AsyncSessionLocal() as s:
        auth_repo = AuthRepository(s)
        email_service = EmailService()
        token_service = TokenService(session=s, auth_repository=auth_repo)
        service = AuthService(
            session=s,
            auth_repository=auth_repo,
            email_service=email_service,
            token_service=token_service,
        )
        
        req1 = LoginRequest(identifier="sharmavinit7348@gmail.com", password="SuperAdmin@2026")
        user1, access1, refresh1, exp1 = await service.login(req1)
        print("LOGIN 1 SUCCESS:", user1.email, "ROLE:", user1.role, "ACTIVE:", user1.is_active)
        
        req2 = LoginRequest(identifier="superadmin@ofc360.com", password="SuperAdmin@2026")
        user2, access2, refresh2, exp2 = await service.login(req2)
        print("LOGIN 2 SUCCESS:", user2.email, "ROLE:", user2.role, "ACTIVE:", user2.is_active)

if __name__ == "__main__":
    asyncio.run(test_auth())
