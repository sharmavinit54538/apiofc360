"""Small WhatsApp delivery adapter used by payroll workers.

A provider webhook can be configured with ``WHATSAPP_WEBHOOK_URL``.  Keeping
this adapter separate means tests and installations can replace the transport
without changing payslip workflow code.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


async def send_whatsapp_message(
    to_phone: str,
    message: str,
    *,
    attachment: tuple[str, bytes, str] | None = None,
) -> dict[str, Any]:
    """Send a message/document through the configured provider webhook.

    In a local installation without a provider, the message is logged and a
    ``SIMULATED`` result is returned.  Production/staging without a provider
    fails explicitly rather than recording a false successful delivery.
    """
    url = os.getenv("WHATSAPP_WEBHOOK_URL", "").strip()
    if not url:
        environment = os.getenv("ENVIRONMENT", "local").lower()
        if environment in {"production", "prod", "staging"}:
            raise RuntimeError("WHATSAPP_WEBHOOK_URL is not configured")
        logger.info("WhatsApp provider not configured; simulated delivery to %s", to_phone)
        return {"status": "SIMULATED", "to": to_phone}

    payload: dict[str, Any] = {"to": to_phone, "message": message}
    files = None
    if attachment is not None:
        filename, content, mime_type = attachment
        # Providers commonly accept a base64/data field; the webhook adapter
        # keeps the document out of logs and sends it as multipart content.
        files = {"document": (filename, content, mime_type)}
        payload["filename"] = filename
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, data=payload, files=files)
        response.raise_for_status()
    return {"status": "SENT", "to": to_phone, "provider_status": response.status_code}


# Backward/integration-friendly alias.
send_whatsapp = send_whatsapp_message

__all__ = ["send_whatsapp_message", "send_whatsapp"]
