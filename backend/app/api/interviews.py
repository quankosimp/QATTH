from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AppError
from app.schemas.common import APIResponse, make_response
from app.schemas.interview import (
    InterviewCreateRequest,
    InterviewCreateResult,
    InterviewEndResult,
    InterviewResultRead,
)
from app.services.interview import InterviewService

router = APIRouter(prefix="/interviews", tags=["interviews"])


@router.post("", response_model=APIResponse[InterviewCreateResult])
def create_interview(
    request: Request,
    payload: InterviewCreateRequest,
    db: Session = Depends(get_db),
) -> APIResponse[InterviewCreateResult]:
    result = InterviewService(db=db).create(
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
    service = InterviewService(db=db)
    await websocket.accept()

    try:
        service.mark_live(interview_id=interview_id)
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
) -> APIResponse[InterviewEndResult]:
    result = await InterviewService(db=db).end(interview_id=interview_id)
    return make_response(result, request=request)


@router.get("/{interview_id}/result", response_model=APIResponse[InterviewResultRead])
def get_interview_result(
    request: Request,
    interview_id: str,
    db: Session = Depends(get_db),
) -> APIResponse[InterviewResultRead]:
    result = InterviewService(db=db).get_result(interview_id=interview_id)
    return make_response(result, request=request)
