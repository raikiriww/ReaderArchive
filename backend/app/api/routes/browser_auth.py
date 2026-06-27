from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.api.deps import CurrentUser, get_user_repository
from app.core.config import settings
from app.models import AuthSessionRead

router = APIRouter(tags=["auth"])


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, _current_user: CurrentUser) -> Response:
    repository = get_user_repository(request)
    tokens = {
        getattr(request.state, "access_token", ""),
        request.cookies.get(settings.session_cookie_name, ""),
    }
    for token in tokens:
        if token:
            repository.delete_token(token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.session_cookie_name, path="/api/v1")
    response.delete_cookie(settings.session_cookie_name, path="/browser")
    return response


@router.get("/auth/me", response_model=AuthSessionRead)
async def read_current_user(current_user: CurrentUser) -> AuthSessionRead:
    return AuthSessionRead(user=current_user)
