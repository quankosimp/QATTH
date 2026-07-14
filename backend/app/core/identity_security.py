from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.hashes import SHA256
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.db import get_db
from backend.app.core.errors import AppError
from backend.app.models.db import AuthToken, User
from backend.app.models.identity import AuthIdentity, UserProductProfile, UserSession

logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _timestamp(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class ProductCurrentUser:
    id: str
    email: str
    role: str
    email_verified: bool
    scopes: frozenset[str]
    session_id: str | None


class OidcVerifier:
    _lock = threading.Lock()
    _jwks: dict[str, Any] = {}
    _jwks_expires_at = 0.0
    _jwks_uri: str | None = None

    def __init__(self) -> None:
        self.settings = get_settings()
        self.issuer = str(getattr(self.settings, "oidc_issuer", "") or "").rstrip("/")
        self.audience = str(getattr(self.settings, "oidc_audience", "") or "")
        self.configured_jwks_uri = str(getattr(self.settings, "oidc_jwks_url", "") or "")
        self.clock_skew = int(getattr(self.settings, "oidc_clock_skew_seconds", 60) or 60)

    def verify(self, token: str) -> dict[str, Any]:
        parts = token.split(".")
        if len(parts) != 3:
            raise self._invalid_token("Malformed bearer token")
        try:
            header = json.loads(_b64decode(parts[0]))
            claims = json.loads(_b64decode(parts[1]))
            signature = _b64decode(parts[2])
        except (ValueError, json.JSONDecodeError) as exc:
            raise self._invalid_token("Malformed bearer token") from exc
        if header.get("alg") != "RS256" or not header.get("kid"):
            raise self._invalid_token("Unsupported token algorithm")
        key = self._key(str(header["kid"]))
        try:
            public_key = rsa.RSAPublicNumbers(
                int.from_bytes(_b64decode(key["e"]), "big"),
                int.from_bytes(_b64decode(key["n"]), "big"),
            ).public_key()
            public_key.verify(signature, (parts[0] + "." + parts[1]).encode(), padding.PKCS1v15(), SHA256())
        except Exception as exc:
            raise self._invalid_token("Invalid token signature") from exc
        self._validate_claims(claims)
        return claims

    def _validate_claims(self, claims: dict[str, Any]) -> None:
        now = int(time.time())
        if not self.issuer or claims.get("iss", "").rstrip("/") != self.issuer:
            raise self._invalid_token("Invalid token issuer")
        audience = claims.get("aud", [])
        audiences = [audience] if isinstance(audience, str) else audience
        if not self.audience or self.audience not in audiences:
            raise self._invalid_token("Invalid token audience")
        if not claims.get("sub"):
            raise self._invalid_token("Token subject is required")
        if _timestamp(claims.get("exp")) < now - self.clock_skew:
            raise self._invalid_token("Token has expired")
        if _timestamp(claims.get("nbf"), now) > now + self.clock_skew:
            raise self._invalid_token("Token is not active")

    def _key(self, kid: str) -> dict[str, Any]:
        keys = self._load_jwks()
        key = next((candidate for candidate in keys if candidate.get("kid") == kid), None)
        if key is None:
            with self._lock:
                self._jwks_expires_at = 0
            keys = self._load_jwks()
            key = next((candidate for candidate in keys if candidate.get("kid") == kid), None)
        if key is None:
            raise self._invalid_token("Unknown signing key")
        return key

    def _load_jwks(self) -> list[dict[str, Any]]:
        now = time.time()
        if self._jwks and now < self._jwks_expires_at:
            return list(self._jwks.get("keys", []))
        with self._lock:
            if self._jwks and now < self._jwks_expires_at:
                return list(self._jwks.get("keys", []))
            uri = self.configured_jwks_uri or self._discover_jwks_uri()
            self._assert_safe_uri(uri)
            try:
                response = httpx.get(uri, timeout=5.0, follow_redirects=False)
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("oidc_jwks_fetch_failed", extra={"issuer": self.issuer})
                raise AppError(503, "AUTH_PROVIDER_UNAVAILABLE", "Identity provider is unavailable", retryable=True) from exc
            if not isinstance(payload.get("keys"), list):
                raise AppError(503, "AUTH_PROVIDER_INVALID", "Identity provider returned invalid keys", retryable=True)
            self._jwks = payload
            self._jwks_expires_at = now + 300
            return list(payload["keys"])

    def _discover_jwks_uri(self) -> str:
        if self._jwks_uri:
            return self._jwks_uri
        self._assert_safe_uri(self.issuer)
        try:
            response = httpx.get(self.issuer + "/.well-known/openid-configuration", timeout=5.0, follow_redirects=False)
            response.raise_for_status()
            uri = str(response.json().get("jwks_uri", ""))
        except (httpx.HTTPError, ValueError) as exc:
            raise AppError(503, "AUTH_PROVIDER_UNAVAILABLE", "Identity provider is unavailable", retryable=True) from exc
        self._assert_safe_uri(uri)
        self._jwks_uri = uri
        return uri

    @staticmethod
    def _assert_safe_uri(uri: str) -> None:
        parsed = urlparse(uri)
        if parsed.scheme != "https" or not parsed.hostname:
            raise AppError(500, "AUTH_CONFIGURATION_INVALID", "OIDC endpoints must use HTTPS")

    @staticmethod
    def _invalid_token(message: str) -> AppError:
        return AppError(401, "UNAUTHORIZED", message)


def _scopes(claims: dict[str, Any]) -> frozenset[str]:
    values: set[str] = set()
    if isinstance(claims.get("scope"), str):
        values.update(claims["scope"].split())
    if isinstance(claims.get("permissions"), list):
        values.update(str(value) for value in claims["permissions"])
    return frozenset(values)


def _synthetic_email(issuer: str, subject: str) -> str:
    safe_subject = re.sub(r"[^a-zA-Z0-9._-]", "-", subject)[:120] or "user"
    issuer_hash = hashlib.sha256(issuer.encode()).hexdigest()[:12]
    return safe_subject + "+" + issuer_hash + "@oidc.invalid"


def _resolve_oidc_user(db: Session, request: Request, token: str, claims: dict[str, Any]) -> ProductCurrentUser:
    issuer = str(claims["iss"]).rstrip("/")
    subject = str(claims["sub"])
    identity = db.scalar(select(AuthIdentity).where(AuthIdentity.issuer == issuer, AuthIdentity.subject == subject))
    email = str(claims.get("email") or _synthetic_email(issuer, subject)).lower()
    if identity is None:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, password_hash="", full_name=claims.get("name") or email.split("@", 1)[0], role="student", is_active=True)
            db.add(user)
            db.flush()
        identity = AuthIdentity(user_id=user.id, issuer=issuer, subject=subject)
        db.add(identity)
        db.flush()
    else:
        user = db.get(User, identity.user_id)
    if user is None or not user.is_active:
        raise AppError(403, "ACCOUNT_DISABLED", "Account is not active")

    identity.email = email
    identity.email_verified = bool(claims.get("email_verified", False))
    identity.claims_snapshot = {key: claims.get(key) for key in ("iss", "sub", "email", "email_verified", "name", "scope", "permissions") if key in claims}
    identity.last_login_at = _utcnow()

    fingerprint = hashlib.sha256(token.encode()).hexdigest()
    session = db.scalar(select(UserSession).where(UserSession.token_fingerprint == fingerprint))
    expires_at = datetime.fromtimestamp(_timestamp(claims.get("exp")), tz=timezone.utc)
    token_scopes = sorted(_scopes(claims))
    device = {
        "user_agent": request.headers.get("user-agent", "")[:500],
        "ip": request.client.host if request.client else None,
    }
    if session is None:
        session = UserSession(
            user_id=user.id,
            identity_id=identity.id,
            token_fingerprint=fingerprint,
            provider_session_id=claims.get("sid"),
            device=device,
            scopes=token_scopes,
            expires_at=expires_at,
        )
        db.add(session)
    elif session.revoked_at is not None:
        raise AppError(401, "SESSION_REVOKED", "Session has been revoked")
    else:
        session.last_seen_at = _utcnow()
        session.expires_at = expires_at
        session.device = device
        session.scopes = token_scopes
    db.commit()
    return ProductCurrentUser(
        id=user.id,
        email=user.email,
        role=user.role,
        email_verified=identity.email_verified,
        scopes=frozenset(token_scopes),
        session_id=session.id,
    )


