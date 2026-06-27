from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from uuid import uuid4

from app.archiver import (
    BrowserLoginRequiredError,
    BrowserOpener,
    SingleFileArchiver,
    YtDlpDownloader,
)
from app.crud import ArchiveTaskRepository, SemanticSearchMatch
from app.models import (
    ArchiveTagRead,
    ArchiveTaskListRead,
    ArchiveTaskRead,
    ArchiveTaskSourceType,
    ArchiveTaskStatus,
    RssFeedRead,
    RssFeedRefreshResult,
    SemanticHealthRead,
)
from app.rss import RssFeedFetcher, normalize_article_url, title_from_url
from app.semantic import LocalEmbeddingProvider, SemanticDocumentPreparer, semantic_texts_for_embedding


logger = logging.getLogger(__name__)


class ArchiveTaskService:
    def __init__(
        self,
        repository: ArchiveTaskRepository,
        archiver: SingleFileArchiver,
        video_downloader: YtDlpDownloader,
        browser_opener: BrowserOpener,
        embedding_provider: LocalEmbeddingProvider | None = None,
        semantic_preparer: SemanticDocumentPreparer | None = None,
    ) -> None:
        self.repository = repository
        self.archiver = archiver
        self.video_downloader = video_downloader
        self.browser_opener = browser_opener
        self.embedding_provider = embedding_provider
        self.semantic_preparer = semantic_preparer
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.semantic_queue: asyncio.Queue[str] = asyncio.Queue()
        self.worker: asyncio.Task[None] | None = None
        self.semantic_worker: asyncio.Task[None] | None = None
        self.rss_worker: asyncio.Task[None] | None = None
        self.video_retry_workers: set[asyncio.Task[None]] = set()
        self.rss_lock = asyncio.Lock()
        self.semantic_last_error: str | None = None

    async def start(self) -> None:
        self.repository.initialize()
        self.repository.mark_stale_running_tasks_failed()
        for task_id in self.repository.list_queued():
            await self.queue.put(task_id)
        self.worker = asyncio.create_task(self._run_worker())
        self.semantic_worker = asyncio.create_task(self._run_semantic_worker())
        self.rss_worker = asyncio.create_task(self._run_rss_worker())
        await self._enqueue_semantic_backfill()

    async def stop(self) -> None:
        for worker in (
            self.worker,
            self.semantic_worker,
            self.rss_worker,
            *self.video_retry_workers,
        ):
            if worker is None:
                continue
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass

    async def create_task(
        self,
        url: str,
        source_type: ArchiveTaskSourceType = ArchiveTaskSourceType.MANUAL,
        source_feed_id: str | None = None,
        source_title: str | None = None,
        entry_title: str | None = None,
    ) -> ArchiveTaskRead:
        task_id = uuid4().hex
        output_file = f"{task_id}.html"
        task = self.repository.create(
            task_id,
            url,
            output_file,
            normalized_url=normalize_article_url(url),
            source_type=source_type,
            source_feed_id=source_feed_id,
            source_title=source_title,
            entry_title=entry_title,
        )
        await self.queue.put(task_id)
        return task

    def get_task(self, task_id: str) -> ArchiveTaskRead | None:
        task = self.repository.get(task_id)
        if task is None:
            return None
        return self._with_existing_result_files(task)

    def list_tasks(
        self,
        limit: int,
        offset: int = 0,
        include_read: bool = False,
        tag: str | None = None,
        tags: list[str] | None = None,
        title_query: str | None = None,
        query: str | None = None,
        status_filter: str | None = None,
    ) -> ArchiveTaskListRead:
        tag_filters = self._clean_tags([*(tags or []), *([tag] if tag else [])])
        statuses = self._task_statuses_for_filter(status_filter)
        cleaned_query = self._clean_title(query) or self._clean_title(title_query)
        semantic_matches = self._semantic_matches(cleaned_query)
        tasks, total = self.repository.list_recent(
            limit,
            offset=offset,
            include_read=include_read,
            tags=tag_filters,
            title_query=cleaned_query,
            statuses=statuses,
            semantic_matches=semantic_matches,
        )
        return ArchiveTaskListRead(
            items=[self._with_existing_result_files(task) for task in tasks],
            total=total,
            limit=limit,
            offset=offset,
            has_more=offset + len(tasks) < total,
        )

    def list_tags(self) -> list[ArchiveTagRead]:
        return [ArchiveTagRead(**tag) for tag in self.repository.list_tags()]

    def update_task_metadata(
        self,
        task_id: str,
        custom_title_provided: bool = False,
        custom_title: str | None = None,
        tags: list[str] | None = None,
    ) -> ArchiveTaskRead | None:
        if custom_title_provided:
            if not self.repository.update_custom_title(
                task_id,
                self._clean_title(custom_title),
            ):
                return None
        if tags is not None:
            if not self.repository.replace_task_tags(task_id, self._clean_tags(tags)):
                return None
        task = self.repository.get(task_id)
        return self._with_existing_result_files(task) if task else None

    def mark_task_read(self, task_id: str) -> None:
        self.repository.mark_read(task_id)

    async def rearchive_task(self, task_id: str) -> ArchiveTaskRead:
        task = self.repository.get(task_id)
        if task is None:
            msg = "Archive task not found."
            raise ValueError(msg)
        if task.status in {
            ArchiveTaskStatus.QUEUED,
            ArchiveTaskStatus.RUNNING,
            ArchiveTaskStatus.BROWSER_LOGIN_REQUIRED,
        }:
            msg = "Archive task is still running."
            raise RuntimeError(msg)
        files = list(self.archiver.settings.archive_dir.glob(f"{task_id}.*"))
        for path in files:
            if path.is_file():
                path.unlink(missing_ok=True)
        if not self.repository.requeue_for_rearchive(task_id):
            msg = "Archive task not found."
            raise ValueError(msg)
        await self.queue.put(task_id)
        updated = self.repository.get(task_id)
        if updated is None:
            msg = "Archive task not found."
            raise ValueError(msg)
        return self._with_existing_result_files(updated)

    def delete_task(self, task_id: str) -> bool:
        task = self.repository.get(task_id)
        if task is None:
            return False
        if task.status == ArchiveTaskStatus.RUNNING:
            msg = "Archive task is still running."
            raise ValueError(msg)
        files = list(self.archiver.settings.archive_dir.glob(f"{task_id}.*"))
        deleted = self.repository.delete_archive_task(task_id)
        if not deleted:
            return False
        for path in files:
            if path.is_file():
                path.unlink(missing_ok=True)
        return True

    async def continue_after_browser_login(self, task_id: str) -> ArchiveTaskRead:
        task = self.repository.get(task_id)
        if task is None:
            msg = "Archive task not found."
            raise ValueError(msg)
        if task.status != ArchiveTaskStatus.BROWSER_LOGIN_REQUIRED:
            msg = "Archive task is not waiting for browser login."
            raise ValueError(msg)
        self.repository.mark_running(task_id, current_step="video")
        worker = asyncio.create_task(self._retry_video_after_browser_login(task_id))
        self.video_retry_workers.add(worker)
        worker.add_done_callback(self.video_retry_workers.discard)
        updated = self.repository.get(task_id)
        if updated is None:
            msg = "Archive task not found."
            raise ValueError(msg)
        return updated

    async def open_task_in_browser(self, task_id: str) -> None:
        task = self.repository.get(task_id)
        if task is None:
            msg = "Archive task not found."
            raise ValueError(msg)
        await self.browser_opener.open(task.url)

    def get_result_path(self, task: ArchiveTaskRead) -> Path:
        if task.result is None or task.result.file_name is None:
            msg = "Archive task has no result file."
            raise ValueError(msg)
        return self.archiver.settings.archive_dir / task.result.file_name

    def get_video_result_path(self, task: ArchiveTaskRead) -> Path:
        if task.result is None or task.result.video_file_name is None:
            msg = "Archive task has no video result file."
            raise ValueError(msg)
        return self.archiver.settings.archive_dir / task.result.video_file_name

    def list_result_files(self, task: ArchiveTaskRead) -> list[Path]:
        return sorted(
            (
                path
                for path in self.archiver.settings.archive_dir.glob(
                    f"{task.task_id}.*",
                )
                if path.is_file()
            ),
            key=lambda path: path.name,
        )

    def get_task_file_path(self, task: ArchiveTaskRead, file_name: str) -> Path:
        if "/" in file_name or "\\" in file_name or Path(file_name).name != file_name:
            msg = "Invalid file name."
            raise ValueError(msg)
        if not file_name.startswith(f"{task.task_id}."):
            msg = "File does not belong to this archive task."
            raise ValueError(msg)
        return self.archiver.settings.archive_dir / file_name

    async def upload_task_file(
        self,
        task: ArchiveTaskRead,
        original_file_name: str,
        chunks: AsyncIterator[bytes],
    ) -> Path:
        display_name = self._clean_file_display_name(original_file_name)
        if self._display_name_exists(task, display_name):
            msg = "同名文件已存在。"
            raise ValueError(msg)

        suffix = Path(display_name).suffix[:24]
        if suffix and not re.fullmatch(r"\.[A-Za-z0-9][A-Za-z0-9._-]*", suffix):
            suffix = ""
        archive_dir = self.archiver.settings.archive_dir
        archive_dir.mkdir(parents=True, exist_ok=True)
        final_path = archive_dir / f"{task.task_id}.upload-{uuid4().hex}{suffix}"
        temp_path = final_path.with_name(f".{final_path.name}.tmp")
        try:
            with temp_path.open("xb") as handle:
                async for chunk in chunks:
                    if chunk:
                        handle.write(chunk)
            temp_path.replace(final_path)
            if not self.repository.upsert_archive_file(
                task.task_id,
                final_path.name,
                display_name,
                "upload",
            ):
                msg = "Archive task not found."
                raise ValueError(msg)
        except Exception:
            temp_path.unlink(missing_ok=True)
            final_path.unlink(missing_ok=True)
            raise
        return final_path

    def update_task_file_display_name(
        self,
        task: ArchiveTaskRead,
        file_name: str,
        display_name: str,
    ) -> Path:
        path = self.get_task_file_path(task, file_name)
        if not path.exists():
            msg = "Archive file is missing."
            raise FileNotFoundError(msg)
        clean_name = self._clean_file_display_name(display_name)
        if self._display_name_exists(task, clean_name, except_file_name=file_name):
            msg = "同名文件已存在。"
            raise ValueError(msg)
        source_type = self.task_file_source_type(task, path)
        if not self.repository.update_archive_file_display_name(
            task.task_id,
            path.name,
            clean_name,
            source_type,
        ):
            msg = "Archive task not found."
            raise ValueError(msg)
        return path

    def delete_task_file(self, task: ArchiveTaskRead, file_name: str) -> bool:
        path = self.get_task_file_path(task, file_name)
        if not path.exists():
            return False
        path.unlink()
        self.repository.delete_archive_file_metadata(task.task_id, path.name)
        return True

    def task_file_display_name(self, task: ArchiveTaskRead, path: Path) -> str:
        metadata = self.repository.file_metadata_for_task(task.task_id).get(path.name)
        if metadata:
            return metadata["display_name"]
        return self._default_file_display_name(task, path)

    def task_file_source_type(self, task: ArchiveTaskRead, path: Path) -> str:
        metadata = self.repository.file_metadata_for_task(task.task_id).get(path.name)
        if metadata:
            return metadata["source_type"]
        if task.result and path.name == task.result.file_name:
            return "singlefile"
        return "yt-dlp"

    async def create_rss_feed(
        self,
        url: str,
        title: str | None = None,
    ) -> RssFeedRefreshResult:
        clean_title = self._clean_title(title) or title_from_url(url)
        feed = self.repository.create_rss_feed(uuid4().hex, url, clean_title)
        return await self.refresh_rss_feed(feed.feed_id)

    def list_rss_feeds(self) -> list[RssFeedRead]:
        return self.repository.list_rss_feeds()

    def update_rss_feed(
        self,
        feed_id: str,
        title: str | None = None,
        enabled: bool | None = None,
    ) -> RssFeedRead | None:
        clean_title = self._clean_title(title) if title is not None else None
        return self.repository.update_rss_feed(
            feed_id,
            title=clean_title,
            enabled=enabled,
        )

    def delete_rss_feed(self, feed_id: str) -> bool:
        return self.repository.delete_rss_feed(feed_id)

    async def refresh_rss_feed(self, feed_id: str) -> RssFeedRefreshResult:
        async with self.rss_lock:
            feed = self.repository.get_rss_feed(feed_id)
            if feed is None:
                msg = "RSS feed not found."
                raise ValueError(msg)
            discovered_count = 0
            created_task_count = 0
            try:
                fetcher = RssFeedFetcher(
                    self.archiver.settings.rss_request_timeout_seconds,
                )
                parsed_feed = await asyncio.to_thread(fetcher.fetch, feed.url)
                for entry in reversed(parsed_feed.entries):
                    discovered_count += 1
                    if self.repository.rss_entry_exists(entry.normalized_url):
                        continue
                    if self.repository.archive_task_exists_for_normalized_url(
                        entry.normalized_url,
                    ):
                        continue
                    task = await self.create_task(
                        entry.url,
                        source_type=ArchiveTaskSourceType.RSS,
                        source_feed_id=feed.feed_id,
                        source_title=parsed_feed.title or feed.title,
                        entry_title=entry.title,
                    )
                    self.repository.create_rss_entry(
                        uuid4().hex,
                        feed.feed_id,
                        entry.url,
                        entry.normalized_url,
                        entry.title,
                        entry.published_at,
                        task.task_id,
                    )
                    created_task_count += 1
                self.repository.mark_rss_feed_checked(
                    feed.feed_id,
                    parsed_feed.title,
                    None,
                )
            except Exception as exc:
                self.repository.mark_rss_feed_checked(
                    feed.feed_id,
                    None,
                    self._short_error(str(exc)),
                )
            updated_feed = self.repository.get_rss_feed(feed.feed_id)
            if updated_feed is None:
                msg = "RSS feed was deleted during refresh."
                raise ValueError(msg)
            return RssFeedRefreshResult(
                feed=updated_feed,
                discovered_count=discovered_count,
                created_task_count=created_task_count,
            )

    async def _run_worker(self) -> None:
        while True:
            task_id = await self.queue.get()
            task = self.repository.get(task_id)
            if task is None:
                self.queue.task_done()
                continue
            try:
                self.repository.mark_running(task_id, current_step="page+video")
                page_job = asyncio.create_task(
                    self._archive_page(task, f"{task_id}.html"),
                )
                video_job = asyncio.create_task(self._download_video(task.url, task_id))
                page_error, video_result = await asyncio.gather(page_job, video_job)
                video_file, video_title, video_error, needs_browser_login = video_result
                if needs_browser_login:
                    self.repository.mark_browser_login_required(
                        task_id,
                        video_error=video_error or "浏览器登录需手动确认",
                        page_error=page_error,
                    )
                    continue
                if page_error and video_file is None:
                    if video_error:
                        raise RuntimeError(
                            f"网页保存失败：{page_error}；视频下载失败：{video_error}",
                        )
                    raise RuntimeError(page_error)
                self.repository.mark_succeeded(
                    task_id,
                    video_file=video_file,
                    video_title=video_title,
                    video_error=video_error,
                    page_error=page_error,
                )
                if page_error is None:
                    await self._enqueue_semantic_task(task_id)
            except Exception as exc:
                self.repository.mark_failed(task_id, str(exc))
            finally:
                self.queue.task_done()

    async def _run_rss_worker(self) -> None:
        while True:
            try:
                await self._refresh_due_rss_feeds()
            except Exception:
                pass
            await asyncio.sleep(max(1, self.archiver.settings.rss_refresh_interval_seconds))

    async def _run_semantic_worker(self) -> None:
        if self.embedding_provider is not None:
            try:
                await asyncio.to_thread(self.embedding_provider.preload)
            except Exception as exc:
                self.semantic_last_error = self._short_error(str(exc))
                logger.exception("Semantic embedding model failed to preload.")
        while True:
            task_id = await self.semantic_queue.get()
            try:
                await asyncio.to_thread(self._index_task_semantics, task_id)
            except Exception as exc:
                self.semantic_last_error = self._short_error(str(exc))
                logger.exception("Semantic indexing failed for task %s.", task_id)
            finally:
                self.semantic_queue.task_done()

    async def _refresh_due_rss_feeds(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(
            seconds=self.archiver.settings.rss_refresh_interval_seconds,
        )
        for feed in self.repository.list_enabled_rss_feeds_due(cutoff.isoformat()):
            await self.refresh_rss_feed(feed.feed_id)

    async def _archive_page(self, task: ArchiveTaskRead, output_file: str) -> str | None:
        try:
            await self.archiver.archive(task.url, output_file)
            archived_title = await asyncio.to_thread(
                self._title_from_archive,
                self.archiver.settings.archive_dir / output_file,
            )
            if self._should_update_entry_title(task, archived_title):
                self.repository.update_entry_title(task.task_id, archived_title)
        except Exception as exc:
            return self._short_error(str(exc))
        return None

    async def _enqueue_semantic_backfill(self) -> None:
        if not self._semantic_enabled():
            return
        for task_id in self.repository.list_task_ids_requiring_semantic_index(
            self._semantic_model_name(),
            self._semantic_embedding_dimensions(),
            self._semantic_text_version(),
        ):
            await self.semantic_queue.put(task_id)

    async def _enqueue_semantic_task(self, task_id: str) -> None:
        if self._semantic_enabled():
            await self.semantic_queue.put(task_id)

    def _index_task_semantics(self, task_id: str) -> None:
        if not self._semantic_enabled():
            return
        model_name = self._semantic_model_name()
        embedding_dimensions = self._semantic_embedding_dimensions()
        text_version = self._semantic_text_version()
        task = self.repository.get(task_id)
        if task is None or task.result is None or task.result.file_name is None:
            return
        path = self.archiver.settings.archive_dir / task.result.file_name
        if not path.is_file():
            self.repository.mark_semantic_index_failed(
                task_id,
                model_name,
                embedding_dimensions,
                text_version,
                "Archive file is missing.",
            )
            return
        assert self.semantic_preparer is not None
        assert self.embedding_provider is not None
        document_hash: str | None = None
        try:
            prepared = self.semantic_preparer.prepare(path)
            if prepared is None:
                self.repository.mark_semantic_index_skipped(
                    task_id,
                    model_name,
                    embedding_dimensions,
                    text_version,
                    None,
                    "No readable text was extracted.",
                )
                return
            document_hash = prepared.document_hash
            existing = self.repository.semantic_index_record(task_id, model_name, text_version)
            if (
                existing is not None
                and existing.status == "indexed"
                and existing.document_hash == prepared.document_hash
                and existing.embedding_dimensions == embedding_dimensions
            ):
                return
            self.repository.mark_semantic_indexing(
                task_id,
                model_name,
                embedding_dimensions,
                text_version,
            )
            texts = semantic_texts_for_embedding(task.display_title, prepared.chunks)
            embeddings: list[list[float]] = []
            batch_size = max(1, self.archiver.settings.semantic_batch_size)
            for index in range(0, len(texts), batch_size):
                batch = texts[index : index + batch_size]
                batch_embeddings = self.embedding_provider.embed(batch)
                if len(batch_embeddings) != len(batch):
                    msg = "Semantic embedding count did not match chunk count."
                    raise RuntimeError(msg)
                for vector in batch_embeddings:
                    self._validate_embedding_dimensions(vector)
                embeddings.extend(batch_embeddings)
            if not embeddings:
                self.repository.mark_semantic_index_skipped(
                    task_id,
                    model_name,
                    embedding_dimensions,
                    text_version,
                    prepared.document_hash,
                    "No semantic embeddings were generated.",
                )
                return
            self.repository.replace_semantic_chunks(
                task_id,
                model_name,
                embedding_dimensions,
                text_version,
                prepared.document_hash,
                prepared.chunks,
                embeddings,
            )
            self.semantic_last_error = None
        except Exception as exc:
            error = self._short_error(str(exc))
            self.semantic_last_error = error
            self.repository.mark_semantic_index_failed(
                task_id,
                model_name,
                embedding_dimensions,
                text_version,
                error,
                document_hash=document_hash,
            )
            raise

    def _semantic_matches(self, query: str | None) -> dict[str, SemanticSearchMatch]:
        if not query:
            return {}
        model_name = self._semantic_model_name()
        matches = self.repository.search_semantic_chunk_text(
            query,
            model_name,
            self.archiver.settings.semantic_search_limit,
        )
        if not self._semantic_enabled():
            return matches
        assert self.embedding_provider is not None
        try:
            embeddings = self.embedding_provider.embed([query])
            if len(embeddings) != 1:
                return matches
            self._validate_embedding_dimensions(embeddings[0])
            semantic_matches = self.repository.search_semantic_chunks(
                embeddings[0],
                self.embedding_provider.model_name,
                self.archiver.settings.semantic_search_limit,
                self.archiver.settings.semantic_min_score,
            )
        except Exception as exc:
            self.semantic_last_error = self._short_error(str(exc))
            logger.exception("Semantic search failed.")
            return matches
        for task_id, match in semantic_matches.items():
            existing = matches.get(task_id)
            if existing is None or match.score > existing.score:
                matches[task_id] = match
        return matches

    def semantic_health(self) -> SemanticHealthRead:
        enabled = self.archiver.settings.semantic_search_enabled
        model_name = self._semantic_model_name()
        text_version = self._semantic_text_version()
        indexed_count, failed_count = self.repository.semantic_health_counts(model_name, text_version)
        last_error = self.semantic_last_error or self._embedding_last_error()
        if last_error is None:
            last_error = self.repository.latest_semantic_error(model_name, text_version)
        available = enabled and self.embedding_provider is not None and self.embedding_provider.available
        if not enabled:
            status = "disabled"
        elif not available:
            status = "unavailable"
        elif self.semantic_queue.qsize() > 0:
            status = "indexing"
        elif failed_count > 0 or last_error:
            status = "degraded"
        else:
            status = "ready"
        return SemanticHealthRead(
            enabled=enabled,
            available=available,
            status=status,
            model_name=model_name,
            embedding_dimensions=self._semantic_embedding_dimensions(),
            text_version=text_version,
            queued_count=self.semantic_queue.qsize(),
            indexed_count=indexed_count,
            failed_count=failed_count,
            last_error=last_error,
        )

    def _semantic_enabled(self) -> bool:
        return (
            self.archiver.settings.semantic_search_enabled
            and self.embedding_provider is not None
            and self.semantic_preparer is not None
            and self.embedding_provider.available
        )

    def _semantic_model_name(self) -> str:
        if self.embedding_provider is not None:
            return self.embedding_provider.model_name
        return self.archiver.settings.semantic_model_name

    def _semantic_embedding_dimensions(self) -> int:
        return self.archiver.settings.semantic_embedding_dimensions

    def _semantic_text_version(self) -> str:
        return self.archiver.settings.semantic_text_version

    def _embedding_last_error(self) -> str | None:
        if self.embedding_provider is None:
            return None
        return self.embedding_provider.last_error

    def _validate_embedding_dimensions(self, vector: list[float]) -> None:
        actual = len(vector)
        expected = self._semantic_embedding_dimensions()
        if actual != expected:
            msg = f"Embedding dimensions mismatch: expected {expected}, got {actual}."
            raise ValueError(msg)

    async def _retry_video_after_browser_login(self, task_id: str) -> None:
        task = self.repository.get(task_id)
        if task is None:
            return
        page_error = task.result.page_error if task.result else None
        try:
            video_file, video_title, video_error, needs_browser_login = await self._download_video(
                task.url,
                task_id,
            )
            if needs_browser_login:
                self.repository.mark_browser_login_required(
                    task_id,
                    video_error=video_error or "浏览器登录需手动确认",
                    page_error=page_error,
                )
                return
            if page_error and video_file is None:
                if video_error:
                    raise RuntimeError(
                        f"网页保存失败：{page_error}；视频下载失败：{video_error}",
                    )
                raise RuntimeError(page_error)
            self.repository.mark_succeeded(
                task_id,
                video_file=video_file,
                video_title=video_title,
                video_error=video_error,
                page_error=page_error,
            )
            if page_error is None:
                await self._enqueue_semantic_task(task_id)
        except Exception as exc:
            self.repository.mark_failed(task_id, str(exc))

    async def _download_video(
        self,
        url: str,
        task_id: str,
    ) -> tuple[str | None, str | None, str | None, bool]:
        try:
            video_files = await self.video_downloader.download(url, task_id)
            video_title = await asyncio.to_thread(self._title_from_video_info, task_id)
            return self._primary_video_file(video_files), video_title, None, False
        except BrowserLoginRequiredError as exc:
            return None, None, self._short_error(str(exc)), True
        except Exception as exc:
            return None, None, self._short_error(str(exc)), False

    def _short_error(self, value: str) -> str:
        lines = [" ".join(line.split()) for line in value.splitlines() if line.strip()]
        selected = next(
            (line for line in reversed(lines) if line.lower().startswith("error:")),
            lines[-1] if lines else "",
        )
        cleaned = selected.removeprefix("ERROR:").strip() or "未下载到视频。"
        if len(cleaned) > 180:
            return f"{cleaned[:180]}..."
        return cleaned

    def _primary_video_file(self, file_names: list[str]) -> str | None:
        media_extensions = {
            ".3gp",
            ".flv",
            ".m4a",
            ".m4v",
            ".mkv",
            ".mov",
            ".mp3",
            ".mp4",
            ".ogg",
            ".opus",
            ".webm",
        }
        for file_name in file_names:
            if Path(file_name).suffix.lower() in media_extensions:
                return file_name
        return file_names[0] if file_names else None

    def _clean_title(self, value: str | None) -> str | None:
        cleaned = " ".join(str(value or "").split())
        return cleaned or None

    def _clean_file_display_name(self, value: str | None) -> str:
        name = Path(str(value or "").replace("\\", "/")).name
        name = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", " ", name)
        name = re.sub(r"\s+", " ", name).strip(" .")
        if not name:
            msg = "文件名不能为空。"
            raise ValueError(msg)
        return name[:240].rstrip(" .")

    def _display_name_exists(
        self,
        task: ArchiveTaskRead,
        display_name: str,
        except_file_name: str | None = None,
    ) -> bool:
        target = display_name.casefold()
        for path in self.list_result_files(task):
            if except_file_name and path.name == except_file_name:
                continue
            if self.task_file_display_name(task, path).casefold() == target:
                return True
        return False

    def _default_file_display_name(self, task: ArchiveTaskRead, path: Path) -> str:
        original_name = path.name
        prefix = f"{task.task_id}."
        if not original_name.startswith(prefix):
            return original_name
        suffix = original_name.removeprefix(task.task_id)
        return f"{self._safe_file_title(task.display_title)}{suffix}"

    def _safe_file_title(self, value: str) -> str:
        title = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", value)
        title = re.sub(r"\s+", " ", title).strip(" .")
        if not title:
            return "archive"
        return title[:120].rstrip(" .")

    def _with_existing_result_files(self, task: ArchiveTaskRead) -> ArchiveTaskRead:
        if task.result is None:
            return task
        result = task.result.model_copy()
        archive_dir = self.archiver.settings.archive_dir
        if result.file_name and not (archive_dir / result.file_name).is_file():
            result.file_name = None
            result.download_url = None
        if result.video_file_name and not (archive_dir / result.video_file_name).is_file():
            result.video_file_name = None
            result.video_download_url = None
        result.view_url = (
            f"/api/v1/archive-tasks/{task.task_id}/files"
            if self.list_result_files(task)
            else None
        )
        return task.model_copy(update={"result": result})

    def _clean_tag(self, value: str | None) -> str | None:
        cleaned = " ".join(str(value or "").split())
        return cleaned or None

    def _clean_tags(self, values: list[str]) -> list[str]:
        tags: list[str] = []
        seen: set[str] = set()
        for value in values:
            tag = self._clean_tag(value)
            if not tag:
                continue
            key = tag.casefold()
            if key in seen:
                continue
            seen.add(key)
            tags.append(tag)
        return tags

    def _task_statuses_for_filter(self, value: str | None) -> list[str] | None:
        if value == "running":
            return [
                ArchiveTaskStatus.QUEUED,
                ArchiveTaskStatus.RUNNING,
                ArchiveTaskStatus.BROWSER_LOGIN_REQUIRED,
            ]
        if value == "failed":
            return [ArchiveTaskStatus.FAILED]
        return None

    def _should_update_entry_title(
        self,
        task: ArchiveTaskRead,
        archived_title: str | None,
    ) -> bool:
        title = self._clean_title(archived_title)
        if not title:
            return False
        current_title = self._clean_title(task.entry_title)
        return current_title is None or current_title == title_from_url(task.url)

    def _title_from_archive(self, path: Path) -> str | None:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None
        parser = _TitleParser()
        parser.feed(content)
        return self._clean_title(parser.title)

    def _title_from_video_info(self, task_id: str) -> str | None:
        path = self.archiver.settings.archive_dir / f"{task_id}.info.json"
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(metadata, dict):
            return None
        for key in ("title", "fulltitle"):
            title = self._clean_title(metadata.get(key))
            if title:
                return title
        return None


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_title = False
        self._parts: list[str] = []

    @property
    def title(self) -> str | None:
        return " ".join("".join(self._parts).split()) or None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._parts.append(data)
