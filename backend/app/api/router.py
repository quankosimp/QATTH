from fastapi import APIRouter

from app.api import cv, health, interviews

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(cv.router)
api_router.include_router(interviews.router)
