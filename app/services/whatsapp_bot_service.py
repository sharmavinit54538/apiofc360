"""WhatsApp Cloud API command and interactive workflow router."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.communication import Announcement
from app.models.employee import Employee
from app.models.leave import LeaveRequest
from app.models.leave_balance import LeaveBalance
from app.models.payroll import Payslip
from app.models.user import User
from app.models.whatsapp_bot import WhatsAppConversation, WhatsAppInboundMessage
from app.services.leave_service import LeaveService
from app.services.mobile_pwa_service import MobilePWAService
from app.services.whatsapp_service import send_whatsapp_message


HELP = (
    "OFC360 commands:\nLEAVE BALANCE\nLEAVE APPLY (interactive)\nCHECKIN / CHECKOUT (interactive)\n"
    "REGULARISE YYYY-MM-DD HH:MM HH:MM reason\nPAYSLIP [MM YYYY]\nANNOUNCEMENTS\n"
    "APPROVALS\nAPPROVE <leave-id> / REJECT <leave-id> reason\nTICKET (interactive)"
)


class WhatsAppBotService:
    def __init__(self, session: AsyncSession, *, sender=None, mobile_service=None) -> None:
        self.session = session
        self.sender = sender or send_whatsapp_message
        self.mobile_service = mobile_service

    @staticmethod
    def verify_webhook(mode: str | None, token: str | None, challenge: str | None) -> str:
        expected = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
        if not expected:
            raise RuntimeError("WHATSAPP_VERIFY_TOKEN is not configured")
        if mode != "subscribe" or not token or not hmac.compare_digest(token, expected):
            raise PermissionError("WhatsApp webhook verification failed")
        if challenge is None:
            raise ValueError("hub.challenge is required")
        return challenge

    @staticmethod
    def validate_signature(raw_body: bytes, signature: str | None) -> None:
        secret = os.getenv("WHATSAPP_APP_SECRET", "")
        environment = os.getenv("ENVIRONMENT", "local").lower()
        if not secret:
            if environment in {"production", "prod", "staging"}:
                raise RuntimeError("WHATSAPP_APP_SECRET is required outside local development")
            return
        expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        if not signature or not hmac.compare_digest(signature, expected):
            raise PermissionError("Invalid WhatsApp webhook signature")

    @staticmethod
    def _role(user: User) -> str:
        return str(getattr(user.role, "value", user.role) or "employee").lower()

    async def resolve_user(self, phone: str) -> User | None:
        digits = re.sub(r"\D", "", phone)
        candidates = {digits, digits[-10:]}
        # Phone is not globally unique in legacy tenants. Never select an
        # arbitrary account when the same WhatsApp number maps to multiple users.
        users = (await self.session.execute(select(User).where(
            User.phone.in_(candidates), User.is_active.is_(True),
        ).limit(2))).scalars().all()
        return users[0] if len(users) == 1 else None

    async def _employee(self, user: User) -> Employee | None:
        return (await self.session.execute(select(Employee).where(
            Employee.user_id == user.id, Employee.is_deleted.is_(False),
        ))).scalar_one_or_none()

    async def _conversation(self, user_id: uuid.UUID) -> WhatsAppConversation | None:
        conversation = await self.session.get(WhatsAppConversation, user_id)
        if conversation and conversation.expires_at:
            expires = conversation.expires_at
            expires = expires.replace(tzinfo=UTC) if expires.tzinfo is None else expires
            if expires < datetime.now(UTC):
                await self._clear_conversation(user_id)
                return None
        return conversation

    async def _set_conversation(self, user_id: uuid.UUID, flow: str, step: str, data: dict) -> None:
        conversation = await self.session.get(WhatsAppConversation, user_id)
        if conversation is None:
            conversation = WhatsAppConversation(user_id=user_id)
            self.session.add(conversation)
        conversation.flow = flow
        conversation.step = step
        conversation.data_json = data
        conversation.expires_at = datetime.now(UTC) + timedelta(minutes=30)
        await self.session.commit()

    async def _clear_conversation(self, user_id: uuid.UUID) -> None:
        await self.session.execute(delete(WhatsAppConversation).where(WhatsAppConversation.user_id == user_id))
        await self.session.commit()

    @staticmethod
    def _normalise_interactive(text: str) -> str:
        mapping = {
            "leave_balance": "LEAVE BALANCE", "leave_apply": "LEAVE APPLY",
            "attendance_checkin": "CHECKIN", "attendance_checkout": "CHECKOUT",
            "payslip_latest": "PAYSLIP", "announcements_latest": "ANNOUNCEMENTS",
            "manager_approvals": "APPROVALS", "helpdesk_new": "TICKET",
        }
        return mapping.get(text.strip().lower(), text.strip())

    async def execute_command(self, user: User, text: str, *, message: dict | None = None) -> dict[str, Any]:
        employee = await self._employee(user)
        if employee is None:
            return {"text": "Your WhatsApp number is not linked to an active employee profile."}
        message = message or {"type": "text", "text": {"body": text}}
        text = self._normalise_interactive(text)
        upper = text.upper().strip()
        if upper in {"CANCEL", "STOP"}:
            await self._clear_conversation(user.id)
            return {"text": "Current flow cancelled. Send MENU for commands."}

        conversation = await self._conversation(user.id)
        new_command = any(upper.startswith(prefix) for prefix in (
            "MENU", "HELP", "LEAVE ", "CHECKIN", "CHECKOUT", "REGULARISE", "REGULARIZE",
            "PAYSLIP", "ANNOUNCEMENTS", "APPROVALS", "APPROVE ", "REJECT ", "TICKET",
        ))
        if conversation and not new_command:
            return await self._continue_flow(user, employee, conversation, text, message)

        if upper in {"MENU", "HELP", "HI", "HELLO"}:
            return {"text": HELP}
        if upper == "LEAVE BALANCE":
            return {"text": await self._leave_balance(employee)}
        if upper == "LEAVE APPLY":
            await self._set_conversation(user.id, "LEAVE", "TYPE", {})
            return {"text": "Which leave type? Reply Sick Leave, Casual Leave, Vacation Leave, or Bereavement Leave."}
        if upper.startswith("LEAVE APPLY "):
            return await self._leave_apply_direct(employee, text[12:].strip())
        if upper in {"CHECKIN", "CHECKOUT", "ATTENDANCE CHECKIN", "ATTENDANCE CHECKOUT"}:
            operation = "CHECK_OUT" if "CHECKOUT" in upper else "CHECK_IN"
            await self._set_conversation(user.id, "ATTENDANCE", "LOCATION", {"operation": operation})
            return {"text": "Share your current GPS location using WhatsApp location attachment."}
        if upper.startswith("REGULARISE ") or upper.startswith("REGULARIZE "):
            return {"text": await self._regularise(employee, text)}
        if upper.startswith("PAYSLIP"):
            return await self._payslip(employee, upper)
        if upper == "ANNOUNCEMENTS":
            return {"text": await self._announcements(employee)}
        if upper == "APPROVALS":
            return {"text": await self._approvals(user, employee)}
        if upper.startswith("APPROVE ") or upper.startswith("REJECT "):
            return {"text": await self._review_leave(user, employee, text)}
        if upper == "TICKET":
            await self._set_conversation(user.id, "TICKET", "CATEGORY", {})
            return {"text": "Helpdesk category? For example: Payroll, IT, HR, or Facilities."}
        if upper.startswith("TICKET "):
            return {"text": await self._ticket_direct(user, text[7:].strip())}
        return {"text": "I did not understand that command.\n" + HELP}

    async def _continue_flow(self, user: User, employee: Employee, conversation: WhatsAppConversation,
                             text: str, message: dict) -> dict[str, Any]:
        data = dict(conversation.data_json or {})
        if conversation.flow == "LEAVE":
            if conversation.step == "TYPE":
                data["leave_type"] = text.strip()
                await self._set_conversation(user.id, "LEAVE", "START", data)
                return {"text": "Enter leave start date as YYYY-MM-DD."}
            if conversation.step == "START":
                data["start_date"] = date.fromisoformat(text.strip()).isoformat()
                await self._set_conversation(user.id, "LEAVE", "END", data)
                return {"text": "Enter leave end date as YYYY-MM-DD."}
            if conversation.step == "END":
                data["end_date"] = date.fromisoformat(text.strip()).isoformat()
                await self._set_conversation(user.id, "LEAVE", "REASON", data)
                return {"text": "Enter a short reason (at least 5 characters)."}
            if conversation.step == "REASON":
                result = await self._apply_leave(employee, data["leave_type"], data["start_date"], data["end_date"], text.strip())
                await self._clear_conversation(user.id)
                return {"text": result}

        if conversation.flow == "TICKET":
            if conversation.step == "CATEGORY":
                data["category"] = text.strip()
                await self._set_conversation(user.id, "TICKET", "SUBJECT", data)
                return {"text": "Enter the ticket subject."}
            if conversation.step == "SUBJECT":
                data["subject"] = text.strip()
                await self._set_conversation(user.id, "TICKET", "DESCRIPTION", data)
                return {"text": "Describe the issue. Include error details if available."}
            if conversation.step == "DESCRIPTION":
                result = await self._create_ticket(user, data["category"], data["subject"], text.strip())
                await self._clear_conversation(user.id)
                return {"text": result}

        if conversation.flow == "ATTENDANCE":
            if conversation.step == "LOCATION":
                location = message.get("location") or {}
                latitude = location.get("latitude")
                longitude = location.get("longitude")
                if latitude is None and "," in text:
                    lat, lng = text.split(",", 1)
                    latitude, longitude = float(lat), float(lng)
                if latitude is None or longitude is None:
                    return {"text": "Please share a GPS location, or reply as latitude,longitude."}
                data.update(latitude=float(latitude), longitude=float(longitude))
                await self._set_conversation(user.id, "ATTENDANCE", "SELFIE", data)
                return {"text": "Now capture and send a live selfie for biometric verification."}
            if conversation.step == "SELFIE":
                image_base64 = await self._image_base64(message)
                if not image_base64:
                    return {"text": "Please attach a selfie image to complete attendance."}
                service = self.mobile_service or MobilePWAService(self.session)
                message_id = str(message.get("id") or uuid.uuid4())
                result = await service.mark_attendance(
                    user_id=user.id, company_id=employee.company_id, operation=data["operation"],
                    idempotency_key=f"wa-{message_id}"[:128], image_base64=image_base64,
                    latitude=data["latitude"], longitude=data["longitude"], device_info="WHATSAPP",
                )
                await self._clear_conversation(user.id)
                action = "checked in" if data["operation"] == "CHECK_IN" else "checked out"
                return {"text": f"Face and GPS verified. You are {action}; attendance {result['attendance_id']}."}
        return {"text": "This flow has expired. Send MENU to start again."}

    async def _leave_balance(self, employee: Employee) -> str:
        year = date.today().year
        balances = (await self.session.execute(select(LeaveBalance).where(
            LeaveBalance.employee_id == employee.id, or_(LeaveBalance.year == year, LeaveBalance.year.is_(None)),
        ).order_by(LeaveBalance.leave_type))).scalars().all()
        if not balances:
            computed = await LeaveService(self.session).get_leave_balances(employee.id)
            return "Leave balances:\n" + "\n".join(f"{b.leave_type}: {b.remaining_days:g} days" for b in computed)
        return "Leave balances:\n" + "\n".join(f"{b.leave_type}: {float(b.remaining_days):g} days" for b in balances)

    async def _apply_leave(self, employee: Employee, leave_type: str, start: str, end: str, reason: str) -> str:
        from app.schemas.leave import LeaveRequestCreate
        request = await LeaveService(self.session).apply_leave(employee.id, LeaveRequestCreate(
            leave_type=leave_type, start_date=date.fromisoformat(start), end_date=date.fromisoformat(end), reason=reason,
        ))
        return f"Leave request {request.id} submitted. Status: {request.status}."

    async def _leave_apply_direct(self, employee: Employee, value: str) -> dict[str, Any]:
        parts = [part.strip() for part in value.split("|")]
        if len(parts) == 4:
            return {"text": await self._apply_leave(employee, *parts)}
        match = re.match(r"^(\S+)\s+(\d{4}-\d{2}-\d{2})\s+(\d{4}-\d{2}-\d{2})\s+(.+)$", value)
        if not match:
            return {"text": "Use LEAVE APPLY, or LEAVE APPLY type | YYYY-MM-DD | YYYY-MM-DD | reason."}
        return {"text": await self._apply_leave(employee, *match.groups())}

    async def _regularise(self, employee: Employee, text: str) -> str:
        from app.schemas.core_modules.attendance import AttendanceRegularizationCreateRequest
        from app.services.core_modules.attendance_service import AttendanceCoreService
        parts = text.split(maxsplit=4)
        if len(parts) < 5:
            return "Use REGULARISE YYYY-MM-DD HH:MM HH:MM reason."
        _, day, check_in, check_out, reason = parts
        request_date = date.fromisoformat(day)
        payload = AttendanceRegularizationCreateRequest(
            request_date=request_date,
            requested_check_in=datetime.combine(request_date, time.fromisoformat(check_in)),
            requested_check_out=datetime.combine(request_date, time.fromisoformat(check_out)), reason=reason,
        )
        request = await AttendanceCoreService(self.session).create_regularization(employee.id, employee.company_id, payload)
        return f"Attendance regularisation {request.id} submitted for approval."

    async def _payslip(self, employee: Employee, upper: str) -> dict[str, Any]:
        stmt = select(Payslip).where(Payslip.employee_id == employee.id, Payslip.company_id == employee.company_id)
        match = re.match(r"^PAYSLIP\s+(\d{1,2})\s+(\d{4})$", upper)
        if match:
            stmt = stmt.where(Payslip.period_month == int(match.group(1)), Payslip.period_year == int(match.group(2)))
        payslip = (await self.session.execute(stmt.order_by(Payslip.period_year.desc(), Payslip.period_month.desc()))).scalars().first()
        if payslip is None:
            return {"text": "No payslip found for the requested period."}
        from app.services.payroll.payslip_service import PayslipService
        content, filename = await PayslipService.get_payslip_file(self.session, payslip.payroll_run_id, employee.id)
        return {"text": f"Payslip for {payslip.period_month:02d}/{payslip.period_year}.", "attachment": (filename, content, "application/pdf")}

    async def _announcements(self, employee: Employee) -> str:
        today = date.today()
        rows = (await self.session.execute(select(Announcement).where(
            Announcement.company_id == employee.company_id, Announcement.status == "PUBLISHED",
            Announcement.is_deleted.is_(False), Announcement.publish_date <= today,
            or_(Announcement.expiry_date.is_(None), Announcement.expiry_date >= today),
        ).order_by(Announcement.is_pinned.desc(), Announcement.publish_date.desc()).limit(20))).scalars().all()
        targeted = [a for a in rows if (not a.department or a.department == employee.department) and (not a.branch or a.branch == employee.branch)][:5]
        if not targeted:
            return "There are no current announcements for you."
        return "Announcements:\n" + "\n".join(f"• {a.title}: {a.description[:240]}" for a in targeted)

    async def _approvals(self, user: User, employee: Employee) -> str:
        role = self._role(user)
        if role not in {"manager", "admin", "hr_admin", "super_admin"}:
            return "Manager approval commands are not enabled for your role."
        stmt = select(LeaveRequest).join(Employee, Employee.id == LeaveRequest.employee_id).where(
            Employee.company_id == employee.company_id, LeaveRequest.status == "PENDING",
        )
        if role == "manager":
            stmt = stmt.where(or_(Employee.manager_id == employee.id, Employee.reporting_manager_id == employee.id))
        rows = (await self.session.execute(stmt.order_by(LeaveRequest.created_at).limit(10))).scalars().all()
        if not rows:
            return "No pending leave approvals."
        return "Pending approvals:\n" + "\n".join(f"{r.id} | {r.leave_type} | {r.start_date} to {r.end_date}" for r in rows) + "\nReply APPROVE <id> or REJECT <id> reason."

    async def _review_leave(self, user: User, employee: Employee, text: str) -> str:
        parts = text.split(maxsplit=2)
        if len(parts) < 2:
            return "Use APPROVE <leave-id> or REJECT <leave-id> reason."
        decision = parts[0].upper()
        leave = await LeaveService(self.session).review_leave(
            uuid.UUID(parts[1]), decision, user.id, self._role(user), employee.company_id,
            rejection_reason=parts[2] if len(parts) > 2 else None,
        )
        return f"Leave request {leave.id} is {leave.status}."

    async def _create_ticket(self, user: User, category: str, subject: str, description: str) -> str:
        from app.services.helpdesk_service import HelpdeskService
        ticket = await HelpdeskService(self.session).create_ticket(
            user=user, company_id=user.company_id, category=category, priority="Medium",
            subject=subject, description=description,
        )
        return f"Helpdesk ticket {ticket.ticketNumber} created. Status: {ticket.status}."

    async def _ticket_direct(self, user: User, value: str) -> str:
        parts = [part.strip() for part in value.split("|")]
        if len(parts) != 3:
            return "Use TICKET, or TICKET category | subject | description."
        return await self._create_ticket(user, *parts)

    async def _image_base64(self, message: dict) -> str | None:
        image = message.get("image") or {}
        if image.get("base64"):
            return image["base64"]
        media_id = image.get("id")
        token = os.getenv("WHATSAPP_ACCESS_TOKEN")
        if not media_id or not token:
            return None
        version = os.getenv("WHATSAPP_GRAPH_VERSION", "v20.0")
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=30) as client:
            metadata = await client.get(f"https://graph.facebook.com/{version}/{media_id}", headers=headers)
            metadata.raise_for_status()
            media_url = metadata.json()["url"]
            content = await client.get(media_url, headers=headers)
            content.raise_for_status()
        return base64.b64encode(content.content).decode()

    @staticmethod
    def _safe_message(message: dict) -> dict:
        copied = json.loads(json.dumps(message))
        def redact(value):
            if isinstance(value, dict):
                for key in list(value):
                    if key.lower() in {"base64", "image_base64"}:
                        value[key] = "[REDACTED]"
                    else:
                        redact(value[key])
            elif isinstance(value, list):
                for item in value:
                    redact(item)
        redact(copied)
        return copied

    async def handle_inbound(self, payload: dict) -> list[dict[str, Any]]:
        responses: list[dict[str, Any]] = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for message in value.get("messages", []):
                    provider_id = str(message.get("id") or uuid.uuid4())
                    phone = str(message.get("from") or "")
                    existing = (await self.session.execute(select(WhatsAppInboundMessage).where(
                        WhatsAppInboundMessage.provider_message_id == provider_id,
                    ))).scalar_one_or_none()
                    if existing and existing.response_json is not None:
                        responses.append({"message_id": provider_id, "duplicate": True, **existing.response_json})
                        continue
                    record = existing or WhatsAppInboundMessage(
                        id=uuid.uuid4(), provider_message_id=provider_id, from_phone=phone,
                        payload_json=self._safe_message(message),
                    )
                    if not existing:
                        self.session.add(record)
                        await self.session.commit()
                    user = await self.resolve_user(phone)
                    if user is None:
                        result = {"text": "This phone number is not registered with OFC360."}
                    else:
                        interactive = message.get("interactive") or {}
                        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
                        text = reply.get("id") or reply.get("title") or (message.get("text") or {}).get("body") or message.get("type", "")
                        result = await self.execute_command(user, text, message=message)
                    attachment = result.get("attachment")
                    await self.sender(phone, result["text"], attachment=attachment)
                    stored = {"text": result["text"], "has_attachment": attachment is not None}
                    record.response_json = stored
                    await self.session.commit()
                    responses.append({"message_id": provider_id, "duplicate": False, **stored})
        return responses
