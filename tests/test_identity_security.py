from datetime import datetime, timedelta, timezone

import pytest
from fastapi import Request
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.identity_security import _resolve_oidc_user
from app.models.db import Base, User
from app.models.identity import AuthIdentity, UserProductProfile, UserSession


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/v1/me",
            "raw_path": b"/v1/me",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 443),
        }
    )


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[User.__table__, AuthIdentity.__table__, UserProductProfile.__table__, UserSession.__table__],
    )
    with Session(engine) as session:
        yield session


def _claims(**overrides):
    claims = {
        "iss": "https://identity.example",
        "sub": "candidate-1",
        "email": "candidate@example.com",
        "email_verified": True,
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        "sid": "provider-session-1",
    }
    claims.update(overrides)
    return claims


def test_unverified_oidc_email_does_not_link_existing_account(db: Session) -> None:
    existing = User(email="candidate@example.com", password_hash="existing", role="student", is_active=True)
    db.add(existing)
    db.commit()

    current = _resolve_oidc_user(db, _request(), "first-token", _claims(email_verified=False))

    assert current.id != existing.id
    assert current.email.endswith("@oidc.invalid")
    identity = db.scalar(select(AuthIdentity).where(AuthIdentity.user_id == current.id))
    assert identity is not None
    assert identity.email == "candidate@example.com"
    assert identity.email_verified is False


def test_revoked_provider_session_rejects_refreshed_token(db: Session) -> None:
    current = _resolve_oidc_user(db, _request(), "first-token", _claims())
    session = db.get(UserSession, current.session_id)
    assert session is not None
    session.revoked_at = datetime.now(timezone.utc)
    db.commit()

    with pytest.raises(AppError) as raised:
        _resolve_oidc_user(db, _request(), "refreshed-token", _claims())

    assert raised.value.code == "SESSION_REVOKED"
    assert db.scalar(select(UserSession).where(UserSession.provider_session_id == "provider-session-1")) is not None
