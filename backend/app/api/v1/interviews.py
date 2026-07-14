from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Request, Response, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, get_db
from app.core.errors import AppError
from app.core.identity_security import ProductCurrentUser, get_product_user
from app.schemas.common import APIResponse, make_response
from app.schemas.product_interview import (
    CreateInterviewRequest,
    InterviewFeedbackRequest,
    InterviewFeedbackView,
    InterviewPage,
    InterviewReportView,
    InterviewView,
    RealtimeTokenView,
)
from app.services.gemini_interview_gateway import GeminiInterviewGateway
from app.services.product_interview import ProductInterviewService

router = APIRouter(prefix="/interviews", tags=["Interviews"])


@router.get("", response_model=APIResponse[InterviewPage])
def list_interviews(
    request: Request,
    cursor: str | None = None,
    limit: int = 20,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    if limit < 1 or limit > 100:
        raise AppError(422, "INVALID_LIMIT", "Limit must be between 1 and 100")
    return make_response(ProductInterviewService(db).list(current, cursor, limit), request=request)


@router.post("", response_model=APIResponse[InterviewView], status_code=status.HTTP_201_CREATED)
def create_interview(
    payload: CreateInterviewRequest,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=255),
):
    service = ProductInterviewService(db)
    return make_response(service.view(service.create(current, payload)), request=request)


@router.get("/{interview_id}", response_model=APIResponse[InterviewView])
def get_interview(
    interview_id: str,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    service = ProductInterviewService(db)
    return make_response(service.view(service.get(current, interview_id)), request=request)


@router.post("/{interview_id}/realtime-token", response_model=APIResponse[RealtimeTokenView], status_code=status.HTTP_201_CREATED)
def create_realtime_token(
    interview_id: str,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    token = ProductInterviewService(db).create_realtime_token(current, interview_id, str(request.base_url))
    return make_response(token, request=request)


@router.websocket("/{interview_id}/realtime")
async def interview_realtime(
    websocket: WebSocket,
    interview_id: str,
    token: str = Query(min_length=20, max_length=512),
):
    with SessionLocal() as db:
        service = ProductInterviewService(db)
        try:
            interview = service.consume_realtime_token(interview_id, token)
        except AppError:
            await websocket.close(code=4401)
            return
    await websocket.accept()
    try:
        await GeminiInterviewGateway().run(websocket, interview)
        with SessionLocal() as db:
            ProductInterviewService(db).mark_interrupted(interview_id)
    except WebSocketDisconnect:
        with SessionLocal() as db:
            ProductInterviewService(db).mark_interrupted(interview_id)
    except AppError as exc:
        with SessionLocal() as db:
            ProductInterviewService(db).mark_interrupted(interview_id)
        await websocket.send_json({"type": "error", "payload": {"code": exc.code, "message": exc.message, "retryable": exc.retryable}})
        await websocket.close(code=1011 if exc.retryable else 1008)


@router.post("/{interview_id}/end", response_model=APIResponse[InterviewView], status_code=status.HTTP_202_ACCEPTED)
def end_interview(
    interview_id: str,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=255),
):
    service = ProductInterviewService(db)
    return make_response(service.view(service.end(current, interview_id)), request=request)


@router.post("/{interview_id}/cancel", response_model=APIResponse[InterviewView])
def cancel_interview(
    interview_id: str,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=255),
):
    service = ProductInterviewService(db)
    return make_response(service.view(service.cancel(current, interview_id)), request=request)


@router.get("/{interview_id}/report", response_model=APIResponse[InterviewReportView])
def get_interview_report(
    interview_id: str,
    request: Request,
    response: Response,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    service = ProductInterviewService(db)
    report = service.report(current, interview_id)
    if report is None:
        raise AppError(404, "INTERVIEW_REPORT_NOT_FOUND", "Interview report was not found")
    if report.status == "processing":
        response.status_code = status.HTTP_202_ACCEPTED
    return make_response(service.report_view(report), request=request)


@router.post("/{interview_id}/feedback", response_model=APIResponse[InterviewFeedbackView], status_code=status.HTTP_201_CREATED)
def create_interview_feedback(
    interview_id: str,
    payload: InterviewFeedbackRequest,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    feedback = ProductInterviewService(db).feedback(current, interview_id, payload)
    return make_response(InterviewFeedbackView.model_validate(feedback), request=request)
