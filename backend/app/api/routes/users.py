from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import get_user_repository
from app.models import UserCreate, UserPasswordReset, UserRead, UserUpdate


def create_router() -> APIRouter:
    router = APIRouter(prefix="/users", tags=["users"])

    @router.get("", response_model=list[UserRead])
    async def list_users(request: Request) -> list[UserRead]:
        require_admin(request)
        return get_user_repository(request).list_users()

    @router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
    async def create_user(payload: UserCreate, request: Request) -> UserRead:
        require_admin(request)
        try:
            return get_user_repository(request).create_user(
                payload.username,
                payload.password,
                payload.role,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.patch("/{user_id}", response_model=UserRead)
    async def update_user(user_id: str, payload: UserUpdate, request: Request) -> UserRead:
        require_admin(request)
        try:
            user = get_user_repository(request).update_user(
                user_id,
                enabled=payload.enabled,
                role=payload.role,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if user is None:
            raise HTTPException(status_code=404, detail="User not found.")
        return user

    @router.post("/{user_id}/reset-password", response_model=UserRead)
    async def reset_user_password(
        user_id: str,
        payload: UserPasswordReset,
        request: Request,
    ) -> UserRead:
        require_admin(request)
        user = get_user_repository(request).reset_password(user_id, payload.password)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found.")
        return user

    @router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_user(user_id: str, request: Request) -> None:
        require_admin(request)
        if user_id == request.state.user.user_id:
            raise HTTPException(status_code=409, detail="You cannot delete your own user.")
        try:
            deleted = get_user_repository(request).delete_user(user_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="User not found.")

    return router


def require_admin(request: Request) -> None:
    if request.state.user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access is required.")


router = create_router()
