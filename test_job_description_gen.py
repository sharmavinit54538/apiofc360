import asyncio
from app.services.recruitment_ai_service import RecruitmentAIService
from app.core.config import settings

async def main():
    print("=== Testing RecruitmentAIService with llama3:latest ===")
    print(f"OLLAMA_MODEL: {getattr(settings, 'OLLAMA_MODEL', None)}")
    
    service = RecruitmentAIService.get_instance()
    desc = await service.get_or_generate_description(
        title="Senior Python FastAPI Developer",
        department="Engineering",
        employment_type="Full-time",
        location="Remote",
        skills=["Python", "FastAPI", "Ollama", "PostgreSQL"],
        experience="5+ years"
    )
    
    print("\nGenerated Job Description Output:")
    print(desc[:500])
    print("...")
    assert len(desc) > 100, "Generated description is too short"
    print("\nSUCCESS: Job Description generated using Ollama!")

if __name__ == "__main__":
    asyncio.run(main())
