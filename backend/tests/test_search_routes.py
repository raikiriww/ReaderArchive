"""Search requests must not block unrelated requests while the model is running."""

import asyncio
import threading

import httpx
import pytest
from fastapi import FastAPI

from app.api.routes.archive_tasks import create_router
from app.models import ArchiveSearchRead


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/archive-search?q=backup", "/archive-tasks?q=backup"])
async def test_search_leaves_event_loop_available(path: str) -> None:
    entered = threading.Event()
    release = threading.Event()

    class SlowSearch:
        def search_tasks(self, *args, **kwargs):
            entered.set()
            release.wait(timeout=2)
            return ArchiveSearchRead(items=[], total=0, limit=20, has_more=False)

        list_tasks = search_tasks

    app = FastAPI()
    app.state.archive_task_service = SlowSearch()
    app.include_router(create_router())

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        search = asyncio.create_task(client.get(path))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            assert not release.is_set()
            response = await asyncio.wait_for(client.get("/ping"), timeout=0.5)
            assert response.json() == {"ok": True}
            assert not search.done(), "The slow search finished before the responsiveness check."
        finally:
            release.set()
            result = await search
        assert result.status_code == 200


@pytest.mark.asyncio
async def test_unavailable_search_text_is_not_an_empty_success() -> None:
    class NoText:
        def get_search_text(self, task_id: str):
            return None

    app = FastAPI()
    app.state.archive_task_service = NoText()
    app.include_router(create_router())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/archive-search/missing/text")
        assert response.status_code == 404
