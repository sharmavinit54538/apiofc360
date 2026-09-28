import asyncio
from app.services.recruitment_ai_service import RecruitmentAIService
from app.services.jd_generator_service import get_jd_generator_service
from app.schemas.recruitment import JobDescriptionStructuredRequest
from app.core.config import settings

async def main():
    print("=== Testing AI Job Description Generation ===")
    print(f"OLLAMA_MODEL: {getattr(settings, 'OLLAMA_MODEL', None)}")
    
    # 1. Test Structured JD Generator
    generator = get_jd_generator_service()
    req = JobDescriptionStructuredRequest(
        job_title="Senior React Developer",
        skills=["ReactJS", "TypeScript", "Node.js", "Tailwind CSS"],
        location="Bangalore",
        experience_min=3,
        experience_max=6,
        employment_type="Full Time",
        department="Engineering",
        work_mode="Hybrid",
        tone="Professional",
        length="Standard",
    )
    structured_jd = await generator.generate_structured_jd(req, {"name": "OFC360 Tech", "industry": "Enterprise Software"})
    
    print("\n--- Structured JD Output ---")
    print(f"Title: {structured_jd.title}")
    print(f"Summary: {structured_jd.summary}")
    print(f"Required Skills: {structured_jd.required_skills}")
    print(f"Preferred Skills: {structured_jd.preferred_skills}")
    print(f"Experience: {structured_jd.experience.text} ({structured_jd.experience.min_years}-{structured_jd.experience.max_years}y)")
    print(f"Responsibilities ({len(structured_jd.responsibilities)} items):")
    for r in structured_jd.responsibilities[:3]:
        print(f"  - {r}")
    print(f"Benefits ({len(structured_jd.benefits)} items):")
    for b in structured_jd.benefits[:2]:
        print(f"  - {b}")
    print(f"ATS Keywords: {structured_jd.ats_keywords}")
    print(f"Metadata: {structured_jd.metadata}")

    assert structured_jd.title == "Senior React Developer"
    assert "React" in structured_jd.required_skills
    assert structured_jd.experience.min_years == 3.0
    assert structured_jd.experience.max_years == 6.0
    assert len(structured_jd.responsibilities) >= 3

    # 2. Test Legacy Service compatibility
    service = RecruitmentAIService.get_instance()
    desc = await service.get_or_generate_description(
        title="Senior Python FastAPI Developer",
        department="Engineering",
        employment_type="Full-time",
        location="Remote",
        skills=["Python", "FastAPI", "Ollama", "PostgreSQL"],
        experience="5+ years"
    )
    assert len(desc) > 50, "Generated description is too short"
    print("\nSUCCESS: All AI Job Description tests passed successfully!")

if __name__ == "__main__":
    asyncio.run(main())

