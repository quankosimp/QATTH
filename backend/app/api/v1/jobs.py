from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, get_db
from app.core.errors import AppError
from app.core.identity_security import ProductCurrentUser, get_product_user
from app.schemas.common import APIResponse, make_response
from app.schemas.product_jobs import CreateJobSearchRequest, JobMatchPage, JobPage, JobSearchRunView, JobView
from app.services.product_job_search import ProductJobSearchService

router = APIRouter(tags=["Jobs"])


@router.get("/jobs", response_model=APIResponse[JobPage])
def search_indexed_jobs(
    request: Request,
    q: str | None = Query(default=None, max_length=500),
    location: str | None = None,
    remote_mode: str | None = None,
    skills: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    skill_list = [value.strip() for value in (skills or "").split(",") if value.strip()]
    return make_response(ProductJobSearchService(db).indexed_jobs(q, location, remote_mode, skill_list, cursor, limit), request=request)


@router.get("/jobs/{job_id}", response_model=APIResponse[JobView])
def get_job(
    job_id: str,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    service = ProductJobSearchService(db)
    return make_response(service.job_view(service.get_job(job_id)), request=request)


@router.post("/job-search-runs", response_model=APIResponse[JobSearchRunView], status_code=status.HTTP_202_ACCEPTED)
def create_job_search_run(
    payload: CreateJobSearchRequest,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=255),
):
    service = ProductJobSearchService(db)
    return make_response(
        service.run_view(service.create_run(current, payload, idempotency_key)),
        request=request,
    )


@router.get("/job-search-runs/{run_id}", response_model=APIResponse[JobSearchRunView])
def get_job_search_run(
    run_id: str,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    service = ProductJobSearchService(db)
    return make_response(service.run_view(service.get_run(current, run_id)), request=request)


@router.get("/job-search-runs/{run_id}/results", response_model=APIResponse[JobMatchPage])
def get_job_search_results(
    run_id: str,
    request: Request,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    return make_response(ProductJobSearchService(db).results(current, run_id, cursor, limit), request=request)


@router.get("/job-search-runs/{run_id}/events")
def stream_job_search_events(
    run_id: str,
    current: ProductCurrentUser = Depends(get_product_user),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    try:
        start_sequence = int(last_event_id or 0)
    except ValueError as exc:
        raise AppError(422, "INVALID_LAST_EVENT_ID", "Last-Event-ID must be numeric") from exc
    with SessionLocal() as db:
        ProductJobSearchService(db).get_run(current, run_id)

    async def generate() -> AsyncIterator[str]:
        sequence = start_sequence
        idle = 0
        while idle < 120:
            with SessionLocal() as db:
                service = ProductJobSearchService(db)
                events = service.events_after(current, run_id, sequence)
                run = service.get_run(current, run_id)
                terminal = run.status in {"completed", "failed", "cancelled"}
            if events:
                idle = 0
                for event in events:
                    sequence = event.sequence
                    yield "id: " + str(event.sequence) + "\nevent: " + event.event_type + "\ndata: " + json.dumps(event.payload, ensure_ascii=False) + "\n\n"
            else:
                idle += 1
                yield ": keep-alive\n\n"
            if terminal and not events:
                return
            await asyncio.sleep(1)

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
