from fastapi import APIRouter

from backend.app.api.v1.identity import router as identity_router

router = APIRouter()
router.include_router(identity_router)
