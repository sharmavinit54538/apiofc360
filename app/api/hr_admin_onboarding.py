"""HR Admin Onboarding API routes matching frontend requirements."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.company import Company
from app.models.user import User
from app.models.employee import Employee
from app.schemas.auth import APIResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hr-admin/onboarding", tags=["HR Admin Onboarding"])

# In-memory stores for mockable workflows, new hires, documents, tasks (keyed by company_id)
_STORE: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}


def _get_store(company_id: str) -> Dict[str, List[Dict[str, Any]]]:
    if company_id not in _STORE:
        _STORE[company_id] = {
            "workflows": [
                {
                    "id": "wf-1",
                    "title": "Standard Employee Onboarding",
                    "description": "Default workflow for all standard new hires",
                    "stepsCount": 5,
                    "targetRole": "ALL",
                    "isDefault": True,
                    "createdAt": datetime.now().isoformat(),
                }
            ],
            "new_hires": [],
            "documents": [],
            "tasks": [],
        }
    return _STORE[company_id]


async def _get_company_and_user(session: AsyncSession, claims: dict):
    company_id_str = claims.get("company_id")
    company = None
    if company_id_str:
        try:
            cid = uuid.UUID(company_id_str)
            comp_res = await session.execute(select(Company).where(Company.id == cid))
            company = comp_res.scalar_one_or_none()
        except ValueError:
            company = None

    if not company:
        comp_res = await session.execute(select(Company).limit(1))
        company = comp_res.scalar_one_or_none()

    user_id_str = claims.get("sub")
    user = None
    if user_id_str:
        try:
            uid = uuid.UUID(user_id_str)
            user_res = await session.execute(select(User).where(User.id == uid))
            user = user_res.scalar_one_or_none()
        except ValueError:
            pass

    return company, user


def _build_onboarding_data(company: Company | None, user: User | None) -> Dict[str, Any]:
    prof = (company.company_profile or {}) if company else {}
    return {
        "current_step": getattr(company, "onboarding_step", 0) or 0,
        "completed": getattr(company, "onboarding_completed", False) or False,
        "completed_at": prof.get("completed_at"),
        "companyName": (company.name if company else None) or prof.get("companyName") or prof.get("company_name") or "",
        "logo": prof.get("logo") or prof.get("logo_url") or "",
        "industry": prof.get("industry") or "",
        "companySize": prof.get("companySize") or prof.get("company_size") or "",
        "website": prof.get("website") or "",
        "country": prof.get("country") or "India",
        "timezone": prof.get("timezone") or "Asia/Kolkata",
        "address": prof.get("address") or "",
        "city": prof.get("city") or "",
        "state": prof.get("state") or "",
        "zipCode": prof.get("zipCode") or prof.get("zip_code") or "",
        "gstNumber": prof.get("gstNumber") or prof.get("gst_number") or "",
        "fullName": (user.name if user else None) or prof.get("fullName") or "",
        "phone": (user.phone if user else None) or prof.get("phone") or "",
        "avatar": (getattr(user, "avatar_url", None) if user else None) or prof.get("avatar") or "",
        "termsAccepted": prof.get("termsAccepted", True),
        "dpaAccepted": prof.get("dpaAccepted", True),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. Organization Onboarding Step Wizard Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/status", response_model=APIResponse[Dict[str, Any]])
async def get_onboarding_status(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    """Get onboarding completion status."""
    company, _ = await _get_company_and_user(session, claims)
    completed = getattr(company, "onboarding_completed", False) or False
    step = getattr(company, "onboarding_step", 0) or 0
    return APIResponse(
        success=True,
        message="Onboarding status retrieved successfully.",
        data={
            "completed": completed,
            "current_step": step,
            "total_steps": 4,
        },
    )


@router.get("", response_model=APIResponse[Dict[str, Any]])
async def get_onboarding_data(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    """Get all saved onboarding wizard data."""
    company, user = await _get_company_and_user(session, claims)
    data = _build_onboarding_data(company, user)
    return APIResponse(
        success=True,
        message="Onboarding data retrieved successfully.",
        data=data,
    )


@router.post("/step/{step_index}", response_model=APIResponse[Dict[str, Any]])
async def save_onboarding_step(
    step_index: int,
    payload: Dict[str, Any],
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    """Save an onboarding step payload (Step 0, 1, 2, 3)."""
    company, user = await _get_company_and_user(session, claims)

    if company:
        prof = company.company_profile or {}
        prof.update(payload)

        # Sync top-level company attributes
        if "companyName" in payload and payload["companyName"]:
            company.name = str(payload["companyName"]).strip()
            prof["name"] = company.name

        company.company_profile = prof
        flag_modified(company, "company_profile")

        if company.onboarding_step is None or company.onboarding_step <= step_index:
            company.onboarding_step = step_index + 1

    if user:
        if "fullName" in payload and payload["fullName"]:
            user.name = str(payload["fullName"]).strip()
        if "phone" in payload and payload["phone"]:
            user.phone = str(payload["phone"]).strip()

    await session.commit()

    updated_data = _build_onboarding_data(company, user)
    return APIResponse(
        success=True,
        message=f"Onboarding step {step_index} saved successfully.",
        data=updated_data,
    )


@router.post("/complete", response_model=APIResponse[Dict[str, Any]])
async def complete_onboarding(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    """Mark onboarding as fully completed."""
    company, user = await _get_company_and_user(session, claims)

    if company:
        company.onboarding_completed = True
        company.onboarding_step = 4
        prof = company.company_profile or {}
        prof["completed"] = True
        prof["completed_at"] = datetime.now().isoformat()
        company.company_profile = prof
        flag_modified(company, "company_profile")

    if user:
        if hasattr(user, "is_onboarding_completed"):
            user.is_onboarding_completed = True
        if hasattr(user, "onboarding_step"):
            user.onboarding_step = 4

    await session.commit()

    updated_data = _build_onboarding_data(company, user)
    return APIResponse(
        success=True,
        message="Onboarding completed successfully.",
        data=updated_data,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Onboarding Workflows
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/workflows", response_model=APIResponse[List[Dict[str, Any]]])
async def list_workflows(claims: dict = Depends(get_current_user_claims)):
    cid = claims.get("company_id", "default")
    store = _get_store(cid)
    return APIResponse(success=True, message="Workflows retrieved.", data=store["workflows"])


@router.post("/workflows", response_model=APIResponse[Dict[str, Any]])
async def create_workflow(payload: Dict[str, Any], claims: dict = Depends(get_current_user_claims)):
    cid = claims.get("company_id", "default")
    store = _get_store(cid)
    item = {
        "id": f"wf-{uuid.uuid4().hex[:8]}",
        "title": payload.get("title", "New Workflow"),
        "description": payload.get("description", ""),
        "stepsCount": payload.get("stepsCount", 1),
        "targetRole": payload.get("targetRole", "ALL"),
        "isDefault": payload.get("isDefault", False),
        "createdAt": datetime.now().isoformat(),
    }
    store["workflows"].append(item)
    return APIResponse(success=True, message="Workflow created.", data=item)


@router.delete("/workflows/{workflow_id}", response_model=APIResponse[Dict[str, Any]])
async def delete_workflow(workflow_id: str, claims: dict = Depends(get_current_user_claims)):
    cid = claims.get("company_id", "default")
    store = _get_store(cid)
    store["workflows"] = [w for w in store["workflows"] if w["id"] != workflow_id]
    return APIResponse(success=True, message="Workflow deleted.", data={"id": workflow_id})


# ─────────────────────────────────────────────────────────────────────────────
# 3. New Hires Onboarding
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/new-hires", response_model=APIResponse[List[Dict[str, Any]]])
async def list_new_hires(
    claims: dict = Depends(get_current_user_claims),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
):
    cid = claims.get("company_id", "default")
    store = _get_store(cid)
    items = store["new_hires"]
    if status_filter:
        items = [i for i in items if i.get("status") == status_filter]
    if search:
        s = search.lower()
        items = [i for i in items if s in i.get("fullName", "").lower() or s in i.get("email", "").lower()]
    return APIResponse(success=True, message="New hires retrieved.", data=items)


@router.post("/new-hires", response_model=APIResponse[Dict[str, Any]])
async def create_new_hire(payload: Dict[str, Any], claims: dict = Depends(get_current_user_claims)):
    cid = claims.get("company_id", "default")
    store = _get_store(cid)
    item = {
        "id": f"nh-{uuid.uuid4().hex[:8]}",
        "fullName": payload.get("fullName", ""),
        "email": payload.get("email", ""),
        "department": payload.get("department", "Engineering"),
        "role": payload.get("role", "Software Engineer"),
        "startDate": payload.get("startDate", datetime.now().strftime("%Y-%m-%d")),
        "status": payload.get("status", "INVITED"),
        "progressPercentage": 0,
        "workflowId": payload.get("workflowId", "wf-1"),
        "createdAt": datetime.now().isoformat(),
    }
    store["new_hires"].append(item)
    return APIResponse(success=True, message="New hire added.", data=item)


@router.patch("/new-hires/{hire_id}", response_model=APIResponse[Dict[str, Any]])
async def update_new_hire(hire_id: str, payload: Dict[str, Any], claims: dict = Depends(get_current_user_claims)):
    cid = claims.get("company_id", "default")
    store = _get_store(cid)
    for nh in store["new_hires"]:
        if nh["id"] == hire_id:
            nh.update(payload)
            return APIResponse(success=True, message="New hire updated.", data=nh)
    raise HTTPException(status_code=404, detail="New hire not found.")


@router.delete("/new-hires/{hire_id}", response_model=APIResponse[Dict[str, Any]])
async def delete_new_hire(hire_id: str, claims: dict = Depends(get_current_user_claims)):
    cid = claims.get("company_id", "default")
    store = _get_store(cid)
    store["new_hires"] = [n for n in store["new_hires"] if n["id"] != hire_id]
    return APIResponse(success=True, message="New hire deleted.", data={"id": hire_id})


# ─────────────────────────────────────────────────────────────────────────────
# 4. Onboarding Documents
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/documents", response_model=APIResponse[List[Dict[str, Any]]])
async def list_documents(
    claims: dict = Depends(get_current_user_claims),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
):
    cid = claims.get("company_id", "default")
    store = _get_store(cid)
    items = store["documents"]
    if status_filter:
        items = [i for i in items if i.get("status") == status_filter]
    if search:
        s = search.lower()
        items = [i for i in items if s in i.get("title", "").lower()]
    return APIResponse(success=True, message="Documents retrieved.", data=items)


@router.post("/documents", response_model=APIResponse[Dict[str, Any]])
async def create_document(payload: Dict[str, Any], claims: dict = Depends(get_current_user_claims)):
    cid = claims.get("company_id", "default")
    store = _get_store(cid)
    item = {
        "id": f"doc-{uuid.uuid4().hex[:8]}",
        "title": payload.get("title", "Document"),
        "category": payload.get("category", "IDENTITY"),
        "isRequired": payload.get("isRequired", True),
        "description": payload.get("description", ""),
        "status": "PENDING",
        "createdAt": datetime.now().isoformat(),
    }
    store["documents"].append(item)
    return APIResponse(success=True, message="Document created.", data=item)


@router.patch("/documents/{doc_id}", response_model=APIResponse[Dict[str, Any]])
async def update_document(doc_id: str, payload: Dict[str, Any], claims: dict = Depends(get_current_user_claims)):
    cid = claims.get("company_id", "default")
    store = _get_store(cid)
    for d in store["documents"]:
        if d["id"] == doc_id:
            d.update(payload)
            return APIResponse(success=True, message="Document updated.", data=d)
    raise HTTPException(status_code=404, detail="Document not found.")


@router.delete("/documents/{doc_id}", response_model=APIResponse[Dict[str, Any]])
async def delete_document(doc_id: str, claims: dict = Depends(get_current_user_claims)):
    cid = claims.get("company_id", "default")
    store = _get_store(cid)
    store["documents"] = [d for d in store["documents"] if d["id"] != doc_id]
    return APIResponse(success=True, message="Document deleted.", data={"id": doc_id})


# ─────────────────────────────────────────────────────────────────────────────
# 5. Onboarding Tasks
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/tasks", response_model=APIResponse[List[Dict[str, Any]]])
async def list_tasks(
    claims: dict = Depends(get_current_user_claims),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
):
    cid = claims.get("company_id", "default")
    store = _get_store(cid)
    items = store["tasks"]
    if status_filter:
        items = [i for i in items if i.get("status") == status_filter]
    if search:
        s = search.lower()
        items = [i for i in items if s in i.get("title", "").lower()]
    return APIResponse(success=True, message="Tasks retrieved.", data=items)


@router.post("/tasks", response_model=APIResponse[Dict[str, Any]])
async def create_task(payload: Dict[str, Any], claims: dict = Depends(get_current_user_claims)):
    cid = claims.get("company_id", "default")
    store = _get_store(cid)
    item = {
        "id": f"task-{uuid.uuid4().hex[:8]}",
        "title": payload.get("title", "Task"),
        "assigneeRole": payload.get("assigneeRole", "HR_ADMIN"),
        "dueDaysOffset": payload.get("dueDaysOffset", 1),
        "description": payload.get("description", ""),
        "status": "PENDING",
        "createdAt": datetime.now().isoformat(),
    }
    store["tasks"].append(item)
    return APIResponse(success=True, message="Task created.", data=item)


@router.patch("/tasks/{task_id}", response_model=APIResponse[Dict[str, Any]])
async def update_task(task_id: str, payload: Dict[str, Any], claims: dict = Depends(get_current_user_claims)):
    cid = claims.get("company_id", "default")
    store = _get_store(cid)
    for t in store["tasks"]:
        if t["id"] == task_id:
            t.update(payload)
            return APIResponse(success=True, message="Task updated.", data=t)
    raise HTTPException(status_code=404, detail="Task not found.")


@router.delete("/tasks/{task_id}", response_model=APIResponse[Dict[str, Any]])
async def delete_task(task_id: str, claims: dict = Depends(get_current_user_claims)):
    cid = claims.get("company_id", "default")
    store = _get_store(cid)
    store["tasks"] = [t for t in store["tasks"] if t["id"] != task_id]
    return APIResponse(success=True, message="Task deleted.", data={"id": task_id})
