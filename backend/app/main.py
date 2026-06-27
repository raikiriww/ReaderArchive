from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles

from app.api.main import api_router
from app.api.middleware import require_login_middleware
from app.api.routes import browser, pages
from app.core.config import Settings, get_settings
from app.lifespan import create_lifespan

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = next(
    (
        candidate
        for candidate in (BACKEND_ROOT.parent, BACKEND_ROOT, Path.cwd())
        if (candidate / "frontend").exists()
    ),
    BACKEND_ROOT.parent,
)
FRONTEND_DIR = PROJECT_ROOT / "frontend"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}" if route.tags else route.name


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    app = FastAPI(
        title=app_settings.app_name,
        lifespan=create_lifespan(app_settings),
        openapi_url=f"{app_settings.api_v1_str}/openapi.json",
        generate_unique_id_function=custom_generate_unique_id,
    )
    app.state.settings = app_settings
    frontend_root = FRONTEND_DIST_DIR if FRONTEND_DIST_DIR.exists() else FRONTEND_DIR
    static_root = frontend_root / "static"
    if not static_root.exists():
        static_root = FRONTEND_DIR / "public" / "static"
    app.mount("/static", StaticFiles(directory=static_root), name="static")

    @app.middleware("http")
    async def require_login(request: Request, call_next):  # type: ignore[no-untyped-def]
        return await require_login_middleware(request, call_next, app_settings)

    app.include_router(pages.create_router(frontend_root))
    app.include_router(browser.create_router(app_settings))
    app.include_router(api_router, prefix=app_settings.api_v1_str)
    return app


app = create_app()
