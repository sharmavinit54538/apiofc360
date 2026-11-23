"""Autopilot views and retries over canonical onboarding and payroll records."""
import uuid
from pathlib import Path
from collections import defaultdict
from fastapi import HTTPException
from sqlalchemy import select, func
from app.models.employee import Employee
from app.models.employee_onboarding import EmployeeOnboarding as Step
from app.models.employee_document import EmployeeDocument
from app.models.automation_jobs import AutomationExecution
from app.services.automation_queue import enqueue, serialize


def run_data(employee, steps):
    completed = [s for s in steps if s.is_completed]
    failed = next((s for s in steps if s.status.upper() == "FAILED"), None)
    current = next((s for s in steps if not s.is_completed), None)
    status = "failed" if failed else "completed" if len(completed) == len(steps) else "in_progress" if completed else "pending"
    return {"id": str(employee.id), "employee_id": str(employee.id),
            "employee_name": f"{employee.first_name} {employee.last_name}".strip(), "template_id": None,
            "status": status, "current_step": current.step_name if current else None,
            "completed_steps": [s.step_name for s in completed],
            "failed_step": failed.step_name if failed else None, "failure_reason": failed.notes if failed else None,
            "started_at": min(s.created_at for s in steps), "created_at": min(s.created_at for s in steps),
            "completed_at": max((s.completed_at for s in completed if s.completed_at), default=None) if status == "completed" else None}


async def list_runs(db, company_id, status=None, page=1, limit=20):
    ids = select(Step.employee_id).join(Employee, Employee.id == Step.employee_id).where(
        Employee.company_id == company_id, Employee.is_deleted.is_(False)).group_by(Step.employee_id)
    failed = func.count().filter(Step.status == "FAILED")
    done = func.count().filter(Step.is_completed.is_(True))
    if status == "failed":
        ids = ids.having(failed > 0)
    elif status == "completed":
        ids = ids.having(done == func.count(), failed == 0)
    elif status == "pending":
        ids = ids.having(done == 0, failed == 0)
    elif status == "in_progress":
        ids = ids.having(done > 0, done < func.count(), failed == 0)
    elif status:
        ids = ids.having(False)
    total = await db.scalar(select(func.count()).select_from(ids.subquery()))
    selected = ids.order_by(Step.employee_id).offset((page-1)*limit).limit(limit)
    rows = (await db.execute(select(Employee, Step).join(Step, Step.employee_id == Employee.id).where(
        Employee.company_id == company_id, Employee.id.in_(selected)).order_by(Step.step_order))).all()
    grouped, employees = defaultdict(list), {}
    for employee, step in rows:
        employees[employee.id] = employee
        grouped[employee.id].append(step)
    pages = (total + limit - 1) // limit
    return {"items": [run_data(employees[eid], steps) for eid, steps in grouped.items()],
            "total": total, "page": page, "limit": limit, "pages": pages,
            "has_next": page < pages, "has_previous": page > 1}


async def get_run(db, company_id, run_id):
    employee = await db.scalar(select(Employee).where(Employee.id == run_id, Employee.company_id == company_id,
                                                    Employee.is_deleted.is_(False)))
    if not employee:
        raise HTTPException(404, "Onboarding run not found")
    steps = (await db.scalars(select(Step).where(Step.employee_id == run_id).order_by(Step.step_order))).all()
    if not steps:
        raise HTTPException(404, "Onboarding run not found")
    history = (await db.scalars(select(AutomationExecution).where(
        AutomationExecution.company_id == company_id, AutomationExecution.kind == "onboarding",
        AutomationExecution.payload["employee_id"].as_string() == str(run_id))
        .order_by(AutomationExecution.created_at.desc()).limit(100))).all()
    return {**run_data(employee, steps), "steps": [{"id": str(s.id), "name": s.step_name,
            "status": s.status, "completed_at": s.completed_at, "verified_by": str(s.verified_by) if s.verified_by else None,
            "failure_reason": s.notes} for s in steps], "step_history": [serialize(j) for j in history]}


async def retry_run(db, company_id, actor_id, run_id, key):
    await get_run(db, company_id, run_id)
    docs = (await db.scalars(select(EmployeeDocument.id).where(
        EmployeeDocument.employee_id == run_id, EmployeeDocument.ocr_status == "FAILED"))).all()
    if not docs:
        raise HTTPException(409, "No failed automatic document step is available; manual steps require employee input or HR review")
    job = await enqueue(db, company_id=company_id, actor_id=actor_id, kind="onboarding",
        key=f"{run_id}:{key}", payload={"employee_id": str(run_id), "document_ids": [str(d) for d in docs]})
    await db.commit()
    return {"run_id": str(run_id), "retried": False, "status": job.status, "job_id": str(job.id), "idempotency_key": key}


async def execute_onboarding_retry(db, job):
    from app.services.employee_onboarding_service import EmployeeOnboardingService
    from app.services.storage_service import DOCUMENTS_DIR_ABSOLUTE
    employee_id = uuid.UUID(job.payload["employee_id"])
    employee = await db.scalar(select(Employee).where(Employee.id == employee_id, Employee.company_id == job.company_id))
    if not employee:
        raise LookupError("Employee not found")
    documents = (await db.scalars(select(EmployeeDocument).where(EmployeeDocument.employee_id == employee_id,
        EmployeeDocument.id.in_([uuid.UUID(value) for value in job.payload["document_ids"]])))).all()
    if len(documents) != len(job.payload["document_ids"]):
        raise LookupError("Onboarding documents are unavailable")
    results = []
    for document in documents:
        path = Path(document.file_path).resolve()
        if not path.is_relative_to(Path(DOCUMENTS_DIR_ABSOLUTE).resolve()) or not path.is_file():
            raise ValueError("Document is outside private storage or unavailable")
        result = await EmployeeOnboardingService(db).process_onboarding_document(document, file_bytes=path.read_bytes())
        results.append({"document_id": str(document.id), "valid": result["valid"]})
    # Processing genuinely ran. Verification failure remains visible on documents.
    return {"documents": results, "all_valid": all(r["valid"] for r in results)}


async def payroll_status(db, company_id):
    from app.models.payroll import PayrollRun
    from app.models.payroll_models import PayrollRunEmployee
    run = await db.scalar(select(PayrollRun).where(PayrollRun.company_id == company_id).order_by(PayrollRun.created_at.desc()).limit(1))
    processed = await db.scalar(select(func.count()).select_from(PayrollRunEmployee).where(PayrollRunEmployee.run_id == run.id)) if run else 0
    state = run.status if run else None
    status = "running" if state == "PROCESSING" else "failed" if state == "FAILED" else "completed" if state in {"PROCESSED", "APPROVED", "FINALIZED", "PAID"} else "idle"
    total = run.total_employees if run else 0
    return {"status": status, "current_phase": state, "progress_percentage": min(100.0, processed / total * 100) if total else 0.0,
            "employees_processed": processed, "employees_total": total, "errors_count": len(run.validation_errors or []) if run else 0,
            "warnings_count": 0, "started_at": run.run_at if run else None, "estimated_completion": None,
            "last_run": run.run_at if run else None, "last_run_status": state, "next_scheduled_run": None}
