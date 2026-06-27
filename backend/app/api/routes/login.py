from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import CurrentUser, get_user_repository
from app.core.config import settings
from app.core.security import create_access_token
from app.models import LoginRequest, PasswordChange, Token, UserRead

router = APIRouter(tags=["login"])


@router.post("/login/access-token", response_model=Token)
async def login_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
) -> Response:
    return _login_response(form_data.username, form_data.password, request)


@router.post("/login/test-token", response_model=UserRead)
async def test_token(current_user: CurrentUser) -> UserRead:
    return current_user


@router.post("/auth/login", response_model=Token)
async def login_json(payload: LoginRequest, request: Request) -> Response:
    return _login_response(payload.username, payload.password, request)


@router.post("/auth/change-password", response_model=UserRead)
async def change_password(payload: PasswordChange, current_user: CurrentUser, request: Request) -> UserRead:
    user = get_user_repository(request).change_password(
        current_user.user_id,
        payload.current_password,
        payload.new_password,
    )
    if user is None:
        raise HTTPException(status_code=400, detail="Incorrect current password.")
    return user


def _login_response(username: str, password: str, request: Request) -> Response:
    limiter = request.app.state.login_rate_limiter
    key = f"{request.client.host if request.client else 'unknown'}:{username.casefold()}"
    if not limiter.check(key):
        raise HTTPException(status_code=429, detail="Too many login attempts.")

    repository = get_user_repository(request)
    user = repository.authenticate(username, password)
    if user is None:
        limiter.record_failure(key)
        raise HTTPException(status_code=400, detail="Incorrect username or password.")

    limiter.clear(key)
    token, token_id, expires_at = create_access_token(
        user.user_id,
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )
    repository.create_login_token(user.user_id, token_id, expires_at)
    response = JSONResponse(Token(access_token=token, user=user).model_dump(mode="json"))
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return response
