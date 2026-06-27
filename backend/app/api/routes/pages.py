from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


def create_router(frontend_dir: Path) -> APIRouter:
    router = APIRouter(include_in_schema=False)

    @router.get("/", response_class=FileResponse)
    async def read_frontend() -> FileResponse:
        return FileResponse(frontend_dir / "index.html", media_type="text/html")

    @router.get("/login", response_class=FileResponse)
    async def read_login() -> FileResponse:
        login_file = frontend_dir / "login.html"
        if not login_file.exists():
            login_file = frontend_dir / "index.html"
        return FileResponse(login_file, media_type="text/html")

    return router
