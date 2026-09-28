"""Canonical Document Templates and idempotent seeding helper (Rule 3.7)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document.template import DocumentTemplate

logger = logging.getLogger(__name__)

CANONICAL_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "Offer Letter",
        "description": "Standard Employment Offer Letter with compensation and role details",
        "template_body": (
            "OFFER OF EMPLOYMENT\n\n"
            "Date: {{today}}\n\n"
            "Dear {{employee_name}},\n\n"
            "We are pleased to offer you employment with {{company_name}} in the position of {{designation}} "
            "within the {{department}} department, located at {{location}}.\n\n"
            "Your annual compensation package will be {{salary}} per annum, subject to standard statutory deductions. "
            "You will report directly to {{manager_name}}.\n\n"
            "Your anticipated start date is {{joining_date}}.\n\n"
            "Sincerely,\n"
            "Human Resources Department\n"
            "{{company_name}}"
        ),
    },
    {
        "name": "Non-Disclosure Agreement (NDA)",
        "description": "Standard Employee Non-Disclosure and Confidentiality Agreement",
        "template_body": (
            "NON-DISCLOSURE AND CONFIDENTIALITY AGREEMENT\n\n"
            "This Agreement is entered into on {{today}} by and between {{company_name}} and {{employee_name}} "
            "(Employee ID: {{employee_id}}).\n\n"
            "1. Confidential Information: The Employee agrees to hold all proprietary trade secrets, customer data, "
            "and business processes in strict confidence.\n"
            "2. Non-Disclosure: The Employee shall not disclose any proprietary materials to external parties.\n\n"
            "Employee Signature: {{employee_name}}\n"
            "Date: {{today}}"
        ),
    },
    {
        "name": "Relieving Letter",
        "description": "Standard Employee Relieving and Experience Certificate",
        "template_body": (
            "RELIEVING AND EXPERIENCE CERTIFICATE\n\n"
            "Date: {{today}}\n\n"
            "To Whom It May Concern,\n\n"
            "This is to certify that {{employee_name}} (Employee ID: {{employee_id}}) was employed with {{company_name}} "
            "in the {{department}} department as {{designation}} from {{joining_date}} to {{last_working_day}}.\n\n"
            "During their tenure, they performed their responsibilities with diligence and professionalism. "
            "They have been relieved of all duties effective the close of business hours on {{last_working_day}}.\n\n"
            "We wish them all the best in their future endeavors.\n\n"
            "Sincerely,\n"
            "Authorized Signatory\n"
            "{{company_name}}"
        ),
    },
    {
        "name": "Employee Handbook Acknowledgment",
        "description": "Company Policy Handbook and Code of Conduct Acknowledgment",
        "template_body": (
            "EMPLOYEE HANDBOOK AND CODE OF CONDUCT ACKNOWLEDGMENT\n\n"
            "I, {{employee_name}} (Employee ID: {{employee_id}}), hereby acknowledge that I have received a copy "
            "of the {{company_name}} Employee Handbook (Version {{handbook_version}}).\n\n"
            "I understand that it is my responsibility to read, familiarize myself with, and comply with all policies, "
            "guidelines, and standards of conduct outlined in this handbook.\n\n"
            "Employee Signature: {{employee_name}}\n"
            "Date: {{today}}"
        ),
    },
]


async def seed_canonical_templates_idempotent(session: AsyncSession) -> None:
    """Idempotently seed the four canonical document templates (Offer, NDA, Relieving, Handbook)."""
    try:
        stmt = select(DocumentTemplate.name)
        result = await session.execute(stmt)
        existing_names = set(result.scalars().all())

        system_user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        inserted = 0
        for item in CANONICAL_TEMPLATES:
            if item["name"] not in existing_names:
                tmpl = DocumentTemplate(
                    company_id=None,  # Global canonical templates
                    name=item["name"],
                    description=item["description"],
                    template_body=item["template_body"],
                    created_by=system_user_id,
                )
                session.add(tmpl)
                inserted += 1

        if inserted > 0:
            await session.commit()
            logger.info("Seeded %d canonical document templates.", inserted)
    except Exception as exc:
        await session.rollback()
        logger.warning("Canonical templates seed notice: %s", exc)
