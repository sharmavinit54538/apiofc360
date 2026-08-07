"""Test AIService send_message_stream with newly implemented validation and caching."""
import asyncio
import sys
import os

sys.path.insert(0, os.getcwd())

async def run():
    from app.db.database import AsyncSessionLocal
    from app.services.ai_service import AIService
    from app.models.user import User
    from sqlalchemy import select
    
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(User).where(User.email == "sharmavinit7348@gmail.com"))
        user = res.scalar_one_or_none()
        if not user:
            print("User not found!")
            return
            
        service = AIService(session)
        
        # Test schema description cache load
        print("=== Test Schema Description Cache ===")
        schema_desc = await service.schema_cache.get_schema_description(session)
        print(schema_desc)
        
        # Test Greeting Stream
        print("\n=== Test Greeting Stream ===")
        generator = service.send_message_stream(
            user_id=user.id,
            company_id=user.company_id,
            message="hii",
            conversation_id=None
        )
        async for chunk in generator:
            print("YIELD:", chunk)
            
        # Test SQL generation, validation, and repair loop
        print("\n=== Test Database Query Stream ===")
        generator = service.send_message_stream(
            user_id=user.id,
            company_id=user.company_id,
            message="Show all employees",
            conversation_id=None
        )
        async for chunk in generator:
            print("YIELD:", chunk)

asyncio.run(run())
