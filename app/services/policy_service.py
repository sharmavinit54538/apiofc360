"""AI Policy Explainer RAG Search and Chat service.

Splits policies manuals into chunks, generates vector embeddings, and performs
vector cosine similarity search queries to answer chatbot inputs.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.llm.client import get_llm_client
from app.llm.prompts import PromptLibrary

# Models
from app.models.policy import CompanyPolicyDocument, CompanyPolicyChunk

logger = logging.getLogger(__name__)


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Compute basic cosine similarity between two vector float lists."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_v1 = sum(a * a for a in v1) ** 0.5
    norm_v2 = sum(b * b for b in v2) ** 0.5
    if not norm_v1 or not norm_v2:
        return 0.0
    return dot_product / (norm_v1 * norm_v2)


class PolicyService:
    """Enterprise Policy RAG explainer service."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.llm = get_llm_client()

    async def upload_policy_document(
        self,
        company_id: uuid.UUID,
        title: str,
        category: str,
        raw_content: str,
    ) -> CompanyPolicyDocument:
        """Register policy manual and partition it into vector embedded chunks."""
        doc = CompanyPolicyDocument(
            id=uuid.uuid4(),
            company_id=company_id,
            title=title,
            category=category.upper(),
            raw_content=raw_content,
        )
        self.db.add(doc)
        await self.db.flush()

        # Chunk content into semantic 500-char parts
        chunk_size = 500
        words = raw_content.split()
        chunks = []
        current_chunk = []
        current_len = 0

        for w in words:
            current_chunk.append(w)
            current_len += len(w) + 1
            if current_len >= chunk_size:
                chunks.append(" ".join(current_chunk))
                current_chunk = []
                current_len = 0
        if current_chunk:
            chunks.append(" ".join(current_chunk))

        # Generate embeddings and save chunks
        for idx, text_block in enumerate(chunks):
            # nomic-embed-text generates 768 float values
            try:
                vector = await self.llm.embed(text_block)
            except Exception as exc:
                logger.error("Embedding generation failed: %s", exc)
                from app.core.exceptions import AppException
                raise AppException(message=f"Failed to generate embedding for policy document chunk: {exc}", status_code=500) from exc

            chunk = CompanyPolicyChunk(
                id=uuid.uuid4(),
                policy_document_id=doc.id,
                chunk_text=text_block,
                vector=vector,
                chunk_order=idx,
            )
            self.db.add(chunk)

        await self.db.commit()
        await self.db.refresh(doc)
        logger.info("Policy document uploaded: %s with %s chunks", doc.title, len(chunks))
        return doc

    async def search_relevant_chunks(
        self,
        company_id: uuid.UUID,
        query_text: str,
        limit: int = 3,
    ) -> list[tuple[CompanyPolicyChunk, float]]:
        """Fetch search query embedding and query local chunks using cosine similarity."""
        try:
                query_vector = await self.llm.embed(query_text)
        except Exception as exc:
            logger.error("Query embedding failed: %s", exc)
            return []

        # Retrieve all policy chunks belonging to this company
        stmt = (
            select(CompanyPolicyChunk)
            .join(CompanyPolicyChunk.document)
            .where(CompanyPolicyDocument.company_id == company_id)
        )
        res = await self.db.execute(stmt)
        chunks = res.scalars().all()

        scored_chunks = []
        for c in chunks:
            sim = cosine_similarity(query_vector, c.vector)
            scored_chunks.append((c, sim))

        # Sort descending by similarity
        scored_chunks.sort(key=lambda x: x[1], reverse=True)
        return scored_chunks[:limit]

    async def answer_policy_query(
        self,
        company_id: uuid.UUID,
        user_query: str,
        language: str = "English",
        model: Optional[str] = None,
    ) -> dict[str, Any]:
        """Query policy manuals RAG database and formulate LLM context answer response."""
        matches = await self.search_relevant_chunks(company_id, user_query, limit=3)

        context_blocks = []
        sources = []
        for c, score in matches:
            if score > 0.1:  # check minimum threshold
                context_blocks.append(f"[Policy: {c.document.title}]\n{c.chunk_text}")
                sources.append({
                    "title": c.document.title,
                    "category": c.document.category,
                    "similarity": float(score)
                })

        context_str = "\n\n".join(context_blocks) or "No relevant policy documents found."

        try:
            prompt = PromptLibrary.ai_policy_user(context_str, user_query, language)
            answer = await self.llm.complete(
                prompt=prompt,
                system=PromptLibrary.AI_POLICY_EXPLAINER_CHAT,
                model=model,
                temperature=0.2
            )
        except Exception as exc:
            logger.error("LLM explainer prompt query failed: %s", exc)
            answer = "Sorry, I encountered an internal error compiling policy details."

        return {
            "answer": answer,
            "language": language,
            "sources": sources
        }


