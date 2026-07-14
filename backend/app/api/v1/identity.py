from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.identity_security import ProductCurrentUser, get_product_user
from app.schemas.identity import (
    ConsentView,
    ConsentWrite,
    ProductProfile,
    ProfilePatch,
    SessionRevoked,
    SessionView,
    UserMe,
)
from app.services.identity import IdentityService

router = APIRouter(prefix="/me", tags=["Identity and profile"])


@router.get("", response_model=UserMe)
def get_me(
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
) -> UserMe:
    user, profile = IdentityService(db).get_user(current)
    return UserMe(
        id=user.id,
        email=user.email,
        role=user.role,
        email_verified=current.email_verified,
        profile=ProductProfile.model_validate(profile),
    )


@router.patch("/profile", response_model=ProductProfile)
def patch_profile(
    payload: ProfilePatch,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
) -> ProductProfile:
    return ProductProfile.model_validate(IdentityService(db).update_profile(current.id, payload))


@router.get("/consents", response_model=list[ConsentView])
def list_consents(
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
) -> list[ConsentView]:
    return [ConsentView.model_validate(item) for item in IdentityService(db).list_consents(current.id)]


@router.put("/consents", response_model=ConsentView)
def put_consent(
    payload: ConsentWrite,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=255),
) -> ConsentView:
    evidence = {
        "request_id": getattr(request.state, "request_id", None),
        "ip": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent", "")[:500],
        "idempotency_key": idempotency_key,
    }
    return ConsentView.model_validate(IdentityService(db).write_consent(current.id, payload, evidence))


@router.get("/sessions", response_model=list[SessionView])
def list_sessions(
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
) -> list[SessionView]:
    sessions = IdentityService(db).list_sessions(current.id)
    return [
        SessionView.model_validate(session).model_copy(update={"current": session.id == current.session_id})
        for session in sessions
    ]


@router.delete("/sessions/{session_id}", response_model=SessionRevoked)
def revoke_session(
    session_id: str,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
) -> SessionRevoked:
    session = IdentityService(db).revoke_session(current.id, session_id)
    return SessionRevoked(id=session.id, revoked=True)
