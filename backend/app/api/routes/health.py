from __future__ import annotations

from fastapi import APIRouter, Request

from app.models import HealthRead


def create_router() -> APIRouter:
    router = APIRouter(tags=["health"])

    @router.get("/health", response_model=HealthRead)
    async def health(request: Request) -> HealthRead:
        service = getattr(request.app.state, "archive_task_service", None)
        semantic_search = service.semantic_health() if service is not None else None
        return HealthRead(status="ok", semantic_search=semantic_search)

    return router


router = create_router()
