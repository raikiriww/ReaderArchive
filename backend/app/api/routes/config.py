from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.api.deps import get_archive_task_service, get_runtime_config_repository
from app.models import AppConfigRead, AppConfigUpdate

router = APIRouter(tags=["config"])


@router.get("/app-config", response_model=AppConfigRead)
async def read_app_config(request: Request) -> AppConfigRead:
    return get_runtime_config_repository(request).read_app_config(
        request.app.state.settings,
        get_archive_task_service(request).semantic_health(),
    )


@router.patch("/app-config", response_model=AppConfigRead)
async def update_app_config(payload: AppConfigUpdate, request: Request) -> AppConfigRead:
    if request.state.user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access is required.")
    return get_runtime_config_repository(request).update_app_config(
        request.app.state.settings,
        payload,
        get_archive_task_service(request).semantic_health(),
    )
