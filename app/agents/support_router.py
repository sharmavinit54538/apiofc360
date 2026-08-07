"""Central Intent Router for Employee Support Agent.

Classifies incoming user queries and delegates tasks to specialised sub-agents:
- LeaveAgent (leave balance, apply/cancel)
- AttendanceAgent (punch state, late check-ins)
- PayrollAgent (latest payslip, CTC structure, salary history)
- AssetAgent (assigned inventory, hardware request, damage filing)
- ITHelpdeskAgent (VPN, email, password recovery stubs)
- TicketAgent (ticket CRUD operations and alerts)
- RAG Pipeline (policy manuals, employee handbook Q&A)
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.llm.client import get_llm_client
from app.llm.prompts import PromptLibrary
from app.llm.response_parser import ResponseParser

# Sub-agents
from app.agents.leave_agent import LeaveAgent
from app.agents.attendance_agent import AttendanceAgent
from app.agents.payroll_agent import PayrollAgent
from app.agents.asset_agent import AssetAgent
from app.agents.it_helpdesk_agent import ITHelpdeskAgent
from app.agents.ticket_agent import TicketAgent
from app.rag.doc_rag_pipeline import get_rag_pipeline

logger = logging.getLogger(__name__)


class SupportRouter:
    """Orchestrates query classification and routes processing to target sub-agents."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.llm = get_llm_client()
        self.leave_agent = LeaveAgent(db)
        self.attendance_agent = AttendanceAgent(db)
        self.payroll_agent = PayrollAgent(db)
        self.asset_agent = AssetAgent(db)
        self.it_agent = ITHelpdeskAgent(db)
        self.ticket_agent = TicketAgent(db)
        self.rag = get_rag_pipeline()

    async def handle_query(
        self,
        employee_id: uuid.UUID,
        message: str,
        chat_context: Optional[str] = None,
        model: Optional[str] = None,
    ) -> dict[str, Any]:
        """Classify message intent, invoke specialized sub-agent, and generate final response."""
        # 1. Fetch employee context
        from app.models.employee import Employee
        emp_res = await self.db.execute(select(Employee).where(Employee.id == employee_id))
        emp = emp_res.scalar_one_or_none()
        if not emp:
            return {"answer": "I'm sorry, I couldn't find your employee record in the database."}

        profile_context = (
            f"Employee ID: {emp.employee_id}\n"
            f"Name: {emp.first_name} {emp.last_name}\n"
            f"Department: {emp.department}\n"
            f"Designation: {emp.designation}\n"
            f"Status: {emp.status}\n"
            f"Joining Date: {emp.joining_date}\n"
            f"Phone: {emp.phone}\n"
            f"Pan Number: {emp.pan_number}\n"
        )

        # 2. Fetch active support tickets
        tickets = await self.ticket_agent.get_tickets_by_employee(employee_id)
        ticket_history = "\n".join(
            f"- [{t.status}] ID: {t.id} - '{t.title}' (Category: {t.category}, Priority: {t.priority})"
            for t in tickets
        ) if tickets else "No open or past support tickets."

        # 3. Classify intent via Ollama
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        router_prompt = PromptLibrary.support_router_user(
            message=message,
            profile_context=profile_context,
            ticket_history=ticket_history,
            current_time=current_time
        )
        
        try:
            res_text = await self.llm.complete(
                prompt=router_prompt,
                system=PromptLibrary.SUPPORT_ROUTER_SYSTEM,
                model=model,
                json_mode=True,
                temperature=0.1
            )
            classification = ResponseParser.extract_json_object(res_text)
        except Exception as exc:
            logger.error("Intent routing failed: %s. Defaulting to general RAG.", exc)
            classification = {
                "intent": "GENERAL_RAG",
                "confidence": 0.5,
                "parameters": {},
                "conversational_reply": "Let me lookup company policies for you."
            }

        intent = classification.get("intent", "GENERAL_RAG").upper()
        params = classification.get("parameters") or {}
        reply_prologue = classification.get("conversational_reply") or ""

        # Delegate
        agent_data = {}
        decision_notes = ""

        if intent == "PROFILE_INFO":
            # Check if updating phone number
            if "update" in message.lower() and ("phone" in message.lower() or "number" in message.lower()):
                # Extract new phone from message
                phone_match = re.search(r'\b\d{10,12}\b', message)
                if phone_match:
                    new_phone = phone_match.group(0)
                    emp.phone = new_phone
                    await self.db.commit()
                    decision_notes = f"Your phone number has been updated to {new_phone} in the database."
                else:
                    decision_notes = "Please provide your new 10-digit phone number, for example: 'Update my phone number to 9876543210'."
            else:
                decision_notes = (
                    f"**Profile Details:**\n"
                    f"- Name: {emp.first_name} {emp.last_name}\n"
                    f"- Employee ID: {emp.employee_id}\n"
                    f"- Department: {emp.department}\n"
                    f"- Designation: {emp.designation}\n"
                    f"- Phone Number: {emp.phone}\n"
                    f"- Date of Joining: {emp.joining_date}\n"
                )
            agent_data = {"profile": profile_context}

        elif intent == "LEAVE_SUPPORT":
            action = params.get("action") or ""
            if "apply" in action.lower() or "apply" in message.lower():
                # Parse start/end dates
                s_date = self._parse_date_param(params.get("start_date")) or date.today()
                e_date = self._parse_date_param(params.get("end_date")) or s_date
                ltype = params.get("leave_type") or "casual_leave"
                
                res = await self.leave_agent.apply_leave(employee_id, ltype, s_date, e_date)
                decision_notes = res.get("message") or res.get("error")
                agent_data = res
            elif "cancel" in action.lower() or "cancel" in message.lower():
                ltype = params.get("leave_type") or "casual_leave"
                res = await self.leave_agent.cancel_leave(employee_id, ltype, days=1.0)
                decision_notes = res.get("message") or res.get("error")
                agent_data = res
            elif "holiday" in message.lower() or "calendar" in message.lower():
                hols = await self.leave_agent.get_upcoming_holidays()
                decision_notes = "**Upcoming Holidays:**\n" + "\n".join(
                    f"- {h['date']}: {h['name']} ({h['day_of_week']})" for h in hols[:5]
                )
                agent_data = {"holidays": hols}
            else:
                # Default check balance
                balances = await self.leave_agent.get_leave_balances(employee_id)
                decision_notes = "**Current Leave Balances:**\n" + "\n".join(
                    f"- {k.replace('_', ' ')}: {v['remaining']} day(s) remaining (Allocated: {v['allocated']}, Used: {v['used']})"
                    for k, v in balances.items()
                )
                agent_data = {"balances": balances}

        elif intent == "ATTENDANCE_SUPPORT":
            if "today" in message.lower() or "check-in" in message.lower() or "checked" in message.lower():
                res = await self.attendance_agent.check_today_punch(employee_id)
                decision_notes = res.get("message")
                agent_data = res
            elif "late" in message.lower():
                today = date.today()
                res = await self.attendance_agent.get_late_checkins_count(employee_id, today.month, today.year)
                decision_notes = f"You have {res['late_check_ins']} late check-in(s) in this month."
                agent_data = res
            else:
                today = date.today()
                res = await self.attendance_agent.get_monthly_attendance_summary(employee_id, today.year, today.month)
                decision_notes = f"**Attendance Summary ({res['period']}):**\n- Paid days: {res['paid_days']}\n- LOP days: {res['lop_days']}\n- Status: {res['remarks']}"
                agent_data = res

        elif intent == "PAYROLL_SUPPORT":
            if "history" in message.lower() or "past" in message.lower():
                history = await self.payroll_agent.get_salary_history(employee_id)
                decision_notes = "**Salary Net Pay History:**\n" + "\n".join(
                    f"- Month: {h['period']} - Net Pay: {h['net_pay']} ({h['status']})"
                    for h in history
                )
                agent_data = {"salary_history": history}
            else:
                payslip = await self.payroll_agent.get_latest_payslip(employee_id)
                if payslip:
                    decision_notes = (
                        f"**Latest Payslip ({payslip['period']}):**\n"
                        f"- Basic: ₹{payslip['earnings']['basic']:.2f}\n"
                        f"- HRA: ₹{payslip['earnings']['hra']:.2f}\n"
                        f"- Gross Earnings: ₹{payslip['earnings']['gross']:.2f}\n"
                        f"- PF Deduction: ₹{payslip['deductions']['provident_fund']:.2f}\n"
                        f"- TDS Tax: ₹{payslip['deductions']['tax_deducted_at_source_tds']:.2f}\n"
                        f"- **Net Take Home Pay: ₹{payslip['net_pay']:.2f}**\n"
                    )
                agent_data = {"payslip": payslip}

        elif intent == "ASSET_SUPPORT":
            if "request" in message.lower() or "need" in message.lower():
                atype = params.get("asset_type") or "mouse"
                res = await self.asset_agent.request_peripheral(employee_id, atype)
                decision_notes = res.get("message")
                agent_data = res
            elif "damage" in message.lower() or "broken" in message.lower() or "damaged" in message.lower():
                assets = await self.asset_agent.get_assigned_assets(employee_id)
                tag = assets[0]["tag"] if assets else "AST-LAP-9021"
                res = await self.asset_agent.report_damage(employee_id, tag, message)
                decision_notes = res.get("message")
                agent_data = res
            else:
                assets = await self.asset_agent.get_assigned_assets(employee_id)
                decision_notes = "**Assigned Assets:**\n" + "\n".join(
                    f"- {a['brand']} {a['model']} (Tag: {a['tag']}, Category: {a['category']})"
                    for a in assets
                )
                agent_data = {"assets": assets}

        elif intent == "IT_HELPDESK":
            guide = await self.it_agent.get_troubleshooting_guide(message)
            if guide:
                decision_notes = guide
            else:
                decision_notes = (
                    "**IT Troubleshooting:** I couldn't find a direct self-service troubleshooting guide "
                    "for your issue. Let me open an IT support ticket so our service desk team can investigate."
                )
                # Auto raise IT ticket
                res = await self.it_agent.auto_raise_it_ticket(
                    employee_id=employee_id,
                    subject=message[:80],
                    problem_description=message,
                    company_id=emp.company_id
                )
                decision_notes += f"\n\n*Auto-generated Ticket: ID {res['ticket_id']} raised in IT queue.*"
            agent_data = {"topic": message}

        elif intent == "TICKET_ACTION":
            action = params.get("action") or ""
            if "create" in action.lower() or "create" in message.lower() or "open" in message.lower():
                # Extract structured ticket parameters
                t_prompt = PromptLibrary.ticket_creation_user(message, chat_context or "")
                res_t = await self.llm.complete(
                    prompt=t_prompt,
                    system=PromptLibrary.TICKET_CREATION_SYSTEM,
                    model=model,
                    json_mode=True,
                    temperature=0.15
                )
                t_data = ResponseParser.extract_json_object(res_t)
                
                ticket = await self.ticket_agent.create_ticket(
                    employee_id=employee_id,
                    category=t_data.get("category", "GENERAL"),
                    priority=t_data.get("priority", "MEDIUM"),
                    title=t_data.get("title", "Employee Support Request"),
                    description=t_data.get("description", message),
                    company_id=emp.company_id
                )
                decision_notes = f"I've raised a support ticket for you:\n- **Ticket ID:** {ticket.id}\n- **Title:** '{ticket.title}'\n- **Category:** {ticket.category}\n- **Priority:** {ticket.priority}\nWe will keep you updated."
                agent_data = {"ticket_id": str(ticket.id)}
            elif "close" in action.lower() or "close" in message.lower():
                # Close latest ticket
                if tickets:
                    await self.ticket_agent.close_ticket(tickets[0].id)
                    decision_notes = f"Ticket '{tickets[0].title}' has been marked as resolved and closed."
                else:
                    decision_notes = "No active support tickets found to close."
            else:
                # List status of tickets
                decision_notes = "**Support Ticket History & Status:**\n" + (
                    "\n".join(f"- [{t.status}] '{t.title}' (ID: {t.id})" for t in tickets)
                ) if tickets else "You have no active support tickets."

        else:
            # GENERAL_RAG / Policy manual lookups
            # Find matching policy manuals from vector DB
            from app.models.document import CompanyDocument
            comp_docs_res = await self.db.execute(select(CompanyDocument).where(CompanyDocument.is_deleted == False))
            comp_docs = comp_docs_res.scalars().all()
            doc_ids = [str(d.id) for d in comp_docs]

            if doc_ids:
                # Query RAG
                rag_res = await self.rag.answer_question(
                    question=message,
                    document_ids=doc_ids,
                    company_id=str(emp.company_id) if emp.company_id else None,
                    model=model
                )
                decision_notes = rag_res.get("answer")
                agent_data = {"sources": rag_res.get("sources", [])}
            else:
                # General HR fallback
                system = "You are a senior HR support assistant. Answer the employee's query using standard company policy guidelines."
                ans = await self.llm.complete(prompt=message, system=system, model=model, temperature=0.3)
                decision_notes = ans
                agent_data = {"fallback": True}

        # 4. Generate final structured conversational response
        system_synth = """You are Aurix Employee Support AI.
Use the facts/database actions retrieved by our sub-agent to formulate a clear, professional, and friendly response.
Ground your response strictly on the retrieved facts. Mention specific dates, balances, names, or ticket IDs.
Do not hallucinate details."""

        prompt_synth = f"""Employee Message: "{message}"

Retrieved Sub-Agent Facts/Database Actions:
{decision_notes}

Synthesize a complete conversational response to the employee."""

        final_answer = await self.llm.complete(
            prompt=prompt_synth,
            system=system_synth,
            model=model,
            temperature=0.3
        )

        return {
            "intent": intent,
            "reply_prologue": reply_prologue,
            "sub_agent_notes": decision_notes,
            "answer": final_answer or decision_notes,
            "data": agent_data
        }

    # ------------------------------------------------------------------
    # Helper Date Parser
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_date_param(val: Any) -> Optional[date]:
        if not val:
            return None
        try:
            return datetime.strptime(str(val), "%Y-%m-%d").date()
        except ValueError:
            return None


# Import Regex helper
import re
