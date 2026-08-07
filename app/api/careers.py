"""Public Career Portal API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, UploadFile, status

from app.schemas.auth import APIResponse
from app.schemas.recruitment import (
    ApplicationCreate,
    ApplicationResponse,
    CareerPortalJobDetail,
    JobResponse,
)
from app.services.recruitment_service import RecruitmentService, get_recruitment_service

router = APIRouter(prefix="/public/careers", tags=["Public Career Portal"])

@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[JobResponse]],
    summary="List all published jobs for career portal",
)
async def list_published_jobs(
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[list[JobResponse]]:
    """Retrieve all active published job postings. Public / Unauthenticated."""
    jobs = await service.get_public_careers()
    return APIResponse[list[JobResponse]](
        success=True,
        message="Active jobs retrieved successfully.",
        data=jobs,
        errors=None,
    )

@router.get(
    "/search",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[JobResponse]],
    summary="Search career portal jobs",
)
async def search_jobs(
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    q: str = Query(..., description="Search query term"),
) -> APIResponse[list[JobResponse]]:
    """Search job postings by title, department, or description. Public / Unauthenticated."""
    result = await service.list_jobs(
        status="PUBLISHED",
        search=q,
        department=None,
        location=None,
        page=1,
        limit=100,
    )
    return APIResponse[list[JobResponse]](
        success=True,
        message="Search results retrieved successfully.",
        data=result.items,
        errors=None,
    )

@router.get(
    "/filter",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[JobResponse]],
    summary="Filter career portal jobs",
)
async def filter_jobs(
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    department: str | None = Query(None),
    location: str | None = Query(None),
) -> APIResponse[list[JobResponse]]:
    """Filter published jobs by department or location. Public / Unauthenticated."""
    result = await service.list_jobs(
        status="PUBLISHED",
        search=None,
        department=department,
        location=location,
        page=1,
        limit=100,
    )
    return APIResponse[list[JobResponse]](
        success=True,
        message="Filtered results retrieved successfully.",
        data=result.items,
        errors=None,
    )

@router.get(
    "/{slug}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CareerPortalJobDetail],
    summary="Get job detail by slug",
)
async def get_job_by_slug(
    slug: str,
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[CareerPortalJobDetail]:
    """Retrieve full detail of a published job posting. Public / Unauthenticated."""
    job = await service.get_public_job_detail(slug)
    return APIResponse[CareerPortalJobDetail](
        success=True,
        message="Job details retrieved successfully.",
        data=CareerPortalJobDetail.model_validate(job),
        errors=None,
    )

@router.post(
    "/{slug}/apply",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[ApplicationResponse],
    summary="Apply for a job posting",
)
@router.post(
    "/apply/{slug}",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[ApplicationResponse],
    summary="Apply for a job posting by ID or slug",
)
async def apply_to_job(
    slug: str,
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    resume_file: UploadFile,
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    country: str = Form(...),
    state: str = Form(...),
    city: str = Form(...),
    current_company: str | None = Form(None),
    current_designation: str | None = Form(None),
    current_ctc: float | None = Form(None),
    expected_ctc: float | None = Form(None),
    notice_period: str | None = Form(None),
    highest_qualification: str | None = Form(None),
    experience_years: float = Form(0.0),
    is_fresher: bool | None = Form(None),
    linkedin_url: str | None = Form(None),
    portfolio_url: str | None = Form(None),
    cover_letter: str | None = Form(None),
    declaration_checked: bool = Form(...),
) -> APIResponse[ApplicationResponse]:
    """Submit candidate application form and resume. PDF/DOCX <= 5MB. Public / Unauthenticated."""
    payload = ApplicationCreate(
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
        country=country,
        state=state,
        city=city,
        current_company=current_company,
        current_designation=current_designation,
        current_ctc=current_ctc,
        expected_ctc=expected_ctc,
        notice_period=notice_period,
        highest_qualification=highest_qualification,
        experience_years=experience_years,
        is_fresher=is_fresher,
        linkedin_url=linkedin_url,
        portfolio_url=portfolio_url,
        cover_letter=cover_letter,
        declaration_checked=declaration_checked,
    )
    app = await service.apply_to_job(slug, payload, resume_file)
    return APIResponse[ApplicationResponse](
        success=True,
        message="Application submitted successfully.",
        data=app,
        errors=None,
    )


@router.get(
    "/apply/{ukey}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[JobResponse],
    summary="Get job detail by unique channel key",
)
async def get_job_by_ukey(
    ukey: str,
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[JobResponse]:
    """Retrieve details of a published job by its unique channel key. Public / Unauthenticated."""
    job = await service.get_job_by_ukey(ukey)
    return APIResponse[JobResponse](
        success=True,
        message="Job details retrieved successfully.",
        data=job,
        errors=None,
    )


@router.post(
    "/apply/{ukey}",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[ApplicationResponse],
    summary="Apply for a job posting using unique channel key",
)
async def apply_to_job_by_ukey(
    ukey: str,
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    resume_file: UploadFile,
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    country: str = Form(...),
    state: str = Form(...),
    city: str = Form(...),
    current_company: str | None = Form(None),
    current_designation: str | None = Form(None),
    current_ctc: float | None = Form(None),
    expected_ctc: float | None = Form(None),
    notice_period: str | None = Form(None),
    highest_qualification: str | None = Form(None),
    experience_years: float = Form(0.0),
    linkedin_url: str | None = Form(None),
    portfolio_url: str | None = Form(None),
    cover_letter: str | None = Form(None),
    declaration_checked: bool = Form(...),
) -> APIResponse[ApplicationResponse]:
    """Submit candidate application form and resume via unique channel key. PDF/DOCX <= 5MB. Public / Unauthenticated."""
    payload = ApplicationCreate(
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
        country=country,
        state=state,
        city=city,
        current_company=current_company,
        current_designation=current_designation,
        current_ctc=current_ctc,
        expected_ctc=expected_ctc,
        notice_period=notice_period,
        highest_qualification=highest_qualification,
        experience_years=experience_years,
        linkedin_url=linkedin_url,
        portfolio_url=portfolio_url,
        cover_letter=cover_letter,
        declaration_checked=declaration_checked,
    )
    app = await service.apply_to_job_by_ukey(ukey, payload, resume_file)
    return APIResponse[ApplicationResponse](
        success=True,
        message="Application submitted successfully.",
        data=app,
        errors=None,
    )
