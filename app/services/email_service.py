"""Email service layer – real SMTP transactional email sending.

Supports:
- STARTTLS (SMTP_USE_TLS=true, typically port 587)
- SSL      (SMTP_USE_SSL=true, typically port 465)
- Plain     (neither flag set, for internal relay / local dev MailHog)

Retry policy: 3 attempts with exponential back-off (1 s, 2 s).
Raises RuntimeError if all attempts fail so FastAPI returns HTTP 500.
"""

from __future__ import annotations

import asyncio
import logging
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

_SMTP_TIMEOUT = 15          # seconds per connection / operation
_SMTP_MAX_RETRIES = 3       # total attempts before giving up


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

def _render_template(template_name: str, context: dict) -> str:
    """Render an HTML email template.

    Supports:
    - ``{{ key }}`` and ``{{key}}`` variable substitution
    - ``{% if key %}...{% endif %}`` conditional blocks (shows block when value is truthy)
    - ``{% if key %}...{% else %}...{% endif %}`` optional else branch
    - Strips any unrecognised ``{% ... %}`` tags that remain (never leaks raw Jinja)
    """

    template_path = Path(__file__).parent.parent / "templates" / template_name
    try:
        with open(template_path, encoding="utf-8") as fh:
            content = fh.read()
    except FileNotFoundError:
        logger.error("Email template not found: %s", template_path)
        raise RuntimeError(f"Email template not found: {template_name}")

    # ── 1. Process {% if key %}...{% else %}...{% endif %} blocks ──────────
    def _process_if_else(m: re.Match) -> str:
        key = m.group(1).strip()
        if_body = m.group(2)
        else_body = m.group(3) or ""
        val = context.get(key)
        return if_body if val else else_body

    # with else
    content = re.sub(
        r"{%\s*if\s+(\w+)\s*%}(.*?){%\s*else\s*%}(.*?){%\s*endif\s*%}",
        _process_if_else,
        content,
        flags=re.DOTALL,
    )

    # without else
    def _process_if(m: re.Match) -> str:
        key = m.group(1).strip()
        body = m.group(2)
        val = context.get(key)
        return body if val else ""

    content = re.sub(
        r"{%\s*if\s+(\w+)\s*%}(.*?){%\s*endif\s*%}",
        _process_if,
        content,
        flags=re.DOTALL,
    )

    # ── 2. Strip any remaining {% ... %} tags so they never appear ─────────
    content = re.sub(r"{%.*?%}", "", content, flags=re.DOTALL)

    # ── 3. Replace {{ key }} and {{key}} variables ──────────────────────────
    for key, value in context.items():
        safe = str(value) if value is not None else ""
        content = content.replace(f"{{{{ {key} }}}}", safe)
        content = content.replace(f"{{{{{key}}}}}", safe)

    # ── 4. Remove any unreplaced {{ placeholders }} so they don't leak ──────
    content = re.sub(r"\{\{.*?\}\}", "", content)

    return content


def _html_to_plain(html: str) -> str:
    """Very lightweight HTML → plain-text converter for the fallback MIME part."""

    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Synchronous SMTP worker (runs in a thread via asyncio.to_thread)
# ---------------------------------------------------------------------------

def _build_message(to_email: str, subject: str, html_content: str) -> MIMEMultipart:
    """Construct a MIMEMultipart/alternative message with plain-text + HTML parts."""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    msg["To"] = to_email
    msg["X-Mailer"] = "HRMS-Mailer/1.0"

    plain_text = _html_to_plain(html_content)
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))
    return msg


