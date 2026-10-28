"""Google Workspace / Microsoft Entra OIDC and signed SAML 2.0 SSO."""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from jose import jwt
from lxml import etree
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password
from app.models.enterprise_auth import ExternalIdentity, IdentityProvider, SSOAssertion
from app.models.user import User

SAML_NS = {"saml2": "urn:oasis:names:tc:SAML:2.0:assertion", "saml2p": "urn:oasis:names:tc:SAML:2.0:protocol", "ds": "http://www.w3.org/2000/09/xmldsig#"}
EXCLUSIVE_C14N = "http://www.w3.org/2001/10/xml-exc-c14n#"


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


class SSOService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def configure_provider(
        self, *, company_id: uuid.UUID, provider_type: str,
        allowed_domains: list[str], client_id: str | None = None,
        client_secret: str | None = None, issuer: str | None = None,
        authorization_endpoint: str | None = None, token_endpoint: str | None = None,
        jwks_uri: str | None = None, saml_sso_url: str | None = None,
        sp_entity_id: str | None = None, x509_certificate: str | None = None,
    ) -> IdentityProvider:
        provider_type = provider_type.upper()
        if provider_type not in {"GOOGLE_OIDC", "MICROSOFT_OIDC", "SAML"}:
            raise ValueError("Unsupported identity provider.")
        domains = sorted({domain.strip().lower().lstrip("@") for domain in allowed_domains if domain.strip()})
        if not domains:
            raise ValueError("At least one allowed email domain is required for SSO.")
        if provider_type != "SAML" and not all((client_id, issuer, authorization_endpoint, token_endpoint, jwks_uri)):
            raise ValueError("OIDC client and endpoint configuration is incomplete.")
        if provider_type == "SAML" and not (x509_certificate and sp_entity_id):
            raise ValueError("SAML requires the IdP X.509 signing certificate and SP entity ID.")
        provider = (await self.session.execute(select(IdentityProvider).where(
            IdentityProvider.company_id == company_id, IdentityProvider.provider_type == provider_type,
        ))).scalar_one_or_none()
        provider = provider or IdentityProvider(id=uuid.uuid4(), company_id=company_id, provider_type=provider_type)
        for key, value in {
            "client_id": client_id, "client_secret": client_secret, "issuer": issuer,
            "authorization_endpoint": authorization_endpoint, "token_endpoint": token_endpoint,
            "jwks_uri": jwks_uri, "saml_sso_url": saml_sso_url, "sp_entity_id": sp_entity_id,
            "x509_certificate": x509_certificate,
        }.items():
            if value is not None:
                setattr(provider, key, value)
        provider.allowed_domains = domains
        provider.is_active = True
        self.session.add(provider)
        await self.session.commit()
        return provider

    async def _provider(self, company_id: uuid.UUID, provider_type: str) -> IdentityProvider:
        provider = (await self.session.execute(select(IdentityProvider).where(
            IdentityProvider.company_id == company_id,
            IdentityProvider.provider_type == provider_type.upper(), IdentityProvider.is_active.is_(True),
        ))).scalar_one_or_none()
        if provider is None:
            raise LookupError("Identity provider not found or inactive.")
        return provider

    async def authorization_url(
        self, *, company_id: uuid.UUID, provider_type: str,
        redirect_uri: str, state: str, nonce: str,
    ) -> str:
        provider = await self._provider(company_id, provider_type)
        if not provider.client_id or not provider.authorization_endpoint:
            raise ValueError("OIDC provider is not configured.")
        query = urlencode({
            "client_id": provider.client_id, "response_type": "code", "scope": "openid email profile",
            "redirect_uri": redirect_uri, "state": state, "nonce": nonce,
        })
        return f"{provider.authorization_endpoint}?{query}"

    async def _token_and_jwks(self, provider: IdentityProvider, code: str, redirect_uri: str) -> tuple[str, dict]:
        if not provider.client_secret:
            raise ValueError("OIDC client secret is not configured.")
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            token_response = await client.post(provider.token_endpoint, data={
                "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                "client_id": provider.client_id, "client_secret": provider.client_secret,
            })
            token_response.raise_for_status()
            token_data = token_response.json()
            jwks_response = await client.get(provider.jwks_uri)
            jwks_response.raise_for_status()
            jwks = jwks_response.json()
        id_token = token_data.get("id_token")
        if not id_token or not isinstance(jwks, dict):
            raise ValueError("OIDC provider response is incomplete.")
        return id_token, jwks

    async def authenticate_oidc(
        self, *, company_id: uuid.UUID, provider_type: str,
        code: str, redirect_uri: str, expected_nonce: str,
        id_token: str | None = None, jwks: dict | None = None,
    ) -> User:
        provider = await self._provider(company_id, provider_type)
        if id_token is None or jwks is None:
            id_token, jwks = await self._token_and_jwks(provider, code, redirect_uri)
        try:
            claims = jwt.decode(
                id_token, jwks, algorithms=["RS256"], audience=provider.client_id,
                issuer=provider.issuer, options={"verify_at_hash": False},
            )
        except Exception as exc:
            raise PermissionError("OIDC ID token validation failed.") from exc
        if not expected_nonce or not hmac.compare_digest(str(claims.get("nonce") or ""), expected_nonce):
            raise PermissionError("OIDC nonce validation failed.")
        email = str(claims.get("email") or claims.get("preferred_username") or "").lower()
        if not claims.get("sub") or not email:
            raise PermissionError("OIDC identity claims are incomplete.")
        if provider_type.upper() == "GOOGLE_OIDC" and claims.get("email_verified") is False:
            raise PermissionError("OIDC email address is not verified.")
        return await self._provision_identity(
            company_id=company_id, provider=provider, external_id=str(claims["sub"]),
            email=email, first_name=claims.get("given_name"), last_name=claims.get("family_name"),
            attributes={key: claims.get(key) for key in ("sub", "iss", "hd", "tid", "locale") if claims.get(key) is not None},
        )

    async def _provision_identity(
        self, *, company_id: uuid.UUID, provider: IdentityProvider,
        external_id: str, email: str, first_name: str | None = None,
        last_name: str | None = None, attributes: dict | None = None,
    ) -> User:
        email = email.strip().lower()
        domain = email.rsplit("@", 1)[-1]
        if "@" not in email or domain not in provider.allowed_domains:
            raise PermissionError("SSO email domain is not allowed for this tenant.")
        user = (await self.session.execute(select(User).where(User.email == email).execution_options(bypass_tenant=True))).scalar_one_or_none()
        if user is not None and user.company_id != company_id:
            raise PermissionError("SSO identity belongs to a different tenant.")
        if user is None:
            user = User(
                id=uuid.uuid4(), company_id=company_id, email=email,
                name=" ".join(filter(None, [first_name, last_name])) or email.split("@")[0],
                phone=str(uuid.uuid4().int)[:10], password_hash=hash_password(secrets.token_urlsafe(32)),
                role="employee", is_active=True, is_verified=True, account_status="ACTIVE",
                onboarding_completed=False,
            )
            self.session.add(user)
            await self.session.flush()
        if user.is_deleted or not user.is_active or user.account_status in {"DEACTIVATED", "SUSPENDED", "INACTIVE"}:
            raise PermissionError("SSO user has been deprovisioned or disabled.")
        identity = (await self.session.execute(select(ExternalIdentity).where(
            ExternalIdentity.company_id == company_id, ExternalIdentity.provider_type == provider.provider_type,
            ExternalIdentity.external_id == external_id,
        ))).scalar_one_or_none()
        if identity and identity.user_id != user.id:
            raise PermissionError("External identity is already linked to another user.")
        identity = identity or ExternalIdentity(
            id=uuid.uuid4(), company_id=company_id, provider_type=provider.provider_type, external_id=external_id,
        )
        identity.user_id = user.id
        identity.attributes_json = attributes or {}
        identity.last_login_at = _now()
        user.last_login_at = identity.last_login_at
        self.session.add(identity)
        await self.session.commit()
        return user

    async def authenticate_saml(
        self, *, company_id: uuid.UUID, encoded_response: str,
        recipient_url: str, now: datetime | None = None,
    ) -> User:
        provider = await self._provider(company_id, "SAML")
        try:
            raw = base64.b64decode(encoded_response, validate=True)
        except Exception as exc:
            raise ValueError("SAMLResponse is not valid base64.") from exc
        if not raw or len(raw) > 2 * 1024 * 1024:
            raise ValueError("SAML response size is invalid.")
        claims = self.validate_saml_assertion(
            raw, certificate_pem=provider.x509_certificate or "", recipient_url=recipient_url,
            expected_audience=provider.sp_entity_id or "", now=now,
        )
        consumed = (await self.session.execute(select(SSOAssertion).where(
            SSOAssertion.company_id == company_id, SSOAssertion.assertion_id == claims["assertion_id"],
        ))).scalar_one_or_none()
        if consumed is not None:
            raise PermissionError("SAML assertion has already been consumed.")
        self.session.add(SSOAssertion(
            id=uuid.uuid4(), company_id=company_id, assertion_id=claims["assertion_id"],
            expires_at=claims["expires_at"],
        ))
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise PermissionError("SAML assertion has already been consumed.") from exc
        return await self._provision_identity(
            company_id=company_id, provider=provider, external_id=claims["name_id"],
            email=claims["email"], first_name=claims.get("first_name"), last_name=claims.get("last_name"),
            attributes=claims.get("attributes", {}),
        )

    @staticmethod
    def validate_saml_assertion(
        raw_xml: bytes, *, certificate_pem: str, recipient_url: str,
        expected_audience: str, now: datetime | None = None,
    ) -> dict[str, Any]:
        """Verify a signed SAML assertion (RSA-SHA256 + SHA256, exclusive C14N)."""
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        from cryptography.x509 import load_pem_x509_certificate
        now = now or _now()
        parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
        try:
            root = etree.fromstring(raw_xml, parser=parser)
        except etree.XMLSyntaxError as exc:
            raise PermissionError("Invalid SAML XML.") from exc
        assertions = root.xpath(".//saml2:Assertion", namespaces=SAML_NS)
        if len(assertions) != 1:
            raise PermissionError("SAML response must contain exactly one assertion.")
        assertion = assertions[0]
        assertion_id = assertion.get("ID")
        signatures = assertion.xpath("./ds:Signature", namespaces=SAML_NS)
        if not assertion_id or len(signatures) != 1:
            raise PermissionError("SAML assertion must contain one XML signature.")
        signature = signatures[0]
        signed_info = signature.find("ds:SignedInfo", SAML_NS)
        if signed_info is None:
            raise PermissionError("SAML SignedInfo is missing.")
        signature_method = signed_info.find("ds:SignatureMethod", SAML_NS)
        c14n_method = signed_info.find("ds:CanonicalizationMethod", SAML_NS)
        if signature_method is None or signature_method.get("Algorithm") != "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256":
            raise PermissionError("Only RSA-SHA256 SAML signatures are accepted.")
        if c14n_method is None or c14n_method.get("Algorithm") != EXCLUSIVE_C14N:
            raise PermissionError("Only exclusive XML canonicalization is accepted.")
        references = signed_info.findall("ds:Reference", SAML_NS)
        if len(references) != 1 or references[0].get("URI") != f"#{assertion_id}":
            raise PermissionError("SAML signature must reference the assertion.")
        reference = references[0]
        digest_method = reference.find("ds:DigestMethod", SAML_NS)
        digest_value = reference.findtext("ds:DigestValue", namespaces=SAML_NS)
        if digest_method is None or digest_method.get("Algorithm") != "http://www.w3.org/2001/04/xmlenc#sha256" or not digest_value:
            raise PermissionError("Only SHA-256 SAML assertion digests are accepted.")
        transforms = [item.get("Algorithm") for item in reference.findall("ds:Transforms/ds:Transform", SAML_NS)]
        if set(transforms) != {"http://www.w3.org/2000/09/xmldsig#enveloped-signature", EXCLUSIVE_C14N} or len(transforms) != 2:
            raise PermissionError("SAML reference transforms are invalid.")
        unsigned = copy.deepcopy(assertion)
        for item in unsigned.xpath("./ds:Signature", namespaces=SAML_NS):
            item.getparent().remove(item)
        canonical_assertion = etree.tostring(unsigned, method="c14n", exclusive=True, with_comments=False)
        actual_digest = base64.b64encode(hashlib.sha256(canonical_assertion).digest()).decode()
        if not hmac.compare_digest(actual_digest, digest_value.strip()):
            raise PermissionError("SAML assertion digest validation failed.")
        signature_value = signature.findtext("ds:SignatureValue", namespaces=SAML_NS)
        if not signature_value:
            raise PermissionError("SAML signature value is missing.")
        try:
            certificate = load_pem_x509_certificate(certificate_pem.encode())
            public_key = certificate.public_key()
            if not isinstance(public_key, rsa.RSAPublicKey):
                raise PermissionError("SAML IdP certificate must contain an RSA public key.")
            public_key.verify(
                base64.b64decode("".join(signature_value.split()), validate=True),
                etree.tostring(signed_info, method="c14n", exclusive=True, with_comments=False),
                padding.PKCS1v15(), hashes.SHA256(),
            )
        except PermissionError:
            raise
        except Exception as exc:
            raise PermissionError("SAML assertion signature validation failed.") from exc
        conditions = assertion.find("saml2:Conditions", SAML_NS)
        audience = assertion.findtext("saml2:Conditions/saml2:AudienceRestriction/saml2:Audience", namespaces=SAML_NS)
        if conditions is None or not audience or not expected_audience or audience != expected_audience:
            raise PermissionError("SAML conditions and expected audience are required.")
        skew = timedelta(seconds=60)
        not_before = conditions.get("NotBefore")
        not_after = conditions.get("NotOnOrAfter")
        if not_before and now + skew < _parse_time(not_before):
            raise PermissionError("SAML assertion is not yet valid.")
        if not_after and now - skew >= _parse_time(not_after):
            raise PermissionError("SAML assertion has expired.")
        confirmation = assertion.find("saml2:Subject/saml2:SubjectConfirmation/saml2:SubjectConfirmationData", SAML_NS)
        if confirmation is None or confirmation.get("Recipient") != recipient_url:
            raise PermissionError("SAML recipient validation failed.")
        if confirmation.get("NotOnOrAfter") and now - skew >= _parse_time(confirmation.get("NotOnOrAfter")):
            raise PermissionError("SAML subject confirmation has expired.")
        name_id = assertion.findtext("saml2:Subject/saml2:NameID", namespaces=SAML_NS)
        attributes = {}
        for item in assertion.findall("saml2:AttributeStatement/saml2:Attribute", SAML_NS):
            values = [value.text or "" for value in item.findall("saml2:AttributeValue", SAML_NS)]
            attributes[item.get("Name", "")] = values[0] if len(values) == 1 else values
        email = str(attributes.get("email") or attributes.get("mail") or name_id or "").lower()
        if not name_id or not email:
            raise PermissionError("SAML NameID and email are required.")
        return {
            "name_id": name_id, "email": email, "audience": audience,
            "assertion_id": assertion_id, "expires_at": _parse_time(not_after) if not_after else now + timedelta(minutes=10),
            "first_name": attributes.get("first_name") or attributes.get("given_name"),
            "last_name": attributes.get("last_name") or attributes.get("surname"), "attributes": attributes,
        }
