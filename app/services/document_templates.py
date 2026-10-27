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
    {
        "name": "Appointment Letter",
        "description": "Canonical appointment letter confirming role, joining and employment terms",
        "template_body": (
            "APPOINTMENT LETTER\n\nDate: {{today}}\n\nDear {{employee_name}},\n\n"
            "We are pleased to appoint you as {{designation}} in the {{department}} department of {{company_name}}, "
            "effective {{joining_date}}. Your work location will be {{location}} and you will report to {{manager_name}}.\n\n"
            "Your annual compensation is {{salary}}, subject to applicable tax and statutory deductions. "
            "Your employment is governed by the company's current policies and applicable law.\n\n"
            "For {{company_name}}\nAuthorized Signatory"
        ),
    },
    {
        "name": "Confirmation Letter",
        "description": "Canonical employment confirmation after successful probation",
        "template_body": (
            "CONFIRMATION OF EMPLOYMENT\n\nDate: {{today}}\n\nDear {{employee_name}},\n\n"
            "We are pleased to confirm your employment with {{company_name}} as {{designation}} in the {{department}} "
            "department, effective {{confirmation_date}}. Your employee ID is {{employee_id}}.\n\n"
            "All other terms and conditions of your appointment remain unchanged.\n\n"
            "For {{company_name}}\nAuthorized Signatory"
        ),
    },
    {
        "name": "Increment Letter",
        "description": "Canonical compensation revision and increment letter",
        "template_body": (
            "COMPENSATION REVISION\n\nDate: {{today}}\n\nDear {{employee_name}},\n\n"
            "In recognition of your contributions, {{company_name}} is pleased to revise your annual compensation "
            "from {{previous_salary}} to {{revised_salary}}, effective {{effective_date}}. "
            "Your designation and other employment terms remain unchanged unless separately communicated.\n\n"
            "For {{company_name}}\nAuthorized Signatory"
        ),
    },
    {
        "name": "Transfer Letter",
        "description": "Canonical department, branch or work-location transfer letter",
        "template_body": (
            "EMPLOYEE TRANSFER\n\nDate: {{today}}\n\nDear {{employee_name}},\n\n"
            "You are hereby transferred from {{previous_location}} to {{new_location}}, and from {{previous_department}} "
            "to {{new_department}}, effective {{effective_date}}. Your designation will be {{new_designation}} "
            "and you will report to {{manager_name}}.\n\nAll other employment terms remain unchanged.\n\n"
            "For {{company_name}}\nAuthorized Signatory"
        ),
    },
    {
        "name": "Experience Letter",
        "description": "Canonical experience certificate with tenure and role",
        "template_body": (
            "EXPERIENCE CERTIFICATE\n\nDate: {{today}}\n\nTo Whom It May Concern,\n\n"
            "This is to certify that {{employee_name}} (Employee ID: {{employee_id}}) was employed with {{company_name}} "
            "as {{designation}} in the {{department}} department from {{joining_date}} to {{last_working_day}}.\n\n"
            "We appreciate their contribution and wish them success in future endeavours.\n\n"
            "For {{company_name}}\nAuthorized Signatory"
        ),
    },
    {
        "name": "Warning Letter",
        "description": "Canonical employee warning letter with issue and corrective action",
        "template_body": (
            "EMPLOYEE WARNING NOTICE\n\nDate: {{today}}\n\nDear {{employee_name}},\n\n"
            "This letter records a formal warning concerning {{warning_reason}} identified on {{incident_date}}. "
            "You are required to complete the following corrective action: {{corrective_action}}.\n\n"
            "Failure to demonstrate the required improvement may result in further disciplinary action in accordance "
            "with company policy and applicable law. You may submit a written response to Human Resources.\n\n"
            "For {{company_name}}\nAuthorized Signatory"
        ),
    },
]


async def seed_canonical_templates_idempotent(session: AsyncSession) -> int:
    """Idempotently seed eight canonical HR letters plus legacy NDA/handbook templates.
    
    Uses legitimate existing admin user if available, or None for global system templates.
    Returns the number of templates inserted.
    """
    try:
        stmt = select(DocumentTemplate.name)
        result = await session.execute(stmt)
        existing_names = set(result.scalars().all())

        # Safely resolve an active administrative user if one exists; otherwise use None for global templates
        system_user_id: uuid.UUID | None = None
        try:
            from app.models.user import User
            user_stmt = select(User.id).where(User.is_active == True).limit(1)  # noqa: E712
            res = await session.execute(user_stmt)
            system_user_id = res.scalar_one_or_none()
        except Exception:
            system_user_id = None

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
        return inserted
    except Exception as exc:
        await session.rollback()
        logger.error("Failed to seed canonical document templates: %s", exc)
        raise
