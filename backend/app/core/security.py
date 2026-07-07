import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, Header, WebSocket
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AppError
from app.models.db import AuthToken, User

PBKDF2_ITERATIONS = 260_000


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str
    role: str
    is_active: bool

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt, expected = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations_text),
        ).hex()
        return hmac.compare_digest(digest, expected)
    except ValueError:
        return False


def new_access_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> CurrentUser:
    token = _extract_bearer_token(authorization)
    return resolve_current_user(db=db, token=token)


def require_admin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not current_user.is_admin:
        raise AppError(
            status_code=403,
            code="ADMIN_REQUIRED",
            message="Admin privileges are required.",
        )
    return current_user


def get_websocket_user(*, websocket: WebSocket, db: Session) -> CurrentUser:
    token = websocket.query_params.get("token")
    if not token:
        header = websocket.headers.get("authorization")
        token = _extract_bearer_token(header)
    return resolve_current_user(db=db, token=token)


def resolve_current_user(*, db: Session, token: str) -> CurrentUser:
    token_hash = hash_token(token)
    auth_token = db.query(AuthToken).filter(AuthToken.token_hash == token_hash).first()
    if not auth_token:
        raise AppError(
            status_code=401,
            code="INVALID_TOKEN",
            message="Invalid or expired authentication token.",
        )

    now = datetime.now(UTC)
    if auth_token.revoked_at is not None or auth_token.expires_at <= now:
        raise AppError(
            status_code=401,
            code="INVALID_TOKEN",
            message="Invalid or expired authentication token.",
        )

    user = db.get(User, auth_token.user_id)
    if not user or not user.is_active:
        raise AppError(
            status_code=401,
            code="USER_INACTIVE",
            message="User account is inactive.",
        )

    return CurrentUser(id=user.id, email=user.email, role=user.role, is_active=user.is_active)


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise AppError(
            status_code=401,
            code="AUTH_REQUIRED",
            message="Authorization bearer token is required.",
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AppError(
            status_code=401,
            code="INVALID_AUTH_HEADER",
            message="Authorization header must use Bearer token.",
        )
    return token
