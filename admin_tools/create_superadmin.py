import asyncio
import os
import sys

sys.path.insert(0, os.getcwd())
from sqlalchemy import text
from app.db.database import AsyncSessionLocal
from app.core.security import hash_password

async def setup_super_admin():
    email = "superadmin@ofc360.com"
    password = "SuperAdmin@2026"
    pwd_hash = hash_password(password)
    
    async with AsyncSessionLocal() as s:
        # Check if superadmin@ofc360.com exists
        res = await s.execute(text("SELECT id, email, role FROM users WHERE email=:email"), {"email": email})
        user = res.fetchone()
        
        if user:
            await s.execute(
                text("""
                    UPDATE users 
                    SET password_hash=:pwd_hash, 
                        is_active=TRUE, 
                        is_verified=TRUE, 
                        role='super_admin',
                        onboarding_completed=TRUE
                    WHERE email=:email
                """),
                {"email": email, "pwd_hash": pwd_hash}
            )
            print(f"Updated existing user {email}")
        else:
            # Also update sharmavinit7348@gmail.com if present
            await s.execute(
                text("""
                    UPDATE users 
                    SET password_hash=:pwd_hash, 
                        is_active=TRUE, 
                        is_verified=TRUE, 
                        role='super_admin',
                        onboarding_completed=TRUE
                    WHERE email='sharmavinit7348@gmail.com'
                """),
                {"pwd_hash": pwd_hash}
            )
            print("Activated and updated sharmavinit7348@gmail.com with new password")
            
            # Also create superadmin@ofc360.com if not present
            import uuid
            new_id = uuid.uuid4()
            # Fetch any company id
            c_res = await s.execute(text("SELECT id FROM companies LIMIT 1"))
            c_row = c_res.fetchone()
            company_id = c_row[0] if c_row else None
            
            await s.execute(
                text("""
                    INSERT INTO users (
                        id, name, email, phone, password_hash, role, 
                        is_active, is_verified, onboarding_completed, company_id
                    ) VALUES (
                        :id, :name, :email, :phone, :password_hash, :role, 
                        TRUE, TRUE, TRUE, :company_id
                    )
                """),
                {
                    "id": new_id,
                    "name": "Super Admin",
                    "email": email,
                    "phone": "9999900000",
                    "password_hash": pwd_hash,
                    "role": "super_admin",
                    "company_id": company_id
                }
            )
            print(f"Created new super admin user: {email}")

        await s.commit()
        print("Database updated successfully!")

if __name__ == "__main__":
    asyncio.run(setup_super_admin())
