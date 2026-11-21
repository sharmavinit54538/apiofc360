"""Company-bound, serialized screening using persisted candidate facts."""
import json
import uuid
from pathlib import Path
from sqlalchemy import select, func, text
from sqlalchemy.dialects.postgresql import insert
from app.db.database import AsyncSessionLocal
from app.db.base import tenant_id_ctx
from app.models.recruitment import Application, Candidate, Job
from app.models.ai_recruitment import AIResumeDocument, CandidateMatchScore


async def associate_candidate(session, application, company_id):
    if application.company_id != company_id:
        raise PermissionError("Application tenant mismatch")
    job = await session.scalar(select(Job).where(Job.id == application.job_id, Job.company_id == company_id))
    if not job:
        raise PermissionError("Job ownership could not be verified")
    if application.candidate_id:
        candidate = await session.scalar(select(Candidate).where(
            Candidate.id == application.candidate_id, Candidate.company_id == company_id))
        if not candidate:
            raise PermissionError("Candidate ownership could not be verified")
        return candidate
    if not application.phone or not application.email:
        raise ValueError("Candidate contact details are incomplete")
    email = application.email.strip().lower()
    # Lock the normalized company/email pair across concurrent applications.
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))").execution_options(tenant_safe=True),
                          {"key": f"candidate:{company_id}:{email}"})
    candidate = await session.scalar(select(Candidate).where(
        Candidate.company_id == company_id, func.lower(Candidate.email) == email))
    if candidate is None:
        candidate = Candidate(company_id=company_id, email=email, phone=application.phone,
            first_name=application.first_name, last_name=application.last_name,
            location=", ".join(filter(None, [application.city, application.state, application.country]))[:100],
            years_experience=application.experience_years, current_company=application.current_company,
            current_role=application.current_designation, expected_salary=application.expected_ctc,
            source="Application", is_talent_pool=False)
        session.add(candidate)
        await session.flush()
    application.candidate_id = candidate.id
    return candidate


async def screen_application(application_id, company_id, candidate_id=None, job_id=None):
    from app.agents.resume_parser import ResumeParserAgent
    from app.agents.candidate_matcher import CandidateMatcherAgent
    from app.llm.client import get_llm_client
    from app.ocr.engine_selector import get_ocr_selector
    from app.core.config import settings
    context = tenant_id_ctx.set(company_id)
    try:
        async with AsyncSessionLocal() as session, session.begin():
            application = await session.scalar(select(Application).where(
                Application.id == application_id, Application.company_id == company_id).with_for_update())
            if not application:
                raise LookupError("Application not found in company")
            candidate = await associate_candidate(session, application, company_id)
            if candidate_id and candidate.id != candidate_id or job_id and application.job_id != job_id:
                raise PermissionError("Screening identity mismatch")
            await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))").execution_options(tenant_safe=True),
                                  {"key": f"screen:{company_id}:{candidate.id}:{application.job_id}"})
            existing = await session.scalar(select(CandidateMatchScore.id).where(
                CandidateMatchScore.candidate_id == candidate.id, CandidateMatchScore.job_id == application.job_id).limit(1))
            if existing:
                return {"status": "completed", "score_id": str(existing)}
            job = await session.scalar(select(Job).where(Job.id == application.job_id, Job.company_id == company_id))
            llm = get_llm_client()
            path = Path(candidate.resume_path).resolve() if candidate.resume_path else None
            if path:
                if not path.is_relative_to(Path(settings.UPLOAD_DIR).resolve()) or not path.is_file():
                    raise ValueError("Resume storage path is unavailable")
                parsed = await ResumeParserAgent(llm_client=llm, ocr_selector=get_ocr_selector()).parse_file(str(path))
                facts, raw_text = parsed.to_dict(), parsed.raw_text
            else:
                facts = {"name": f"{candidate.first_name} {candidate.last_name}", "skills": candidate.skills or [],
                         "experience_years": str(candidate.years_experience), "summary": candidate.summary,
                         "current_role": candidate.current_role}
                raw_text = json.dumps(facts)
            result = await CandidateMatcherAgent(llm_client=llm).match(
                resume_text=raw_text, jd_text=job.job_description or "", candidate_metadata=facts)
            doc = AIResumeDocument(application_id=application.id, candidate_id=candidate.id,
                file_path=str(path) if path else "", file_name=candidate.resume_name or "",
                file_size=path.stat().st_size if path else 0, file_type=path.suffix.lstrip('.') if path else "profile",
                parse_status="COMPLETED", raw_text=raw_text, parsed_data=facts)
            session.add(doc)
            await session.flush()
            fields = ("overall_match_score", "skill_match_score", "experience_match_score", "education_match_score",
                      "domain_match_score", "industry_match_score", "location_match_score", "salary_match_score",
                      "availability_score", "ai_confidence_score", "matching_skills", "missing_skills", "extra_skills")
            score = CandidateMatchScore(resume_document_id=doc.id, job_id=job.id, candidate_id=candidate.id,
                recommendation="REVIEW", **{name: getattr(result, name) for name in fields})
            session.add(score)
            await session.flush()
            return {"status": "completed", "score_id": str(score.id)}
    finally:
        tenant_id_ctx.reset(context)
