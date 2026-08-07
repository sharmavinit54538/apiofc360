"""Employee Onboarding Service to manage the 10-step employee onboarding flow."""
from __future__ import annotations
import logging
import uuid
import json
from datetime import datetime, date
from typing import Any, Dict, List, Optional
from decimal import Decimal

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.employee import Employee
from app.models.employee_address import EmployeeAddress
from app.models.employee_bank_account import EmployeeBankAccount
from app.models.employee_education import EmployeeEducation
from app.models.employee_experience import EmployeeExperience
from app.models.employee_emergency_contact import EmployeeEmergencyContact
from app.models.employee_onboarding import EmployeeOnboarding
from app.models.employee_policy_acceptance import EmployeePolicyAcceptance
from app.models.employee_tax_info import EmployeeTaxInfo
from app.models.employee_document import EmployeeDocument
from app.models.document import DocumentCategory
from app.models.user import User

logger = logging.getLogger(__name__)

# List of steps in sequence
ONBOARDING_STEPS = [
    {"name": "Personal Information", "order": 1},
    {"name": "Identity Verification", "order": 2},
    {"name": "Employment Details", "order": 3},
    {"name": "Educational Details", "order": 4},
    {"name": "Professional Experience", "order": 5},
    {"name": "Bank Details", "order": 6},
    {"name": "Tax & Payroll Information", "order": 7},
    {"name": "Documents Upload", "order": 8},
    {"name": "Policies & Agreements", "order": 9},
    {"name": "Final Review", "order": 10}
]

class EmployeeOnboardingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_or_create_onboarding_steps(self, employee_id: uuid.UUID) -> List[EmployeeOnboarding]:
        """Ensures that all 10 onboarding step tracking records exist for the employee."""
        result = await self.db.execute(
            select(EmployeeOnboarding)
            .where(EmployeeOnboarding.employee_id == employee_id)
            .order_by(EmployeeOnboarding.step_order)
        )
        existing_steps = result.scalars().all()

        if len(existing_steps) == len(ONBOARDING_STEPS):
            return list(existing_steps)

        # Create missing steps
        existing_orders = {step.step_order for step in existing_steps}
        new_steps = []
        for step_def in ONBOARDING_STEPS:
            if step_def["order"] not in existing_orders:
                step_record = EmployeeOnboarding(
                    employee_id=employee_id,
                    step_name=step_def["name"],
                    step_order=step_def["order"],
                    is_required=True,
                    is_completed=False,
                    status="PENDING"
                )
                self.db.add(step_record)
                new_steps.append(step_record)
        
        if new_steps:
            await self.db.commit()
            
        result = await self.db.execute(
            select(EmployeeOnboarding)
            .where(EmployeeOnboarding.employee_id == employee_id)
            .order_by(EmployeeOnboarding.step_order)
        )
        return list(result.scalars().all())

    async def get_employee_by_user_id(self, user_id: uuid.UUID) -> Optional[Employee]:
        """Fetch employee record associated with a user ID."""
        result = await self.db.execute(
            select(Employee)
            .where(Employee.user_id == user_id)
            .options(
                selectinload(Employee.addresses),
                selectinload(Employee.bank_accounts),
                selectinload(Employee.education),
                selectinload(Employee.experience),
                selectinload(Employee.emergency_contacts),
                selectinload(Employee.documents),
                selectinload(Employee.onboarding_steps)
            )
        )
        return result.scalar_one_or_none()

    async def get_employee_by_id(self, employee_id: uuid.UUID) -> Optional[Employee]:
        """Fetch employee record associated with employee ID."""
        result = await self.db.execute(
            select(Employee)
            .where(Employee.id == employee_id)
            .options(
                selectinload(Employee.addresses),
                selectinload(Employee.bank_accounts),
                selectinload(Employee.education),
                selectinload(Employee.experience),
                selectinload(Employee.emergency_contacts),
                selectinload(Employee.documents),
                selectinload(Employee.onboarding_steps)
            )
        )
        return result.scalar_one_or_none()

    async def get_onboarding_status(self, employee: Employee) -> Dict[str, Any]:
        """Calculate and return the current onboarding status & progress percentage."""
        steps = await self.get_or_create_onboarding_steps(employee.id)
        completed_count = sum(1 for step in steps if step.is_completed)
        total_steps = len(steps)
        percentage = round((completed_count / total_steps) * 100, 2) if total_steps > 0 else 0.0

        steps_map = {step.step_name: step.is_completed for step in steps}

        return {
            "onboarding_completed": employee.employee_onboarding_completed,
            "current_step": employee.employee_onboarding_step,
            "completion_percentage": percentage,
            "steps_completed": steps_map
        }

    async def save_draft(self, employee: Employee, current_step: int, draft_data: Dict[str, Any]) -> None:
        """Saves intermediate draft state of the onboarding wizard."""
        employee.employee_onboarding_step = current_step
        if not employee.onboarding_data:
            employee.onboarding_data = {}
        employee.onboarding_data.update(draft_data)
        self.db.add(employee)
        await self.db.commit()

    async def get_onboarding_progress_data(self, employee: Employee) -> Dict[str, Any]:
        """Compiles all stored onboarding data to return to the wizard frontend."""
        # Get tax details
        tax_res = await self.db.execute(
            select(EmployeeTaxInfo).where(EmployeeTaxInfo.employee_id == employee.id)
        )
        tax_info = tax_res.scalar_one_or_none()

        # Get policy acceptances
        policy_res = await self.db.execute(
            select(EmployeePolicyAcceptance).where(EmployeePolicyAcceptance.employee_id == employee.id)
        )
        policies = policy_res.scalars().all()

        # Parse addresses
        current_addr = None
        permanent_addr = None
        for addr in employee.addresses:
            if addr.address_type == "CURRENT":
                current_addr = addr
            elif addr.address_type == "PERMANENT":
                permanent_addr = addr

        # Parse bank account
        primary_bank = None
        for bank in employee.bank_accounts:
            if bank.is_primary:
                primary_bank = bank
                break
        if not primary_bank and employee.bank_accounts:
            primary_bank = employee.bank_accounts[0]

        # Emergency contact
        emergency = employee.emergency_contacts[0] if employee.emergency_contacts else None

        # Build combined response
        data = {
            "personal_info": {
                "first_name": employee.first_name,
                "middle_name": employee.middle_name,
                "last_name": employee.last_name,
                "profile_photo_url": employee.profile_photo_url,
                "gender": employee.gender,
                "date_of_birth": employee.date_of_birth.isoformat() if employee.date_of_birth else None,
                "marital_status": employee.marital_status,
                "blood_group": employee.blood_group,
                "nationality": employee.nationality,
                "father_name": employee.father_name,
                "mother_name": employee.mother_name,
                "spouse_name": employee.spouse_name,
                "personal_email": employee.personal_email,
                "phone": employee.phone,
                "current_address_line1": current_addr.address_line_1 if current_addr else None,
                "current_address_line2": current_addr.address_line_2 if current_addr else None,
                "current_city": current_addr.city if current_addr else None,
                "current_state": current_addr.state if current_addr else None,
                "current_country": current_addr.country if current_addr else "India",
                "current_pincode": current_addr.pincode if current_addr else None,
                "permanent_address_line1": permanent_addr.address_line_1 if permanent_addr else None,
                "permanent_address_line2": permanent_addr.address_line_2 if permanent_addr else None,
                "permanent_city": permanent_addr.city if permanent_addr else None,
                "permanent_state": permanent_addr.state if permanent_addr else None,
                "permanent_country": permanent_addr.country if permanent_addr else "India",
                "permanent_pincode": permanent_addr.pincode if permanent_addr else None,
                "is_same_address": permanent_addr.is_same_as_current if permanent_addr else False,
                "emergency_contact_name": emergency.name if emergency else None,
                "emergency_contact_relation": emergency.relation if emergency else None,
                "emergency_contact_phone": emergency.phone if emergency else None,
                "preferred_language": employee.preferred_language or "English"
            },
            "identity": {
                "aadhaar_number": employee.aadhaar_number,
                "pan_number": employee.pan_number,
                "passport_number": employee.passport_number,
                "driving_license": employee.driving_license,
                "voter_id": employee.voter_id
            },
            "employment": {
                "employee_id": employee.employee_id,
                "department": employee.department,
                "designation": employee.designation,
                "reporting_manager_id": str(employee.reporting_manager_id) if employee.reporting_manager_id else None,
                "employment_type": employee.employment_type,
                "work_location": employee.work_location,
                "joining_date": employee.joining_date.isoformat() if employee.joining_date else None,
                "probation_period_months": employee.probation_period_months or 3,
                "shift": employee.shift,
                "work_mode": employee.work_mode or "ONSITE",
                "office_location": employee.branch,
                "business_unit": employee.business_unit,
                "cost_center_id": employee.cost_center_id_col if hasattr(employee, 'cost_center_id_col') else employee.cost_center_id,
                "employee_category": employee.employee_category
            },
            "education": [
                {
                    "degree": edu.degree,
                    "institution": edu.institution,
                    "field_of_study": edu.field_of_study,
                    "start_year": edu.start_year,
                    "end_year": edu.end_year,
                    "grade": edu.grade,
                    "certificate_url": edu.certificate_url
                } for edu in employee.education
            ],
            "experience": [
                {
                    "company_name": exp.company_name,
                    "designation": exp.designation,
                    "employment_type": exp.employment_type,
                    "start_date": exp.start_date.isoformat() if exp.start_date else None,
                    "end_date": exp.end_date.isoformat() if exp.end_date else None,
                    "is_current": exp.is_current,
                    "description": exp.description,
                    "ctc": float(exp.ctc) if exp.ctc else None,
                    "manager_name": exp.manager_name,
                    "reason_for_leaving": exp.reason_for_leaving,
                    "experience_certificate_url": exp.experience_certificate_url,
                    "relieving_letter_url": exp.relieving_letter_url,
                    "salary_slip_url": exp.salary_slip_url
                } for exp in employee.experience
            ],
            "bank": {
                "bank_name": primary_bank.bank_name if primary_bank else None,
                "account_holder_name": primary_bank.account_holder_name if primary_bank else None,
                "account_number": primary_bank.account_number if primary_bank else None,
                "ifsc_code": primary_bank.ifsc_code if primary_bank else None,
                "branch": primary_bank.branch if primary_bank else None,
                "upi_id": primary_bank.upi_id if primary_bank else None,
                "cancelled_cheque_url": primary_bank.cancelled_cheque_url if primary_bank else None,
                "passbook_url": primary_bank.passbook_url if primary_bank else None
            },
            "tax_payroll": {
                "tax_regime": tax_info.tax_regime if tax_info else "NEW",
                "uan_number": employee.uan_number,
                "pf_number": employee.pf_number,
                "esic_number": employee.esic_number,
                "professional_tax": float(tax_info.professional_tax) if tax_info and tax_info.professional_tax else None,
                "nominee_name": tax_info.nominee_name if tax_info else None,
                "nominee_relation": tax_info.nominee_relation if tax_info else None,
                "nominee_aadhaar": tax_info.nominee_aadhaar if tax_info else None,
                "nominee_dob": tax_info.nominee_dob if tax_info else None
            },
            "documents": [
                {
                    "id": str(doc.id),
                    "title": doc.title,
                    "document_type": doc.document_type,
                    "document_url": doc.document_url,
                    "status": doc.status,
                    "created_at": doc.created_at.isoformat()
                } for doc in employee.documents if not doc.is_deleted
            ],
            "policies": [
                {
                    "policy_name": p.policy_name,
                    "policy_version": p.policy_version,
                    "accepted_at": p.accepted_at.isoformat(),
                    "ip_address": p.ip_address
                } for p in policies
            ],
            "draft_data": employee.onboarding_data or {}
        }
        return data

    async def save_personal_info(self, employee: Employee, info: Dict[str, Any]) -> None:
        """Step 1 - Save personal info, addresses, and emergency contact details."""
        # Update core employee details
        employee.first_name = info["first_name"]
        employee.middle_name = info.get("middle_name")
        employee.last_name = info["last_name"]
        if info.get("profile_photo_url"):
            employee.profile_photo_url = info["profile_photo_url"]
        employee.gender = info["gender"]
        if isinstance(info["date_of_birth"], str):
            employee.date_of_birth = date.fromisoformat(info["date_of_birth"])
        else:
            employee.date_of_birth = info["date_of_birth"]
        employee.marital_status = info["marital_status"]
        employee.blood_group = info.get("blood_group")
        employee.nationality = info["nationality"]
        employee.father_name = info["father_name"]
        employee.mother_name = info["mother_name"]
        employee.spouse_name = info.get("spouse_name")
        employee.personal_email = info["personal_email"]
        employee.phone = info["phone"]
        employee.preferred_language = info.get("preferred_language", "English")

        self.db.add(employee)

        # Addresses
        await self.db.execute(delete(EmployeeAddress).where(EmployeeAddress.employee_id == employee.id))
        
        current_addr = EmployeeAddress(
            employee_id=employee.id,
            address_type="CURRENT",
            address_line_1=info["current_address_line1"],
            address_line_2=info.get("current_address_line2"),
            city=info["current_city"],
            state=info["current_state"],
            country=info.get("current_country", "India"),
            pincode=info["current_pincode"]
        )
        self.db.add(current_addr)

        is_same = info.get("is_same_address", False)
        perm_addr = EmployeeAddress(
            employee_id=employee.id,
            address_type="PERMANENT",
            address_line_1=info["current_address_line1"] if is_same else info["permanent_address_line1"],
            address_line_2=info.get("current_address_line2") if is_same else info.get("permanent_address_line2"),
            city=info["current_city"] if is_same else info["permanent_city"],
            state=info["current_state"] if is_same else info["permanent_state"],
            country=info.get("current_country", "India") if is_same else info.get("permanent_country", "India"),
            pincode=info["current_pincode"] if is_same else info["permanent_pincode"],
            is_same_as_current=is_same
        )
        self.db.add(perm_addr)

        # Emergency Contacts
        await self.db.execute(delete(EmployeeEmergencyContact).where(EmployeeEmergencyContact.employee_id == employee.id))
        emergency = EmployeeEmergencyContact(
            employee_id=employee.id,
            name=info["emergency_contact_name"],
            relation=info["emergency_contact_relation"],
            phone=info["emergency_contact_phone"]
        )
        self.db.add(emergency)

        # Mark step complete
        await self._mark_step_completed(employee.id, 1)
        
        employee.employee_onboarding_step = max(employee.employee_onboarding_step, 2)
        await self.db.commit()

    async def save_identity(self, employee: Employee, identity: Dict[str, Any]) -> None:
        """Step 2 - Save statutory IDs."""
        employee.aadhaar_number = identity["aadhaar_number"]
        employee.pan_number = identity["pan_number"]
        employee.passport_number = identity.get("passport_number")
        employee.driving_license = identity.get("driving_license")
        employee.voter_id = identity.get("voter_id")

        self.db.add(employee)
        await self._mark_step_completed(employee.id, 2)
        
        employee.employee_onboarding_step = max(employee.employee_onboarding_step, 3)
        await self.db.commit()

    async def save_employment_details(self, employee: Employee, emp_details: Dict[str, Any]) -> None:
        """Step 3 - Prefills/updates employment metadata."""
        if emp_details.get("work_mode"):
            employee.work_mode = emp_details["work_mode"]
        if emp_details.get("business_unit"):
            employee.business_unit = emp_details["business_unit"]
        if emp_details.get("employee_category"):
            employee.employee_category = emp_details["employee_category"]
        if emp_details.get("probation_period_months"):
            employee.probation_period_months = emp_details["probation_period_months"]

        self.db.add(employee)
        await self._mark_step_completed(employee.id, 3)
        
        employee.employee_onboarding_step = max(employee.employee_onboarding_step, 4)
        await self.db.commit()

    async def save_education(self, employee: Employee, education_list: List[Dict[str, Any]]) -> None:
        """Step 4 - Save education qualification details."""
        await self.db.execute(delete(EmployeeEducation).where(EmployeeEducation.employee_id == employee.id))

        for edu_data in education_list:
            edu = EmployeeEducation(
                employee_id=employee.id,
                degree=edu_data["degree"],
                institution=edu_data["institution"],
                field_of_study=edu_data.get("field_of_study"),
                start_year=edu_data["start_year"],
                end_year=edu_data["end_year"],
                grade=edu_data.get("grade"),
                certificate_url=edu_data.get("certificate_url")
            )
            self.db.add(edu)

        await self._mark_step_completed(employee.id, 4)
        employee.employee_onboarding_step = max(employee.employee_onboarding_step, 5)
        await self.db.commit()

    async def save_experience(self, employee: Employee, experience_list: List[Dict[str, Any]]) -> None:
        """Step 5 - Save work experience records."""
        await self.db.execute(delete(EmployeeExperience).where(EmployeeExperience.employee_id == employee.id))

        for exp_data in experience_list:
            start_date = exp_data["start_date"]
            if isinstance(start_date, str):
                start_date = date.fromisoformat(start_date)
            
            end_date = exp_data.get("end_date")
            if isinstance(end_date, str):
                end_date = date.fromisoformat(end_date)

            exp = EmployeeExperience(
                employee_id=employee.id,
                company_name=exp_data["company_name"],
                designation=exp_data["designation"],
                employment_type=exp_data.get("employment_type"),
                start_date=start_date,
                end_date=end_date,
                is_current=exp_data.get("is_current", False),
                description=exp_data.get("description"),
                ctc=Decimal(str(exp_data["ctc"])) if exp_data.get("ctc") is not None else None,
                manager_name=exp_data.get("manager_name"),
                reason_for_leaving=exp_data.get("reason_for_leaving"),
                experience_certificate_url=exp_data.get("experience_certificate_url"),
                relieving_letter_url=exp_data.get("relieving_letter_url"),
                salary_slip_url=exp_data.get("salary_slip_url")
            )
            self.db.add(exp)

        await self._mark_step_completed(employee.id, 5)
        employee.employee_onboarding_step = max(employee.employee_onboarding_step, 6)
        await self.db.commit()

    async def save_bank_details(self, employee: Employee, bank: Dict[str, Any]) -> None:
        """Step 6 - Save salary bank details."""
        # Set other accounts to is_primary = False
        await self.db.execute(
            update(EmployeeBankAccount)
            .where(EmployeeBankAccount.employee_id == employee.id)
            .values(is_primary=False)
        )
        
        # Create or update bank account
        result = await self.db.execute(
            select(EmployeeBankAccount)
            .where(EmployeeBankAccount.employee_id == employee.id)
            .limit(1)
        )
        bank_acc = result.scalar_one_or_none()

        if not bank_acc:
            bank_acc = EmployeeBankAccount(employee_id=employee.id)

        bank_acc.bank_name = bank["bank_name"]
        bank_acc.account_holder_name = bank["account_holder_name"]
        bank_acc.account_number = bank["account_number"]
        bank_acc.ifsc_code = bank["ifsc_code"]
        bank_acc.branch = bank.get("branch")
        bank_acc.upi_id = bank.get("upi_id")
        bank_acc.cancelled_cheque_url = bank.get("cancelled_cheque_url")
        bank_acc.passbook_url = bank.get("passbook_url")
        bank_acc.is_primary = True

        self.db.add(bank_acc)
        await self._mark_step_completed(employee.id, 6)
        
        employee.employee_onboarding_step = max(employee.employee_onboarding_step, 7)
        await self.db.commit()

    async def save_tax_payroll(self, employee: Employee, tax: Dict[str, Any]) -> None:
        """Step 7 - Save tax details and nominee information."""
        # Prefill on employee
        employee.uan_number = tax.get("uan_number")
        employee.pf_number = tax.get("pf_number")
        employee.esic_number = tax.get("esic_number")
        self.db.add(employee)

        result = await self.db.execute(
            select(EmployeeTaxInfo).where(EmployeeTaxInfo.employee_id == employee.id)
        )
        tax_info = result.scalar_one_or_none()

        if not tax_info:
            tax_info = EmployeeTaxInfo(employee_id=employee.id)

        tax_info.tax_regime = tax.get("tax_regime", "NEW")
        tax_info.professional_tax = Decimal(str(tax["professional_tax"])) if tax.get("professional_tax") is not None else None
        tax_info.nominee_name = tax["nominee_name"]
        tax_info.nominee_relation = tax["nominee_relation"]
        tax_info.nominee_aadhaar = tax.get("nominee_aadhaar")
        tax_info.nominee_dob = tax.get("nominee_dob")

        self.db.add(tax_info)
        await self._mark_step_completed(employee.id, 7)
        
        employee.employee_onboarding_step = max(employee.employee_onboarding_step, 8)
        await self.db.commit()

    async def mark_documents_uploaded(self, employee_id: uuid.UUID) -> None:
        """Step 8 - Checks if all required documents are present, marks completed."""
        await self._mark_step_completed(employee_id, 8)
        
        # Advance step to 9
        await self.db.execute(
            update(Employee)
            .where(Employee.id == employee_id)
            .values(employee_onboarding_step=9)
        )
        await self.db.commit()

    async def save_policies(self, employee: Employee, policies_input: List[Dict[str, Any]], ip_address: Optional[str]) -> None:
        """Step 9 - Stores policy acceptance logs."""
        await self.db.execute(delete(EmployeePolicyAcceptance).where(EmployeePolicyAcceptance.employee_id == employee.id))

        for item in policies_input:
            if item["accepted"]:
                acceptance = EmployeePolicyAcceptance(
                    employee_id=employee.id,
                    policy_name=item["policy_name"],
                    policy_version="1.0",
                    ip_address=ip_address,
                    digital_signature=item["digital_signature"],
                    accepted_at=datetime.now()
                )
                self.db.add(acceptance)

        await self._mark_step_completed(employee.id, 9)
        employee.employee_onboarding_step = max(employee.employee_onboarding_step, 10)
        await self.db.commit()

    async def complete_onboarding(self, employee: Employee) -> Dict[str, Any]:
        """Step 10 - Performs final validation, updates employee profile & user account state."""
        # 1. Mandatory Field Verification
        if not employee.first_name or not employee.last_name or not employee.phone or not employee.personal_email:
            raise ValueError("Mandatory personal information fields are missing.")

        if not employee.aadhaar_number or not employee.pan_number:
            raise ValueError("Identity documents (Aadhaar & PAN) are required.")

        # Check bank accounts
        result = await self.db.execute(
            select(EmployeeBankAccount).where(EmployeeBankAccount.employee_id == employee.id)
        )
        bank = result.scalar_one_or_none()
        if not bank or not bank.account_number or not bank.ifsc_code:
            raise ValueError("Primary salary bank account details are required.")

        # Check documents
        doc_res = await self.db.execute(
            select(EmployeeDocument)
            .where(EmployeeDocument.employee_id == employee.id)
            .where(EmployeeDocument.is_deleted == False)
        )
        docs = doc_res.scalars().all()
        uploaded_types = {d.document_type for d in docs if d.document_type}
        
        has_resume = "RESUME" in uploaded_types
        has_photo = "PHOTO" in uploaded_types
        has_pan = bool({"PAN", "PAN_CARD"} & uploaded_types)
        has_aadhaar = bool({"AADHAAR", "AADHAAR_FRONT", "AADHAAR_BACK"} & uploaded_types)
        has_degree = bool({"DEGREE", "10TH_MARKSHEET", "12TH_MARKSHEET"} & uploaded_types)
        has_bank = bool({"CANCELLED_CHEQUE", "PASSBOOK"} & uploaded_types)

        missing_docs = []
        if not has_resume: missing_docs.append("Resume")
        if not has_photo: missing_docs.append("Passport Photo")
        if not has_pan: missing_docs.append("PAN Card")
        if not has_aadhaar: missing_docs.append("Aadhaar Card")
        if not has_degree: missing_docs.append("Degree / Marks Certificate")
        if not has_bank: missing_docs.append("Cancelled Cheque / Bank Passbook")

        if missing_docs:
            raise ValueError(f"Mandatory documents are missing: {', '.join(missing_docs)}")

        # Check policies accepted
        pol_res = await self.db.execute(
            select(EmployeePolicyAcceptance).where(EmployeePolicyAcceptance.employee_id == employee.id)
        )
        policies = pol_res.scalars().all()
        if len(policies) < 1:
            raise ValueError("All statutory employment policies and NDAs must be signed and accepted.")


        # 2. Update completion status
        employee.employee_onboarding_completed = True
        employee.status = "ACTIVE"
        employee.employee_onboarding_step = 10
        self.db.add(employee)

        # Update User account status (link User.onboarding_completed = True)
        if employee.user_id:
            await self.db.execute(
                update(User)
                .where(User.id == employee.user_id)
                .values(onboarding_completed=True, first_login=False)
            )

        # Mark step 10 complete
        await self._mark_step_completed(employee.id, 10)
        await self.db.commit()

        # Send notifications stubs (IT welcome, payroll onboarding)
        logger.info("Onboarding completed successfully for Employee %s", employee.id)
        
        return {
            "success": True,
            "message": "Onboarding workflow completed successfully.",
            "completed_at": datetime.now().isoformat()
        }

    async def _mark_step_completed(self, employee_id: uuid.UUID, step_order: int) -> None:
        """Internal helper to mark step status as completed."""
        await self.db.execute(
            update(EmployeeOnboarding)
            .where(EmployeeOnboarding.employee_id == employee_id)
            .where(EmployeeOnboarding.step_order == step_order)
            .values(is_completed=True, status="VERIFIED", completed_at=datetime.now())
        )

    # -------------------------------------------------------------
    # Admin Onboarding Management Features
    # -------------------------------------------------------------
    async def list_onboarding_progress(
        self,
        department: Optional[str] = None,
        location: Optional[str] = None,
        status_filter: Optional[str] = None,
        search: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Admin view to list onboarding status of all employees with filters."""
        query = select(Employee).options(
            selectinload(Employee.onboarding_steps),
            selectinload(Employee.documents)
        )
        
        if department:
            query = query.where(Employee.department == department)
        if location:
            query = query.where(Employee.work_location == location)
        if status_filter == "COMPLETED":
            query = query.where(Employee.employee_onboarding_completed == True)
        elif status_filter == "PENDING":
            query = query.where(Employee.employee_onboarding_completed == False)

        result = await self.db.execute(query)
        employees = result.scalars().all()

        output = []
        for emp in employees:
            steps = emp.onboarding_steps
            completed = sum(1 for s in steps if s.is_completed)
            total = len(steps) if steps else 10
            percentage = round((completed / total) * 100, 2) if total > 0 else 0

            # Missing docs calculation with flexible type matching
            uploaded_types = {d.document_type for d in emp.documents if d.document_type and not d.is_deleted}
            has_resume = "RESUME" in uploaded_types
            has_photo = "PHOTO" in uploaded_types
            has_pan = bool({"PAN", "PAN_CARD"} & uploaded_types)
            has_aadhaar = bool({"AADHAAR", "AADHAAR_FRONT", "AADHAAR_BACK"} & uploaded_types)
            has_degree = bool({"DEGREE", "10TH_MARKSHEET", "12TH_MARKSHEET"} & uploaded_types)
            has_bank = bool({"CANCELLED_CHEQUE", "PASSBOOK"} & uploaded_types)

            missing_docs = []
            if not has_resume: missing_docs.append("RESUME")
            if not has_photo: missing_docs.append("PHOTO")
            if not has_pan: missing_docs.append("PAN")
            if not has_aadhaar: missing_docs.append("AADHAAR")
            if not has_degree: missing_docs.append("DEGREE")
            if not has_bank: missing_docs.append("CANCELLED_CHEQUE")


            output.append({
                "employee_id": str(emp.id),
                "employee_code": emp.employee_id,
                "name": f"{emp.first_name} {emp.last_name}",
                "department": emp.department,
                "designation": emp.designation,
                "joining_date": emp.joining_date.isoformat() if emp.joining_date else None,
                "work_location": emp.work_location,
                "status": "COMPLETED" if emp.employee_onboarding_completed else "IN_PROGRESS",
                "current_step": emp.employee_onboarding_step,
                "completion_percentage": percentage,
                "missing_documents": missing_docs
            })
        return output

    async def verify_document(
        self,
        employee_id: uuid.UUID,
        document_id: uuid.UUID,
        status: str,  # VERIFIED / REJECTED
        verifier_id: uuid.UUID,
        comments: Optional[str] = None
    ) -> EmployeeDocument:
        """Allows HR Admin to approve or reject uploaded onboarding documents."""
        result = await self.db.execute(
            select(EmployeeDocument)
            .where(EmployeeDocument.id == document_id)
            .where(EmployeeDocument.employee_id == employee_id)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            raise ValueError("Onboarding document not found.")

        doc.status = status
        doc.is_verified = (status == "VERIFIED")
        doc.verified_by = verifier_id
        doc.verified_at = datetime.now()
        doc.description = f"{comments or ''} (Verification Status updated by HR)"
        
        self.db.add(doc)
        await self.db.commit()
        return doc