def _resolve_local_token(db: Session, token: str) -> ProductCurrentUser:
    digest = hashlib.sha256(token.encode()).hexdigest()
    auth_token = db.scalar(select(AuthToken).where(AuthToken.token_hash == digest))
    now = _utcnow()
    if auth_token is None or auth_token.revoked_at is not None or auth_token.expires_at < now:
        raise AppError(401, "UNAUTHORIZED", "Invalid or expired bearer token")
    user = db.get(User, auth_token.user_id)
    if user is None or not user.is_active:
        raise AppError(403, "ACCOUNT_DISABLED", "Account is not active")
    return ProductCurrentUser(
        id=user.id,
        email=user.email,
        role=user.role,
        email_verified=True,
        scopes=frozenset({"local:all"}),
        session_id=None,
    )


def get_product_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> ProductCurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(401, "UNAUTHORIZED", "Bearer token is required")
    token = credentials.credentials
    settings = get_settings()
    environment = str(getattr(settings, "app_env", "local")).lower()
    oidc_configured = bool(getattr(settings, "oidc_issuer", "") and getattr(settings, "oidc_audience", ""))
    if oidc_configured:
        current = _resolve_oidc_user(db, request, token, OidcVerifier().verify(token))
    elif environment in {"local", "development", "test"}:
        current = _resolve_local_token(db, token)
    else:
        raise AppError(500, "AUTH_CONFIGURATION_INVALID", "OIDC must be configured outside local environments")
    account_status = db.scalar(select(UserProductProfile.account_status).where(UserProductProfile.user_id == current.id))
    privacy_status_path = request.url.path.startswith(str(settings.api_v1_prefix).rstrip("/") + "/privacy/requests/")
    if account_status == "pending_deletion" and not privacy_status_path:
        raise AppError(403, "ACCOUNT_PENDING_DELETION", "Account deletion is in progress")
    return current


def require_product_admin(current: ProductCurrentUser = Depends(get_product_user)) -> ProductCurrentUser:
    if current.role != "admin" and "admin" not in current.scopes:
        raise AppError(403, "FORBIDDEN", "Administrator access is required")
    return current


def require_product_scopes(*required_scopes: str):
    required = frozenset(required_scopes)

    def dependency(current: ProductCurrentUser = Depends(get_product_user)) -> ProductCurrentUser:
        if "local:all" in current.scopes or "admin" in current.scopes:
            return current
        if not required.issubset(current.scopes):
            raise AppError(403, "FORBIDDEN", "Required authorization scope is missing", details={"required_scopes": sorted(required)})
        return current

    return dependency