def _send_via_smtp(to_email: str, subject: str, html_content: str) -> None:
    """Synchronous SMTP send.  Called inside asyncio.to_thread()."""

    msg = _build_message(to_email, subject, html_content)
    raw = msg.as_string()

    host = settings.SMTP_HOST
    port = settings.SMTP_PORT
    username = settings.SMTP_USERNAME
    password = settings.SMTP_PASSWORD.get_secret_value() if settings.SMTP_PASSWORD else None

    logger.info(
        "SMTP connecting | host=%s port=%d tls=%s ssl=%s user=%s to=%s subject=%r",
        host, port, settings.SMTP_USE_TLS, settings.SMTP_USE_SSL, username, to_email, subject,
    )

    if settings.SMTP_USE_SSL:
        # Direct SSL connection (port 465)
        with smtplib.SMTP_SSL(host, port, timeout=_SMTP_TIMEOUT) as server:
            server.set_debuglevel(0)
            if username and password:
                server.login(username, password)
            server.sendmail(settings.SMTP_FROM_EMAIL, to_email, raw)
            logger.info("SMTP SSL send OK | to=%s", to_email)

    else:
        # Plain SMTP, optionally upgraded via STARTTLS (port 587 or 25)
        with smtplib.SMTP(host, port, timeout=_SMTP_TIMEOUT) as server:
            server.set_debuglevel(0)
            server.ehlo()
            if settings.SMTP_USE_TLS:
                server.starttls()
                server.ehlo()
            if username and password:
                server.login(username, password)
            server.sendmail(settings.SMTP_FROM_EMAIL, to_email, raw)
            logger.info("SMTP STARTTLS send OK | to=%s", to_email)


# ---------------------------------------------------------------------------
# Async wrapper with retry logic
# ---------------------------------------------------------------------------

async def send_email(to_email: str, subject: str, html_content: str) -> None:
    """Send an HTML email (with plain-text fallback) over real SMTP.

    Retries up to ``_SMTP_MAX_RETRIES`` times with exponential back-off.
    In local/debug environments logs failure but does NOT raise, so the
    application continues. In production raises ``RuntimeError`` so the
    caller can surface an appropriate HTTP error.
    """

    last_exc: Exception | None = None
    is_local = settings.ENVIRONMENT.lower() in {"local", "development", "dev"} or settings.DEBUG
    max_attempts = 1 if is_local else _SMTP_MAX_RETRIES

    for attempt in range(1, max_attempts + 1):
        try:
            logger.info(
                "Email send attempt %d/%d | to=%s | subject=%r",
                attempt, max_attempts, to_email, subject,
            )
            await asyncio.to_thread(_send_via_smtp, to_email, subject, html_content)
            logger.info(
                "Email delivered | attempt=%d | to=%s | subject=%r",
                attempt, to_email, subject,
            )
            return

        except smtplib.SMTPAuthenticationError as exc:
            logger.error(
                "SMTP AUTH FAILED | to=%s | user=%s | error=%s",
                to_email, settings.SMTP_USERNAME, exc,
                exc_info=True,
            )
            last_exc = exc
            break  # Auth errors will never succeed on retry

        except smtplib.SMTPRecipientsRefused as exc:
            logger.error(
                "SMTP RECIPIENTS REFUSED | to=%s | error=%s", to_email, exc, exc_info=True,
            )
            last_exc = exc
            break

        except smtplib.SMTPException as exc:
            last_exc = exc
            logger.warning(
                "SMTP error attempt %d/%d | to=%s | error=%s",
                attempt, max_attempts, to_email, exc, exc_info=True,
            )
            if attempt < max_attempts:
                await asyncio.sleep(2 ** (attempt - 1))

        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Email error attempt %d/%d | to=%s | error=%s",
                attempt, max_attempts, to_email, exc, exc_info=True,
            )
            if attempt < max_attempts:
                await asyncio.sleep(2 ** (attempt - 1))

    # All attempts exhausted
    logger.error(
        "Email delivery FAILED after %d attempt(s) | to=%s | subject=%r | error=%s",
        max_attempts, to_email, subject, last_exc,
        exc_info=last_exc,
    )

    if is_local:
        logger.warning(
            "LOCAL DEV: email not delivered (SMTP failure). Check SMTP settings. "
            "to=%s subject=%r error=%s",
            to_email, subject, last_exc,
        )
        # Print plain-text version to console for easy dev debugging
        print(
            f"\n{'='*60}\n"
            f"[DEV EMAIL LOG] To: {to_email}\nSubject: {subject}\n"
            f"{'='*60}\n"
            f"{_html_to_plain(html_content)}\n"
            f"{'='*60}\n"
        )

    raise RuntimeError(
        f"Failed to send email to {to_email!r} after {max_attempts} attempts: {last_exc}"
    ) from last_exc


