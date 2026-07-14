from fastapi import APIRouter

from backend.app.api.v1.cv import router as cv_router
from backend.app.api.v1.files import router as files_router
from backend.app.api.v1.identity import router as identity_router
from backend.app.api.v1.interviews import router as interviews_router
from backend.app.api.v1.jobs import router as jobs_router
from backend.app.api.v1.recommendations import router as recommendations_router

router = APIRouter()
router.include_router(identity_router)
router.include_router(files_router)
router.include_router(cv_router)
router.include_router(interviews_router)
router.include_router(jobs_router)
router.include_router(recommendations_router)
