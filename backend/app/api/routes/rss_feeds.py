from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import get_archive_task_service
from app.models import RssFeedCreate, RssFeedRead, RssFeedRefreshResult, RssFeedUpdate


def create_router() -> APIRouter:
    router = APIRouter(prefix="/rss-feeds", tags=["rss-feeds"])

    @router.post(
        "",
        response_model=RssFeedRefreshResult,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_rss_feed(
        payload: RssFeedCreate,
        request: Request,
    ) -> RssFeedRefreshResult:
        service = get_archive_task_service(request)
        try:
            return await service.create_rss_feed(
                str(payload.url),
                title=payload.title,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("", response_model=list[RssFeedRead])
    async def list_rss_feeds(request: Request) -> list[RssFeedRead]:
        service = get_archive_task_service(request)
        return service.list_rss_feeds()

    @router.patch("/{feed_id}", response_model=RssFeedRead)
    async def update_rss_feed(
        feed_id: str,
        payload: RssFeedUpdate,
        request: Request,
    ) -> RssFeedRead:
        service = get_archive_task_service(request)
        feed = service.update_rss_feed(
            feed_id,
            title=payload.title,
            enabled=payload.enabled,
        )
        if feed is None:
            raise HTTPException(status_code=404, detail="RSS feed not found.")
        return feed

    @router.delete("/{feed_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_rss_feed(feed_id: str, request: Request) -> None:
        service = get_archive_task_service(request)
        if not service.delete_rss_feed(feed_id):
            raise HTTPException(status_code=404, detail="RSS feed not found.")

    @router.post("/{feed_id}/refresh", response_model=RssFeedRefreshResult)
    async def refresh_rss_feed(
        feed_id: str,
        request: Request,
    ) -> RssFeedRefreshResult:
        service = get_archive_task_service(request)
        try:
            return await service.refresh_rss_feed(feed_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router


router = create_router()
