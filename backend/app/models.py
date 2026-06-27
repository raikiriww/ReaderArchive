from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, HttpUrl
from pydantic import Field as PydanticField
from sqlalchemy import Column, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid4().hex


class User(SQLModel, table=True):
    __tablename__ = "reader_users"

    id: str = Field(default_factory=new_id, primary_key=True)
    username: str = Field(
        sa_column=Column(CITEXT(), unique=True, index=True, nullable=False),
    )
    password_hash: str
    role: str = Field(default="user", index=True)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @staticmethod
    def now() -> datetime:
        return utc_now()


class LoginToken(SQLModel, table=True):
    __tablename__ = "reader_login_tokens"

    id: str = Field(default_factory=new_id, primary_key=True)
    token_hash: str = Field(index=True, unique=True)
    user_id: str = Field(index=True, foreign_key="reader_users.id")
    created_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime


class ArchiveTask(SQLModel, table=True):
    __tablename__ = "reader_archive_tasks"

    id: str = Field(default_factory=new_id, primary_key=True)
    url: str
    normalized_url: str | None = Field(default=None, index=True)
    status: str = Field(index=True)
    output_file: str | None = None
    video_file: str | None = None
    video_error: str | None = None
    page_error: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now, index=True)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    current_step: str | None = None
    is_read: bool = Field(default=False, index=True)
    source_type: str = Field(default="manual", index=True)
    source_feed_id: str | None = Field(default=None, index=True)
    source_title: str | None = None
    entry_title: str | None = None
    video_title: str | None = None
    custom_title: str | None = None
    created_by_id: str | None = Field(default=None, foreign_key="reader_users.id")
    updated_at: datetime = Field(default_factory=utc_now)


class ArchiveFile(SQLModel, table=True):
    __tablename__ = "reader_archive_files"
    __table_args__ = (UniqueConstraint("task_id", "file_name"),)

    id: str = Field(default_factory=new_id, primary_key=True)
    task_id: str = Field(index=True, foreign_key="reader_archive_tasks.id")
    file_name: str = Field(index=True)
    display_name: str
    source_type: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ArchiveSemanticChunk(SQLModel, table=True):
    __tablename__ = "reader_archive_semantic_chunks"
    __table_args__ = (UniqueConstraint("task_id", "model_name", "chunk_index"),)

    id: str = Field(default_factory=new_id, primary_key=True)
    task_id: str = Field(index=True, foreign_key="reader_archive_tasks.id")
    chunk_index: int
    content: str
    content_hash: str = Field(index=True)
    document_hash: str = Field(index=True)
    model_name: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ArchiveSemanticIndex(SQLModel, table=True):
    __tablename__ = "reader_archive_semantic_indexes"
    __table_args__ = (UniqueConstraint("task_id", "model_name", "text_version"),)

    id: str = Field(default_factory=new_id, primary_key=True)
    task_id: str = Field(index=True, foreign_key="reader_archive_tasks.id")
    model_name: str = Field(index=True)
    embedding_dimensions: int
    text_version: str = Field(index=True)
    document_hash: str | None = Field(default=None, index=True)
    status: str = Field(index=True)
    chunk_count: int = Field(default=0)
    last_error: str | None = None
    indexed_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ArchiveTag(SQLModel, table=True):
    __tablename__ = "reader_tags"

    id: str = Field(default_factory=new_id, primary_key=True)
    name: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=utc_now)


class ArchiveTaskTag(SQLModel, table=True):
    __tablename__ = "reader_archive_task_tags"
    __table_args__ = (UniqueConstraint("task_id", "tag_id"),)

    id: str = Field(default_factory=new_id, primary_key=True)
    task_id: str = Field(index=True, foreign_key="reader_archive_tasks.id")
    tag_id: str = Field(index=True, foreign_key="reader_tags.id")
    created_at: datetime = Field(default_factory=utc_now)


class RssSource(SQLModel, table=True):
    __tablename__ = "reader_rss_sources"

    id: str = Field(default_factory=new_id, primary_key=True)
    url: str = Field(index=True, unique=True)
    title: str
    is_enabled: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_checked_at: datetime | None = None
    last_error: str | None = None


class RssEntry(SQLModel, table=True):
    __tablename__ = "reader_rss_entries"

    id: str = Field(default_factory=new_id, primary_key=True)
    source_id: str = Field(index=True, foreign_key="reader_rss_sources.id")
    url: str
    normalized_url: str = Field(index=True, unique=True)
    title: str
    published_at: str | None = None
    discovered_at: datetime = Field(default_factory=utc_now)
    archive_task_id: str = Field(index=True, foreign_key="reader_archive_tasks.id")


class AppSetting(SQLModel, table=True):
    __tablename__ = "reader_app_settings"

    id: str = Field(default_factory=new_id, primary_key=True)
    key: str = Field(index=True, unique=True)
    value: str
    updated_at: datetime = Field(default_factory=utc_now)


class ArchiveTaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    BROWSER_LOGIN_REQUIRED = "browser_login_required"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ArchiveTaskSourceType(StrEnum):
    MANUAL = "manual"
    RSS = "rss"


class ArchiveTaskCreate(BaseModel):
    url: HttpUrl = PydanticField(..., examples=["https://www.v2ex.com/"])


class ArchiveTaskCreated(BaseModel):
    task_id: str
    status: ArchiveTaskStatus
    status_url: str


class ArchiveTaskResult(BaseModel):
    file_name: str | None = None
    download_url: str | None = None
    view_url: str | None = None
    video_file_name: str | None = None
    video_download_url: str | None = None
    video_error: str | None = None
    page_error: str | None = None


class ArchiveTaskSearchMatch(BaseModel):
    excerpt: str
    score: float


class SemanticHealthRead(BaseModel):
    enabled: bool
    available: bool
    status: str
    model_name: str
    embedding_dimensions: int
    text_version: str
    queued_count: int = 0
    indexed_count: int = 0
    failed_count: int = 0
    last_error: str | None = None


class HealthRead(BaseModel):
    status: str
    semantic_search: SemanticHealthRead | None = None


class ArchiveTaskFileRead(BaseModel):
    file_name: str
    display_name: str
    tool: str
    source_type: str
    size_bytes: int
    view_url: str
    download_url: str


class ArchiveTaskFileUpdate(BaseModel):
    display_name: str = PydanticField(..., min_length=1, max_length=240)


class ArchiveTaskRead(BaseModel):
    task_id: str
    url: str
    status: ArchiveTaskStatus
    is_read: bool = False
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    current_step: str | None = None
    source_type: ArchiveTaskSourceType = ArchiveTaskSourceType.MANUAL
    source_feed_id: str | None = None
    source_title: str | None = None
    entry_title: str | None = None
    video_title: str | None = None
    custom_title: str | None = None
    display_title: str
    tags: list[str] = PydanticField(default_factory=list)
    search_match: ArchiveTaskSearchMatch | None = None
    result: ArchiveTaskResult | None = None
    error: str | None = None


class ArchiveTaskListRead(BaseModel):
    items: list[ArchiveTaskRead]
    total: int
    limit: int
    offset: int = 0
    has_more: bool


class ArchiveTaskUpdate(BaseModel):
    custom_title: str | None = PydanticField(default=None, max_length=200)
    tags: list[str] | None = PydanticField(default=None, max_length=20)


class ArchiveTagRead(BaseModel):
    name: str
    task_count: int


class RssFeedCreate(BaseModel):
    url: HttpUrl = PydanticField(..., examples=["https://example.com/feed.xml"])
    title: str | None = PydanticField(default=None, max_length=200)


class RssFeedUpdate(BaseModel):
    title: str | None = PydanticField(default=None, max_length=200)
    enabled: bool | None = None


class RssFeedRead(BaseModel):
    feed_id: str
    url: str
    title: str
    enabled: bool
    created_at: datetime
    updated_at: datetime
    last_checked_at: datetime | None = None
    last_error: str | None = None


class RssFeedRefreshResult(BaseModel):
    feed: RssFeedRead
    discovered_count: int
    created_task_count: int


class AppConfigRead(BaseModel):
    desktop_url: str
    archive_dir: str
    poll_interval_ms: int
    rss_refresh_interval_seconds: int
    semantic_search: SemanticHealthRead | None = None


class AppConfigUpdate(BaseModel):
    poll_interval_ms: int | None = PydanticField(default=None, ge=1000, le=3600000)
    rss_refresh_interval_seconds: int | None = PydanticField(default=None, ge=60, le=86400)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead
    csrf_token: str = ""


class TokenPayload(BaseModel):
    sub: str | None = None
    jti: str | None = None


class LoginRequest(BaseModel):
    username: str = PydanticField(..., min_length=1, max_length=80)
    password: str = PydanticField(..., min_length=1, max_length=240)


class UserRead(BaseModel):
    user_id: str
    username: str
    role: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    username: str = PydanticField(..., min_length=1, max_length=80)
    password: str = PydanticField(..., min_length=8, max_length=240)
    role: str = PydanticField(default="user", pattern="^(admin|user)$")


class UserUpdate(BaseModel):
    enabled: bool | None = None
    role: str | None = PydanticField(default=None, pattern="^(admin|user)$")


class UserPasswordReset(BaseModel):
    password: str = PydanticField(..., min_length=8, max_length=240)


class PasswordChange(BaseModel):
    current_password: str = PydanticField(..., min_length=1, max_length=240)
    new_password: str = PydanticField(..., min_length=8, max_length=240)


class Message(BaseModel):
    message: str


class AuthSessionRead(BaseModel):
    user: UserRead
    csrf_token: str = ""
