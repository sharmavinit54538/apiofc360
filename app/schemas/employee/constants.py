"""Enums and constant values for Employee schemas."""

GENDER_VALUES = {"MALE", "FEMALE", "OTHER"}
BLOOD_GROUP_VALUES = {"A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"}
MARITAL_STATUS_VALUES = {"SINGLE", "MARRIED", "DIVORCED", "WIDOWED"}
EMPLOYMENT_TYPE_VALUES = {"FULL_TIME", "PART_TIME", "CONTRACT", "INTERN"}
EMPLOYMENT_STATUS_VALUES = {"PROBATION", "CONFIRMED", "NOTICE_PERIOD", "ACTIVE", "INACTIVE", "SUSPENDED", "TERMINATED", "RESIGNED", "ONBOARDING", "ON_LEAVE"}
DOCUMENT_TYPE_VALUES = {"AADHAAR", "PAN", "PASSPORT", "DRIVING_LICENSE"}
ADDRESS_TYPE_VALUES = {"CURRENT", "PERMANENT"}
PROFICIENCY_VALUES = {"BEGINNER", "INTERMEDIATE", "EXPERT"}
ACCOUNT_TYPE_VALUES = {"SAVINGS", "CURRENT"}
EMPLOYEE_STATUS_VALUES = {
    "DRAFT", "CREATED", "INVITATION_SENT", "EMAIL_VERIFIED",
    "PASSWORD_CREATED", "ONBOARDING_PENDING", "DOCUMENT_PENDING",
    "UNDER_VERIFICATION", "ACTIVE", "INACTIVE", "TERMINATED",
    "PROBATION", "NOTICE_PERIOD", "SUSPENDED", "RESIGNED", "RETIRED",
    "LEAVE_OF_ABSENCE", "ON_LEAVE", "ONBOARDING", "PENDING", "CONFIRMED",
}
ONBOARDING_STEP_STATUS_VALUES = {"PENDING", "SUBMITTED", "VERIFIED", "REJECTED"}
ROLE_VALUES = {"employee", "manager", "admin", "ceo", "cfo", "cto", "coo", "cmo", "clo", "ciso", "cio"}

VERIFICATION_STATUS_VALUES = {
    "PENDING_ADMIN_CREATED", "PENDING_SELF_ONBOARDING", "VERIFIED", "CERTIFIED",
}

# Allowed metadata keys per role (used for validation in schema)
ROLE_METADATA_KEYS: dict[str, set[str]] = {
    "employee": set(),
    "admin": set(),
    "manager": {
        "budget_authority_limit", "approval_levels",
    },
    "ceo": {
        "board_reporting", "signing_authority", "equity_percentage",
    },
    "cfo": {
        "signing_authority", "financial_systems_access", "audit_committee_member",
    },
    "cto": {
        "tech_stack_oversight", "infra_access_level", "production_deploy_access",
    },
    "coo": {
        "operational_units_managed", "vendor_approval_limit",
    },
    "cmo": {
        "marketing_budget_authority", "brand_approval_rights",
    },
    "clo": {
        "bar_council_number", "legal_jurisdiction", "contract_signing_authority",
    },
    "ciso": {
        "security_clearance_level", "incident_response_authority", "access_to_prod_secrets",
    },
    "cio": {
        "it_infra_ownership", "data_governance_authority", "system_admin_access",
    },
}
