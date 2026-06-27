from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.api.routes import archive_tasks, browser_auth, config, health, login, rss_feeds, users

api_router = APIRouter()
protected_router = APIRouter(dependencies=[Depends(get_current_user)])

api_router.include_router(login.router)
api_router.include_router(health.router)
protected_router.include_router(users.router)
protected_router.include_router(config.router)
protected_router.include_router(archive_tasks.router)
protected_router.include_router(rss_feeds.router)
protected_router.include_router(browser_auth.router)
api_router.include_router(protected_router)
