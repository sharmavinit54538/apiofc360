"""DigiLocker requester OAuth and issuer-document integrity verification.

Provider contract: Meri Pehchaan Authorized Partner API Specification v2.0.
No provider access/refresh tokens or document contents are persisted here.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
from urllib.parse import quote

import httpx

from app.core.config import settings


class DigiLockerFailure(ValueError):
    """A safe, user-facing provider failure without credential/body disclosure."""


def configured() -> bool:
    return bool(settings.DIGILOCKER_CLIENT_ID and settings.DIGILOCKER_CLIENT_SECRET)


def _normal(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _matches(document_type: str | None, item: dict) -> bool:
    expected = _normal(document_type or "")
    aliases = {
        "PAN": {"PAN", "PANCR", "PANCARD"},
        "AADHAAR": {"AADHAAR", "AADHAR", "ADHAR"},
        "DRIVINGLICENSE": {"DRIVINGLICENSE", "DRIVINGLICENCE", "DRVLC"},
        "PASSPORT": {"PASSPORT", "PSPRT"},
    }
    valid = next((values for values in aliases.values() if expected in values), {expected})
    return bool(expected) and any(_normal(str(item.get(key, ""))) in valid for key in ("doctype", "name", "description"))


async def fetch_evidence(*, code: str, code_verifier: str, document_type: str | None) -> dict:
    if not configured():
        raise DigiLockerFailure("DigiLocker credentials are not configured.")
    base = settings.DIGILOCKER_API_BASE_URL.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            response = await client.post(f"{base}/1/token", data={
                "grant_type": "authorization_code", "code": code,
                "client_id": settings.DIGILOCKER_CLIENT_ID,
                "client_secret": settings.DIGILOCKER_CLIENT_SECRET,
                "redirect_uri": settings.DIGILOCKER_REDIRECT_URI,
                "code_verifier": code_verifier,
            })
            response.raise_for_status()
            token = response.json()
            access = token.get("access_token")
            subject = token.get("digilockerid") or token.get("digilocker_id") or token.get("sub")
            if not isinstance(access, str) or not access or not subject or str(token.get("token_type", "")).lower() != "bearer":
                raise DigiLockerFailure("DigiLocker token response has no valid account evidence.")
            headers = {"Authorization": f"Bearer {access}"}
            response = await client.get(f"{base}/2/files/issued", headers=headers)
            response.raise_for_status()
            items = response.json().get("items", [])
            if not isinstance(items, list):
                raise DigiLockerFailure("DigiLocker returned invalid issued-document metadata.")
            matching = [item for item in items if isinstance(item, dict) and item.get("uri") and item.get("issuerid") and _matches(document_type, item)]
            if not matching:
                raise DigiLockerFailure("DigiLocker has no issued document matching this document type.")
            item = matching[0]
            response = await client.get(f"{base}/1/file/{quote(str(item['uri']), safe='')}", headers=headers)
            response.raise_for_status()
            content = response.content
            expected = base64.b64encode(hmac.new(settings.DIGILOCKER_CLIENT_SECRET.encode(), content, hashlib.sha256).digest()).decode()
            received = response.headers.get("hmac", "")
            if not content or not received or not hmac.compare_digest(expected, received):
                raise DigiLockerFailure("DigiLocker document integrity evidence is missing or invalid.")
            return {
                "provider": "digilocker", "digilocker_user_id": str(subject),
                "documents_fetched": [str(item.get("name") or item["doctype"])],
                "uri": item["uri"], "issuer_id": item["issuerid"],
                "document_type": item.get("doctype"), "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content), "integrity_verified": True,
            }
    except httpx.HTTPStatusError as exc:
        raise DigiLockerFailure(f"DigiLocker provider returned HTTP {exc.response.status_code}; verification was not completed.") from exc
    except httpx.RequestError as exc:
        raise DigiLockerFailure("DigiLocker provider is unavailable; initiate authorization again to retry.") from exc
    except (TypeError, KeyError, ValueError) as exc:
        if isinstance(exc, DigiLockerFailure):
            raise
        raise DigiLockerFailure("DigiLocker returned malformed provider evidence.") from exc
