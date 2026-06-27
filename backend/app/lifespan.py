from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import Session

from app.archiver import BrowserOpener, SingleFileArchiver, YtDlpDownloader
from app.core.config import Settings
from app.core.db import get_engine, init_db, run_migrations
from app.crud import (
    ArchiveTaskRepository,
    LoginRateLimiter,
    RuntimeConfigRepository,
    UserRepository,
)
from app.semantic import LocalEmbeddingProvider, SemanticDocumentPreparer
from app.service import ArchiveTaskService


def create_lifespan(settings: Settings):
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        run_migrations(settings.database_url)
        with Session(get_engine(settings.database_url)) as session:
            init_db(session)
        runtime_config_repository = RuntimeConfigRepository(settings.database_url)
        runtime_config_repository.apply_to_settings(settings)

        user_repository = UserRepository(settings.database_url)
        user_repository.cleanup_expired_tokens()

        repository = ArchiveTaskRepository(settings.database_url)
        archiver = SingleFileArchiver(settings)
        video_downloader = YtDlpDownloader(settings)
        browser_opener = BrowserOpener(settings)
        embedding_provider = LocalEmbeddingProvider(settings)
        semantic_preparer = SemanticDocumentPreparer(
            min_chars=settings.semantic_chunk_min_chars,
            max_chars=settings.semantic_chunk_max_chars,
            overlap_chars=settings.semantic_chunk_overlap_chars,
        )
        service = ArchiveTaskService(
            repository,
            archiver,
            video_downloader,
            browser_opener,
            embedding_provider,
            semantic_preparer,
        )
        await service.start()

        app.state.settings = settings
        app.state.runtime_config_repository = runtime_config_repository
        app.state.user_repository = user_repository
        app.state.login_rate_limiter = LoginRateLimiter()
        app.state.archive_task_service = service
        try:
            yield
        finally:
            await service.stop()

    return lifespan
