"""Public WhatsApp Cloud API verification and inbound webhook."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.services.whatsapp_bot_service import WhatsAppBotService

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp Bot v2"])


@router.get("/webhook")
async def verify_whatsapp_webhook(
    mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> Response:
    try:
        value = WhatsAppBotService.verify_webhook(mode, token, challenge)
        return Response(content=value, media_type="text/plain")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/webhook")
async def receive_whatsapp_webhook(
    request: Request,
    signature: Annotated[str | None, Header(alias="X-Hub-Signature-256")] = None,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    raw = await request.body()
    try:
        WhatsAppBotService.validate_signature(raw, signature)
        payload = await request.json()
        responses = await WhatsAppBotService(db).handle_inbound(payload)
        # Always acknowledge processed messages so Meta does not repeatedly
        # deliver them.  Application validation errors are returned in the reply.
        return {"status": "ok", "responses": responses}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid WhatsApp webhook payload") from exc
