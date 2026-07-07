from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user
from app.schemas.common import APIResponse, make_response
from app.schemas.tasks import BackgroundTaskCreate, BackgroundTaskList, BackgroundTaskRead
from app.services.background_tasks import BackgroundTaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=APIResponse[BackgroundTaskRead])
def enqueue_task(
    request: Request,
    payload: BackgroundTaskCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[BackgroundTaskRead]:
    result = BackgroundTaskService(db=db, current_user=current_user).enqueue(payload)
    return make_response(result, request=request)


@router.get("", response_model=APIResponse[BackgroundTaskList])
def list_tasks(
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[BackgroundTaskList]:
    result = BackgroundTaskService(db=db, current_user=current_user).list()
    return make_response(result, request=request)


@router.get("/{task_id}", response_model=APIResponse[BackgroundTaskRead])
def get_task(
    request: Request,
    task_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[BackgroundTaskRead]:
    result = BackgroundTaskService(db=db, current_user=current_user).get(task_id=task_id)
    return make_response(result, request=request)


@router.post("/{task_id}/retry", response_model=APIResponse[BackgroundTaskRead])
def retry_task(
    request: Request,
    task_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[BackgroundTaskRead]:
    result = BackgroundTaskService(db=db, current_user=current_user).retry(task_id=task_id)
    return make_response(result, request=request)
