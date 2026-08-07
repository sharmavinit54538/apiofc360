"""IT Helpdesk AI Agent.

Handles:
- Resolving basic IT issues: VPN, Email, Password Resets, Access requests.
- Automating ticket creations when issue cannot be resolved via AI instructions.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from app.agents.ticket_agent import TicketAgent

logger = logging.getLogger(__name__)

# Basic troubleshooting guides
TROUBLESHOOTING_GUIDES = {
    "VPN": """**VPN Connection Troubleshooting Guide:**
1. Check your internet connection. Try loading a public website first.
2. Ensure you are using the GlobalProtect/OpenVPN client.
3. Disconnect from your current wifi, reconnect, and try authenticating again.
4. Verify your MFA (Multi-Factor Authentication) application has the correct notification token.
5. If the connection times out, the VPN gateway may be busy. Wait 5 minutes.
*Still having issues? I can open a support ticket for you.*""",

    "PASSWORD_RESET": """**IT Password Self-Service Guide:**
1. Navigate to the self-service portal: `https://sso.company.com/reset`.
2. Input your corporate email ID and click 'Forgot Password'.
3. Verify your identity using the link sent to your registered personal email or mobile phone.
4. Set a strong password (minimum 12 characters, uppercase, lowercase, numbers, and symbols).
*If self-service is locked, reply 'create ticket' and I will escalate to IT support.*""",

    "EMAIL": """**Corporate Email & Outlook Recovery Guide:**
1. Ensure your corporate account is activated (check joining date status).
2. Check Microsoft 365 status dashboard if logging into Outlook Web.
3. Remove old stored credentials from your Windows Credential Manager or macOS Keychain.
4. If you have been recently reassigned a department or manager, it might take 1 hour for changes to sync.
*If the email remains unreachable, I will raise a ticket to IT Mail Admins.*""",

    "ACCESS": """**System & Folder Access Request Guide:**
1. All access requests require active manager approval.
2. Submit your request through the access management portal: `https://access.company.com`.
3. Select the target repository or folder, specify the role (Read/Write), and enter your manager's email.
*If the portal is down, let me know and I will raise an IT ticket.*"""
}


class ITHelpdeskAgent:
    """Specialized agent dealing with IT queries and troubleshooting paths."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.ticket_agent = TicketAgent(db)

    async def get_troubleshooting_guide(self, topic: str) -> Optional[str]:
        """Return structured guide text if matching standard topics."""
        topic_key = topic.upper().strip()
        for k, v in TROUBLESHOOTING_GUIDES.items():
            if k in topic_key:
                return v
        return None

    async def auto_raise_it_ticket(
        self,
        employee_id: uuid.UUID,
        subject: str,
        problem_description: str,
        company_id: Optional[uuid.UUID] = None,
    ) -> dict[str, Any]:
        """Automatically log support ticket in IT category."""
        ticket = await self.ticket_agent.create_ticket(
            employee_id=employee_id,
            category="IT",
            priority="MEDIUM",
            title=subject,
            description=problem_description,
            company_id=company_id
        )
        return {
            "success": True,
            "ticket_id": str(ticket.id),
            "priority": ticket.priority,
            "assigned_to": str(ticket.assigned_to) if ticket.assigned_to else "Unassigned (IT Queue)",
            "message": f"Successfully created ticket '{subject}' (ID: {ticket.id}). IT staff will review it."
        }
