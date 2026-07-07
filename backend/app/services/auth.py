from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import hash_password, hash_token, new_access_token, verify_password
from app.models.db import AuthToken, PasswordResetToken, User
from app.schemas.auth import (
    AuthResult,
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetConfirmResult,
    PasswordResetRequest,
    PasswordResetRequestResult,
    RegisterRequest,
    UserRead,
)


class AuthService:
    def __init__(self, *, db: Session) -> None:
        self.db = db

    def register(self, payload: RegisterRequest) -> AuthResult:
        email = payload.email.lower()
        existing = self.db.scalar(select(User).where(User.email == email))
        if existing:
            raise AppError(
                status_code=409,
                code="EMAIL_ALREADY_REGISTERED",
                message="Email is already registered.",
            )

        user_count = self.db.scalar(select(User).limit(1)) is not None
        role = "student" if user_count else "admin"
        user = User(
            email=email,
            password_hash=hash_password(payload.password),
            full_name=payload.full_name,
            role=role,
            is_active=True,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return self._issue_token(user)

    def login(self, payload: LoginRequest) -> AuthResult:
        user = self.db.scalar(select(User).where(User.email == payload.email.lower()))
        if not user or not verify_password(payload.password, user.password_hash):
            raise AppError(
                status_code=401,
                code="INVALID_CREDENTIALS",
                message="Email or password is incorrect.",
            )
        if not user.is_active:
            raise AppError(
                status_code=403,
                code="USER_INACTIVE",
                message="User account is inactive.",
            )
        return self._issue_token(user)

    def logout(self, *, raw_token: str) -> bool:
        token = self.db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_token(raw_token)))
        if token and token.revoked_at is None:
            token.revoked_at = datetime.now(UTC)
            self.db.commit()
        return True

    def request_password_reset(self, payload: PasswordResetRequest) -> PasswordResetRequestResult:
        user = self.db.scalar(select(User).where(User.email == payload.email.lower()))
        if not user:
            return PasswordResetRequestResult(reset_requested=True, reset_token=None)

        raw_token = new_access_token()
        token = PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
        self.db.add(token)
        self.db.commit()
        return PasswordResetRequestResult(reset_requested=True, reset_token=raw_token)

    def confirm_password_reset(self, payload: PasswordResetConfirm) -> PasswordResetConfirmResult:
        token = self.db.scalar(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(payload.token))
        )
        now = datetime.now(UTC)
        if not token or token.used_at is not None or token.expires_at <= now:
            raise AppError(
                status_code=400,
                code="INVALID_PASSWORD_RESET_TOKEN",
                message="Password reset token is invalid or expired.",
            )

        user = self.db.get(User, token.user_id)
        if not user:
            raise AppError(status_code=404, code="USER_NOT_FOUND", message="User was not found.")

        user.password_hash = hash_password(payload.new_password)
        token.used_at = now
        self.db.query(AuthToken).filter(AuthToken.user_id == user.id).update({"revoked_at": now})
        self.db.commit()
        return PasswordResetConfirmResult(password_reset=True)

    def to_user_read(self, user: User) -> UserRead:
        return UserRead(
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            is_active=user.is_active,
            created_at=user.created_at,
        )

    def _issue_token(self, user: User) -> AuthResult:
        raw_token = new_access_token()
        token = AuthToken(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=datetime.now(UTC) + timedelta(days=14),
        )
        self.db.add(token)
        self.db.commit()
        return AuthResult(access_token=raw_token, user=self.to_user_read(user))