class PolicyGovernanceService:
    """Versioning, audience targeting and acknowledgement-proof workflows."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _targets(data: dict[str, Any]) -> dict[str, list[str]]:
        return {
            key: [str(v) for v in (data.get(key) or [])]
            for key in ("target_branch_ids", "target_departments", "target_roles", "target_employment_types")
        }

    async def create_version(self, *, company_id: uuid.UUID, title: str, category: str,
                             raw_content: str, version_number: str,
                             effective_date=None, supersedes_policy_id: uuid.UUID | None = None,
                             acknowledgement_due_date=None, acknowledgement_required: bool = True,
                             reminder_after_days: int = 3, escalation_after_days: int = 7,
                             **targets) -> CompanyPolicyDocument:
        from datetime import date
        if not version_number.strip():
            raise ValueError("version_number is required")
        if reminder_after_days < 1 or escalation_after_days < reminder_after_days:
            raise ValueError("Escalation must be on or after the reminder interval")
        if supersedes_policy_id:
            old = await self.db.get(CompanyPolicyDocument, supersedes_policy_id)
            if old is None or old.company_id != company_id:
                raise LookupError("Superseded policy not found")
            if old.title != title:
                raise ValueError("A new version must retain the superseded policy title")
        duplicate = (await self.db.execute(select(CompanyPolicyDocument).where(
            CompanyPolicyDocument.company_id == company_id,
            CompanyPolicyDocument.title == title,
            CompanyPolicyDocument.version_number == version_number,
        ))).scalar_one_or_none()
        if duplicate:
            raise ValueError("This policy version already exists")
        doc = CompanyPolicyDocument(
            id=uuid.uuid4(), company_id=company_id, title=title.strip(), category=category.upper(),
            raw_content=raw_content, version_number=version_number.strip(),
            effective_date=effective_date, supersedes_policy_id=supersedes_policy_id,
            status="DRAFT", acknowledgement_required=acknowledgement_required,
            acknowledgement_due_date=acknowledgement_due_date,
            reminder_after_days=reminder_after_days, escalation_after_days=escalation_after_days,
            **self._targets(targets),
        )
        self.db.add(doc)
        await self.db.commit()
        return doc

    @staticmethod
    def employee_matches(policy: CompanyPolicyDocument, employee) -> bool:
        def matches(configured, *actual) -> bool:
            if not configured:
                return True
            wanted = {str(v).strip().upper() for v in configured}
            return any(str(v).strip().upper() in wanted for v in actual if v is not None)

        user = getattr(employee, "user", None)
        role = getattr(user, "role", None)
        role = getattr(role, "value", role)
        return all((
            matches(policy.target_branch_ids, getattr(employee, "branch_id", None), getattr(employee, "branch", None)),
            matches(policy.target_departments, getattr(employee, "department_id", None), getattr(employee, "department", None)),
            matches(policy.target_roles, role),
            matches(policy.target_employment_types, getattr(employee, "employment_type", None)),
        ))

    async def targeted_employees(self, policy: CompanyPolicyDocument):
        from sqlalchemy.orm import selectinload
        from app.models.employee import Employee
        rows = (await self.db.execute(
            select(Employee).options(selectinload(Employee.user)).where(
                Employee.company_id == policy.company_id, Employee.is_deleted.is_(False),
                Employee.status == "ACTIVE",
            )
        )).scalars().all()
        return [employee for employee in rows if self.employee_matches(policy, employee)]

    async def publish(self, policy_id: uuid.UUID, *, company_id: uuid.UUID):
        from datetime import UTC, date, datetime, time, timedelta
        from app.models.employee_policy_acceptance import PolicyAcknowledgementAssignment
        policy = await self.db.get(CompanyPolicyDocument, policy_id)
        if policy is None or policy.company_id != company_id:
            raise LookupError("Policy not found")
        now = datetime.now(UTC)
        policy.status = "PUBLISHED"
        policy.effective_date = policy.effective_date or date.today()
        if policy.supersedes_policy_id:
            old = await self.db.get(CompanyPolicyDocument, policy.supersedes_policy_id)
            if old and old.company_id == company_id:
                old.status = "SUPERSEDED"
                from app.models.employee_policy_acceptance import PolicyAcknowledgementAssignment
                old_assignments = (await self.db.execute(select(PolicyAcknowledgementAssignment).where(
                    PolicyAcknowledgementAssignment.policy_document_id == old.id,
                    PolicyAcknowledgementAssignment.status == "PENDING",
                ))).scalars().all()
                for assignment in old_assignments:
                    assignment.status = "CANCELLED"
        employees = await self.targeted_employees(policy) if policy.acknowledgement_required else []
        existing = (await self.db.execute(select(PolicyAcknowledgementAssignment).where(
            PolicyAcknowledgementAssignment.policy_document_id == policy.id,
        ))).scalars().all()
        assigned = {row.employee_id for row in existing}
        if policy.acknowledgement_due_date:
            due_at = datetime.combine(policy.acknowledgement_due_date, time(23, 59, 59), tzinfo=UTC)
        else:
            due_at = now + timedelta(days=policy.escalation_after_days)
        for employee in employees:
            if employee.id not in assigned:
                self.db.add(PolicyAcknowledgementAssignment(
                    id=uuid.uuid4(), policy_document_id=policy.id, employee_id=employee.id,
                    company_id=company_id, status="PENDING", due_at=due_at, assigned_at=now,
                ))
        await self.db.commit()
        return policy, len(employees)

    async def acknowledge(self, policy_id: uuid.UUID, *, employee_id: uuid.UUID,
                          digital_signature: str, ip_address: str | None,
                          user_agent: str | None, user_id: uuid.UUID | None = None,
                          request_id: str | None = None):
        from datetime import UTC, datetime
        import hashlib
        from app.models.employee import Employee
        from app.models.employee_policy_acceptance import EmployeePolicyAcceptance, PolicyAcknowledgementAssignment
        policy = await self.db.get(CompanyPolicyDocument, policy_id)
        from sqlalchemy.orm import selectinload
        employee = (await self.db.execute(
            select(Employee).options(selectinload(Employee.user)).where(Employee.id == employee_id)
        )).scalar_one_or_none()
        if policy is None or employee is None or policy.company_id != employee.company_id:
            raise LookupError("Policy or employee not found")
        if policy.status != "PUBLISHED":
            raise ValueError("Only a published policy can be acknowledged")
        if user_id is not None and employee.user_id != user_id:
            raise PermissionError("You may acknowledge only for your own employee profile")
        if not self.employee_matches(policy, employee):
            raise PermissionError("This policy is not targeted to the employee")
        if not digital_signature.strip():
            raise ValueError("digital_signature is required")
        existing = (await self.db.execute(select(EmployeePolicyAcceptance).where(
            EmployeePolicyAcceptance.policy_document_id == policy.id,
            EmployeePolicyAcceptance.employee_id == employee.id,
        ))).scalar_one_or_none()
        assignment = (await self.db.execute(select(PolicyAcknowledgementAssignment).where(
            PolicyAcknowledgementAssignment.policy_document_id == policy.id,
            PolicyAcknowledgementAssignment.employee_id == employee.id,
        ))).scalar_one_or_none()
        if existing:
            return existing
        accepted_at = datetime.now(UTC)
        canonical = "|".join((
            str(policy.id), str(employee.id), policy.version_number,
            accepted_at.isoformat(), digital_signature.strip(),
        ))
        acceptance = EmployeePolicyAcceptance(
            id=uuid.uuid4(), employee_id=employee.id, policy_document_id=policy.id,
            policy_name=policy.title, policy_version=policy.version_number,
            accepted_at=accepted_at, ip_address=ip_address, user_agent=(user_agent or "")[:500] or None,
            digital_signature=digital_signature.strip(),
            signature_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(), request_id=request_id,
        )
        self.db.add(acceptance)
        await self.db.flush()
        if assignment:
            assignment.status = "ACKNOWLEDGED"
            assignment.acceptance_id = acceptance.id
        await self.db.commit()
        return acceptance

    @staticmethod
    def acknowledgement_proof(acceptance) -> dict[str, Any]:
        import hashlib
        from datetime import UTC
        accepted_at = acceptance.accepted_at
        accepted_at = accepted_at.replace(tzinfo=UTC) if accepted_at.tzinfo is None else accepted_at.astimezone(UTC)
        canonical = "|".join((
            str(acceptance.policy_document_id), str(acceptance.employee_id), acceptance.policy_version,
            accepted_at.isoformat(), acceptance.digital_signature.strip(),
        ))
        calculated = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return {
            "policy_document_id": str(acceptance.policy_document_id),
            "employee_id": str(acceptance.employee_id), "version": acceptance.policy_version,
            "acknowledged_at": acceptance.accepted_at.isoformat(), "ip_address": acceptance.ip_address,
            "user_agent": acceptance.user_agent, "signature_hash": acceptance.signature_hash,
            "hash_algorithm": "SHA256", "verified": secrets_compare(calculated, acceptance.signature_hash),
        }

    async def pending(self, *, company_id: uuid.UUID, employee_id: uuid.UUID | None = None):
        from app.models.employee_policy_acceptance import PolicyAcknowledgementAssignment
        stmt = select(PolicyAcknowledgementAssignment, CompanyPolicyDocument).join(
            CompanyPolicyDocument, CompanyPolicyDocument.id == PolicyAcknowledgementAssignment.policy_document_id,
        ).where(
            PolicyAcknowledgementAssignment.company_id == company_id,
            PolicyAcknowledgementAssignment.status == "PENDING",
        )
        if employee_id:
            stmt = stmt.where(PolicyAcknowledgementAssignment.employee_id == employee_id)
        return (await self.db.execute(stmt)).all()

    async def trigger_reminders(self, *, company_id: uuid.UUID, now=None) -> dict[str, Any]:
        from datetime import UTC, datetime, timedelta
        now = now or datetime.now(UTC)
        now = now.replace(tzinfo=UTC) if now.tzinfo is None else now
        pending = await self.pending(company_id=company_id)
        reminders, escalations = [], []
        from app.models.employee import Employee
        from app.models.user import User
        from app.services import notification_service
        for assignment, policy in pending:
            employee = (await self.db.execute(
                select(Employee).options(selectinload(Employee.user)).where(Employee.id == assignment.employee_id)
            )).scalar_one_or_none()
            assigned_at = assignment.assigned_at
            assigned_at = assigned_at.replace(tzinfo=UTC) if assigned_at.tzinfo is None else assigned_at
            age = now - assigned_at
            if age >= timedelta(days=policy.escalation_after_days) and assignment.escalated_at is None:
                assignment.escalated_at = now
                escalations.append({"assignment_id": str(assignment.id), "employee_id": str(assignment.employee_id), "policy_id": str(policy.id)})
                recipients = []
                if employee and employee.user_id:
                    recipients.append(employee.user_id)
                manager_id = getattr(employee, "reporting_manager_id", None) or getattr(employee, "manager_id", None) if employee else None
                if manager_id:
                    manager = await self.db.get(Employee, manager_id)
                    if manager and manager.user_id:
                        recipients.append(manager.user_id)
                administrators = (await self.db.execute(select(User.id).where(
                    User.company_id == company_id, User.is_active.is_(True),
                    User.role.in_(["admin", "hr_admin", "super_admin"]),
                ).limit(20))).scalars().all()
                recipients.extend(administrators)
                await notification_service.notify(
                    self.db, company_id=company_id, recipient_ids=recipients,
                    type="policy.acknowledgement.escalated", category="system", module="policy",
                    title=f"Policy acknowledgement escalated: {policy.title}",
                    body=f"Acknowledgement of {policy.title} version {policy.version_number} is overdue for {employee.first_name + ' ' + employee.last_name if employee else 'an employee'}.",
                    link="/policies/acknowledgements/pending", priority="high", mandatory=True,
                    entity={"type": "policy", "id": str(policy.id)},
                    dedupe_key=f"policy-escalation:{assignment.id}",
                )
            last = assignment.last_reminder_at or assigned_at
            last = last.replace(tzinfo=UTC) if last.tzinfo is None else last
            if now - last >= timedelta(days=policy.reminder_after_days):
                assignment.last_reminder_at = now
                assignment.reminder_count += 1
                if employee and employee.user_id:
                    await notification_service.notify(
                        self.db, company_id=company_id, recipient_ids=[employee.user_id],
                        type="policy.acknowledgement.reminder", category="system", module="policy",
                        title=f"Policy acknowledgement due: {policy.title}",
                        body=f"Please acknowledge {policy.title} version {policy.version_number} before {assignment.due_at.isoformat()}.",
                        link="/policies/acknowledgements/pending", priority="normal",
                        entity={"type": "policy", "id": str(policy.id)},
                        dedupe_key=f"policy-reminder:{assignment.id}:{assignment.reminder_count}",
                    )
                reminders.append({"assignment_id": str(assignment.id), "employee_id": str(assignment.employee_id), "policy_id": str(policy.id), "reminder_count": assignment.reminder_count})
        await self.db.commit()
        return {"reminders": reminders, "escalations": escalations}


def secrets_compare(left: str, right: str | None) -> bool:
    import hmac
    return bool(right) and hmac.compare_digest(left, right)
