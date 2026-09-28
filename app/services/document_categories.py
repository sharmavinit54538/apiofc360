"""Canonical document categories definition - Single Source of Truth."""

from __future__ import annotations

import logging
from typing import Any
import uuid
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

CANONICAL_CATEGORIES: list[dict[str, Any]] = [
    # Employee Documents
    {"name": "Aadhaar", "code": "AADHAAR", "group": "Employee Documents", "is_company": False},
    {"name": "PAN", "code": "PAN", "group": "Employee Documents", "is_company": False},
    {"name": "Passport", "code": "PASSPORT", "group": "Employee Documents", "is_company": False},
    {"name": "Driving License", "code": "DRIVING_LICENSE", "group": "Employee Documents", "is_company": False},
    {"name": "Voter ID", "code": "VOTER_ID", "group": "Employee Documents", "is_company": False},
    {"name": "Resume", "code": "RESUME", "group": "Employee Documents", "is_company": False},
    {"name": "Photograph", "code": "PHOTOGRAPH", "group": "Employee Documents", "is_company": False},
    {"name": "Bank Passbook", "code": "BANK_PASSBOOK", "group": "Employee Documents", "is_company": False},
    {"name": "Cancelled Cheque", "code": "CANCELLED_CHEQUE", "group": "Employee Documents", "is_company": False},
    {"name": "Medical Certificate", "code": "MEDICAL_CERTIFICATE", "group": "Employee Documents", "is_company": False},
    {"name": "PF Documents", "code": "PF_DOCUMENTS", "group": "Employee Documents", "is_company": False},
    {"name": "ESIC Documents", "code": "ESIC_DOCUMENTS", "group": "Employee Documents", "is_company": False},
    {"name": "Visa", "code": "VISA", "group": "Employee Documents", "is_company": False},
    {"name": "Work Permit", "code": "WORK_PERMIT", "group": "Employee Documents", "is_company": False},
    {"name": "Other", "code": "OTHER_EMPLOYEE", "group": "Employee Documents", "is_company": False},

    # Education
    {"name": "10th Certificate", "code": "10TH_CERTIFICATE", "group": "Education", "is_company": False},
    {"name": "12th Certificate", "code": "12TH_CERTIFICATE", "group": "Education", "is_company": False},
    {"name": "Graduation", "code": "GRADUATION", "group": "Education", "is_company": False},
    {"name": "Post Graduation", "code": "POST_GRADUATION", "group": "Education", "is_company": False},
    {"name": "Certifications", "code": "CERTIFICATIONS", "group": "Education", "is_company": False},
    {"name": "Educational Certificates", "code": "EDU_CERT", "group": "Education", "is_company": False},

    # Employment
    {"name": "Offer Letter", "code": "OFFER_LETTER", "group": "Employment", "is_company": False},
    {"name": "Appointment Letter", "code": "APPT_LETTER", "group": "Employment", "is_company": False},
    {"name": "Employment Contract", "code": "CONTRACT", "group": "Employment", "is_company": False},
    {"name": "Experience Letter", "code": "EXP_LETTER", "group": "Employment", "is_company": False},
    {"name": "Relieving Letter", "code": "RELIEVING_LETTER", "group": "Employment", "is_company": False},
    {"name": "Salary Slip", "code": "SALARY_SLIP", "group": "Employment", "is_company": False},

    # Company Documents
    {"name": "HR Policy", "code": "HR_POLICY", "group": "Company Documents", "is_company": True},
    {"name": "Leave Policy", "code": "LEAVE_POLICY", "group": "Company Documents", "is_company": True},
    {"name": "Payroll Policy", "code": "PAYROLL_POLICY", "group": "Company Documents", "is_company": True},
    {"name": "Code of Conduct", "code": "CODE_OF_CONDUCT", "group": "Company Documents", "is_company": True},
    {"name": "Employee Handbook", "code": "HANDBOOK", "group": "Company Documents", "is_company": True},
    {"name": "Company Handbook", "code": "COMPANY_HANDBOOK", "group": "Company Documents", "is_company": True},
    {"name": "NDA", "code": "NDA", "group": "Company Documents", "is_company": True},
    {"name": "Employment Agreement", "code": "EMPLOYMENT_AGREEMENT", "group": "Company Documents", "is_company": True},
    {"name": "Holiday Calendar", "code": "HOLIDAY_CALENDAR", "group": "Company Documents", "is_company": True},
    {"name": "Compliance Documents", "code": "COMPLIANCE_DOCUMENTS", "group": "Company Documents", "is_company": True},
    {"name": "ISO Documents", "code": "ISO_DOCUMENTS", "group": "Company Documents", "is_company": True},
    {"name": "Audit Reports", "code": "AUDIT_REPORTS", "group": "Company Documents", "is_company": True},
    {"name": "Legal Agreements", "code": "LEGAL_AGREEMENTS", "group": "Company Documents", "is_company": True},
    {"name": "Training Materials", "code": "TRAINING_MATERIALS", "group": "Company Documents", "is_company": True},
    {"name": "Company Forms", "code": "COMPANY_FORMS", "group": "Company Documents", "is_company": True},
    {"name": "Templates", "code": "TEMPLATES", "group": "Company Documents", "is_company": True},
    {"name": "Other", "code": "OTHER_COMPANY", "group": "Company Documents", "is_company": True},
]

# Mapping for legacy codes to groups
LEGACY_CODE_TO_GROUP: dict[str, str] = {
    "employee_docs": "Employee Documents",
    "education": "Education",
    "employment": "Employment",
    "company_docs": "Company Documents",
    "dl": "Employee Documents",
    "other": "Other",
}


async def seed_canonical_categories_idempotent(session: AsyncSession) -> None:
    """Seed or update canonical categories idempotently without deleting or renaming existing rows."""
    from app.models.document.category import DocumentCategory

    # Fetch existing categories
    res = await session.execute(select(DocumentCategory))
    existing_cats = list(res.scalars().all())
    existing_by_code = {c.code.upper(): c for c in existing_cats}

    # 1. Update group for existing categories if group is missing
    for c in existing_cats:
        code_upper = c.code.upper()
        target_group = None
        # Check canonical
        for item in CANONICAL_CATEGORIES:
            if item["code"].upper() == code_upper:
                target_group = item["group"]
                break
        if not target_group:
            target_group = LEGACY_CODE_TO_GROUP.get(c.code.lower(), "Other")
        
        if hasattr(c, "group") and (c.group is None or c.group != target_group):
            c.group = target_group
            session.add(c)

    # 2. Insert missing categories by code
    for item in CANONICAL_CATEGORIES:
        code_upper = item["code"].upper()
        if code_upper not in existing_by_code:
            new_cat = DocumentCategory(
                id=uuid.uuid4(),
                name=item["name"],
                code=item["code"],
                group=item.get("group"),
                is_company=item["is_company"],
            )
            session.add(new_cat)
            existing_by_code[code_upper] = new_cat

    await session.commit()
    logger.info("Canonical categories seeded idempotently.")
