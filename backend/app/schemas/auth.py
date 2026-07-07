from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserRead(BaseModel):
    user_id: str
    email: EmailStr
    full_name: str | None = None
    role: str
    is_active: bool
    created_at: datetime | None = None


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=160)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResult(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class LogoutResult(BaseModel):
    revoked: bool


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetRequestResult(BaseModel):
    reset_requested: bool
    reset_token: str | None = Field(
        default=None,
        description="Returned for local/dev until an email provider is configured.",
    )


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class PasswordResetConfirmResult(BaseModel):
    password_reset: bool
