from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.crud import RuntimeConfigRepository, UserRepository
from app.models import UserRead
from app.service import ArchiveTaskService

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.api_v1_str}/login/access-token",
    auto_error=False,
)


def get_db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]
TokenDep = Annotated[str | None, Depends(reusable_oauth2)]


def get_archive_task_service(request: Request) -> ArchiveTaskService:
    return request.app.state.archive_task_service


def get_user_repository(request: Request) -> UserRepository:
    return request.app.state.user_repository


def get_runtime_config_repository(request: Request) -> RuntimeConfigRepository:
    return request.app.state.runtime_config_repository


def get_current_user(request: Request, token: TokenDep) -> UserRead:
    access_token = token or request.cookies.get(settings.session_cookie_name)
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    user = get_user_repository(request).current_user_from_token(access_token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials.",
        )
    request.state.user = user
    request.state.access_token = access_token
    return user


CurrentUser = Annotated[UserRead, Depends(get_current_user)]


def get_current_active_admin(current_user: CurrentUser) -> UserRead:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access is required.")
    return current_user


AdminUser = Annotated[UserRead, Depends(get_current_active_admin)]
