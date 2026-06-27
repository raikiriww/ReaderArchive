from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, delete, select

from app.core.db import get_engine
from app.core.security import (
    decode_access_token,
    get_password_hash,
    hash_token,
    verify_password,
)
from app.models import (
    AppConfigRead,
    AppConfigUpdate,
    AppSetting,
    ArchiveFile,
    ArchiveSemanticChunk,
    ArchiveSemanticIndex,
    ArchiveTag,
    ArchiveTask,
    ArchiveTaskRead,
    ArchiveTaskResult,
    ArchiveTaskSearchMatch,
    ArchiveTaskSourceType,
    ArchiveTaskStatus,
    ArchiveTaskTag,
    LoginToken,
    RssEntry,
    RssFeedRead,
    RssSource,
    SemanticHealthRead,
    User,
    UserRead,
    new_id,
    utc_now,
)


@dataclass(frozen=True)
class SemanticSearchMatch:
    task_id: str
    excerpt: str
    score: float


@dataclass(frozen=True)
class SemanticIndexRecord:
    task_id: str
    model_name: str
    embedding_dimensions: int
    text_version: str
    document_hash: str | None
    status: str
    chunk_count: int
    last_error: str | None


def _clean_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


class LoginRateLimiter:
    def __init__(self) -> None:
        self.attempts: dict[str, list[datetime]] = {}

    def check(self, key: str) -> bool:
        now = datetime.now(UTC)
        window_start = now - timedelta(minutes=10)
        recent = [attempt for attempt in self.attempts.get(key, []) if attempt > window_start]
        self.attempts[key] = recent
        return len(recent) < 8

    def record_failure(self, key: str) -> None:
        self.attempts.setdefault(key, []).append(datetime.now(UTC))

    def clear(self, key: str) -> None:
        self.attempts.pop(key, None)


class UserRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.engine = get_engine(database_url)

    def list_users(self) -> list[UserRead]:
        with self._session() as session:
            users = session.exec(select(User).order_by(col(User.username))).all()
            return [self._to_user_read(user) for user in users]

    def get_user(self, user_id: str) -> UserRead | None:
        with self._session() as session:
            user = session.get(User, user_id)
            return self._to_user_read(user) if user else None

    def get_user_by_username(self, username: str) -> User | None:
        with self._session() as session:
            return session.exec(select(User).where(User.username == username.strip())).first()

    def authenticate(self, username: str, password: str) -> UserRead | None:
        with self._session() as session:
            user = session.exec(select(User).where(User.username == username.strip())).first()
            if user is None or not user.is_active:
                return None
            verified, updated_hash = verify_password(password, user.password_hash)
            if not verified:
                return None
            if updated_hash:
                user.password_hash = updated_hash
                user.updated_at = utc_now()
                session.add(user)
                session.commit()
                session.refresh(user)
            return self._to_user_read(user)

    def create_login_token(self, user_id: str, token_id: str, expires_at: datetime) -> None:
        now = utc_now()
        with self._session() as session:
            session.add(
                LoginToken(
                    token_hash=hash_token(token_id),
                    user_id=user_id,
                    created_at=now,
                    last_seen_at=now,
                    expires_at=expires_at,
                )
            )
            session.commit()

    def current_user_from_token(self, token: str) -> UserRead | None:
        try:
            payload = decode_access_token(token)
        except Exception:
            return None
        user_id = payload.get("sub")
        token_id = payload.get("jti")
        if not isinstance(user_id, str) or not isinstance(token_id, str):
            return None
        now = utc_now()
        token_hash = hash_token(token_id)
        with self._session() as session:
            login_token = session.exec(
                select(LoginToken).where(LoginToken.token_hash == token_hash)
            ).first()
            if login_token is None:
                return None
            expires_at = _clean_datetime(login_token.expires_at)
            if expires_at is None or expires_at <= now:
                if login_token is not None:
                    session.delete(login_token)
                    session.commit()
                return None
            user = session.get(User, user_id)
            if user is None or not user.is_active:
                return None
            login_token.last_seen_at = now
            session.add(login_token)
            session.commit()
            return self._to_user_read(user)

    def delete_token(self, token: str) -> None:
        try:
            payload = decode_access_token(token)
        except Exception:
            return
        token_id = payload.get("jti")
        if not isinstance(token_id, str):
            return
        with self._session() as session:
            login_token = session.exec(
                select(LoginToken).where(LoginToken.token_hash == hash_token(token_id))
            ).first()
            if login_token is not None:
                session.delete(login_token)
                session.commit()

    def cleanup_expired_tokens(self) -> None:
        with self._session() as session:
            session.exec(delete(LoginToken).where(LoginToken.expires_at <= utc_now()))
            session.commit()

    def create_user(self, username: str, password: str, role: str) -> UserRead:
        now = utc_now()
        user = User(
            username=username.strip(),
            password_hash=get_password_hash(password),
            role=role,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        with self._session() as session:
            try:
                session.add(user)
                session.commit()
                session.refresh(user)
            except IntegrityError as exc:
                session.rollback()
                msg = "Username already exists."
                raise ValueError(msg) from exc
            return self._to_user_read(user)

    def update_user(
        self,
        user_id: str,
        enabled: bool | None = None,
        role: str | None = None,
    ) -> UserRead | None:
        with self._session() as session:
            user = session.get(User, user_id)
            if user is None:
                return None
            new_enabled = user.is_active if enabled is None else enabled
            new_role = user.role if role is None else role
            if user.role == "admin" and (not new_enabled or new_role != "admin"):
                self._ensure_another_enabled_admin(session, user_id)
            if enabled is not None:
                user.is_active = enabled
            if role is not None:
                user.role = role
            user.updated_at = utc_now()
            session.add(user)
            session.commit()
            session.refresh(user)
            return self._to_user_read(user)

    def reset_password(self, user_id: str, password: str) -> UserRead | None:
        with self._session() as session:
            user = session.get(User, user_id)
            if user is None:
                return None
            user.password_hash = get_password_hash(password)
            user.updated_at = utc_now()
            session.add(user)
            session.exec(delete(LoginToken).where(LoginToken.user_id == user_id))
            session.commit()
            session.refresh(user)
            return self._to_user_read(user)

    def change_password(
        self,
        user_id: str,
        current_password: str,
        new_password: str,
    ) -> UserRead | None:
        with self._session() as session:
            user = session.get(User, user_id)
            if user is None:
                return None
            verified, _updated_hash = verify_password(current_password, user.password_hash)
            if not verified:
                return None
            user.password_hash = get_password_hash(new_password)
            user.updated_at = utc_now()
            session.add(user)
            session.commit()
            session.refresh(user)
            return self._to_user_read(user)

    def delete_user(self, user_id: str) -> bool:
        with self._session() as session:
            user = session.get(User, user_id)
            if user is None:
                return False
            if user.role == "admin" and user.is_active:
                self._ensure_another_enabled_admin(session, user_id)
            session.exec(delete(LoginToken).where(LoginToken.user_id == user_id))
            session.delete(user)
            session.commit()
            return True

    def _ensure_another_enabled_admin(self, session: Session, user_id: str) -> None:
        count = session.exec(
            select(func.count())
            .select_from(User)
            .where(User.id != user_id, User.role == "admin", User.is_active == True)  # noqa: E712
        ).one()
        if int(count) == 0:
            msg = "At least one enabled admin user is required."
            raise ValueError(msg)

    def _to_user_read(self, user: User) -> UserRead:
        return UserRead(
            user_id=user.id,
            username=user.username,
            role=user.role,
            enabled=user.is_active,
            created_at=_clean_datetime(user.created_at) or utc_now(),
            updated_at=_clean_datetime(user.updated_at) or utc_now(),
        )

    def _session(self) -> Session:
        return Session(self.engine, expire_on_commit=False)


class RuntimeConfigRepository:
    integer_keys = {
        "poll_interval_ms",
        "rss_refresh_interval_seconds",
    }

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.engine = get_engine(database_url)

    def apply_to_settings(self, settings) -> None:  # type: ignore[no-untyped-def]
        for key, value in self._read_values().items():
            if key not in self.integer_keys:
                continue
            try:
                setattr(settings, key, int(value))
            except ValueError:
                continue

    def read_app_config(  # type: ignore[no-untyped-def]
        self,
        settings,
        semantic_search: SemanticHealthRead | None = None,
    ) -> AppConfigRead:
        return AppConfigRead(
            desktop_url=settings.desktop_url,
            archive_dir=str(settings.archive_dir),
            poll_interval_ms=settings.poll_interval_ms,
            rss_refresh_interval_seconds=settings.rss_refresh_interval_seconds,
            semantic_search=semantic_search,
        )

    def update_app_config(  # type: ignore[no-untyped-def]
        self,
        settings,
        payload: AppConfigUpdate,
        semantic_search: SemanticHealthRead | None = None,
    ) -> AppConfigRead:
        values = payload.model_dump(exclude_none=True)
        if not values:
            return self.read_app_config(settings, semantic_search)

        with self._session() as session:
            for key, value in values.items():
                setting = session.exec(select(AppSetting).where(AppSetting.key == key)).first()
                if setting is None:
                    setting = AppSetting(key=key, value=str(value), updated_at=utc_now())
                else:
                    setting.value = str(value)
                    setting.updated_at = utc_now()
                session.add(setting)
                setattr(settings, key, value)
            session.commit()

        return self.read_app_config(settings, semantic_search)

    def _read_values(self) -> dict[str, str]:
        with self._session() as session:
            rows = session.exec(select(AppSetting)).all()
            return {row.key: row.value for row in rows}

    def _session(self) -> Session:
        return Session(self.engine, expire_on_commit=False)


class ArchiveTaskRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.engine = get_engine(database_url)

    def initialize(self) -> None:
        return

    def create(
        self,
        task_id: str,
        url: str,
        output_file: str,
        normalized_url: str | None = None,
        source_type: ArchiveTaskSourceType = ArchiveTaskSourceType.MANUAL,
        source_feed_id: str | None = None,
        source_title: str | None = None,
        entry_title: str | None = None,
    ) -> ArchiveTaskRead:
        now = utc_now()
        task = ArchiveTask(
            id=task_id,
            url=url,
            normalized_url=normalized_url,
            status=ArchiveTaskStatus.QUEUED,
            output_file=output_file,
            created_at=now,
            updated_at=now,
            current_step="queued",
            source_type=str(source_type),
            source_feed_id=source_feed_id,
            source_title=source_title,
            entry_title=entry_title,
        )
        with self._session() as session:
            session.add(task)
            session.commit()
            session.refresh(task)
            return self._to_task(session, task)

    def get(self, task_id: str) -> ArchiveTaskRead | None:
        with self._session() as session:
            task = session.get(ArchiveTask, task_id)
            return self._to_task(session, task) if task else None

    def list_recent(
        self,
        limit: int,
        offset: int = 0,
        include_read: bool = False,
        tags: list[str] | None = None,
        title_query: str | None = None,
        statuses: list[str] | None = None,
        semantic_matches: dict[str, SemanticSearchMatch] | None = None,
    ) -> tuple[list[ArchiveTaskRead], int]:
        status_values = [str(status) for status in (statuses or [])]
        tag_names = [tag.casefold() for tag in (tags or [])]
        cleaned_query = " ".join(str(title_query or "").split()).casefold()
        semantic_matches = semantic_matches or {}
        with self._session() as session:
            statement = select(ArchiveTask).order_by(col(ArchiveTask.created_at).desc())
            if not include_read:
                statement = statement.where(ArchiveTask.is_read == False)  # noqa: E712
            if status_values:
                statement = statement.where(col(ArchiveTask.status).in_(status_values))
            tasks = session.exec(statement).all()
            selected: list[tuple[ArchiveTaskRead, float]] = []
            for task in tasks:
                response = self._to_task(session, task)
                lexical_score = self._lexical_score(response, cleaned_query)
                semantic_match = semantic_matches.get(task.id)
                if cleaned_query and lexical_score <= 0 and semantic_match is None:
                    continue
                if tag_names:
                    task_tags = {tag.casefold() for tag in response.tags}
                    if not any(tag in task_tags for tag in tag_names):
                        continue
                if semantic_match is not None:
                    response = response.model_copy(
                        update={
                            "search_match": ArchiveTaskSearchMatch(
                                excerpt=semantic_match.excerpt,
                                score=semantic_match.score,
                            )
                        }
                    )
                selected.append((response, lexical_score))
            if cleaned_query:
                selected.sort(
                    key=lambda item: (
                        (item[0].search_match.score if item[0].search_match else 0.0)
                        + item[1],
                        item[0].created_at,
                    ),
                    reverse=True,
                )
            total = len(selected)
            return [task for task, _lexical_score in selected[offset : offset + limit]], total

    def list_task_ids_requiring_semantic_index(
        self,
        model_name: str,
        embedding_dimensions: int,
        text_version: str,
    ) -> list[str]:
        with self._session() as session:
            rows = session.execute(
                text(
                    """
                    SELECT task.id
                    FROM reader_archive_tasks task
                    LEFT JOIN reader_archive_semantic_indexes semantic_index
                        ON semantic_index.task_id = task.id
                        AND semantic_index.model_name = :model_name
                        AND semantic_index.text_version = :text_version
                    WHERE task.status = :status
                        AND task.output_file IS NOT NULL
                        AND task.page_error IS NULL
                        AND (
                            semantic_index.id IS NULL
                            OR semantic_index.status != 'indexed'
                            OR semantic_index.embedding_dimensions != :embedding_dimensions
                        )
                    ORDER BY task.created_at DESC
                    """
                ),
                {
                    "model_name": model_name,
                    "embedding_dimensions": embedding_dimensions,
                    "text_version": text_version,
                    "status": str(ArchiveTaskStatus.SUCCEEDED),
                },
            ).all()
            return [str(row[0]) for row in rows]

    def semantic_index_record(
        self,
        task_id: str,
        model_name: str,
        text_version: str,
    ) -> SemanticIndexRecord | None:
        with self._session() as session:
            row = session.exec(
                select(ArchiveSemanticIndex)
                .where(
                    ArchiveSemanticIndex.task_id == task_id,
                    ArchiveSemanticIndex.model_name == model_name,
                    ArchiveSemanticIndex.text_version == text_version,
                )
                .limit(1)
            ).first()
            if row is None:
                return None
            return SemanticIndexRecord(
                task_id=row.task_id,
                model_name=row.model_name,
                embedding_dimensions=row.embedding_dimensions,
                text_version=row.text_version,
                document_hash=row.document_hash,
                status=row.status,
                chunk_count=row.chunk_count,
                last_error=row.last_error,
            )

    def mark_semantic_indexing(
        self,
        task_id: str,
        model_name: str,
        embedding_dimensions: int,
        text_version: str,
    ) -> None:
        self._upsert_semantic_index(
            task_id,
            model_name,
            embedding_dimensions,
            text_version,
            status="indexing",
            document_hash=None,
            chunk_count=0,
            last_error=None,
            indexed_at=None,
        )

    def mark_semantic_index_skipped(
        self,
        task_id: str,
        model_name: str,
        embedding_dimensions: int,
        text_version: str,
        document_hash: str | None,
        reason: str,
    ) -> None:
        self._upsert_semantic_index(
            task_id,
            model_name,
            embedding_dimensions,
            text_version,
            status="skipped",
            document_hash=document_hash,
            chunk_count=0,
            last_error=reason,
            indexed_at=utc_now(),
        )

    def mark_semantic_index_failed(
        self,
        task_id: str,
        model_name: str,
        embedding_dimensions: int,
        text_version: str,
        error: str,
        document_hash: str | None = None,
    ) -> None:
        self._upsert_semantic_index(
            task_id,
            model_name,
            embedding_dimensions,
            text_version,
            status="failed",
            document_hash=document_hash,
            chunk_count=0,
            last_error=error,
            indexed_at=None,
        )

    def replace_semantic_chunks(
        self,
        task_id: str,
        model_name: str,
        embedding_dimensions: int,
        text_version: str,
        document_hash: str,
        chunks: list[str],
        embeddings: list[list[float]],
    ) -> None:
        if len(chunks) != len(embeddings):
            msg = "Semantic chunk and embedding counts differ."
            raise ValueError(msg)
        now = utc_now()
        with self._session() as session:
            session.exec(
                delete(ArchiveSemanticChunk).where(
                    ArchiveSemanticChunk.task_id == task_id,
                    ArchiveSemanticChunk.model_name == model_name,
                )
            )
            for index, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
                session.execute(
                    text(
                        """
                        INSERT INTO reader_archive_semantic_chunks
                            (id, task_id, chunk_index, content, content_hash,
                             document_hash, model_name, embedding, created_at, updated_at)
                        VALUES
                            (:id, :task_id, :chunk_index, :content, :content_hash,
                             :document_hash, :model_name, CAST(:embedding AS vector), :created_at,
                             :updated_at)
                        """
                    ),
                    {
                        "id": new_id(),
                        "task_id": task_id,
                        "chunk_index": index,
                        "content": chunk,
                        "content_hash": self._hash_text(chunk),
                        "document_hash": document_hash,
                        "model_name": model_name,
                        "embedding": self._vector_literal(embedding),
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            self._upsert_semantic_index_in_session(
                session,
                task_id,
                model_name,
                embedding_dimensions,
                text_version,
                status="indexed",
                document_hash=document_hash,
                chunk_count=len(chunks),
                last_error=None,
                indexed_at=now,
            )
            session.commit()

    def semantic_health_counts(self, model_name: str, text_version: str) -> tuple[int, int]:
        with self._session() as session:
            indexed = session.exec(
                select(func.count())
                .select_from(ArchiveSemanticIndex)
                .where(
                    ArchiveSemanticIndex.model_name == model_name,
                    ArchiveSemanticIndex.text_version == text_version,
                    ArchiveSemanticIndex.status == "indexed",
                )
            ).one()
            failed = session.exec(
                select(func.count())
                .select_from(ArchiveSemanticIndex)
                .where(
                    ArchiveSemanticIndex.model_name == model_name,
                    ArchiveSemanticIndex.text_version == text_version,
                    ArchiveSemanticIndex.status == "failed",
                )
            ).one()
            return int(indexed), int(failed)

    def latest_semantic_error(self, model_name: str, text_version: str) -> str | None:
        with self._session() as session:
            row = session.exec(
                select(ArchiveSemanticIndex.last_error)
                .where(
                    ArchiveSemanticIndex.model_name == model_name,
                    ArchiveSemanticIndex.text_version == text_version,
                    ArchiveSemanticIndex.last_error.is_not(None),
                )
                .order_by(col(ArchiveSemanticIndex.updated_at).desc())
                .limit(1)
            ).first()
            return str(row) if row else None

    def search_semantic_chunks(
        self,
        query_embedding: list[float],
        model_name: str,
        limit: int,
        min_score: float,
    ) -> dict[str, SemanticSearchMatch]:
        if not query_embedding:
            return {}
        with self._session() as session:
            session.execute(text("SET LOCAL hnsw.ef_search = 100"))
            rows = session.execute(
                text(
                    """
                    SELECT task_id, content, 1 - (embedding <=> CAST(:embedding AS vector)) AS score
                    FROM reader_archive_semantic_chunks
                    WHERE model_name = :model_name
                        AND 1 - (embedding <=> CAST(:embedding AS vector)) >= :min_score
                    ORDER BY embedding <=> CAST(:embedding AS vector)
                    LIMIT :limit
                    """
                ),
                {
                    "embedding": self._vector_literal(query_embedding),
                    "model_name": model_name,
                    "limit": limit,
                    "min_score": min_score,
                },
            ).all()
        matches: dict[str, SemanticSearchMatch] = {}
        for task_id, content, score in rows:
            task_key = str(task_id)
            score_value = float(score)
            existing = matches.get(task_key)
            if existing is not None and existing.score >= score_value:
                continue
            matches[task_key] = SemanticSearchMatch(
                task_id=task_key,
                excerpt=self._excerpt(str(content)),
                score=score_value,
            )
        return matches

    def search_semantic_chunk_text(
        self,
        query: str,
        model_name: str,
        limit: int,
    ) -> dict[str, SemanticSearchMatch]:
        cleaned_query = " ".join(query.split())
        if not cleaned_query:
            return {}
        exact_pattern = f"%{self._escape_like(cleaned_query)}%"
        term_patterns = [f"%{self._escape_like(term)}%" for term in self._search_terms(cleaned_query)]
        with self._session() as session:
            rows = session.execute(
                text(
                    r"""
                    SELECT task_id, content
                    FROM reader_archive_semantic_chunks
                    WHERE model_name = :model_name
                        AND content ILIKE :pattern ESCAPE '\'
                    ORDER BY updated_at DESC
                    LIMIT :limit
                    """
                ),
                {
                    "model_name": model_name,
                    "pattern": exact_pattern,
                    "limit": limit,
                },
            ).all()
            if term_patterns:
                for pattern in term_patterns:
                    rows.extend(
                        session.execute(
                            text(
                                r"""
                                SELECT task_id, content
                                FROM reader_archive_semantic_chunks
                                WHERE model_name = :model_name
                                    AND content ILIKE :pattern ESCAPE '\'
                                ORDER BY updated_at DESC
                                LIMIT :limit
                                """
                            ),
                            {
                                "model_name": model_name,
                                "pattern": pattern,
                                "limit": limit,
                            },
                        ).all()
                    )
        matches: dict[str, SemanticSearchMatch] = {}
        for task_id, content in rows:
            task_key = str(task_id)
            score = self._text_match_score(cleaned_query, str(content))
            if score <= 0:
                continue
            existing = matches.get(task_key)
            if existing is not None and existing.score >= score:
                continue
            matches[task_key] = SemanticSearchMatch(
                task_id=task_key,
                excerpt=self._excerpt(str(content)),
                score=score,
            )
        return matches

    def list_tags(self) -> list[dict[str, str | int]]:
        with self._session() as session:
            tags = sorted(session.exec(select(ArchiveTag)).all(), key=lambda item: item.name.casefold())
            result: list[dict[str, str | int]] = []
            for tag in tags:
                count = session.exec(
                    select(func.count())
                    .select_from(ArchiveTaskTag)
                    .where(ArchiveTaskTag.tag_id == tag.id)
                ).one()
                if int(count) > 0:
                    result.append({"name": tag.name, "task_count": int(count)})
            return result

    def list_queued(self) -> list[str]:
        with self._session() as session:
            tasks = session.exec(
                select(ArchiveTask)
                .where(ArchiveTask.status == ArchiveTaskStatus.QUEUED)
                .order_by(col(ArchiveTask.created_at))
            ).all()
            return [task.id for task in tasks]

    def archive_task_exists_for_normalized_url(self, normalized_url: str) -> bool:
        with self._session() as session:
            return (
                session.exec(
                    select(ArchiveTask.id).where(ArchiveTask.normalized_url == normalized_url)
                ).first()
                is not None
            )

    def delete_archive_task(self, task_id: str) -> bool:
        with self._session() as session:
            task = session.get(ArchiveTask, task_id)
            if task is None:
                return False
            session.exec(delete(ArchiveSemanticChunk).where(ArchiveSemanticChunk.task_id == task_id))
            session.exec(delete(ArchiveSemanticIndex).where(ArchiveSemanticIndex.task_id == task_id))
            session.exec(delete(ArchiveFile).where(ArchiveFile.task_id == task_id))
            session.exec(delete(ArchiveTaskTag).where(ArchiveTaskTag.task_id == task_id))
            session.exec(delete(RssEntry).where(RssEntry.archive_task_id == task_id))
            session.delete(task)
            self._delete_unused_tags(session)
            session.commit()
            return True

    def file_metadata_for_task(self, task_id: str) -> dict[str, dict[str, str]]:
        with self._session() as session:
            files = session.exec(select(ArchiveFile).where(ArchiveFile.task_id == task_id)).all()
            return {
                item.file_name: {
                    "display_name": item.display_name,
                    "source_type": item.source_type,
                }
                for item in files
            }

    def upsert_archive_file(
        self,
        task_id: str,
        file_name: str,
        display_name: str,
        source_type: str,
    ) -> bool:
        with self._session() as session:
            if session.get(ArchiveTask, task_id) is None:
                return False
            item = session.exec(
                select(ArchiveFile).where(
                    ArchiveFile.task_id == task_id,
                    ArchiveFile.file_name == file_name,
                )
            ).first()
            now = utc_now()
            if item is None:
                item = ArchiveFile(
                    task_id=task_id,
                    file_name=file_name,
                    display_name=display_name,
                    source_type=source_type,
                    created_at=now,
                    updated_at=now,
                )
            else:
                item.display_name = display_name
                item.source_type = source_type
                item.updated_at = now
            session.add(item)
            session.commit()
            return True

    def update_archive_file_display_name(
        self,
        task_id: str,
        file_name: str,
        display_name: str,
        fallback_source_type: str,
    ) -> bool:
        return self.upsert_archive_file(task_id, file_name, display_name, fallback_source_type)

    def delete_archive_file_metadata(self, task_id: str, file_name: str) -> None:
        with self._session() as session:
            session.exec(
                delete(ArchiveFile).where(
                    ArchiveFile.task_id == task_id,
                    ArchiveFile.file_name == file_name,
                )
            )
            session.commit()

    def mark_stale_running_tasks_failed(self) -> None:
        with self._session() as session:
            tasks = session.exec(
                select(ArchiveTask).where(ArchiveTask.status == ArchiveTaskStatus.RUNNING)
            ).all()
            for task in tasks:
                task.status = ArchiveTaskStatus.FAILED
                task.error = "Task was interrupted before the service restarted."
                task.finished_at = utc_now()
                task.current_step = None
                task.updated_at = utc_now()
                session.add(task)
            session.commit()

    def mark_running(self, task_id: str, current_step: str = "page") -> None:
        self._update_task(
            task_id,
            status=ArchiveTaskStatus.RUNNING,
            started_at=utc_now(),
            error=None,
            current_step=current_step,
        )

    def update_current_step(self, task_id: str, current_step: str) -> None:
        self._update_task(task_id, current_step=current_step)

    def update_entry_title(self, task_id: str, entry_title: str) -> None:
        self._update_task(task_id, entry_title=entry_title)

    def update_custom_title(self, task_id: str, custom_title: str | None) -> bool:
        return self._update_task(task_id, custom_title=custom_title)

    def replace_task_tags(self, task_id: str, tags: list[str]) -> bool:
        with self._session() as session:
            task = session.get(ArchiveTask, task_id)
            if task is None:
                return False
            session.exec(delete(ArchiveTaskTag).where(ArchiveTaskTag.task_id == task_id))
            now = utc_now()
            for tag_name in tags:
                tag = session.exec(select(ArchiveTag).where(ArchiveTag.name == tag_name)).first()
                if tag is None:
                    tag = ArchiveTag(name=tag_name, created_at=now)
                    session.add(tag)
                    session.flush()
                session.add(ArchiveTaskTag(task_id=task_id, tag_id=tag.id, created_at=now))
            self._delete_unused_tags(session)
            session.commit()
            return True

    def mark_read(self, task_id: str) -> None:
        self._update_task(task_id, is_read=True)

    def requeue_for_rearchive(self, task_id: str) -> bool:
        with self._session() as session:
            task = session.get(ArchiveTask, task_id)
            if task is None:
                return False
            session.exec(delete(ArchiveSemanticChunk).where(ArchiveSemanticChunk.task_id == task_id))
            session.exec(delete(ArchiveSemanticIndex).where(ArchiveSemanticIndex.task_id == task_id))
            session.exec(delete(ArchiveFile).where(ArchiveFile.task_id == task_id))
            task.status = ArchiveTaskStatus.QUEUED
            task.output_file = f"{task_id}.html"
            task.video_file = None
            task.video_error = None
            task.page_error = None
            task.error = None
            task.started_at = None
            task.finished_at = None
            task.current_step = "queued"
            task.updated_at = utc_now()
            session.add(task)
            session.commit()
            return True

    def mark_succeeded(
        self,
        task_id: str,
        video_file: str | None = None,
        video_title: str | None = None,
        video_error: str | None = None,
        page_error: str | None = None,
    ) -> None:
        self._update_task(
            task_id,
            status=ArchiveTaskStatus.SUCCEEDED,
            finished_at=utc_now(),
            error=None,
            current_step=None,
            video_file=video_file,
            video_title=video_title,
            video_error=video_error,
            page_error=page_error,
        )

    def mark_browser_login_required(
        self,
        task_id: str,
        video_error: str,
        page_error: str | None = None,
    ) -> None:
        self._update_task(
            task_id,
            status=ArchiveTaskStatus.BROWSER_LOGIN_REQUIRED,
            error=None,
            current_step="browser_login",
            finished_at=None,
            video_file=None,
            video_error=video_error,
            page_error=page_error,
        )

    def mark_failed(self, task_id: str, error: str) -> None:
        self._update_task(
            task_id,
            status=ArchiveTaskStatus.FAILED,
            finished_at=utc_now(),
            error=error,
            current_step=None,
        )

    def create_rss_feed(self, feed_id: str, url: str, title: str) -> RssFeedRead:
        now = utc_now()
        source = RssSource(
            id=feed_id,
            url=url,
            title=title,
            is_enabled=True,
            created_at=now,
            updated_at=now,
        )
        with self._session() as session:
            try:
                session.add(source)
                session.commit()
                session.refresh(source)
            except IntegrityError as exc:
                session.rollback()
                msg = "RSS feed already exists."
                raise ValueError(msg) from exc
            return self._to_rss_feed(source)

    def list_rss_feeds(self) -> list[RssFeedRead]:
        with self._session() as session:
            feeds = session.exec(select(RssSource).order_by(col(RssSource.created_at).desc())).all()
            return [self._to_rss_feed(feed) for feed in feeds]

    def list_enabled_rss_feeds_due(self, before: str) -> list[RssFeedRead]:
        cutoff = datetime.fromisoformat(before)
        with self._session() as session:
            feeds = session.exec(
                select(RssSource)
                .where(RssSource.is_enabled == True)  # noqa: E712
                .order_by(col(RssSource.last_checked_at), col(RssSource.created_at))
            ).all()
            return [self._to_rss_feed(feed) for feed in feeds if self._rss_feed_is_due(feed, cutoff)]

    def get_rss_feed(self, feed_id: str) -> RssFeedRead | None:
        with self._session() as session:
            feed = session.get(RssSource, feed_id)
            return self._to_rss_feed(feed) if feed else None

    def update_rss_feed(
        self,
        feed_id: str,
        title: str | None = None,
        enabled: bool | None = None,
    ) -> RssFeedRead | None:
        with self._session() as session:
            feed = session.get(RssSource, feed_id)
            if feed is None:
                return None
            if title is not None:
                feed.title = title
            if enabled is not None:
                feed.is_enabled = enabled
            feed.updated_at = utc_now()
            session.add(feed)
            session.commit()
            session.refresh(feed)
            return self._to_rss_feed(feed)

    def delete_rss_feed(self, feed_id: str) -> bool:
        with self._session() as session:
            feed = session.get(RssSource, feed_id)
            if feed is None:
                return False
            session.exec(delete(RssEntry).where(RssEntry.source_id == feed_id))
            session.delete(feed)
            session.commit()
            return True

    def mark_rss_feed_checked(
        self,
        feed_id: str,
        title: str | None,
        error: str | None,
    ) -> None:
        with self._session() as session:
            feed = session.get(RssSource, feed_id)
            if feed is None:
                return
            if title:
                feed.title = title
            feed.last_checked_at = utc_now()
            feed.last_error = error
            feed.updated_at = utc_now()
            session.add(feed)
            session.commit()

    def rss_entry_exists(self, normalized_url: str) -> bool:
        with self._session() as session:
            return (
                session.exec(
                    select(RssEntry.id).where(RssEntry.normalized_url == normalized_url)
                ).first()
                is not None
            )

    def create_rss_entry(
        self,
        entry_id: str,
        feed_id: str,
        url: str,
        normalized_url: str,
        title: str | None,
        published_at: str | None,
        archive_task_id: str,
    ) -> None:
        with self._session() as session:
            session.add(
                RssEntry(
                    id=entry_id,
                    source_id=feed_id,
                    url=url,
                    normalized_url=normalized_url,
                    title=title or "",
                    published_at=published_at,
                    discovered_at=utc_now(),
                    archive_task_id=archive_task_id,
                )
            )
            session.commit()

    def _update_task(self, task_id: str, **values: str | int | bool | datetime | None) -> bool:
        with self._session() as session:
            task = session.get(ArchiveTask, task_id)
            if task is None:
                return False
            for key, value in values.items():
                setattr(task, key, value)
            task.updated_at = utc_now()
            session.add(task)
            session.commit()
            return True

    def _to_task(self, session: Session, task: ArchiveTask) -> ArchiveTaskRead:
        result = None
        if task.status in {
            ArchiveTaskStatus.SUCCEEDED,
            ArchiveTaskStatus.BROWSER_LOGIN_REQUIRED,
        }:
            file_name = None if task.page_error else task.output_file
            result = ArchiveTaskResult(
                file_name=file_name,
                download_url=(
                    f"/api/v1/archive-tasks/{task.id}/result"
                    if file_name
                    else None
                ),
                view_url=f"/api/v1/archive-tasks/{task.id}/files",
                video_file_name=task.video_file,
                video_download_url=(
                    f"/api/v1/archive-tasks/{task.id}/result/video"
                    if task.video_file
                    else None
                ),
                video_error=task.video_error,
                page_error=task.page_error,
            )
        display_title = (
            str(task.custom_title or "").strip()
            or str(task.entry_title or "").strip()
            or str(task.video_title or "").strip()
            or self._title_from_url(task.url)
        )
        return ArchiveTaskRead(
            task_id=task.id,
            url=task.url,
            status=ArchiveTaskStatus(task.status),
            is_read=task.is_read,
            created_at=_clean_datetime(task.created_at) or utc_now(),
            started_at=_clean_datetime(task.started_at),
            finished_at=_clean_datetime(task.finished_at),
            current_step=task.current_step,
            source_type=ArchiveTaskSourceType(task.source_type),
            source_feed_id=task.source_feed_id,
            source_title=task.source_title,
            entry_title=task.entry_title,
            video_title=task.video_title,
            custom_title=task.custom_title,
            display_title=display_title,
            tags=self._tags_for_task(session, task.id),
            result=result,
            error=task.error,
        )

    def _to_rss_feed(self, feed: RssSource) -> RssFeedRead:
        return RssFeedRead(
            feed_id=feed.id,
            url=feed.url,
            title=feed.title,
            enabled=feed.is_enabled,
            created_at=_clean_datetime(feed.created_at) or utc_now(),
            updated_at=_clean_datetime(feed.updated_at) or utc_now(),
            last_checked_at=_clean_datetime(feed.last_checked_at),
            last_error=feed.last_error,
        )

    def _rss_feed_is_due(self, feed: RssSource, cutoff: datetime) -> bool:
        checked_at = _clean_datetime(feed.last_checked_at)
        return checked_at is None or checked_at <= cutoff

    def _tags_for_task(self, session: Session, task_id: str) -> list[str]:
        tag_links = session.exec(
            select(ArchiveTaskTag).where(ArchiveTaskTag.task_id == task_id)
        ).all()
        names: list[str] = []
        for link in tag_links:
            tag = session.get(ArchiveTag, link.tag_id)
            if tag is not None:
                names.append(tag.name)
        return sorted(names, key=str.casefold)

    def _delete_unused_tags(self, session: Session) -> None:
        tags = session.exec(select(ArchiveTag)).all()
        for tag in tags:
            count = session.exec(
                select(func.count())
                .select_from(ArchiveTaskTag)
                .where(ArchiveTaskTag.tag_id == tag.id)
            ).one()
            if int(count) == 0:
                session.delete(tag)

    def _search_text(self, task: ArchiveTaskRead) -> str:
        return " ".join(
            value
            for value in (
                task.custom_title,
                task.entry_title,
                task.video_title,
                task.display_title,
                task.url,
                " ".join(task.tags),
            )
            if value
        ).casefold()

    def _lexical_score(self, task: ArchiveTaskRead, cleaned_query: str) -> float:
        if not cleaned_query:
            return 0.0
        title_values = (
            task.custom_title,
            task.entry_title,
            task.video_title,
            task.display_title,
        )
        if any(cleaned_query in str(value or "").casefold() for value in title_values):
            return 0.45
        tag_text = " ".join(task.tags).casefold()
        if cleaned_query in tag_text:
            return 0.35
        if cleaned_query in task.url.casefold():
            return 0.25
        if cleaned_query in self._search_text(task):
            return 0.15
        return 0.0

    def _upsert_semantic_index(
        self,
        task_id: str,
        model_name: str,
        embedding_dimensions: int,
        text_version: str,
        *,
        status: str,
        document_hash: str | None,
        chunk_count: int,
        last_error: str | None,
        indexed_at: datetime | None,
    ) -> None:
        with self._session() as session:
            self._upsert_semantic_index_in_session(
                session,
                task_id,
                model_name,
                embedding_dimensions,
                text_version,
                status=status,
                document_hash=document_hash,
                chunk_count=chunk_count,
                last_error=last_error,
                indexed_at=indexed_at,
            )
            session.commit()

    def _upsert_semantic_index_in_session(
        self,
        session: Session,
        task_id: str,
        model_name: str,
        embedding_dimensions: int,
        text_version: str,
        *,
        status: str,
        document_hash: str | None,
        chunk_count: int,
        last_error: str | None,
        indexed_at: datetime | None,
    ) -> None:
        now = utc_now()
        item = session.exec(
            select(ArchiveSemanticIndex).where(
                ArchiveSemanticIndex.task_id == task_id,
                ArchiveSemanticIndex.model_name == model_name,
                ArchiveSemanticIndex.text_version == text_version,
            )
        ).first()
        if item is None:
            item = ArchiveSemanticIndex(
                task_id=task_id,
                model_name=model_name,
                embedding_dimensions=embedding_dimensions,
                text_version=text_version,
                document_hash=document_hash,
                status=status,
                chunk_count=chunk_count,
                last_error=last_error,
                indexed_at=indexed_at,
                created_at=now,
                updated_at=now,
            )
        else:
            item.embedding_dimensions = embedding_dimensions
            item.document_hash = document_hash
            item.status = status
            item.chunk_count = chunk_count
            item.last_error = last_error
            item.indexed_at = indexed_at
            item.updated_at = now
        session.add(item)

    def _vector_literal(self, values: list[float]) -> str:
        return "[" + ",".join(f"{float(value):.8g}" for value in values) + "]"

    def _hash_text(self, value: str) -> str:
        import hashlib

        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _escape_like(self, value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")

    def _search_terms(self, value: str) -> list[str]:
        import re

        compact = re.sub(r"\s+", "", value.casefold())
        terms: list[str] = []
        if re.search(r"[\u4e00-\u9fff]", compact):
            terms.extend(compact[index : index + 2] for index in range(0, max(0, len(compact) - 1)))
        terms.extend(part for part in re.split(r"[^a-z0-9]+", value.casefold()) if len(part) >= 3)
        seen: set[str] = set()
        result: list[str] = []
        for term in terms:
            if term in seen:
                continue
            seen.add(term)
            result.append(term)
        return result[:16]

    def _text_match_score(self, query: str, content: str) -> float:
        lowered = content.casefold()
        if query.casefold() in lowered:
            return 0.98
        terms = self._search_terms(query)
        if not terms:
            return 0.0
        hits = sum(1 for term in terms if term in lowered)
        if hits == 0:
            return 0.0
        coverage = hits / len(terms)
        if coverage < 0.45:
            return 0.0
        return min(0.94, 0.7 + coverage * 0.24)

    def _excerpt(self, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) <= 220:
            return cleaned
        return f"{cleaned[:220].rstrip()}..."

    def _title_from_url(self, value: str) -> str:
        parsed = urlparse(value)
        path = parsed.path.rstrip("/")
        return f"{parsed.netloc}{path}" if parsed.netloc else value

    def _session(self) -> Session:
        return Session(self.engine, expire_on_commit=False)
