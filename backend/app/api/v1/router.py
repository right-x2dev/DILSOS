from fastapi import APIRouter

from app.api.v1 import audit, auth, dashboard, health, master, runs, scenarios

api_router = APIRouter()
api_router.include_router(audit.router)
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(master.router)
api_router.include_router(scenarios.router)
api_router.include_router(runs.router)
api_router.include_router(dashboard.router)
