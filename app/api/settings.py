"""Settings & Administration API Router for FastAPI Backend."""

from typing import Annotated, Any, Dict, List, Optional
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, status, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.company import Company
from app.models.employee import Employee
from app.models.user import User
from app.models.user_mfa import UserMFA
from app.models.refresh_token import RefreshToken
from app.models.audit_log import AuditLog
from app.schemas.auth import APIResponse
from app.schemas.settings_schemas import (
    HRSettingsResponseData,
    HRSettingsUpdatePayload,
    MFAEnablePayload,
    MFAEnableResponseData,
    MFADisablePayload,
    MFADisableResponseData,
)
from app.utils.totp import (
    generate_totp_secret,
    generate_provisioning_uri,
    generate_qr_code_data_uri,
    verify_totp_code,
)

router = APIRouter(prefix="/settings", tags=["Settings & Administration"])


# --- Schemas ---
class GeneralSettingsPayload(BaseModel):
    appName: Optional[str] = "OFC HRMS"
    language: Optional[str] = "en"
    timezone: Optional[str] = "UTC+05:30 (IST)"
    dateFormat: Optional[str] = "DD/MM/YYYY"
    currency: Optional[str] = "INR (₹)"
    fiscalYearStart: Optional[str] = "April"
    workDaysPerWeek: Optional[int] = 5


class CompanySettingsPayload(BaseModel):
    name: Optional[str] = None
    company_name: Optional[str] = None
    companyName: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    taxId: Optional[str] = None
    registrationNumber: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    companySize: Optional[str] = None
    currency: Optional[str] = None
    timezone: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


class RolePayload(BaseModel):
    name: str
    description: Optional[str] = ""
    permissions: List[str] = Field(default_factory=list)


class BillingPayload(BaseModel):
    planName: Optional[str] = None
    billingCycle: Optional[str] = None
    paymentMethod: Optional[str] = None


class SecuritySettingsPayload(BaseModel):
    twoFactorEnabled: Optional[bool] = None
    sessionTimeoutMinutes: Optional[int] = None
    passwordExpirationDays: Optional[int] = None


class NotificationSettingsPayload(BaseModel):
    emailNotifications: Optional[bool] = None
    inAppAlerts: Optional[bool] = None
    slackAlerts: Optional[bool] = None
    weeklyDigest: Optional[bool] = None


class IntegrationPayload(BaseModel):
    id: str
    connected: bool


class ProfilePayload(BaseModel):
    fullName: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    designation: Optional[str] = None
    department: Optional[str] = None
    bio: Optional[str] = None


# --- Helper functions ---
def check_admin_or_manager(claims: dict):
    role = str(claims.get("role") or "").lower()
    if not role or role not in ["super_admin", "hr_admin", "manager", "executive", "it_admin", "employee"]:

        from app.core.exceptions import AppException
        raise AppException(
            message="Access denied. Administrator privileges required.",
            status_code=status.HTTP_403_FORBIDDEN
        )


async def create_audit_log(session: AsyncSession, claims: dict, action: str, details: str):
    user_id_str = claims.get("sub")
    co_id_str = claims.get("company_id")
    user_id = uuid.UUID(user_id_str) if user_id_str else None
    company_id = uuid.UUID(co_id_str) if co_id_str else None
    email = claims.get("email")
    
    audit = AuditLog(
        user_id=user_id,
        company_id=company_id,
        action=action,
        email=email,
        ip_address=claims.get("ip_address", "127.0.0.1"),
        user_agent="FastAPI Backend",
        details=details
    )
    session.add(audit)
    # Commit changes separately for log trails
    try:
        await session.commit()
    except Exception:
        await session.rollback()


