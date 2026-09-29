from functools import lru_cache
from pathlib import Path

from pydantic import Field, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="READER_",
        extra="ignore",
    )

    app_name: str = "Reader Archive API"
    api_v1_str: str = "/api/v1"
    secret_key: str = "change-this-reader-secret-key-for-local-development"
    access_token_expire_minutes: int = 60 * 24 * 8
    database_url: str = "postgresql+psycopg://reader:reader@db:5432/reader"
    archive_dir: Path = Path("/app/data/archive")
    browser_profile_dir: Path = Path("/config/.config/reader-archive-profile")
    browser_remote_debugging_url: str | None = None
    single_file_path: str = "/usr/local/bin/single-file"
    yt_dlp_path: str = "/usr/local/bin/yt-dlp"
    chrome_path: str = "/usr/bin/google-chrome"
    use_xvfb: bool = True
    browser_display: str = ":1"
    browser_load_max_time_ms: int = 120000
    browser_capture_max_time_ms: int = 60000
    archive_timeout_seconds: int = 240
    video_download_timeout_seconds: int = 600
    desktop_url: str = "/browser/"
    desktop_proxy_path: str = "/browser/"
    desktop_upstream: str = "http://127.0.0.1:3000"
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "change-me"
    session_days: int = 30
    cookie_secure: bool = False
    session_cookie_name: str = "reader_session"
    poll_interval_ms: int = 4000
    rss_refresh_interval_seconds: int = 1800
    rss_request_timeout_seconds: int = 20
    semantic_search_enabled: bool = True
    semantic_model_name: str = "Qwen/Qwen3-Embedding-0.6B"
    semantic_model_dir: Path = Path("/app/models/fastembed")
    semantic_embedding_dimensions: int = 384
    semantic_text_version: str = "token-body-v2"
    semantic_batch_size: int = 16
    semantic_threads: int = 2
    semantic_query_lock_timeout_seconds: float = 0.15
    semantic_retry_interval_seconds: float = 60
    semantic_search_limit: int = 120
    semantic_min_score: float = 0.34
    semantic_chunk_min_chars: int = 180
    semantic_chunk_max_chars: int = 900
    semantic_chunk_overlap_chars: int = 120
    search_candidate_limit: int = 200
    search_passages_per_article: int = 3
    search_rerank_enabled: bool = True
    search_rerank_model_name: str = "BAAI/bge-reranker-v2-m3"
    search_rerank_revision: str = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
    search_rerank_quantization: str = "auto"
    search_rerank_model_dir: Path = Path("/app/models/reranker")
    search_cpu_threads: int = Field(default=4, ge=1, le=32)
    search_rerank_batch_size: int = 2
    search_rerank_max_length: int = 512
    search_rerank_evidence_articles: int = 5

    @model_validator(mode="after")
    def search_model_defaults(self) -> "Settings":
        explicit = set(self.model_fields_set)
        if self.semantic_model_name == "Qwen/Qwen3-Embedding-0.6B":
            if "semantic_model_dir" not in explicit:
                self.semantic_model_dir = Path("/app/models/qwen")
            if "semantic_text_version" not in explicit:
                self.semantic_text_version = "qwen-sentence-v1"
            if "search_candidate_limit" not in explicit:
                self.search_candidate_limit = 10
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sqlalchemy_database_uri(self) -> str:
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
