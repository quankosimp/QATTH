from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.errors import AppError
from app.core.security import CurrentUser, get_current_user, get_websocket_user
from app.schemas.common import APIResponse, make_response
from app.schemas.interview import (
    InterviewCreateRequest,
    InterviewCreateResult,
    InterviewEndResult,
    InterviewResultRead,
)
from app.services.interview import InterviewService
from app.services.gemini_live import GeminiLiveProxy

router = APIRouter(prefix="/interviews", tags=["interviews"])


@router.post("", response_model=APIResponse[InterviewCreateResult])
def create_interview(
    request: Request,
    payload: InterviewCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[InterviewCreateResult]:
    result = InterviewService(db=db, current_user=current_user).create(
        cv_id=payload.cv_id,
        target_role=payload.target_role,
        language=payload.language,
    )
    return make_response(result, request=request)


@router.websocket("/{interview_id}/stream")
async def interview_stream(
    websocket: WebSocket,
    interview_id: str,
    db: Session = Depends(get_db),
) -> None:
    await websocket.accept()

    try:
        current_user = get_websocket_user(websocket=websocket, db=db)
        service = InterviewService(db=db, current_user=current_user)
        service.mark_live(interview_id=interview_id)
        settings = get_settings()

        if settings.gemini_api_key:
            await GeminiLiveProxy(db=db, settings=settings).run(
                websocket=websocket,
                interview_id=interview_id,
            )
            return

        await websocket.send_json({"type": "interview.state", "payload": {"state": "live"}})

        while True:
            raw_event = await websocket.receive_json()
            events = service.handle_client_event(interview_id=interview_id, raw_event=raw_event)
            for event in events:
                await websocket.send_json(event)

    except WebSocketDisconnect:
        service.mark_disconnected(interview_id=interview_id)
    except AppError as exc:
        await websocket.send_json(
            {"type": "error", "payload": {"code": exc.code, "message": exc.message}}
        )
        await websocket.close(code=1008)


@router.post("/{interview_id}/end", response_model=APIResponse[InterviewEndResult])
async def end_interview(
    request: Request,
    interview_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[InterviewEndResult]:
    result = await InterviewService(db=db, current_user=current_user).end(interview_id=interview_id)
    return make_response(result, request=request)


@router.get("/{interview_id}/result", response_model=APIResponse[InterviewResultRead])
def get_interview_result(
    request: Request,
    interview_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[InterviewResultRead]:
    result = InterviewService(db=db, current_user=current_user).get_result(interview_id=interview_id)
    return make_response(result, request=request)