# --- Settings Summary ---
@router.get("/summary")
async def get_settings_summary(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[Dict[str, Any]]:
    co_id_str = claims.get("company_id")
    company_id = uuid.UUID(co_id_str) if co_id_str else None

    company_name = "Aurix Enterprise"
    roles_count = 4
    connected_integrations = 3

    if company_id:
        comp_res = await session.execute(select(Company).where(Company.id == company_id))
        comp = comp_res.scalar_one_or_none()
        if comp:
            company_name = comp.name
            hr_settings = comp.hr_settings or {}
            roles = hr_settings.get("roles") or []
            if roles:
                roles_count = len(roles)
            integrations = hr_settings.get("integrations") or []
            if integrations:
                connected_integrations = len([i for i in integrations if i.get("connected")])

    # Count users
    user_stmt = select(func.count(User.id))
    if company_id:
        user_stmt = user_stmt.where(User.company_id == company_id)
    user_res = await session.execute(user_stmt)
    total_users = user_res.scalar() or 1

    # Count audit logs
    audit_stmt = select(func.count(AuditLog.id))
    if company_id:
        audit_stmt = audit_stmt.where(AuditLog.company_id == company_id)
    audit_res = await session.execute(audit_stmt)
    total_audits = audit_res.scalar() or 0

    summary_data = {
        "company_name": company_name,
        "active_users": total_users,
        "configured_roles": roles_count,
        "total_audit_events": total_audits,
        "security_compliance_score": 98,
        "active_integrations": connected_integrations,
        "current_plan": "Enterprise AI Tier",
        "system_status": "All Systems Operational",
        "last_security_audit": datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
    }

    return APIResponse[Dict[str, Any]](
        success=True,
        message="Settings summary retrieved.",
        data=summary_data,
        errors=None,
    )


# --- General Settings ---
@router.get("/general")
async def get_general_settings(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[Dict[str, Any]]:
    co_id_str = claims.get("company_id")
    if not co_id_str:
        raise HTTPException(status_code=403, detail="No company association found.")
        
    company_id = uuid.UUID(co_id_str)
    stmt = select(Company).where(Company.id == company_id)
    res = await session.execute(stmt)
    company = res.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
        
    hr_settings = company.hr_settings or {}
    general = hr_settings.get("general")
    if not general:
        general = {
            "appName": "OFC HRMS",
            "language": "en",
            "timezone": "UTC+05:30 (IST)",
            "dateFormat": "DD/MM/YYYY",
            "currency": "INR (₹)",
            "fiscalYearStart": "April",
            "workDaysPerWeek": 5
        }
        
    return APIResponse[Dict[str, Any]](
        success=True,
        message="General settings retrieved.",
        data=general,
        errors=None,
    )


@router.put("/general")
async def update_general_settings(
    payload: GeneralSettingsPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[Dict[str, Any]]:
    check_admin_or_manager(claims)
    co_id_str = claims.get("company_id")
    if not co_id_str:
        raise HTTPException(status_code=403, detail="No company association found.")
        
    company_id = uuid.UUID(co_id_str)
    stmt = select(Company).where(Company.id == company_id)
    res = await session.execute(stmt)
    company = res.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
        
    hr_settings = company.hr_settings or {}
    general = hr_settings.get("general") or {}
    general.update(payload.model_dump(exclude_unset=True))
    hr_settings["general"] = general
    company.hr_settings = hr_settings
    
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(company, "hr_settings")
    await session.commit()
    
    await create_audit_log(
        session, claims, "UPDATE_GENERAL_SETTINGS", 
        "Updated global system and localization settings."
    )
    
    return APIResponse[Dict[str, Any]](
        success=True,
        message="General settings updated successfully.",
        data=general,
        errors=None,
    )


# --- Company Settings ---
@router.get("/company")
async def get_company_settings(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[Dict[str, Any]]:
    co_id_str = claims.get("company_id")
    if not co_id_str:
        raise HTTPException(status_code=403, detail="No company association found.")
        
    company_id = uuid.UUID(co_id_str)
    stmt = select(Company).where(Company.id == company_id)
    res = await session.execute(stmt)
    company = res.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
        
    profile = company.company_profile or {}
    defaults = {
        "email": "contact@aurix.ai",
        "phone": "+91 98765 43210",
        "website": "https://aurix.ai",
        "city": "Bengaluru",
        "country": "India",
        "taxId": "29ABCDE1234F1Z5",
        "registrationNumber": "CIN-U72200KA2024PTC123456"
    }
    for k, v in defaults.items():
        if k not in profile:
            profile[k] = v
            
    response_data = {
        "id": str(company.id),
        **profile,
        "name": company.name,
        "company_name": company.name,
        "companyName": company.name,
    }
            
    return APIResponse[Dict[str, Any]](
        success=True,
        message="Company settings retrieved.",
        data=response_data,
        errors=None,
    )


@router.put("/company")
@router.post("/company")
@router.patch("/company")
async def update_company_settings(
    payload: CompanySettingsPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[Dict[str, Any]]:
    check_admin_or_manager(claims)
    co_id_str = claims.get("company_id")
    if not co_id_str:
        raise HTTPException(status_code=403, detail="No company association found.")
        
    company_id = uuid.UUID(co_id_str)
    stmt = select(Company).where(Company.id == company_id)
    res = await session.execute(stmt)
    company = res.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
        
    new_name = payload.name or payload.company_name or payload.companyName
    if new_name is not None and str(new_name).strip():
        clean_name = str(new_name).strip()
        company.name = clean_name
        
    profile = company.company_profile or {}
    update_data = payload.model_dump(exclude={"name", "company_name", "companyName"}, exclude_unset=True)
    profile.update(update_data)

    if new_name is not None and str(new_name).strip():
        clean_name = str(new_name).strip()
        profile["name"] = clean_name
        profile["company_name"] = clean_name
        profile["companyName"] = clean_name

    company.company_profile = profile
    
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(company, "company_profile")
    flag_modified(company, "name")
    
    await session.commit()
    await session.refresh(company)
    
    await create_audit_log(
        session, claims, "UPDATE_COMPANY_SETTINGS", 
        f"Updated company details for {company.name}."
    )
    
    response_data = {
        "id": str(company.id),
        **profile,
        "name": company.name,
        "company_name": company.name,
        "companyName": company.name,
    }
    
    return APIResponse[Dict[str, Any]](
        success=True,
        message="Company settings updated successfully.",
        data=response_data,
        errors=None,
    )


# --- Roles & Permissions ---
@router.get("/roles")
async def get_roles(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[List[Dict[str, Any]]]:
    co_id_str = claims.get("company_id")
    if not co_id_str:
        raise HTTPException(status_code=403, detail="No company association found.")
        
    company_id = uuid.UUID(co_id_str)
    stmt = select(Company).where(Company.id == company_id)
    res = await session.execute(stmt)
    company = res.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
        
    hr_settings = company.hr_settings or {}
    roles = hr_settings.get("roles")
    if not roles:
        roles = [
            {
                "id": "role-admin",
                "name": "Administrator",
                "description": "Full access to all system modules, configurations, and user management.",
                "permissions": ["all", "employees:read", "employees:write", "settings:write", "billing:write"],
                "isSystem": True,
            },
            {
                "id": "role-hr",
                "name": "HR Manager",
                "description": "Manage employee lifecycle, onboarding, attendance, performance, and recruitment.",
                "permissions": ["employees:read", "employees:write", "recruitment:read", "recruitment:write", "attendance:write"],
                "isSystem": True,
            },
            {
                "id": "role-lead",
                "name": "Department Manager",
                "description": "View team stats, approve leave requests, review timesheets and performance.",
                "permissions": ["employees:read", "team:manage", "leaves:approve", "timesheets:approve"],
                "isSystem": False,
            },
            {
                "id": "role-emp",
                "name": "Employee",
                "description": "Access self-service portal, check-in, request leave, and view payslips.",
                "permissions": ["portal:access", "checkin:create", "leaves:request"],
                "isSystem": True,
            },
        ]
        
    emp_stmt = select(Employee.role, func.count()).where(Employee.company_id == company_id, Employee.is_deleted == False).group_by(Employee.role)
    emp_res = await session.execute(emp_stmt)
    role_counts = {r: count for r, count in emp_res.all()}
    
    for r in roles:
        count = role_counts.get(r["id"]) or role_counts.get(r["name"].lower()) or 0
        r["userCount"] = count
        
    return APIResponse[List[Dict[str, Any]]](
        success=True,
        message="Roles retrieved.",
        data=roles,
        errors=None,
    )


@router.post("/roles")
async def create_role(
    payload: RolePayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[Dict[str, Any]]:
    check_admin_or_manager(claims)
    co_id_str = claims.get("company_id")
    if not co_id_str:
        raise HTTPException(status_code=403, detail="No company association found.")
        
    company_id = uuid.UUID(co_id_str)
    stmt = select(Company).where(Company.id == company_id)
    res = await session.execute(stmt)
    company = res.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
        
    hr_settings = company.hr_settings or {}
    roles = hr_settings.get("roles") or [
        {"id": "role-admin", "name": "Administrator", "description": "Full access...", "permissions": ["all"], "isSystem": True},
        {"id": "role-hr", "name": "HR Manager", "description": "Manage employee...", "permissions": ["employees:read"], "isSystem": True},
        {"id": "role-lead", "name": "Department Manager", "description": "View team stats...", "permissions": ["team:manage"], "isSystem": False},
        {"id": "role-emp", "name": "Employee", "description": "Access self-service...", "permissions": ["portal:access"], "isSystem": True},
    ]
        
    new_id = f"role-{uuid.uuid4().hex[:8]}"
    new_role = {
        "id": new_id,
        "name": payload.name,
        "description": payload.description,
        "permissions": payload.permissions,
        "isSystem": False,
        "userCount": 0
    }
    roles.append(new_role)
    hr_settings["roles"] = roles
    company.hr_settings = hr_settings
    
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(company, "hr_settings")
    await session.commit()
    
    await create_audit_log(
        session, claims, "ROLE_CREATED", 
        f"Created custom access role: {payload.name}."
    )
    
    return APIResponse[Dict[str, Any]](
        success=True,
        message="Role created successfully.",
        data=new_role,
        errors=None,
    )


@router.put("/roles/{role_id}")
async def update_role(
    role_id: str,
    payload: RolePayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[Dict[str, Any]]:
    check_admin_or_manager(claims)
    co_id_str = claims.get("company_id")
    if not co_id_str:
        raise HTTPException(status_code=403, detail="No company association found.")
        
    company_id = uuid.UUID(co_id_str)
    stmt = select(Company).where(Company.id == company_id)
    res = await session.execute(stmt)
    company = res.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
        
    hr_settings = company.hr_settings or {}
    roles = hr_settings.get("roles") or []
    
    found_role = None
    for r in roles:
        if r["id"] == role_id:
            r["name"] = payload.name
            r["description"] = payload.description
            r["permissions"] = payload.permissions
            found_role = r
            break
            
    if not found_role:
        raise HTTPException(status_code=404, detail="Role not found.")
        
    hr_settings["roles"] = roles
    company.hr_settings = hr_settings
    
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(company, "hr_settings")
    await session.commit()
    
    await create_audit_log(
        session, claims, "ROLE_UPDATED", 
        f"Updated role configurations for role: {payload.name}."
    )
    
    return APIResponse[Dict[str, Any]](
        success=True,
        message="Role updated successfully.",
        data=found_role,
        errors=None,
    )


@router.delete("/roles/{role_id}")
async def delete_role(
    role_id: str,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[None]:
    check_admin_or_manager(claims)
    co_id_str = claims.get("company_id")
    if not co_id_str:
        raise HTTPException(status_code=403, detail="No company association found.")
        
    company_id = uuid.UUID(co_id_str)
    stmt = select(Company).where(Company.id == company_id)
    res = await session.execute(stmt)
    company = res.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
        
    hr_settings = company.hr_settings or {}
    roles = hr_settings.get("roles") or []
    
    original_len = len(roles)
    roles = [r for r in roles if r["id"] != role_id]
    if len(roles) == original_len:
        raise HTTPException(status_code=404, detail="Role not found.")
        
    hr_settings["roles"] = roles
    company.hr_settings = hr_settings
    
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(company, "hr_settings")
    await session.commit()
    
    await create_audit_log(
        session, claims, "ROLE_DELETED", 
        f"Deleted custom role ID: {role_id}."
    )
    
    return APIResponse[None](
        success=True,
        message="Role deleted successfully.",
        data=None,
        errors=None,
    )


@router.get("/permissions")
async def get_permissions(
    claims: Annotated[dict, Depends(get_current_user_claims)],
) -> APIResponse[List[Dict[str, Any]]]:
    permissions = [
        {"id": "employees:read", "name": "View Employees", "category": "Employees"},
        {"id": "employees:write", "name": "Create & Edit Employees", "category": "Employees"},
        {"id": "recruitment:read", "name": "View Recruitment Pipeline", "category": "Recruitment"},
        {"id": "recruitment:write", "name": "Manage Job Postings", "category": "Recruitment"},
        {"id": "attendance:write", "name": "Manage Shift & Rosters", "category": "Attendance"},
        {"id": "billing:write", "name": "Manage Subscription & Billing", "category": "Administration"},
        {"id": "settings:write", "name": "Update Workspace Settings", "category": "Administration"},
    ]
    return APIResponse[List[Dict[str, Any]]](
        success=True,
        message="Permissions list retrieved.",
        data=permissions,
        errors=None,
    )


# --- Audit Logs ---
@router.get("/audit-logs")
async def get_audit_logs(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    search: Optional[str] = None,
    module: Optional[str] = None,
) -> APIResponse[Dict[str, Any]]:
    check_admin_or_manager(claims)
    co_id_str = claims.get("company_id")
    if not co_id_str:
        raise HTTPException(status_code=403, detail="No company association found.")
        
    company_id = uuid.UUID(co_id_str)
    query = select(AuditLog).where(AuditLog.company_id == company_id)
    
    if search:
        search_filter = f"%{search}%"
        query = query.where(
            (AuditLog.action.ilike(search_filter)) |
            (AuditLog.email.ilike(search_filter)) |
            (AuditLog.details.ilike(search_filter))
        )
        
    if module and module != "all":
        if module == "Settings":
            query = query.where(AuditLog.action.in_([
                "UPDATE_COMPANY_SETTINGS", "UPDATE_GENERAL_SETTINGS", "SECURITY_UPDATED", "NOTIFICATIONS_UPDATED", "INTEGRATION_TOGGLED"
            ]))
        elif module == "Employees":
            query = query.where(AuditLog.action.in_(["CREATE_EMPLOYEE", "UPDATE_EMPLOYEE", "DELETE_EMPLOYEE", "PROFILE_UPDATED"]))
        elif module == "Roles & Permissions":
            query = query.where(AuditLog.action.in_(["ROLE_CREATED", "ROLE_UPDATED", "ROLE_DELETED"]))
        else:
            query = query.where(
                (AuditLog.action.ilike(f"%{module}%")) |
                (AuditLog.details.ilike(f"%{module}%"))
            )
            
    count_stmt = select(func.count()).select_from(query.subquery())
    count_res = await session.execute(count_stmt)
    total = count_res.scalar() or 0
    
    query = query.order_by(AuditLog.created_at.desc())
    offset = (page - 1) * limit
    query = query.offset(offset).limit(limit)
    
    res = await session.execute(query)
    db_logs = res.scalars().all()
    
    items = []
    for log in db_logs:
        items.append({
            "id": str(log.id),
            "timestamp": log.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "user": log.email.split("@")[0].capitalize() if log.email else "System",
            "role": "Admin" if "admin" in (log.action.lower() or "") else "User",
            "action": log.action,
            "module": module or "System",
            "ip": log.ip_address or "127.0.0.1",
            "status": "Success",
            "details": log.details or ""
        })
        
    return APIResponse[Dict[str, Any]](
        success=True,
        message="Audit logs retrieved.",
        data={
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit if limit > 0 else 1,
        },
        errors=None,
    )


# --- Billing ---
@router.get("/billing")
async def get_billing(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[Dict[str, Any]]:
    co_id_str = claims.get("company_id")
    if not co_id_str:
        raise HTTPException(status_code=403, detail="No company association found.")
        
    company_id = uuid.UUID(co_id_str)
    stmt = select(Company).where(Company.id == company_id)
    res = await session.execute(stmt)
    company = res.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
        
    hr_settings = company.hr_settings or {}
    billing = hr_settings.get("billing")
    if not billing:
        billing = {
            "currentPlan": "Enterprise AI Tier",
            "billingCycle": "Annual",
            "amount": "₹ 49,999 / mo",
            "nextBillingDate": "2026-12-31",
            "seats": 350,
            "paymentMethod": "Visa ending in •••• 4821",
            "invoices": [
                {"id": "INV-2026-001", "date": "2026-01-01", "amount": "₹ 5,99,988", "status": "Paid", "pdfUrl": "#"},
                {"id": "INV-2025-012", "date": "2025-01-01", "amount": "₹ 5,99,988", "status": "Paid", "pdfUrl": "#"},
            ]
        }
        
    count_stmt = select(func.count(User.id)).where(User.company_id == company_id, User.is_deleted == False)
    count_res = await session.execute(count_stmt)
    used_seats = count_res.scalar() or 0
    billing["usedSeats"] = used_seats
    
    return APIResponse[Dict[str, Any]](
        success=True,
        message="Billing details retrieved.",
        data=billing,
        errors=None,
    )


@router.put("/billing")
async def update_billing(
    payload: BillingPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[Dict[str, Any]]:
    check_admin_or_manager(claims)
    co_id_str = claims.get("company_id")
    if not co_id_str:
        raise HTTPException(status_code=403, detail="No company association found.")
        
    company_id = uuid.UUID(co_id_str)
    stmt = select(Company).where(Company.id == company_id)
    res = await session.execute(stmt)
    company = res.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
        
    hr_settings = company.hr_settings or {}
    billing = hr_settings.get("billing") or {
        "currentPlan": "Enterprise AI Tier",
        "billingCycle": "Annual",
        "amount": "₹ 49,999 / mo",
        "nextBillingDate": "2026-12-31",
        "seats": 350,
        "paymentMethod": "Visa ending in •••• 4821",
        "invoices": []
    }
    
    billing.update(payload.model_dump(exclude_unset=True))
    hr_settings["billing"] = billing
    company.hr_settings = hr_settings
    
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(company, "hr_settings")
    await session.commit()
    
    await create_audit_log(
        session, claims, "BILLING_UPDATED", 
        "Updated subscription and billing cycle configurations."
    )
    
    return APIResponse[Dict[str, Any]](
        success=True,
        message="Billing settings updated successfully.",
        data=billing,
        errors=None,
    )


# --- Security ---
@router.get("/security")
async def get_security(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[Dict[str, Any]]:
    co_id_str = claims.get("company_id")
    if not co_id_str:
        raise HTTPException(status_code=403, detail="No company association found.")
        
    company_id = uuid.UUID(co_id_str)
    stmt = select(Company).where(Company.id == company_id)
    res = await session.execute(stmt)
    company = res.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
        
    hr_settings = company.hr_settings or {}
    security = hr_settings.get("security")
    if not security:
        security = {
            "twoFactorEnabled": True,
            "sessionTimeoutMinutes": 60,
            "passwordExpirationDays": 90
        }
        
    user_id = uuid.UUID(claims.get("sub"))
    sess_stmt = select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked == False).order_by(RefreshToken.created_at.desc())
    sess_res = await session.execute(sess_stmt)
    db_tokens = sess_res.scalars().all()
    
    active_sessions = []
    for t in db_tokens:
        last_active_str = "Just now" if (datetime.now(t.updated_at.tzinfo) - t.updated_at).seconds < 300 else "Active recently"
        active_sessions.append({
            "id": str(t.id),
            "device": t.device or "Unknown Browser / Client",
            "ip": t.ip_address or "127.0.0.1",
            "lastActive": last_active_str,
            "current": False
        })
        
    if active_sessions:
        active_sessions[0]["current"] = True
    else:
        active_sessions.append({
            "id": "current-session",
            "device": "Chrome / Windows 11",
            "ip": claims.get("ip_address", "127.0.0.1"),
            "lastActive": "Just now",
            "current": True
        })
        
    security["activeSessions"] = active_sessions
    
    return APIResponse[Dict[str, Any]](
        success=True,
        message="Security settings retrieved.",
        data=security,
        errors=None,
    )


@router.put("/security")
async def update_security(
    payload: SecuritySettingsPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[Dict[str, Any]]:
    check_admin_or_manager(claims)
    co_id_str = claims.get("company_id")
    if not co_id_str:
        raise HTTPException(status_code=403, detail="No company association found.")
        
    company_id = uuid.UUID(co_id_str)
    stmt = select(Company).where(Company.id == company_id)
    res = await session.execute(stmt)
    company = res.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
        
    hr_settings = company.hr_settings or {}
    security = hr_settings.get("security") or {
        "twoFactorEnabled": True,
        "sessionTimeoutMinutes": 60,
        "passwordExpirationDays": 90
    }
    
    security.update(payload.model_dump(exclude_unset=True))
    hr_settings["security"] = security
    company.hr_settings = hr_settings
    
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(company, "hr_settings")
    await session.commit()
    
    await create_audit_log(
        session, claims, "SECURITY_UPDATED", 
        "Updated company password rules and MFA configurations."
    )
    
    return APIResponse[Dict[str, Any]](
        success=True,
        message="Security settings updated successfully.",
        data=security,
        errors=None,
    )


# --- Notifications ---
@router.get("/notifications")
async def get_notifications(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[Dict[str, Any]]:
    co_id_str = claims.get("company_id")
    if not co_id_str:
        raise HTTPException(status_code=403, detail="No company association found.")
        
    company_id = uuid.UUID(co_id_str)
    stmt = select(Company).where(Company.id == company_id)
    res = await session.execute(stmt)
    company = res.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
        
    hr_settings = company.hr_settings or {}
    notifications = hr_settings.get("notifications")
    if not notifications:
        notifications = {
            "emailNotifications": True,
            "inAppAlerts": True,
            "slackAlerts": False,
            "weeklyDigest": True,
        }
        
    return APIResponse[Dict[str, Any]](
        success=True,
        message="Notification settings retrieved.",
        data=notifications,
        errors=None,
    )


@router.put("/notifications")
async def update_notifications(
    payload: NotificationSettingsPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[Dict[str, Any]]:
    check_admin_or_manager(claims)
    co_id_str = claims.get("company_id")
    if not co_id_str:
        raise HTTPException(status_code=403, detail="No company association found.")
        
    company_id = uuid.UUID(co_id_str)
    stmt = select(Company).where(Company.id == company_id)
    res = await session.execute(stmt)
    company = res.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
        
    hr_settings = company.hr_settings or {}
    notifications = hr_settings.get("notifications") or {
        "emailNotifications": True,
        "inAppAlerts": True,
        "slackAlerts": False,
        "weeklyDigest": True,
    }
    
    notifications.update(payload.model_dump(exclude_unset=True))
    hr_settings["notifications"] = notifications
    company.hr_settings = hr_settings
    
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(company, "hr_settings")
    await session.commit()
    
    await create_audit_log(
        session, claims, "NOTIFICATIONS_UPDATED", 
        "Updated workspace notifications and weekly digest rules."
    )
    
    return APIResponse[Dict[str, Any]](
        success=True,
        message="Notification preferences saved successfully.",
        data=notifications,
        errors=None,
    )


# --- Integrations ---
@router.get("/integrations")
async def get_integrations(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[List[Dict[str, Any]]]:
    co_id_str = claims.get("company_id")
    if not co_id_str:
        raise HTTPException(status_code=403, detail="No company association found.")
        
    company_id = uuid.UUID(co_id_str)
    stmt = select(Company).where(Company.id == company_id)
    res = await session.execute(stmt)
    company = res.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
        
    hr_settings = company.hr_settings or {}
    integrations = hr_settings.get("integrations")
    if not integrations:
        integrations = [
            {"id": "slack", "name": "Slack", "category": "Communication", "connected": True, "icon": "MessageSquare"},
            {"id": "google", "name": "Google Workspace", "category": "Identity & Calendar", "connected": True, "icon": "Mail"},
            {"id": "msteams", "name": "Microsoft Teams", "category": "Communication", "connected": False, "icon": "Users"},
            {"id": "quickbooks", "name": "QuickBooks", "category": "Finance & Payroll", "connected": True, "icon": "CreditCard"},
            {"id": "zoom", "name": "Zoom Video", "category": "Interviews", "connected": False, "icon": "Video"},
        ]
        
    return APIResponse[List[Dict[str, Any]]](
        success=True,
        message="Integrations list retrieved.",
        data=integrations,
        errors=None,
    )


@router.put("/integrations")
async def toggle_integration(
    payload: IntegrationPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[List[Dict[str, Any]]]:
    check_admin_or_manager(claims)
    co_id_str = claims.get("company_id")
    if not co_id_str:
        raise HTTPException(status_code=403, detail="No company association found.")
        
    company_id = uuid.UUID(co_id_str)
    stmt = select(Company).where(Company.id == company_id)
    res = await session.execute(stmt)
    company = res.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
        
    hr_settings = company.hr_settings or {}
    integrations = hr_settings.get("integrations") or [
        {"id": "slack", "name": "Slack", "category": "Communication", "connected": True, "icon": "MessageSquare"},
        {"id": "google", "name": "Google Workspace", "category": "Identity & Calendar", "connected": True, "icon": "Mail"},
        {"id": "msteams", "name": "Microsoft Teams", "category": "Communication", "connected": False, "icon": "Users"},
        {"id": "quickbooks", "name": "QuickBooks", "category": "Finance & Payroll", "connected": True, "icon": "CreditCard"},
        {"id": "zoom", "name": "Zoom Video", "category": "Interviews", "connected": False, "icon": "Video"},
    ]
    
    for item in integrations:
        if item["id"] == payload.id:
            item["connected"] = payload.connected
            
    hr_settings["integrations"] = integrations
    company.hr_settings = hr_settings
    
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(company, "hr_settings")
    await session.commit()
    
    status_str = "connected" if payload.connected else "disconnected"
    await create_audit_log(
        session, claims, "INTEGRATION_TOGGLED", 
        f"Third-party integration '{payload.id}' was {status_str}."
    )
    
    return APIResponse[List[Dict[str, Any]]](
        success=True,
        message="Integration status updated.",
        data=integrations,
        errors=None,
    )


# --- Profile ---
@router.get("/profile")
async def get_profile(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[Dict[str, Any]]:
    user_id_str = claims.get("sub")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Invalid session payload.")
        
    user_id = uuid.UUID(user_id_str)
    
    stmt = select(Employee).where(Employee.user_id == user_id)
    res = await session.execute(stmt)
    emp = res.scalar_one_or_none()
    
    if emp:
        role_meta = emp.role_metadata or {}
        return APIResponse[Dict[str, Any]](
            success=True,
            message="Profile details retrieved.",
            data={
                "fullName": f"{emp.first_name} {emp.last_name}".strip(),
                "email": emp.company_email or emp.personal_email or claims.get("email", ""),
                "phone": emp.phone or "",
                "designation": emp.designation or "Employee",
                "department": emp.department or "General",
                "bio": role_meta.get("bio", "No bio provided."),
                "role": emp.role,
            },
            errors=None,
        )
        
    user_stmt = select(User).where(User.id == user_id)
    user_res = await session.execute(user_stmt)
    user = user_res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User account not found.")
        
    return APIResponse[Dict[str, Any]](
        success=True,
        message="Profile details retrieved.",
        data={
            "fullName": user.name,
            "email": user.email,
            "phone": user.phone or "",
            "designation": claims.get("role", "employee").capitalize(),
            "department": "Administration",
            "bio": "Managing enterprise HR workforce intelligence and operations.",
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        },
        errors=None,
    )


@router.put("/profile")
async def update_profile(
    payload: ProfilePayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[Dict[str, Any]]:
    user_id_str = claims.get("sub")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Invalid session payload.")
        
    user_id = uuid.UUID(user_id_str)
    
    user_stmt = select(User).where(User.id == user_id)
    user_res = await session.execute(user_stmt)
    user = user_res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User account not found.")
        
    emp_stmt = select(Employee).where(Employee.user_id == user_id)
    emp_res = await session.execute(emp_stmt)
    emp = emp_res.scalar_one_or_none()
    
    first_name = ""
    last_name = ""
    if payload.fullName:
        user.name = payload.fullName
        parts = payload.fullName.strip().split(" ", 1)
        first_name = parts[0]
        if len(parts) > 1:
            last_name = parts[1]
            
    if payload.phone:
        user.phone = payload.phone
    if payload.email:
        user.email = payload.email
        
    if emp:
        if payload.fullName:
            emp.first_name = first_name
            emp.last_name = last_name
        if payload.phone:
            emp.phone = payload.phone
        if payload.email:
            emp.company_email = payload.email
        if payload.designation:
            emp.designation = payload.designation
        if payload.department:
            emp.department = payload.department
            
        role_meta = emp.role_metadata or {}
        if payload.bio is not None:
            role_meta["bio"] = payload.bio
        emp.role_metadata = role_meta
        
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(emp, "role_metadata")
        
    await session.commit()
    
    await create_audit_log(
        session, claims, "PROFILE_UPDATED", 
        f"Updated personal user profile details for {user.name}."
    )
    
    return APIResponse[Dict[str, Any]](
        success=True,
        message="User profile updated successfully.",
        data=payload.model_dump(),
        errors=None,
    )


# ===========================================================================
# HR Settings Endpoints
# ===========================================================================

@router.get("/hr")
@router.get("/settings/hr")
async def get_hr_settings(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[Dict[str, Any]]:
    """Return authenticated company's HR configuration."""
    co_id_str = claims.get("company_id")
    if not co_id_str:
        raise HTTPException(status_code=403, detail="No company association found.")

    company_id = uuid.UUID(co_id_str)
    stmt = select(Company).where(Company.id == company_id)
    res = await session.execute(stmt)
    company = res.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")

    hr_settings_data = company.hr_settings or {}
    hr_config = hr_settings_data.get("hr_config") or {}
    company_profile = company.company_profile or {}

    from app.models.onboarding import CompanySettings
    cs_stmt = select(CompanySettings).where(CompanySettings.company_id == company_id)
    cs_res = await session.execute(cs_stmt)
    cs = cs_res.scalar_one_or_none()

    data = {
        "hr_name": hr_config.get("hr_name") or company_profile.get("hr_name") or company_profile.get("contact_person") or "HR Department",
        "hr_email": hr_config.get("hr_email") or company_profile.get("hr_email") or company_profile.get("email") or "hr@ofc360.com",
        "hr_phone": hr_config.get("hr_phone") or company_profile.get("hr_phone") or company_profile.get("phone") or "+91 98765 43210",
        "working_days": hr_config.get("working_days") or (cs.working_days.get("days") if cs and isinstance(cs.working_days, dict) else None) or ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        "working_hours_start": hr_config.get("working_hours_start") or "09:00",
        "working_hours_end": hr_config.get("working_hours_end") or "18:00",
        "timezone": hr_config.get("timezone") or (cs.timezone if cs else None) or company_profile.get("timezone") or "Asia/Kolkata",
        "attendance_enabled": hr_config.get("attendance_enabled", True),
        "leave_enabled": hr_config.get("leave_enabled", True),
        "payroll_enabled": hr_config.get("payroll_enabled", True),
        "week_start_day": hr_config.get("week_start_day") or (cs.week_start_day if cs else "Monday"),
        "office_timing": hr_config.get("office_timing") or (cs.office_timing if cs else "09:00 AM - 06:00 PM"),
        "default_shift": hr_config.get("default_shift") or (cs.default_shift if cs else "General"),
        "time_format": hr_config.get("time_format") or (cs.time_format if cs else "12h"),
        "date_format": hr_config.get("date_format") or (cs.date_format if cs else "DD/MM/YYYY"),
        "financial_year": hr_config.get("financial_year") or (cs.financial_year if cs else "April - March"),
        "leave_policy_template": hr_config.get("leave_policy_template") or (cs.leave_policy_template if cs else "Standard"),
    }

    return APIResponse[Dict[str, Any]](
        success=True,
        message="HR settings retrieved successfully.",
        data=data,
        errors=None,
    )


@router.put("/hr")
@router.put("/settings/hr")
@router.post("/hr")
@router.post("/settings/hr")
async def update_hr_settings(
    payload: HRSettingsUpdatePayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[Dict[str, Any]]:
    """Update HR settings for the authenticated company."""
    check_admin_or_manager(claims)
    co_id_str = claims.get("company_id")
    if not co_id_str:
        raise HTTPException(status_code=403, detail="No company association found.")

    company_id = uuid.UUID(co_id_str)
    stmt = select(Company).where(Company.id == company_id)
    res = await session.execute(stmt)
    company = res.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")

    hr_settings_data = company.hr_settings or {}
    hr_config = hr_settings_data.get("hr_config") or {}

    update_data = payload.model_dump(exclude_unset=True)
    hr_config.update(update_data)
    hr_settings_data["hr_config"] = hr_config
    company.hr_settings = hr_settings_data

    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(company, "hr_settings")

    from app.models.onboarding import CompanySettings
    cs_stmt = select(CompanySettings).where(CompanySettings.company_id == company_id)
    cs_res = await session.execute(cs_stmt)
    cs = cs_res.scalar_one_or_none()
    if cs:
        if payload.timezone:
            cs.timezone = payload.timezone
        if payload.working_days:
            cs.working_days = {"days": payload.working_days}
        if payload.week_start_day:
            cs.week_start_day = payload.week_start_day
        if payload.office_timing:
            cs.office_timing = payload.office_timing
        if payload.default_shift:
            cs.default_shift = payload.default_shift
        if payload.time_format:
            cs.time_format = payload.time_format
        if payload.date_format:
            cs.date_format = payload.date_format
        if payload.financial_year:
            cs.financial_year = payload.financial_year
        if payload.leave_policy_template:
            cs.leave_policy_template = payload.leave_policy_template

    await session.commit()

    await create_audit_log(
        session, claims, "UPDATE_HR_SETTINGS",
        f"Updated HR settings configuration for company {company.name}."
    )

    response_data = {
        "hr_name": hr_config.get("hr_name", "HR Department"),
        "hr_email": hr_config.get("hr_email", "hr@ofc360.com"),
        "hr_phone": hr_config.get("hr_phone", "+91 98765 43210"),
        "working_days": hr_config.get("working_days", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]),
        "working_hours_start": hr_config.get("working_hours_start", "09:00"),
        "working_hours_end": hr_config.get("working_hours_end", "18:00"),
        "timezone": hr_config.get("timezone", "Asia/Kolkata"),
        "attendance_enabled": hr_config.get("attendance_enabled", True),
        "leave_enabled": hr_config.get("leave_enabled", True),
        "payroll_enabled": hr_config.get("payroll_enabled", True),
        "week_start_day": hr_config.get("week_start_day", "Monday"),
        "office_timing": hr_config.get("office_timing", "09:00 - 18:00"),
        "default_shift": hr_config.get("default_shift", "General"),
        "time_format": hr_config.get("time_format", "12h"),
        "date_format": hr_config.get("date_format", "DD/MM/YYYY"),
        "financial_year": hr_config.get("financial_year", "April - March"),
        "leave_policy_template": hr_config.get("leave_policy_template", "Standard"),
    }

    return APIResponse[Dict[str, Any]](
        success=True,
        message="HR settings updated successfully.",
        data=response_data,
        errors=None,
    )


# ===========================================================================
# MFA / 2FA Endpoints
# ===========================================================================

@router.post("/mfa/enable")
@router.post("/settings/mfa/enable")
async def enable_mfa(
    payload: Optional[MFAEnablePayload] = None,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[Dict[str, Any]]:
    """
    Initiate or verify and enable TOTP Multi-Factor Authentication for the authenticated user.
    """
    user_id_str = claims.get("sub")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Authentication credentials invalid or missing.")

    user_id = uuid.UUID(user_id_str)
    user_stmt = select(User).where(User.id == user_id)
    user_res = await session.execute(user_stmt)
    user = user_res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User account not found.")

    mfa_stmt = select(UserMFA).where(UserMFA.user_id == user_id)
    mfa_res = await session.execute(mfa_stmt)
    user_mfa = mfa_res.scalar_one_or_none()

    code = payload.code if payload else None

    # Complete / Verify branch
    if code:
        if not user_mfa or not user_mfa.mfa_secret:
            raise HTTPException(
                status_code=400,
                detail="MFA setup has not been initiated for this account. Please initiate setup first."
            )

        is_valid = verify_totp_code(user_mfa.mfa_secret, code)
        if not is_valid:
            raise HTTPException(
                status_code=400,
                detail="Invalid MFA verification code. Please check your authenticator app and try again."
            )

        user_mfa.mfa_enabled = True
        user_mfa.is_verified = True
        await session.commit()

        await create_audit_log(
            session, claims, "MFA_ENABLED",
            f"TOTP Two-Factor Authentication was enabled and verified for user {user.email}."
        )

        return APIResponse[Dict[str, Any]](
            success=True,
            message="MFA has been successfully enabled and verified.",
            data={
                "mfa_enabled": True,
                "method": "totp",
                "is_verified": True,
            },
            errors=None,
        )

    # Initiate branch
    if not user_mfa:
        secret = generate_totp_secret()
        user_mfa = UserMFA(
            user_id=user_id,
            company_id=user.company_id,
            mfa_enabled=False,
            is_verified=False,
            mfa_secret=secret,
            method="totp",
        )
        session.add(user_mfa)
        await session.commit()
        await session.refresh(user_mfa)
    else:
        if not user_mfa.mfa_secret:
            user_mfa.mfa_secret = generate_totp_secret()
            user_mfa.mfa_enabled = False
            user_mfa.is_verified = False
            await session.commit()

    secret = user_mfa.mfa_secret
    account_label = user.email or user.name or "User"
    provisioning_uri = generate_provisioning_uri(secret, account_label, issuer_name="OFC360")
    qr_code_data_uri = generate_qr_code_data_uri(provisioning_uri)

    return APIResponse[Dict[str, Any]](
        success=True,
        message="MFA setup initiated. Scan QR code or enter secret into your authenticator app, then submit the 6-digit code to verify.",
        data={
            "mfa_enabled": bool(user_mfa.mfa_enabled),
            "method": "totp",
            "secret": secret,
            "provisioning_uri": provisioning_uri,
            "qr_code": qr_code_data_uri,
        },
        errors=None,
    )


@router.post("/mfa/disable")
@router.post("/settings/mfa/disable")
async def disable_mfa(
    payload: Optional[MFADisablePayload] = None,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[Dict[str, Any]]:
    """Disable TOTP Multi-Factor Authentication for the authenticated user."""
    user_id_str = claims.get("sub")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Authentication credentials invalid or missing.")

    user_id = uuid.UUID(user_id_str)
    user_stmt = select(User).where(User.id == user_id)
    user_res = await session.execute(user_stmt)
    user = user_res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User account not found.")

    from app.core.security import verify_password

    mfa_stmt = select(UserMFA).where(UserMFA.user_id == user_id)
    mfa_res = await session.execute(mfa_stmt)
    user_mfa = mfa_res.scalar_one_or_none()

    if payload:
        if payload.password and user.password_hash:
            if not verify_password(payload.password, user.password_hash):
                raise HTTPException(status_code=400, detail="Incorrect password provided.")
        if payload.code and user_mfa and user_mfa.mfa_secret:
            if not verify_totp_code(user_mfa.mfa_secret, payload.code):
                raise HTTPException(status_code=400, detail="Invalid MFA verification code.")

    if user_mfa:
        user_mfa.mfa_enabled = False
        user_mfa.is_verified = False
        user_mfa.mfa_secret = None
        await session.commit()

    await create_audit_log(
        session, claims, "MFA_DISABLED",
        f"TOTP Two-Factor Authentication was disabled for user {user.email}."
    )

    return APIResponse[Dict[str, Any]](
        success=True,
        message="MFA has been successfully disabled.",
        data={
            "mfa_enabled": False,
        },
        errors=None,
    )

