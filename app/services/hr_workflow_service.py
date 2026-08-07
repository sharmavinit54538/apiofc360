"""AI Workflow Automation Engine Service.

Orchestrates multi-agent routing, condition evaluation against json rules,
automated approvals, and AI compliance audit decision runs.
"""

from __future__ import annotations

import logging
import json
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.llm.client import get_llm_client
from app.llm.prompts import PromptLibrary
from app.llm.response_parser import ResponseParser

# Models
from app.models.hr_workflow import (
    HRWorkflowDefinition,
    HRWorkflowInstance,
    HRWorkflowStepInstance,
)
from app.models.user import User

logger = logging.getLogger(__name__)


class HRWorkflowService:
    """Enterprise Workflow automation service."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.llm = get_llm_client()

    async def register_workflow_definition(
        self,
        name: str,
        trigger_event: str,
        rule_criteria: Optional[dict] = None,
    ) -> HRWorkflowDefinition:
        """Create a new trigger rule criteria definition."""
        definition = HRWorkflowDefinition(
            id=uuid.uuid4(),
            name=name,
            trigger_event=trigger_event.upper(),
            rule_criteria=rule_criteria or {},
            is_active=True,
        )
        self.db.add(definition)
        await self.db.commit()
        await self.db.refresh(definition)
        logger.info("Workflow definition registered: %s (Trigger: %s)", definition.name, definition.trigger_event)
        return definition

    async def trigger_event_workflow(
        self,
        event_name: str,
        context_id: uuid.UUID,
        context_data: dict[str, Any],
    ) -> Optional[HRWorkflowInstance]:
        """Initiate workflow instances matching trigger events and generate default steps."""
        # Find active definition
        stmt = select(HRWorkflowDefinition).where(
            HRWorkflowDefinition.trigger_event == event_name.upper(),
            HRWorkflowDefinition.is_active == True
        )
        res = await self.db.execute(stmt)
        definition = res.scalars().first()
        if not definition:
            logger.info("No active workflow definition found for event trigger: %s", event_name)
            return None

        # Rule Engine check: verify if context matches definition criteria
        rule_matched = self._evaluate_rule_criteria(definition.rule_criteria, context_data)
        if not rule_matched:
            logger.info("Context data did not match rule criteria. Skipping workflow instance.")
            return None

        # Create instance
        instance = HRWorkflowInstance(
            id=uuid.uuid4(),
            workflow_definition_id=definition.id,
            context_id=context_id,
            status="RUNNING",
            current_step_order=0,
        )
        self.db.add(instance)
        await self.db.flush()

        # Step 1: Automated AI Policy check
        step1 = HRWorkflowStepInstance(
            id=uuid.uuid4(),
            workflow_instance_id=instance.id,
            step_name="AI Compliance Policy Verification",
            step_order=0,
            status="PENDING",
            decision_recommendation=None,
            decision_justification=None,
        )
        self.db.add(step1)

        # Step 2: Human Reviewer check
        step2 = HRWorkflowStepInstance(
            id=uuid.uuid4(),
            workflow_instance_id=instance.id,
            step_name="Human Manager Review Check",
            step_order=1,
            status="PENDING",
            assigned_to_user_id=None,  # to be assigned
        )
        self.db.add(step2)

        await self.db.commit()
        await self.db.refresh(instance)

        logger.info("Workflow instance triggered: %s", instance.id)

        # Auto-run AI check for the first step
        await self.run_ai_decision_check(step1.id, context_data)
        return instance

    async def evaluate_step_decision(
        self,
        step_id: uuid.UUID,
        action: str,  # APPROVED / REJECTED
        notes: Optional[str] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> bool:
        """Advance approval workflow and transition state of instances."""
        action = action.upper()
        if action not in ("APPROVED", "REJECTED"):
            raise ValueError("Action must be APPROVED or REJECTED.")

        stmt = (
            select(HRWorkflowStepInstance)
            .options(selectinload(HRWorkflowStepInstance.instance).selectinload(HRWorkflowInstance.steps))
            .where(HRWorkflowStepInstance.id == step_id)
        )
        res = await self.db.execute(stmt)
        step = res.scalar_one_or_none()
        if not step:
            return False

        step.status = action
        step.decision_justification = notes or f"Manual decision completed: {action}"
        step.completed_at = datetime.utcnow()
        if user_id:
            step.assigned_to_user_id = user_id
        await self.db.flush()

        instance = step.instance
        if action == "REJECTED":
            # If rejected, immediately fail the entire instance
            instance.status = "FAILED"
        else:
            # Check if there is a next step
            next_step_order = step.step_order + 1
            next_step = None
            for s in instance.steps:
                if s.step_order == next_step_order:
                    next_step = s
                    break

            if next_step:
                instance.current_step_order = next_step_order
            else:
                instance.status = "COMPLETED"

        await self.db.commit()
        return True

    async def run_ai_decision_check(
        self,
        step_id: uuid.UUID,
        context_payload: dict[str, Any],
        model: Optional[str] = None,
    ) -> bool:
        """Call LLM decision engine to verify compliance limits and auto-approve if rules hold."""
        stmt = (
            select(HRWorkflowStepInstance)
            .options(selectinload(HRWorkflowStepInstance.instance).selectinload(HRWorkflowInstance.definition))
            .where(HRWorkflowStepInstance.id == step_id)
        )
        res = await self.db.execute(stmt)
        step = res.scalar_one_or_none()
        if not step:
            return False

        definition = step.instance.definition
        rule_str = json.dumps(definition.rule_criteria, indent=2)
        payload_str = json.dumps(context_payload, indent=2)

        try:
            prompt = PromptLibrary.ai_workflow_decision_user(definition.name, rule_str, payload_str)
            res_text = await self.llm.complete(
                prompt=prompt,
                system=PromptLibrary.AI_WORKFLOW_DECISION_ENGINE,
                model=model,
                json_mode=True,
                temperature=0.1
            )
            decision = ResponseParser.extract_json_object(res_text)
        except Exception as exc:
            logger.error("AI Decision completion failed: %s", exc)
            decision = {
                "recommendation": "REVIEW_REQUIRED",
                "justification": "AI check failed due to client exception. Defaulting to human review."
            }

        rec = decision.get("recommendation", "REVIEW_REQUIRED").upper()
        justification = decision.get("justification", "Reviewed by AI Decision Engine.")

        step.decision_recommendation = rec
        step.decision_justification = justification
        step.completed_at = datetime.utcnow()

        if rec == "AUTO_APPROVE":
            step.status = "APPROVED"
            # Auto-advance instance to next step
            step.instance.current_step_order = step.step_order + 1
        else:
            # Requires human oversight
            step.status = "APPROVED"  # The compliance step itself is checked and complete
            step.instance.current_step_order = step.step_order + 1

        await self.db.commit()
        return True

    # ------------------------------------------------------------------
    # Simple Rule Engine evaluator
    # ------------------------------------------------------------------

    @staticmethod
    def _evaluate_rule_criteria(criteria: dict[str, Any], context: dict[str, Any]) -> bool:
        """Evaluate if context values satisfy criteria rules (e.g. check thresholds)."""
        if not criteria:
            return True

        for key, expected_val in criteria.items():
            if key not in context:
                return False

            actual_val = context[key]
            if isinstance(expected_val, dict):
                # evaluate operators like gt, lt
                for op, val in expected_val.items():
                    if op == "gt" and not (actual_val > val):
                        return False
                    if op == "lt" and not (actual_val < val):
                        return False
                    if op == "eq" and not (actual_val == val):
                        return False
            else:
                if actual_val != expected_val:
                    return False

        return True
