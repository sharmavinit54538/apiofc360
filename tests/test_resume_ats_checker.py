"""Unit tests for the Resume ATS Checker API endpoint and scoring pipeline."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.middleware.auth import get_current_user_claims


@pytest.fixture
def mock_user_claims():
    return {
        "sub": "11111111-1111-1111-1111-111111111111",
        "email": "user@example.com",
        "role": "employee",
        "company_id": "22222222-2222-2222-2222-222222222222",
    }


@pytest.fixture
def client(mock_user_claims):
    app.dependency_overrides[get_current_user_claims] = lambda: mock_user_claims
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_current_user_claims, None)


def test_resume_ats_checker_unsupported_file_extension(client):
    """Ensure unsupported file formats return 422 Unprocessable Entity."""
    response = client.post(
        "/api/v2/resume-ats-checker/check",
        files={"file": ("test_resume.exe", b"binary content", "application/octet-stream")},
    )
    assert response.status_code == 422
    data = response.json()
    msg = data.get("message") or data.get("detail") or ""
    assert "not supported" in str(msg).lower()


def test_resume_ats_checker_empty_file(client):
    """Ensure empty files return 422 Unprocessable Entity."""
    response = client.post(
        "/api/v2/resume-ats-checker/check",
        files={"file": ("empty_resume.pdf", b"", "application/pdf")},
    )
    assert response.status_code == 422
    data = response.json()
    msg = data.get("message") or data.get("detail") or ""
    assert "empty" in str(msg).lower()


@patch("app.api.v2.resume_ats_checker.ResumeOCRService")
@patch("app.api.v2.resume_ats_checker.ResumeParserService")
def test_resume_ats_checker_success_with_job(mock_parser_cls, mock_ocr_cls, client):
    """Test full ATS evaluation pipeline with job title, description, and required skills."""
    # Mock OCR
    mock_ocr = MagicMock()
    mock_ocr.extract_text = AsyncMock(return_value={
        "raw_text": "John Doe Senior Python Developer with 6 years experience in FastAPI, Docker, Kubernetes, React.",
        "ocr_engine": "pypdf",
        "confidence": 0.95,
    })
    mock_ocr_cls.return_value = mock_ocr

    # Mock Parser
    mock_parser = MagicMock()
    mock_parser.parse_resume = AsyncMock(return_value={
        "candidate_name": "John Doe",
        "email": "john.doe@example.com",
        "phone": "+1234567890",
        "skills": ["python", "fastapi", "docker", "kubernetes", "react"],
        "technical_skills": ["python", "fastapi", "docker", "kubernetes"],
        "soft_skills": ["communication"],
        "total_experience_years": 6.0,
        "education": [{"degree": "B.Tech Computer Science", "university": "Stanford"}],
        "projects": [{"title": "Cloud Microservices", "technologies": ["python", "fastapi"]}],
        "certifications": ["AWS Certified Solutions Architect"],
        "summary": "Experienced backend engineer passionate about distributed systems.",
    })
    mock_parser_cls.return_value = mock_parser

    response = client.post(
        "/api/v2/resume-ats-checker/check",
        files={"file": ("john_resume.pdf", b"%PDF-1.4 Fake PDF Content for unit test", "application/pdf")},
        data={
            "job_title": "Senior Python Backend Developer",
            "job_description": "We are seeking a Senior Python Engineer with experience in FastAPI, Docker, and PostgreSQL.",
            "required_skills": "python,fastapi,docker,postgresql,redis",
        },
    )

    assert response.status_code == 200
    res_data = response.json()
    assert res_data["success"] is True
    assert "data" in res_data
    ats_data = res_data["data"]

    # Assert critical payload fields
    assert "ats_score" in ats_data
    assert ats_data["ats_score"] > 0
    assert ats_data["has_job_context"] is True
    assert "score_breakdown" in ats_data
    assert "category_scores" in ats_data
    assert "matched_skills" in ats_data
    assert "missing_skills" in ats_data
    assert "extra_skills" in ats_data
    assert "recommendations" in ats_data
    assert "parsed_resume" in ats_data
    assert ats_data["parsed_resume"]["name"] == "John Doe"
    assert ats_data["parsed_resume"]["email"] == "john.doe@example.com"


@patch("app.api.v2.resume_ats_checker.ResumeOCRService")
@patch("app.api.v2.resume_ats_checker.ResumeParserService")
def test_resume_ats_checker_success_without_job(mock_parser_cls, mock_ocr_cls, client):
    """Test ATS evaluation pipeline without target job (resume health diagnostic)."""
    # Mock OCR
    mock_ocr = MagicMock()
    mock_ocr.extract_text = AsyncMock(return_value={
        "raw_text": "Jane Smith Full Stack Developer with JavaScript, Node.js, Python, SQL.",
        "ocr_engine": "docx_fallback",
        "confidence": 0.90,
    })
    mock_ocr_cls.return_value = mock_ocr

    # Mock Parser
    mock_parser = MagicMock()
    mock_parser.parse_resume = AsyncMock(return_value={
        "candidate_name": "Jane Smith",
        "email": "jane@example.com",
        "phone": "+1987654321",
        "skills": ["javascript", "node.js", "python", "sql"],
        "total_experience_years": 3.0,
        "education": [{"degree": "B.S. Information Systems"}],
        "projects": [],
        "certifications": [],
        "summary": "Full stack engineer",
    })
    mock_parser_cls.return_value = mock_parser

    response = client.post(
        "/api/v2/resume-ats-checker/check",
        files={"file": ("jane_resume.docx", b"PK Fake DOCX Content for unit test", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert response.status_code == 200
    res_data = response.json()
    assert res_data["success"] is True
    ats_data = res_data["data"]
    assert ats_data["has_job_context"] is False
    assert ats_data["job_match_score"] is None
    assert ats_data["ats_score"] > 0
    assert len(ats_data["recommendations"]) > 0
