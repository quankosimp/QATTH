from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user
from app.models.db import User
from app.schemas.auth import AuthResult, LoginRequest, RegisterRequest, UserRead
from app.schemas.common import APIResponse, make_response
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=APIResponse[AuthResult])
def register(
    request: Request,
    payload: RegisterRequest,
    db: Session = Depends(get_db),
) -> APIResponse[AuthResult]:
    result = AuthService(db=db).register(payload)
    return make_response(result, request=request)


@router.post("/login", response_model=APIResponse[AuthResult])
def login(
    request: Request,
    payload: LoginRequest,
    db: Session = Depends(get_db),
) -> APIResponse[AuthResult]:
    result = AuthService(db=db).login(payload)
    return make_response(result, request=request)


@router.get("/me", response_model=APIResponse[UserRead])
def me(
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> APIResponse[UserRead]:
    user = db.get(User, current_user.id)
    result = AuthService(db=db).to_user_read(user)
    return make_response(result, request=request)
