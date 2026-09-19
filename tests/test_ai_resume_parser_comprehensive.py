"""Comprehensive Production Test Suite for OFC360 AI Resume Parser."""

from __future__ import annotations

import io
import uuid
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.exceptions import AppException
from app.models.recruitment import Candidate, Job, Application
from app.models.ai_recruitment import AIResumeDocument, CandidateMatchScore
from app.services.storage_service import StorageService
from app.services.resume_ocr_service import ResumeOCRService
from app.services.pdf_docx_parser import extract_text_from_pdf, extract_text_from_docx, extract_text_from_txt
from app.services.resume_cleaner_service import ResumeCleanerService
from app.services.resume_parser_service import ResumeParserService
from app.services.duplicate_detector_service import DuplicateDetectorService
from app.services.ats_scoring_service import ATSScoringService
from app.services.candidate_ranking_service import CandidateRankingService
from app.services.ai_screening_pipeline_service import AIScreeningPipelineService


# ==============================================================================
# 1. FILE VALIDATION & STORAGE TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_storage_validation_allowed_extensions():
    """Verify supported resume file extensions (.pdf, .docx, .doc, .txt)."""
    service = StorageService()

    # Valid PDF
    mock_pdf = MagicMock()
    mock_pdf.filename = "resume.pdf"
    mock_pdf.content_type = "application/pdf"
    mock_pdf.read = AsyncMock(return_value=b"%PDF-1.4 test pdf content stream")
    res_pdf = await service.save_file(mock_pdf)
    assert res_pdf["original_filename"] == "resume.pdf"

    # Valid DOCX
    mock_docx = MagicMock()
    mock_docx.filename = "resume.docx"
    mock_docx.content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    mock_docx.read = AsyncMock(return_value=b"PK\x03\x04test docx zip stream")
    res_docx = await service.save_file(mock_docx)
    assert res_docx["original_filename"] == "resume.docx"

    # Valid TXT
    mock_txt = MagicMock()
    mock_txt.filename = "resume.txt"
    mock_txt.content_type = "text/plain"
    mock_txt.read = AsyncMock(return_value="Candidate Experience: 5 years in Python".encode("utf-8"))
    res_txt = await service.save_file(mock_txt)
    assert res_txt["original_filename"] == "resume.txt"


@pytest.mark.asyncio
async def test_storage_validation_rejections():
    """Verify rejection of invalid extensions, empty files, oversized files, and disguised binaries."""
    service = StorageService()

    # Unsupported extension
    mock_exe = MagicMock()
    mock_exe.filename = "malware.exe"
    mock_exe.content_type = "application/x-msdownload"
    mock_exe.read = AsyncMock(return_value=b"MZ\x90\x00\x03\x00\x00\x00")
    with pytest.raises(AppException) as exc_info:
        await service.save_file(mock_exe)
    assert exc_info.value.status_code == 400

    # Empty file (0 bytes)
    mock_empty = MagicMock()
    mock_empty.filename = "empty.pdf"
    mock_empty.content_type = "application/pdf"
    mock_empty.read = AsyncMock(return_value=b"")
    with pytest.raises(AppException) as exc_info:
        await service.save_file(mock_empty)
    assert "empty" in exc_info.value.message.lower()

    # Oversized file (> 20MB limit)
    mock_oversized = MagicMock()
    mock_oversized.filename = "huge.pdf"
    mock_oversized.content_type = "application/pdf"
    mock_oversized.read = AsyncMock(return_value=b"%PDF-1.4" + b"0" * (25 * 1024 * 1024))
    with pytest.raises(AppException) as exc_info:
        await service.save_file(mock_oversized)
    assert "exceeds" in exc_info.value.message.lower()

    # Corrupted / Disguised TXT with non-text binary
    mock_fake_txt = MagicMock()
    mock_fake_txt.filename = "disguised.txt"
    mock_fake_txt.content_type = "text/plain"
    mock_fake_txt.read = AsyncMock(return_value=b"\x00\x01\x02\xff\xfe\x00\x05")
    with pytest.raises(AppException):
        await service.save_file(mock_fake_txt)