# ---------------------------------------------------------------------------
# EmailService class
# ---------------------------------------------------------------------------


class EmailService:
    """High-level transactional email sender.

    Every public method renders an HTML template, builds a proper MIME
    message (HTML + plain-text), and delivers it via real SMTP.
    """

    # ---- Auth / registration emails ----------------------------------------

    async def send_verification_email(
        self, email: str, name: str, otp: str, expiry_minutes: int, company_name: str = "Aurix HR"
    ) -> None:
        """Send account registration OTP email."""

        html = _render_template(
            "verify_email.html",
            {
                "name": name,
                "otp": otp,
                "expiry_minutes": str(expiry_minutes),
                "logo_url": settings.COMPANY_LOGO_URL or "",
                "support_email": "support@aurix.com",
                "company_name": company_name,
            },
        )
        await send_email(email, "Verify Your Email Address", html)

    async def send_welcome_email(self, email: str, name: str) -> None:
        """Send welcoming email on verification success."""

        html = _render_template("welcome_email.html", {"name": name})
        await send_email(email, "Welcome to HRMS!", html)

    async def send_password_reset_email(
        self, email: str, name: str, token: str
    ) -> None:
        """Send password reset OTP email."""

        html = _render_template(
            "password_reset_email.html", {"name": name, "token": token}
        )
        await send_email(email, "Reset Your Password", html)

    async def send_email_change_otp(
        self, email: str, name: str, otp: str, expiry_minutes: int
    ) -> None:
        """Send OTP to the new email address during change-email flow."""

        html = _render_template(
            "email_change_otp.html",
            {"name": name, "otp": otp, "expiry_minutes": str(expiry_minutes)},
        )
        await send_email(email, "Verify Your New Email Address", html)

    # ---- Employee emails ----------------------------------------------------

    async def send_employee_activation_email(
        self,
        email: str,
        name: str,
        employee_id: str,
        activation_url: str,
        temp_password: str | None,
        expiry_hours: int,
        company_name: str = "Our Company",
        login_email: str = "",
    ) -> None:
        """Send activation link and temporary password to a new employee."""

        html = _render_template(
            "employee_activation.html",
            {
                "name": name,
                "employee_id": employee_id,
                "activation_url": activation_url,
                "temp_password": temp_password or "",
                "expiry_hours": str(expiry_hours),
                "company_name": company_name,
                "login_email": login_email or email,
            },
        )
        await send_email(email, "Activate Your HRMS Employee Account", html)

    async def send_employee_onboarding_invite(
        self,
        *,
        email: str,
        name: str,
        employee_id: str,
        department: str,
        designation: str,
        joining_date: str,
        activation_url: str,
        company_name: str,
        support_email: str = "support@aurix.com",
    ) -> None:
        """Send onboarding link to a new employee."""

        html = _render_template(
            "employee_onboarding_invite.html",
            {
                "name": name,
                "employee_id": employee_id,
                "department": department,
                "designation": designation,
                "joining_date": joining_date,
                "activation_url": activation_url,
                "company_name": company_name,
                "logo_url": settings.COMPANY_LOGO_URL or "",
                "support_email": support_email,
            },
        )
        await send_email(email, f"Welcome to {company_name} – Complete Your Account", html)

    async def send_employee_welcome_email(
        self, email: str, name: str, employee_id: str
    ) -> None:
        """Send welcome email after employee account activation is approved."""

        html = _render_template(
            "employee_welcome.html",
            {"name": name, "employee_id": employee_id},
        )
        await send_email(email, "Welcome to the Team! Account Activated", html)

    async def send_employee_password_reset_email(
        self, email: str, name: str, temp_password: str
    ) -> None:
        """Send temporary password to employee after admin password reset."""

        html = _render_template(
            "employee_password_reset.html",
            {"name": name, "temp_password": temp_password},
        )
        await send_email(email, "Your Employee Account Password Has Been Reset", html)

    # ---- Manager emails -----------------------------------------------------

    async def send_manager_onboarding_invite(
        self,
        *,
        email: str,
        name: str,
        employee_id: str,
        department: str,
        designation: str,
        joining_date: str,
        activation_url: str,
        company_name: str,
        support_email: str = "support@aurix.com",
    ) -> None:
        """Send onboarding link to a new manager."""

        html = _render_template(
            "manager_onboarding_invite.html",
            {
                "name": name,
                "employee_id": employee_id,
                "department": department,
                "designation": designation,
                "joining_date": joining_date,
                "activation_url": activation_url,
                "company_name": company_name,
                "logo_url": settings.COMPANY_LOGO_URL or "",
                "support_email": support_email,
            },
        )
        await send_email(email, f"Welcome to {company_name} – Complete Your Account", html)

    async def send_manager_activation_email(
        self,
        email: str,
        name: str,
        employee_id: str,
        activation_url: str,
        temp_password: str | None,
        expiry_hours: int,
        company_name: str = "Our Company",
        login_email: str = "",
    ) -> None:
        """Send activation link and temporary password to a new manager."""

        html = _render_template(
            "manager_activation.html",
            {
                "name": name,
                "employee_id": employee_id,
                "activation_url": activation_url,
                "temp_password": temp_password or "",
                "expiry_hours": str(expiry_hours),
                "company_name": company_name,
                "login_email": login_email or email,
            },
        )
        await send_email(email, "Activate Your HRMS Manager Account", html)

    async def send_manager_welcome_email(
        self, email: str, name: str, employee_id: str
    ) -> None:
        """Send welcome email after manager account activation is completed."""

        html = _render_template(
            "manager_welcome.html",
            {"name": name, "employee_id": employee_id},
        )
        await send_email(email, "Welcome to the Team! Account Activated", html)

    async def send_manager_password_reset_email(
        self, email: str, name: str, temp_password: str
    ) -> None:
        """Send temporary password to manager after admin password reset."""

        html = _render_template(
            "manager_password_reset.html",
            {"name": name, "temp_password": temp_password},
        )
        await send_email(email, "Your Manager Account Password Has Been Reset", html)

    # ---- Recruitment emails -------------------------------------------------

    async def send_recruitment_confirm_email(
        self, email: str, name: str, job_title: str
    ) -> None:
        """Send application confirmation email to candidate."""

        html = _render_template(
            "recruitment_confirm.html",
            {"name": name, "job_title": job_title},
        )
        await send_email(email, f"Application Received - {job_title}", html)

    async def send_recruitment_reject_email(
        self, email: str, name: str, job_title: str
    ) -> None:
        """Send application rejection email to candidate."""

        html = _render_template(
            "recruitment_reject.html",
            {"name": name, "job_title": job_title},
        )
        await send_email(email, f"Application Update - {job_title}", html)

    async def send_recruitment_interview_email(
        self, email: str, name: str, job_title: str, schedule_url: str
    ) -> None:
        """Send interview scheduling invitation email to candidate."""

        html = _render_template(
            "recruitment_interview.html",
            {"name": name, "job_title": job_title, "schedule_url": schedule_url},
        )
        await send_email(email, f"Interview Invitation - {job_title}", html)

    async def send_recruitment_offer_email(
        self,
        email: str,
        name: str,
        job_title: str,
        ctc: str,
        joining_date: str,
        expiry_date: str,
        offer_url: str,
    ) -> None:
        """Send job offer email to selected candidate."""

        html = _render_template(
            "recruitment_offer.html",
            {
                "name": name,
                "job_title": job_title,
                "ctc": ctc,
                "joining_date": joining_date,
                "expiry_date": expiry_date,
                "offer_url": offer_url,
            },
        )
        await send_email(email, f"Job Offer from Aurix - {job_title}", html)


# ---------------------------------------------------------------------------
# Dependency injection
# ---------------------------------------------------------------------------

_email_service = EmailService()


def get_email_service() -> EmailService:
    """FastAPI dependency provider for EmailService."""

    return _email_service