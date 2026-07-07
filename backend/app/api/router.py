from fastapi import APIRouter

from app.api import cv, health

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(cv.router)