# ==============================================================================
# 2. TEXT EXTRACTION & OCR FALLBACK TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_ocr_service_plain_text_decoding():
    """Verify plain text decoding with various encodings."""
    ocr = ResumeOCRService()
    txt_content = "John Doe\nSoftware Engineer\nSkills: Python, FastAPI, Docker"
    
    # UTF-8
    res = await ocr.extract_text(txt_content.encode("utf-8"), "resume.txt", "text/plain")
    assert "John Doe" in res["raw_text"]
    assert "FastAPI" in res["raw_text"]

    # Latin-1
    res_lat = await ocr.extract_text(txt_content.encode("latin-1"), "resume.txt", "text/plain")
    assert "Software Engineer" in res_lat["raw_text"]


@pytest.mark.asyncio
async def test_ocr_service_pdf_and_docx_fallbacks():
    """Verify fallback mechanisms for PDF and DOCX documents."""
    ocr = ResumeOCRService()

    # PDF simulation
    with patch("pypdf.PdfReader") as mock_pdf_reader:
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Jane Smith\nSenior Full Stack Developer\nReact, Node.js, PostgreSQL"
        mock_pdf_reader.return_value.pages = [mock_page]

        res = await ocr.extract_text(b"%PDF-1.4 mock stream", "resume.pdf", "application/pdf")
        assert "Jane Smith" in res["raw_text"]
        assert "React" in res["raw_text"]

    # DOCX simulation with tables & paragraphs
    with patch("docx.Document") as mock_docx_doc:
        mock_p1 = MagicMock()
        mock_p1.text = "Alex Johnson"
        mock_p1.style.name = "Heading 1"
        mock_p2 = MagicMock()
        mock_p2.text = "Backend Developer with 6 years experience."
        mock_p2.style.name = "Normal"

        mock_cell1 = MagicMock()
        mock_cell1.text = "Python"
        mock_cell2 = MagicMock()
        mock_cell2.text = "Kubernetes"
        mock_row = MagicMock()
        mock_row.cells = [mock_cell1, mock_cell2]
        mock_table = MagicMock()
        mock_table.rows = [mock_row]

        mock_docx_doc.return_value.paragraphs = [mock_p1, mock_p2]
        mock_docx_doc.return_value.tables = [mock_table]

        res_docx = await ocr.extract_text(b"PK\x03\x04 mock docx", "resume.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        assert "Alex Johnson" in res_docx["raw_text"]
        assert "Python | Kubernetes" in res_docx["raw_text"]


# ==============================================================================
# 3. SKILLS NORMALIZATION & EXPERIENCE DATE CALCULATION
# ==============================================================================

def test_skills_canonical_normalization():
    """Verify comprehensive normalization of tech synonyms to canonical forms."""
    cleaner = ResumeCleanerService()
    raw_skills = [
        "ReactJS", "react.js", "React JS",
        "NodeJS", "node.js", "node js",
        "Postgres", "postgresql", "psql",
        "Mongo DB", "mongodb",
        "Java Script", "js", "JavaScript",
        "TypeScript", "ts",
        "Python3", "py",
        "k8s", "kubernetes",
        "amazon web services", "AWS",
        "Communication", "Leadership", "Teamwork"
    ]

    all_skills, tech_skills, soft_skills = cleaner.clean_skills(raw_skills)

    # Check canonical forms
    assert "React" in all_skills
    assert "Node.js" in all_skills
    assert "PostgreSQL" in all_skills
    assert "MongoDB" in all_skills
    assert "JavaScript" in all_skills
    assert "TypeScript" in all_skills
    assert "Python" in all_skills
    assert "Kubernetes" in all_skills
    assert "AWS" in all_skills

    # Deduplication check
    assert all_skills.count("React") == 1
    assert all_skills.count("Node.js") == 1
    assert all_skills.count("PostgreSQL") == 1

    # Soft skills categorization
    assert "Communication" in soft_skills
    assert "Leadership" in soft_skills
    assert "React" in tech_skills


def test_experience_calculation_from_dates():
    """Verify date-based total experience computation from employment history."""
    cleaner = ResumeCleanerService()
    work_history = [
        {
            "company": "Tech Corp",
            "designation": "Software Engineer",
            "start_date": "Jan 2020",
            "end_date": "Dec 2021",
        },
        {
            "company": "NextGen AI",
            "designation": "Senior Developer",
            "start_date": "Jan 2022",
            "end_date": "Dec 2023",
        },
    ]

    # 2 years + 2 years = ~4.0 years
    total_years = cleaner.calculate_experience_from_dates(work_history)
    assert total_years is not None
    assert 3.8 <= total_years <= 4.2

    # Clean parsed data with work history prioritization
    parsed_input = {
        "candidate_name": "Dev User",
        "total_experience_years": 10.0,  # AI hallucinated 10 years, but dates prove ~4
        "work_history": work_history,
        "skills": ["ReactJS", "NodeJS"],
    }
    cleaned = cleaner.clean_parsed_data(parsed_input)
    assert cleaned["total_experience_years"] == total_years
    assert cleaned["skills"] == ["React", "Node.js"]
    assert "ReactJS" in cleaned["raw_skills"]


# ==============================================================================
# 4. PARSER SERVICE & ANTI-HALLUCINATION PROTECTION
# ==============================================================================

@pytest.mark.asyncio
async def test_anti_hallucination_contact_verification():
    """Verify parser rejects hallucinated email/phone that is not in raw resume text."""
    parser = ResumeParserService()
    raw_text = """
    Johnathan Smith
    Email: real.john@example.com
    Phone: +1 555-0199
    Software Engineer with 4 years experience.
    Skills: Python, FastAPI, Docker, Kubernetes.
    """

    # Mock LLM returning a hallucinated email & phone
    mock_llm_data = {
        "candidate_name": "Johnathan Smith",
        "email": "hallucinated.fake@example.com",
        "phone": "+1 999-999-9999",
        "skills": ["Python", "FastAPI"],
    }

    with patch.object(parser, "_extract_with_llm", AsyncMock(return_value=mock_llm_data)):
        result = await parser.parse_resume(raw_text)

        # Anti-hallucination should have discarded the fake email & verified against raw text regex
        assert result["email"] == "real.john@example.com"
        assert result["candidate_name"] == "Johnathan Smith"
        assert result["parsing_confidence"] >= 0.70


# ==============================================================================
# 5. DUPLICATE CANDIDATE DETECTION
# ==============================================================================

@pytest.mark.asyncio
async def test_duplicate_candidate_detection_priority():
    """Verify duplicate detection priority: Email -> Phone -> LinkedIn -> Name+Company."""
    mock_session = AsyncMock()
    detector = DuplicateDetectorService(mock_session)

    existing_cand = Candidate(
        id=uuid.uuid4(),
        first_name="Jane",
        last_name="Doe",
        email="jane.doe@example.com",
        phone="+1 555-123-4567",
        current_company="Acme Corp",
    )

    # 1. Match by Email
    mock_exec_res = MagicMock()
    mock_exec_res.scalar_one_or_none.return_value = existing_cand
    mock_session.execute.return_value = mock_exec_res

    dup_email = await detector.check_duplicate(email="jane.doe@example.com", phone="000")
    assert dup_email["is_duplicate"] is True
    assert "email" in dup_email["matched_by"]
    assert dup_email["duplicate_candidate_id"] == str(existing_cand.id)

    # 2. Match by Phone (normalized digits)
    mock_exec_res.scalar_one_or_none.return_value = None
    mock_exec_res.scalars.return_value.all.return_value = [existing_cand]
    mock_session.execute.return_value = mock_exec_res

    dup_phone = await detector.check_duplicate(email=None, phone="555-123-4567")
    assert dup_phone["is_duplicate"] is True
    assert "phone" in dup_phone["matched_by"]


# ==============================================================================
# 6. ATS SCORING & CANDIDATE MATCHING
# ==============================================================================

def test_ats_scoring_and_insights():
    """Verify ATS scoring calculates dimensional breakdown and ranking insights."""
    ats_service = ATSScoringService()
    ranking_service = CandidateRankingService()

    candidate_data = {
        "candidate_name": "Sarah Connor",
        "skills": ["Python", "FastAPI", "PostgreSQL", "Docker", "AWS"],
        "total_experience_years": 5.0,
        "education": [{"degree": "Bachelor of Computer Science"}],
        "projects": [{"title": "Cloud Migration", "technologies": ["AWS", "Docker"]}],
        "certifications": ["AWS Solutions Architect"],
    }

    job_data = {
        "title": "Senior Python Backend Engineer",
        "job_description": "Looking for experienced Python developer with FastAPI and AWS.",
        "min_experience": 4.0,
        "skills": ["Python", "FastAPI", "PostgreSQL", "AWS", "Kubernetes"],
    }

    score_result = ats_service.calculate_ats_score(candidate_data, job_data)
    assert score_result["overall_ats_score"] >= 70.0
    assert "Python" in score_result["matched_skills"]
    assert "Kubernetes" in score_result["missing_skills"]

    insights = ranking_service.generate_ai_insights(
        candidate_name="Sarah Connor",
        ats_score=score_result["overall_ats_score"],
        ats_breakdown=score_result,
        parsed_data=candidate_data,
        job_title="Senior Python Backend Engineer",
    )
    assert insights["hiring_recommendation"] in ("SHORTLIST", "REVIEW")
    assert len(insights["recommended_interview_questions"]) >= 2


# ==============================================================================
# 7. END-TO-END PIPELINE SERVICE ORCHESTRATION
# ==============================================================================

@pytest.mark.asyncio
async def test_end_to_end_pipeline_flow():
    """Verify end-to-end processing pipeline from upload to candidate record & response."""
    mock_session = AsyncMock()
    pipeline = AIScreeningPipelineService(session=mock_session)

    # Mock storage
    mock_storage = MagicMock()
    mock_storage.save_file = AsyncMock(return_value={
        "file_path": "uploads/resumes/2026/08/sample.pdf",
        "original_filename": "sample_resume.pdf",
        "file_size": 1024 * 50,
        "mime_type": "application/pdf",
        "file_bytes": b"%PDF-1.4 mock content",
    })
    pipeline.storage_service = mock_storage

    # Mock OCR
    mock_ocr = MagicMock()
    mock_ocr.extract_text = AsyncMock(return_value={
        "raw_text": "David Miller\nEmail: david.miller@tech.io\nPhone: +1 415-555-0100\nSenior React & Node.js Developer\nExperience: 6 years",
        "ocr_engine": "pypdf_native",
        "confidence": 0.98,
    })
    pipeline.ocr_service = mock_ocr

    # Mock Parser
    mock_parser = MagicMock()
    mock_parser.parse_resume = AsyncMock(return_value={
        "candidate_name": "David Miller",
        "email": "david.miller@tech.io",
        "phone": "+1 415-555-0100",
        "skills": ["ReactJS", "NodeJS", "Postgres", "Docker"],
        "total_experience_years": 6.0,
        "current_company": "Apex Labs",
        "current_designation": "Senior Fullstack Engineer",
        "parsing_confidence": 0.96,
        "work_history": [{
            "company": "Apex Labs",
            "designation": "Senior Fullstack Engineer",
            "start_date": "2020",
            "end_date": "Present",
            "is_current": True,
        }],
        "education": [{
            "degree": "B.Tech",
            "field_of_study": "Computer Science",
            "university": "State University",
        }],
    })
    pipeline.parser_service = mock_parser

    # Mock Duplicate service
    mock_dup = MagicMock()
    mock_dup.check_duplicate = AsyncMock(return_value={
        "is_duplicate": False,
        "duplicate_candidate_id": None,
        "matched_by": [],
        "candidate": None,
    })
    pipeline.duplicate_service = mock_dup

    # Mock Repository candidate creation
    created_cand = Candidate(
        id=uuid.uuid4(),
        first_name="David",
        last_name="Miller",
        email="david.miller@tech.io",
        phone="+1 415-555-0100",
        current_company="Apex Labs",
        current_role="Senior Fullstack Engineer",
        years_experience=6.0,
        skills=["React", "Node.js", "PostgreSQL", "Docker"],
    )
    pipeline.repo.get_or_create_candidate = AsyncMock(return_value=created_cand)

    created_doc = AIResumeDocument(
        id=uuid.uuid4(),
        candidate_id=created_cand.id,
        file_path="uploads/resumes/2026/08/sample.pdf",
        file_name="sample_resume.pdf",
        file_size=1024 * 50,
        file_type="application/pdf",
        parse_status="COMPLETED",
        created_at=datetime.utcnow(),
    )
    pipeline.repo.create_resume_document = AsyncMock(return_value=created_doc)
    pipeline.repo.create_match_score = AsyncMock()

    # Upload file mock
    mock_upload = MagicMock()
    mock_upload.filename = "sample_resume.pdf"
    mock_upload.content_type = "application/pdf"

    # Execute
    res = await pipeline.process_resume_upload(file=mock_upload)

    assert res.candidate_id == str(created_cand.id)
    assert res.resume_document_id == str(created_doc.id)
    assert res.status == "COMPLETED"
    assert res.candidate_details.candidate_name == "David Miller"
    assert "React" in res.candidate_details.skills
    assert "Node.js" in res.candidate_details.skills
    assert "PostgreSQL" in res.candidate_details.skills
    assert res.parsing_confidence >= 0.90
    assert res.ats_score > 0
