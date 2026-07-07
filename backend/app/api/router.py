from fastapi import APIRouter

from app.api import admin, auth, cv, files, health, interviews, jobs, matches, ops, profile, tasks

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(ops.router)
api_router.include_router(cv.router)
api_router.include_router(files.router)
api_router.include_router(interviews.router)
api_router.include_router(profile.router)
api_router.include_router(jobs.router)
api_router.include_router(matches.router)
api_router.include_router(tasks.router)
