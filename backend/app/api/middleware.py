from __future__ import annotations

from urllib.parse import quote

from fastapi import Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.api.deps import get_user_repository
from app.core.config import Settings
from app.models import UserRead


async def require_login_middleware(
    request: Request,
    call_next,  # type: ignore[no-untyped-def]
    settings: Settings,
) -> Response:
    path = request.url.path
    if is_public_path(path):
        return await call_next(request)

    if not requires_login(path):
        return await call_next(request)

    session = session_from_request(request, settings)
    if session is None:
        return auth_required_response(request)
    request.state.user = session

    return await call_next(request)


def is_public_path(path: str) -> bool:
    return (
        path == "/login"
        or path == "/api/v1/health"
        or path == "/api/v1/login/access-token"
        or path == "/api/v1/auth/login"
        or path == "/api/v1/openapi.json"
        or path.startswith("/static/")
        or path.startswith("/docs")
        or path.startswith("/redoc")
    )


def requires_login(path: str) -> bool:
    return path == "/" or path.startswith("/browser/")


def session_from_request(request: Request, settings: Settings) -> UserRead | None:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    return get_user_repository(request).current_user_from_token(token)


def auth_required_response(request: Request) -> Response:
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    if request.url.path == "/" or request.url.path.startswith("/browser/"):
        return RedirectResponse(f"/login?next={quote(next_path)}")
    return JSONResponse(
        {"detail": "Authentication required."},
        status_code=status.HTTP_401_UNAUTHORIZED,
    )
