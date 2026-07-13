import asyncio
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from time import sleep
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlmodel import Session

from app.archiver import BrowserLoginRequiredError, YtDlpDownloader
from app.core.config import Settings
from app.core.db import get_engine
from app.main import create_app
from app.rss import ParsedFeed, ParsedFeedEntry, rss_entry_key
from app.semantic import SemanticDocumentPreparer

CREATED_DATABASES: list[tuple[str, str]] = []


@pytest.fixture(autouse=True)
def isolate_browser_remote_debugging_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("READER_BROWSER_REMOTE_DEBUGGING_URL", raising=False)


def make_database_url() -> str:
    base_url = make_url(
        os.environ.get("READER_TEST_DATABASE_URL")
        or os.environ.get("READER_DATABASE_URL")
        or "postgresql+psycopg://reader:reader@db:5432/reader"
    )
    database_name = f"reader_test_{uuid4().hex}"
    admin_url = base_url.set(drivername="postgresql", database="postgres")
    with psycopg.connect(admin_url.render_as_string(hide_password=False), autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    CREATED_DATABASES.append((admin_url.render_as_string(hide_password=False), database_name))
    return base_url.set(database=database_name).render_as_string(hide_password=False)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    get_engine.cache_clear()
    for admin_url, database_name in CREATED_DATABASES:
        try:
            with psycopg.connect(admin_url, autocommit=True) as connection:
                connection.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )
        except Exception:
            pass


def wait_for_finished(client: TestClient, task_id: str) -> dict:
    for _ in range(80):
        task_response = client.get(f"/api/v1/archive-tasks/{task_id}")
        assert task_response.status_code == 200
        task = task_response.json()
        if task["status"] in {"succeeded", "failed", "manual_action_required"}:
            return task
        sleep(0.05)
    pytest.fail("Archive task did not finish.")


def list_archive_task_page(client: TestClient, query: str = "") -> dict:
    response = client.get(f"/api/v1/archive-tasks{query}")
    assert response.status_code == 200
    return response.json()


def list_archive_tasks(client: TestClient, query: str = "") -> list[dict]:
    return list_archive_task_page(client, query)["items"]


def login_as_admin(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "change-me"},
    )
    assert response.status_code == 200
    body = response.json()
    client.headers.update({"X-CSRF-Token": body["csrf_token"]})
    return body


@pytest.fixture
def fake_single_file(tmp_path: Path) -> Path:
    script = tmp_path / "single-file"
    script.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys

pathlib.Path(sys.argv[2]).write_text(
    f"<html><head><title>Saved title for {sys.argv[1]}</title></head>"
    f"<body>archived {sys.argv[1]}</body></html>",
    encoding="utf-8",
)
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


@pytest.fixture
def fake_failing_single_file(tmp_path: Path) -> Path:
    script = tmp_path / "single-file-fail"
    script.write_text(
        """#!/usr/bin/env python3
import sys

print("SingleFile failed", file=sys.stderr)
sys.exit(1)
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


@pytest.fixture
def fake_chrome(tmp_path: Path) -> Path:
    script = tmp_path / "chrome"
    script.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys

pathlib.Path(__file__).with_suffix(".args").write_text(
    "\\n".join(sys.argv[1:]),
    encoding="utf-8",
)
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


@pytest.fixture
def fake_yt_dlp(tmp_path: Path) -> Path:
    script = tmp_path / "yt-dlp"
    script.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys

expected_pairs = {
    "--js-runtimes": "node",
    "--format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
    "--merge-output-format": "mp4",
    "--remux-video": "mp4",
}
for option, value in expected_pairs.items():
    if option not in sys.argv or sys.argv[sys.argv.index(option) + 1] != value:
        print(f"missing {option} {value}", file=sys.stderr)
        sys.exit(1)
if "--no-keep-video" not in sys.argv:
    print("missing --no-keep-video", file=sys.stderr)
    sys.exit(1)
if "--cookies-from-browser" not in sys.argv:
    print("missing --cookies-from-browser", file=sys.stderr)
    sys.exit(1)

template = sys.argv[sys.argv.index("--output") + 1]
if "%(playlist_index&.{}|)s" not in template:
    print("missing conditional playlist index", file=sys.stderr)
    sys.exit(1)
output = pathlib.Path(
    template.replace("%(playlist_index&.{}|)s", "").replace("%(ext)s", "mp4")
)
output.write_bytes(b"fake video")
output.with_suffix(".info.json").write_text("{}", encoding="utf-8")
output.with_suffix(".description").write_text("fake description", encoding="utf-8")
output.with_suffix(".webp").write_bytes(b"fake thumbnail")
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


@pytest.fixture
def fake_multi_video_yt_dlp(tmp_path: Path) -> Path:
    script = tmp_path / "yt-dlp-multi-video"
    script.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys

template = sys.argv[sys.argv.index("--output") + 1]
conditional_index = "%(playlist_index&.{}|)s"
if conditional_index not in template:
    print("missing conditional playlist index", file=sys.stderr)
    sys.exit(1)

for index in range(1, 5):
    output = pathlib.Path(
        template.replace(conditional_index, f".{index}").replace("%(ext)s", "mp4")
    )
    output.write_bytes(f"fake video {index}".encode())
    output.with_suffix(".info.json").write_text(
        f'{{"title": "Video {index}"}}',
        encoding="utf-8",
    )
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


@pytest.fixture
def fake_416_yt_dlp(tmp_path: Path) -> Path:
    script = tmp_path / "yt-dlp-416"
    script.write_text(
        """#!/usr/bin/env python3
import sys

print(
    "ERROR: unable to download video data: HTTP Error 416: Requested Range Not Satisfiable",
    file=sys.stderr,
)
sys.exit(1)
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def test_single_video_keeps_original_file_name(
    tmp_path: Path,
    fake_yt_dlp: Path,
) -> None:
    settings = Settings(
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        yt_dlp_path=str(fake_yt_dlp),
        use_xvfb=False,
    )

    files = asyncio.run(YtDlpDownloader(settings).download("https://example.com/video", "task"))

    assert "task.mp4" in files
    assert not any(path.name.startswith("task.NA") for path in settings.archive_dir.iterdir())


def test_multi_video_uses_distinct_playlist_index_file_names(
    tmp_path: Path,
    fake_multi_video_yt_dlp: Path,
) -> None:
    settings = Settings(
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        yt_dlp_path=str(fake_multi_video_yt_dlp),
        use_xvfb=False,
    )

    files = asyncio.run(
        YtDlpDownloader(settings).download("https://weibo.com/1401527553/R81nWpSCx", "task")
    )

    assert [name for name in files if name.endswith(".mp4")] == [
        "task.1.mp4",
        "task.2.mp4",
        "task.3.mp4",
        "task.4.mp4",
    ]


def test_http_416_is_download_failure_not_browser_login(
    tmp_path: Path,
    fake_416_yt_dlp: Path,
) -> None:
    settings = Settings(
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        yt_dlp_path=str(fake_416_yt_dlp),
        use_xvfb=False,
    )

    with pytest.raises(RuntimeError, match="HTTP Error 416") as exc_info:
        asyncio.run(YtDlpDownloader(settings).download("https://example.com/video", "task"))

    assert not isinstance(exc_info.value, BrowserLoginRequiredError)


def test_only_authentication_http_errors_require_browser_login() -> None:
    downloader = YtDlpDownloader(Settings())

    assert downloader._is_browser_login_error("HTTP Error 401: Unauthorized")
    assert downloader._is_browser_login_error("HTTP Error 403: Forbidden")
    assert downloader._is_browser_login_error(
        "ERROR: [BiliBili] HTTP Error 412: Precondition Failed"
    )
    assert not downloader._is_browser_login_error("HTTP Error 412: Precondition Failed")
    assert not downloader._is_browser_login_error("HTTP Error 416: Requested Range Not Satisfiable")


@pytest.fixture
def fake_semantic_single_file(tmp_path: Path) -> Path:
    script = tmp_path / "single-file-semantic"
    script.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys

body = (
    "<article>"
    "<h1>Neural archive</h1>"
    "<p>Neural networks and machine learning systems identify patterns in data.</p>"
    "<p>Deep learning models are useful for semantic search and recommendations.</p>"
    "</article>"
)
pathlib.Path(sys.argv[2]).write_text(
    f"<html><head><title>Neural archive</title></head><body>{body}</body></html>",
    encoding="utf-8",
)
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


class FakeEmbeddingProvider:
    model_name = "fake-local-384"
    available = True
    last_error = None

    def preload(self) -> None:
        return

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector_for(text) for text in texts]

    def _vector_for(self, text: str) -> list[float]:
        lowered = text.casefold()
        values = [0.0] * 384
        if any(token in lowered for token in ("neural", "machine learning", "deep learning", "语义", "学习")):
            values[0] = 1.0
        else:
            values[1] = 1.0
        return values


class CountingEmbeddingProvider(FakeEmbeddingProvider):
    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return super().embed(texts)


class BadDimensionEmbeddingProvider(FakeEmbeddingProvider):
    model_name = "bad-dimension"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _text in texts]


class FailingEmbeddingProvider(FakeEmbeddingProvider):
    model_name = "failing-embedding"
    last_error = "embedding failed"

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding failed")


@pytest.fixture
def fake_titled_yt_dlp(tmp_path: Path) -> Path:
    script = tmp_path / "yt-dlp-titled"
    script.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys

if "--cookies-from-browser" not in sys.argv:
    print("missing --cookies-from-browser", file=sys.stderr)
    sys.exit(1)

template = sys.argv[sys.argv.index("--output") + 1]
output = pathlib.Path(
    template.replace("%(playlist_index&.{}|)s", "").replace("%(ext)s", "mp4")
)
output.write_bytes(b"fake titled video")
output.with_suffix(".info.json").write_text(
    '{"title": "Video title from yt-dlp"}',
    encoding="utf-8",
)
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


@pytest.fixture
def fake_failing_yt_dlp(tmp_path: Path) -> Path:
    script = tmp_path / "yt-dlp-fail"
    script.write_text(
        """#!/usr/bin/env python3
import sys

print("no video formats found", file=sys.stderr)
sys.exit(1)
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


@pytest.fixture
def fake_4xx_then_success_yt_dlp(tmp_path: Path) -> Path:
    script = tmp_path / "yt-dlp-4xx-then-success"
    script.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys

if "--cookies-from-browser" not in sys.argv:
    print("missing --cookies-from-browser", file=sys.stderr)
    sys.exit(1)

marker = pathlib.Path(__file__).with_suffix(".seen")
if not marker.exists():
    marker.write_text("seen", encoding="utf-8")
    print(
        "ERROR: [BiliBili] Unable to download JSON metadata: HTTP Error 412: Precondition Failed",
        file=sys.stderr,
    )
    sys.exit(1)

template = sys.argv[sys.argv.index("--output") + 1]
output = pathlib.Path(
    template.replace("%(playlist_index&.{}|)s", "").replace("%(ext)s", "mp4")
)
output.write_bytes(b"fake video after login")
output.with_suffix(".info.json").write_text("{}", encoding="utf-8")
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def test_archive_task_lifecycle(
    tmp_path: Path,
    fake_single_file: Path,
    fake_yt_dlp: Path,
) -> None:
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        yt_dlp_path=str(fake_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post(
            "/api/v1/archive-tasks",
            json={"url": "https://example.com/"},
        )
        assert response.status_code == 202
        task_id = response.json()["task_id"]

        list_page = list_archive_task_page(client)
        assert list_page["total"] == 1
        assert list_page["items"][0]["task_id"] == task_id

        task = wait_for_finished(client, task_id)

        assert task["is_read"] is False
        assert task["result"]["file_name"] == f"{task_id}.html"
        assert task["result"]["view_url"] == f"/api/v1/archive-tasks/{task_id}/files"


        assert task["result"]["video_file_name"] == f"{task_id}.mp4"
        assert task["result"]["video_download_url"] == (
            f"/api/v1/archive-tasks/{task_id}/result/video"
        )
        assert task["result"]["video_error"] is None
        result_response = client.get(f"/api/v1/archive-tasks/{task_id}/result")
        assert result_response.status_code == 200
        assert "archived https://example.com/" in result_response.text
        assert "attachment" in result_response.headers["content-disposition"]
        assert task["entry_title"] == "Saved title for https://example.com/"

        view_response = client.get(f"/api/v1/archive-tasks/{task_id}/result/view")
        assert view_response.status_code == 200
        assert "archived https://example.com/" in view_response.text
        assert "inline" in view_response.headers["content-disposition"]

        file_list_response = client.get(f"/api/v1/archive-tasks/{task_id}/file-list")
        assert file_list_response.status_code == 200
        file_list = file_list_response.json()
        file_names = {file["file_name"] for file in file_list}
        assert {
            f"{task_id}.html",
            f"{task_id}.mp4",
            f"{task_id}.info.json",
            f"{task_id}.description",
            f"{task_id}.webp",
        }.issubset(file_names)
        html_file = next(file for file in file_list if file["file_name"] == f"{task_id}.html")
        assert html_file["size_bytes"] > 0
        assert html_file["view_url"] == f"/api/v1/archive-tasks/{task_id}/files/{task_id}.html"
        assert html_file["download_url"] == (
            f"/api/v1/archive-tasks/{task_id}/files/{task_id}.html?download=true"
        )
        assert client.get(f"/api/v1/archive-tasks/{task_id}").json()["is_read"] is False

        files_response = client.get(f"/api/v1/archive-tasks/{task_id}/files")
        assert files_response.status_code == 200
        assert f"{task_id}.html" in files_response.text
        assert f"{task_id}.mp4" in files_response.text
        assert f"{task_id}.info.json" in files_response.text
        assert f"{task_id}.description" in files_response.text
        assert f"{task_id}.webp" in files_response.text

        read_task = client.get(f"/api/v1/archive-tasks/{task_id}").json()
        assert read_task["is_read"] is True
        assert list_archive_task_page(client)["items"] == []
        all_tasks = list_archive_tasks(client, "?include_read=true")
        assert len(all_tasks) == 1
        assert all_tasks[0]["task_id"] == task_id

        html_file_response = client.get(f"/api/v1/archive-tasks/{task_id}/files/{task_id}.html")
        assert html_file_response.status_code == 200
        assert "archived https://example.com/" in html_file_response.text
        assert "inline" in html_file_response.headers["content-disposition"]

        metadata_response = client.get(
            f"/api/v1/archive-tasks/{task_id}/files/{task_id}.info.json?download=true",
        )
        assert metadata_response.status_code == 200
        assert metadata_response.text == "{}"
        assert "attachment" in metadata_response.headers["content-disposition"]

        video_response = client.get(f"/api/v1/archive-tasks/{task_id}/result/video")
        assert video_response.status_code == 200
        assert video_response.content == b"fake video"
        assert "attachment" in video_response.headers["content-disposition"]


def test_semantic_search_returns_matching_excerpt(
    tmp_path: Path,
    fake_semantic_single_file: Path,
    fake_failing_yt_dlp: Path,
) -> None:
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_semantic_single_file),
        yt_dlp_path=str(fake_failing_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
        semantic_search_enabled=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post(
            "/api/v1/archive-tasks",
            json={"url": "https://example.com/neural"},
        )
        assert response.status_code == 202
        task_id = response.json()["task_id"]
        task = wait_for_finished(client, task_id)
        assert task["status"] == "succeeded"

        service = client.app.state.archive_task_service
        service.archiver.settings.semantic_search_enabled = True
        service.embedding_provider = FakeEmbeddingProvider()
        service.semantic_preparer = SemanticDocumentPreparer(
            min_chars=20,
            max_chars=900,
            overlap_chars=80,
        )
        service._index_task_semantics(task_id)

        search_page = list_archive_task_page(client, "?include_read=true&q=语义学习")
        assert search_page["total"] == 1
        results = search_page["items"]
        assert [item["task_id"] for item in results] == [task_id]
        assert "machine learning" in results[0]["search_match"]["excerpt"].casefold()

        service.archiver.settings.semantic_search_enabled = False
        exact_page = list_archive_task_page(client, "?include_read=true&q=patterns")
        assert exact_page["total"] == 1
        exact_results = exact_page["items"]
        assert [item["task_id"] for item in exact_results] == [task_id]
        assert "patterns" in exact_results[0]["search_match"]["excerpt"].casefold()


def test_semantic_search_falls_back_to_plain_search(
    tmp_path: Path,
    fake_single_file: Path,
    fake_failing_yt_dlp: Path,
) -> None:
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        yt_dlp_path=str(fake_failing_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
        semantic_search_enabled=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post(
            "/api/v1/archive-tasks",
            json={"url": "https://example.com/plain"},
        )
        assert response.status_code == 202
        task_id = response.json()["task_id"]
        wait_for_finished(client, task_id)

        body = list_archive_task_page(client, "?include_read=true&q=saved%20title")
        assert body["total"] == 1
        body = body["items"]
        assert [task["task_id"] for task in body] == [task_id]
        assert body[0]["search_match"] is None


def test_semantic_index_status_handles_dimension_mismatch(
    tmp_path: Path,
    fake_semantic_single_file: Path,
    fake_failing_yt_dlp: Path,
) -> None:
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_semantic_single_file),
        yt_dlp_path=str(fake_failing_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
        semantic_search_enabled=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post("/api/v1/archive-tasks", json={"url": "https://example.com/bad-dim"})
        assert response.status_code == 202
        task_id = response.json()["task_id"]
        assert wait_for_finished(client, task_id)["status"] == "succeeded"

        service = client.app.state.archive_task_service
        service.archiver.settings.semantic_search_enabled = True
        service.embedding_provider = BadDimensionEmbeddingProvider()
        service.semantic_preparer = SemanticDocumentPreparer(min_chars=20, max_chars=900, overlap_chars=80)

        with pytest.raises(ValueError, match="Embedding dimensions mismatch"):
            service._index_task_semantics(task_id)

        status_response = client.get("/api/v1/app-config")
        assert status_response.status_code == 200
        semantic_status = status_response.json()["semantic_search"]
        assert semantic_status["status"] == "degraded"
        assert semantic_status["failed_count"] == 1
        assert "Embedding dimensions mismatch" in semantic_status["last_error"]


def test_semantic_index_status_handles_embedding_failure(
    tmp_path: Path,
    fake_semantic_single_file: Path,
    fake_failing_yt_dlp: Path,
) -> None:
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_semantic_single_file),
        yt_dlp_path=str(fake_failing_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
        semantic_search_enabled=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post("/api/v1/archive-tasks", json={"url": "https://example.com/failing"})
        assert response.status_code == 202
        task_id = response.json()["task_id"]
        assert wait_for_finished(client, task_id)["status"] == "succeeded"

        service = client.app.state.archive_task_service
        service.archiver.settings.semantic_search_enabled = True
        service.embedding_provider = FailingEmbeddingProvider()
        service.semantic_preparer = SemanticDocumentPreparer(min_chars=20, max_chars=900, overlap_chars=80)

        with pytest.raises(RuntimeError, match="embedding failed"):
            service._index_task_semantics(task_id)

        health_response = client.get("/api/v1/health")
        assert health_response.status_code == 200
        semantic_status = health_response.json()["semantic_search"]
        assert semantic_status["status"] == "degraded"
        assert semantic_status["failed_count"] == 1
        assert semantic_status["last_error"] == "embedding failed"


def test_semantic_index_skips_unchanged_and_reindexes_changed_content(
    tmp_path: Path,
    fake_semantic_single_file: Path,
    fake_failing_yt_dlp: Path,
) -> None:
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_semantic_single_file),
        yt_dlp_path=str(fake_failing_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
        semantic_search_enabled=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post("/api/v1/archive-tasks", json={"url": "https://example.com/reindex"})
        assert response.status_code == 202
        task_id = response.json()["task_id"]
        assert wait_for_finished(client, task_id)["status"] == "succeeded"

        service = client.app.state.archive_task_service
        provider = CountingEmbeddingProvider()
        service.archiver.settings.semantic_search_enabled = True
        service.embedding_provider = provider
        service.semantic_preparer = SemanticDocumentPreparer(min_chars=20, max_chars=900, overlap_chars=80)

        service._index_task_semantics(task_id)
        assert provider.calls == 1
        service._index_task_semantics(task_id)
        assert provider.calls == 1

        archive_path = settings.archive_dir / f"{task_id}.html"
        archive_path.write_text(
            "<html><head><title>Neural archive</title></head>"
            "<body><article><p>New semantic learning content changed.</p></article></body></html>",
            encoding="utf-8",
        )
        service._index_task_semantics(task_id)
        assert provider.calls == 2
        assert service.semantic_health().indexed_count == 1


def test_semantic_index_is_deleted_with_archive_task(
    tmp_path: Path,
    fake_semantic_single_file: Path,
    fake_failing_yt_dlp: Path,
) -> None:
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_semantic_single_file),
        yt_dlp_path=str(fake_failing_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
        semantic_search_enabled=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post("/api/v1/archive-tasks", json={"url": "https://example.com/delete-semantic"})
        assert response.status_code == 202
        task_id = response.json()["task_id"]
        assert wait_for_finished(client, task_id)["status"] == "succeeded"

        service = client.app.state.archive_task_service
        service.archiver.settings.semantic_search_enabled = True
        service.embedding_provider = FakeEmbeddingProvider()
        service.semantic_preparer = SemanticDocumentPreparer(min_chars=20, max_chars=900, overlap_chars=80)
        service._index_task_semantics(task_id)

        delete_response = client.delete(f"/api/v1/archive-tasks/{task_id}")
        assert delete_response.status_code == 204

        with Session(get_engine(settings.database_url)) as session:
            chunk_count = session.execute(
                text("SELECT count(*) FROM reader_archive_semantic_chunks WHERE task_id = :task_id"),
                {"task_id": task_id},
            ).scalar_one()
            index_count = session.execute(
                text("SELECT count(*) FROM reader_archive_semantic_indexes WHERE task_id = :task_id"),
                {"task_id": task_id},
            ).scalar_one()
        assert chunk_count == 0
        assert index_count == 0


def test_versioned_api_prefix(
    tmp_path: Path,
    fake_single_file: Path,
    fake_yt_dlp: Path,
) -> None:
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        yt_dlp_path=str(fake_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "change-me"},
        )
        assert response.status_code == 200
        client.headers.update({"X-CSRF-Token": response.json()["csrf_token"]})

        create_response = client.post(
            "/api/v1/archive-tasks",
            json={"url": "https://example.com/"},
        )
        assert create_response.status_code == 202
        assert create_response.json()["status_url"].startswith("/api/v1/archive-tasks/")

        list_response = client.get("/api/v1/archive-tasks")
        assert list_response.status_code == 200


def test_removed_business_api_paths_are_not_registered(
    tmp_path: Path,
    fake_single_file: Path,
    fake_yt_dlp: Path,
) -> None:
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        yt_dlp_path=str(fake_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        removed_path_response = client.get("/health")
        versioned_response = client.get("/api/v1/health")

    assert removed_path_response.status_code == 404
    assert versioned_response.status_code == 200
    assert "Deprecation" not in versioned_response.headers
    assert "X-Reader-API-Status" not in versioned_response.headers


def test_archive_task_can_be_marked_read_without_opening_files(
    tmp_path: Path,
    fake_single_file: Path,
    fake_failing_yt_dlp: Path,
) -> None:
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        yt_dlp_path=str(fake_failing_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post(
            "/api/v1/archive-tasks",
            json={"url": "https://example.com/"},
        )
        assert response.status_code == 202
        task_id = response.json()["task_id"]
        task = wait_for_finished(client, task_id)
        assert task["is_read"] is False

        mark_response = client.post(f"/api/v1/archive-tasks/{task_id}/mark-read")
        assert mark_response.status_code == 200
        assert mark_response.json()["is_read"] is True
        assert list_archive_tasks(client) == []
        assert len(list_archive_tasks(client, "?include_read=true")) == 1


def test_archive_task_custom_title_and_tags(
    tmp_path: Path,
    fake_single_file: Path,
    fake_failing_yt_dlp: Path,
) -> None:
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        yt_dlp_path=str(fake_failing_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        first_response = client.post(
            "/api/v1/archive-tasks",
            json={"url": "https://example.com/first"},
        )
        second_response = client.post(
            "/api/v1/archive-tasks",
            json={"url": "https://example.com/second"},
        )
        first_id = first_response.json()["task_id"]
        second_id = second_response.json()["task_id"]
        first_task = wait_for_finished(client, first_id)
        wait_for_finished(client, second_id)

        assert first_task["custom_title"] is None
        assert first_task["display_title"] == "Saved title for https://example.com/first"
        assert first_task["tags"] == []

        rename_response = client.patch(
            f"/api/v1/archive-tasks/{first_id}",
            json={
                "custom_title": "  Research copy  ",
                "tags": ["read later", "Research", "research", "  ", "Saved"],
            },
        )
        assert rename_response.status_code == 200
        renamed = rename_response.json()
        assert renamed["custom_title"] == "Research copy"
        assert renamed["display_title"] == "Research copy"
        assert renamed["tags"] == ["read later", "Research", "Saved"]

        custom_title_page = list_archive_task_page(client, "?include_read=true&title=research%20copy")
        assert custom_title_page["total"] == 1
        custom_title_tasks = custom_title_page["items"]
        assert [task["task_id"] for task in custom_title_tasks] == [first_id]

        tagged_title_page = list_archive_task_page(client, "?include_read=true&tags=saved&title=research")
        assert tagged_title_page["total"] == 1
        tagged_title_tasks = tagged_title_page["items"]
        assert [task["task_id"] for task in tagged_title_tasks] == [first_id]

        clear_title_response = client.patch(
            f"/api/v1/archive-tasks/{first_id}",
            json={"custom_title": ""},
        )
        assert clear_title_response.status_code == 200
        cleared = clear_title_response.json()
        assert cleared["custom_title"] is None
        assert cleared["display_title"] == "Saved title for https://example.com/first"

        second_tag_response = client.patch(
            f"/api/v1/archive-tasks/{second_id}",
            json={"tags": ["read later", "Video"]},
        )
        assert second_tag_response.status_code == 200
        assert second_tag_response.json()["tags"] == ["read later", "Video"]

        tags = client.get("/api/v1/archive-tags").json()
        assert tags == [
            {"name": "read later", "task_count": 2},
            {"name": "Research", "task_count": 1},
            {"name": "Saved", "task_count": 1},
            {"name": "Video", "task_count": 1},
        ]

        video_tasks = list_archive_tasks(client, "?include_read=true&tag=video")
        assert [task["task_id"] for task in video_tasks] == [second_id]

        multi_tag_page = list_archive_task_page(client, "?include_read=true&tags=video&tags=saved")
        assert multi_tag_page["total"] == 2
        multi_tag_tasks = multi_tag_page["items"]
        assert [task["task_id"] for task in multi_tag_tasks] == [second_id, first_id]

        archived_title_tasks = list_archive_tasks(client, "?include_read=true&title=SECOND")
        assert [task["task_id"] for task in archived_title_tasks] == [second_id]

        missing_title_tasks = list_archive_tasks(client, "?include_read=true&title=not-found")
        assert missing_title_tasks == []

        remove_response = client.patch(
            f"/api/v1/archive-tasks/{second_id}",
            json={"tags": ["read later"]},
        )
        assert remove_response.status_code == 200
        assert remove_response.json()["tags"] == ["read later"]
        assert "Video" not in {
            tag["name"]
            for tag in client.get("/api/v1/archive-tags").json()
        }

        delete_response = client.delete(f"/api/v1/archive-tasks/{first_id}")
        assert delete_response.status_code == 204
        assert client.get("/api/v1/archive-tags").json() == [
            {"name": "read later", "task_count": 1},
        ]


def test_archive_task_delete_removes_record_and_files(
    tmp_path: Path,
    fake_single_file: Path,
    fake_yt_dlp: Path,
) -> None:
    archive_dir = tmp_path / "archive"
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=archive_dir,
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        yt_dlp_path=str(fake_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post(
            "/api/v1/archive-tasks",
            json={"url": "https://example.com/"},
        )
        assert response.status_code == 202
        task_id = response.json()["task_id"]
        wait_for_finished(client, task_id)
        assert sorted(path.name for path in archive_dir.glob(f"{task_id}.*")) == [
            f"{task_id}.description",
            f"{task_id}.html",
            f"{task_id}.info.json",
            f"{task_id}.mp4",
            f"{task_id}.webp",
        ]

        delete_response = client.delete(f"/api/v1/archive-tasks/{task_id}")
        assert delete_response.status_code == 204
        assert client.get(f"/api/v1/archive-tasks/{task_id}").status_code == 404
        assert client.get(f"/api/v1/archive-tasks/{task_id}/result").status_code == 404
        assert list_archive_tasks(client) == []
        assert list(archive_dir.glob(f"{task_id}.*")) == []


def test_archive_task_can_be_rearchived_in_place(
    tmp_path: Path,
    fake_single_file: Path,
    fake_failing_yt_dlp: Path,
) -> None:
    archive_dir = tmp_path / "archive"
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=archive_dir,
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        yt_dlp_path=str(fake_failing_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post(
            "/api/v1/archive-tasks",
            json={"url": "https://example.com/rearchive"},
        )
        assert response.status_code == 202
        task_id = response.json()["task_id"]
        wait_for_finished(client, task_id)

        rename_response = client.patch(
            f"/api/v1/archive-tasks/{task_id}",
            json={"custom_title": "Saved copy", "tags": ["refresh"]},
        )
        assert rename_response.status_code == 200
        mark_read_response = client.post(f"/api/v1/archive-tasks/{task_id}/mark-read")
        assert mark_read_response.status_code == 200
        upload_response = client.post(
            f"/api/v1/archive-tasks/{task_id}/files?file_name=note.txt",
            content=b"old note",
            headers={"content-type": "text/plain"},
        )
        assert upload_response.status_code == 201
        uploaded_file = upload_response.json()["file_name"]
        assert (archive_dir / uploaded_file).exists()

        (archive_dir / f"{task_id}.html").write_text("old archive", encoding="utf-8")
        rearchive_response = client.post(f"/api/v1/archive-tasks/{task_id}/rearchive")
        assert rearchive_response.status_code == 202
        requeued = rearchive_response.json()
        assert requeued["task_id"] == task_id
        assert requeued["custom_title"] == "Saved copy"
        assert requeued["display_title"] == "Saved copy"
        assert requeued["tags"] == ["refresh"]
        assert requeued["is_read"] is True
        assert requeued["result"] is None
        assert not (archive_dir / uploaded_file).exists()

        task = wait_for_finished(client, task_id)
        assert task["task_id"] == task_id
        assert task["custom_title"] == "Saved copy"
        assert task["display_title"] == "Saved copy"
        assert task["tags"] == ["refresh"]
        assert task["is_read"] is True
        assert task["result"]["file_name"] == f"{task_id}.html"
        assert "archived https://example.com/rearchive" in (
            archive_dir / f"{task_id}.html"
        ).read_text(encoding="utf-8")
        file_list = client.get(f"/api/v1/archive-tasks/{task_id}/file-list").json()
        assert uploaded_file not in {file["file_name"] for file in file_list}
        all_tasks = list_archive_tasks(client, "?include_read=true")
        assert [task["task_id"] for task in all_tasks] == [task_id]


def test_archive_task_rearchive_rejects_running_task(
    tmp_path: Path,
    fake_failing_yt_dlp: Path,
) -> None:
    slow_single_file = tmp_path / "single-file-slow"
    slow_single_file.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys
import time

time.sleep(1)
pathlib.Path(sys.argv[2]).write_text("<html>slow</html>", encoding="utf-8")
""",
        encoding="utf-8",
    )
    slow_single_file.chmod(0o755)
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(slow_single_file),
        yt_dlp_path=str(fake_failing_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post(
            "/api/v1/archive-tasks",
            json={"url": "https://example.com/running"},
        )
        assert response.status_code == 202
        task_id = response.json()["task_id"]

        rearchive_response = client.post(f"/api/v1/archive-tasks/{task_id}/rearchive")
        assert rearchive_response.status_code == 409
        assert "still running" in rearchive_response.json()["detail"]

        wait_for_finished(client, task_id)


def test_archive_task_files_can_be_uploaded_renamed_and_deleted(
    tmp_path: Path,
    fake_single_file: Path,
    fake_yt_dlp: Path,
) -> None:
    archive_dir = tmp_path / "archive"
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=archive_dir,
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        yt_dlp_path=str(fake_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post(
            "/api/v1/archive-tasks",
            json={"url": "https://example.com/"},
        )
        assert response.status_code == 202
        task_id = response.json()["task_id"]
        wait_for_finished(client, task_id)

        upload_response = client.post(
            f"/api/v1/archive-tasks/{task_id}/files?file_name=translated.html",
            content=b"<html>translated</html>",
            headers={"content-type": "text/html"},
        )
        assert upload_response.status_code == 201
        uploaded = upload_response.json()
        assert uploaded["display_name"] == "translated.html"
        assert uploaded["tool"] == "upload"
        assert uploaded["source_type"] == "upload"
        assert uploaded["size_bytes"] == len(b"<html>translated</html>")
        assert uploaded["file_name"].startswith(f"{task_id}.upload-")

        duplicate_upload_response = client.post(
            f"/api/v1/archive-tasks/{task_id}/files?file_name=translated.html",
            content=b"duplicate",
            headers={"content-type": "text/html"},
        )
        assert duplicate_upload_response.status_code == 409
        assert "同名文件" in duplicate_upload_response.json()["detail"]

        file_list = client.get(f"/api/v1/archive-tasks/{task_id}/file-list").json()
        assert uploaded["file_name"] in {file["file_name"] for file in file_list}

        rename_response = client.patch(
            f"/api/v1/archive-tasks/{task_id}/files/{uploaded['file_name']}",
            json={"display_name": "translated-page.html"},
        )
        assert rename_response.status_code == 200
        assert rename_response.json()["display_name"] == "translated-page.html"

        html_display_name = next(
            file["display_name"]
            for file in client.get(f"/api/v1/archive-tasks/{task_id}/file-list").json()
            if file["file_name"] == f"{task_id}.html"
        )
        rename_duplicate_response = client.patch(
            f"/api/v1/archive-tasks/{task_id}/files/{uploaded['file_name']}",
            json={"display_name": html_display_name},
        )
        assert rename_duplicate_response.status_code == 409
        assert "同名文件" in rename_duplicate_response.json()["detail"]

        view_response = client.get(
            f"/api/v1/archive-tasks/{task_id}/files/{uploaded['file_name']}",
        )
        assert view_response.status_code == 200
        assert view_response.text == "<html>translated</html>"
        assert "inline" in view_response.headers["content-disposition"]

        download_response = client.get(
            f"/api/v1/archive-tasks/{task_id}/files/{uploaded['file_name']}?download=true",
        )
        assert download_response.status_code == 200
        assert "translated-page.html" in download_response.headers["content-disposition"]
        assert "attachment" in download_response.headers["content-disposition"]

        delete_uploaded_response = client.delete(
            f"/api/v1/archive-tasks/{task_id}/files/{uploaded['file_name']}",
        )
        assert delete_uploaded_response.status_code == 204
        assert not (archive_dir / uploaded["file_name"]).exists()
        assert uploaded["file_name"] not in {
            file["file_name"]
            for file in client.get(f"/api/v1/archive-tasks/{task_id}/file-list").json()
        }

        delete_page_response = client.delete(
            f"/api/v1/archive-tasks/{task_id}/files/{task_id}.html",
        )
        assert delete_page_response.status_code == 204
        updated_task = client.get(f"/api/v1/archive-tasks/{task_id}").json()
        assert updated_task["status"] == "succeeded"
        assert updated_task["result"]["file_name"] is None
        assert updated_task["result"]["download_url"] is None
        assert client.get(f"/api/v1/archive-tasks/{task_id}/result").status_code == 404


def test_archive_task_upload_works_before_task_finishes(
    tmp_path: Path,
    fake_failing_single_file: Path,
    fake_failing_yt_dlp: Path,
) -> None:
    archive_dir = tmp_path / "archive"
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=archive_dir,
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_failing_single_file),
        yt_dlp_path=str(fake_failing_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post(
            "/api/v1/archive-tasks",
            json={"url": "https://example.com/"},
        )
        assert response.status_code == 202
        task_id = response.json()["task_id"]

        upload_response = client.post(
            f"/api/v1/archive-tasks/{task_id}/files?file_name=manual.pdf",
            content=b"manual file",
            headers={"content-type": "application/pdf"},
        )
        assert upload_response.status_code == 201
        uploaded = upload_response.json()
        assert (archive_dir / uploaded["file_name"]).exists()

        task = wait_for_finished(client, task_id)
        assert task["status"] == "failed"
        assert task["result"] is None
        assert client.get(f"/api/v1/archive-tasks/{task_id}/file-list").json()[0][
            "display_name"
        ] == "manual.pdf"


def test_video_failure_keeps_page_archive_succeeded(
    tmp_path: Path,
    fake_single_file: Path,
    fake_failing_yt_dlp: Path,
) -> None:
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        yt_dlp_path=str(fake_failing_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post(
            "/api/v1/archive-tasks",
            json={"url": "https://example.com/"},
        )
        assert response.status_code == 202
        task = wait_for_finished(client, response.json()["task_id"])

        assert task["status"] == "succeeded"
        assert task["result"]["file_name"].endswith(".html")
        assert task["result"]["video_file_name"] is None
        assert task["result"]["video_download_url"] is None
        assert "no video formats found" in task["result"]["video_error"]


def test_video_4xx_waits_for_browser_login_and_can_continue(
    tmp_path: Path,
    fake_single_file: Path,
    fake_4xx_then_success_yt_dlp: Path,
) -> None:
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        yt_dlp_path=str(fake_4xx_then_success_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post(
            "/api/v1/archive-tasks",
            json={"url": "https://www.bilibili.com/video/BV1fjd1BeESp"},
        )
        assert response.status_code == 202
        task_id = response.json()["task_id"]
        task = wait_for_finished(client, task_id)

        assert task["status"] == "manual_action_required"
        assert len(task["manual_actions"]) == 1
        video_action = task["manual_actions"][0]
        assert video_action["code"] == "video_browser_login"
        assert video_action["kind"] == "login"
        assert video_action["target"] == "video"
        assert video_action["message"].startswith("浏览器登录需手动确认")
        assert video_action["resume"] == "continue_video"
        assert video_action["rule_id"] == "video.browser_login"
        assert task["result"]["file_name"] == f"{task_id}.html"
        assert task["result"]["video_file_name"] is None
        assert task["result"]["video_download_url"] is None
        assert task["result"]["video_error"] is None

        continue_response = client.post(f"/api/v1/archive-tasks/{task_id}/continue-video")
        assert continue_response.status_code == 202
        task = wait_for_finished(client, task_id)

        assert task["status"] == "succeeded"
        assert task["result"]["file_name"] == f"{task_id}.html"
        assert task["result"]["video_file_name"] == f"{task_id}.mp4"
        assert task["result"]["video_error"] is None
        video_response = client.get(f"/api/v1/archive-tasks/{task_id}/result/video")
        assert video_response.status_code == 200
        assert video_response.content == b"fake video after login"


def test_wechat_verification_requires_manual_action_and_can_rearchive(
    tmp_path: Path,
    fake_failing_yt_dlp: Path,
) -> None:
    fake_single_file = tmp_path / "single-file-wechat"
    fake_single_file.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys

output = pathlib.Path(sys.argv[2])
marker = output.parent / "wechat-verified"
if marker.exists():
    output.write_text(
        "<html><head><title>正常微信文章</title></head>"
        "<body><article id='js_article'>正文内容</article></body></html>",
        encoding="utf-8",
    )
else:
    output.write_text(
        "<html><head><title>Weixin Official Accounts Platform</title></head><body>"
        "<h2>环境异常</h2><p>当前环境异常，完成验证后即可继续访问。</p>"
        "<a id='js_verify'>去验证</a><iframe id='tcaptcha_iframe_dy'></iframe>"
        "</body></html>",
        encoding="utf-8",
    )
    marker.write_text("verified", encoding="utf-8")
""",
        encoding="utf-8",
    )
    fake_single_file.chmod(0o755)
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        yt_dlp_path=str(fake_failing_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
        semantic_search_enabled=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post(
            "/api/v1/archive-tasks",
            json={"url": "https://mp.weixin.qq.com/s/example"},
        )
        task_id = response.json()["task_id"]
        task = wait_for_finished(client, task_id)

        assert task["status"] == "manual_action_required"
        assert task["entry_title"] is None
        assert task["finished_at"] is None
        assert task["result"]["file_name"] is None
        assert task["result"]["view_url"] is None
        assert task["manual_actions"] == [
            {
                "code": "wechat_article_verification",
                "kind": "verification",
                "target": "page",
                "message": "微信要求完成访问验证，正文尚未保存。",
                "resume": "retry_page",
                "rule_id": "wechat.mp_article.verification",
                "browser_tab_state": "not_opened",
            }
        ]
        assert not (settings.archive_dir / f"{task_id}.html").exists()
        assert client.get(f"/api/v1/archive-tasks/{task_id}/file-list").json() == []
        assert client.post(f"/api/v1/archive-tasks/{task_id}/continue-video").status_code == 409

        resume_response = client.post(
            f"/api/v1/archive-tasks/{task_id}/resume-manual-action",
            json={"code": "wechat_article_verification"},
        )
        assert resume_response.status_code == 202
        assert resume_response.json()["result"]["file_name"] is None
        assert resume_response.json()["result"]["video_error"] is not None
        task = wait_for_finished(client, task_id)

        assert task["status"] == "succeeded"
        assert task["manual_actions"] == []
        assert task["entry_title"] == "正常微信文章"
        assert task["result"]["file_name"] == f"{task_id}.html"


def test_page_and_video_manual_actions_are_preserved_together(
    tmp_path: Path,
    fake_4xx_then_success_yt_dlp: Path,
) -> None:
    fake_single_file = tmp_path / "single-file-wechat-verification"
    fake_single_file.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys

pathlib.Path(sys.argv[2]).write_text(
    "<html><body><h2>环境异常</h2>"
    "<p>完成验证后即可继续访问。</p><a id='js_verify'>去验证</a></body></html>",
    encoding="utf-8",
)
""",
        encoding="utf-8",
    )
    fake_single_file.chmod(0o755)
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        yt_dlp_path=str(fake_4xx_then_success_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
        semantic_search_enabled=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post(
            "/api/v1/archive-tasks",
            json={"url": "https://mp.weixin.qq.com/s/example"},
        )
        task_id = response.json()["task_id"]
        task = wait_for_finished(client, task_id)

        assert task["status"] == "manual_action_required"
        assert {action["code"] for action in task["manual_actions"]} == {
            "wechat_article_verification",
            "video_browser_login",
        }

        continue_response = client.post(f"/api/v1/archive-tasks/{task_id}/continue-video")
        assert continue_response.status_code == 202
        task = wait_for_finished(client, task_id)

        assert task["status"] == "manual_action_required"
        assert [action["code"] for action in task["manual_actions"]] == [
            "wechat_article_verification"
        ]
        assert task["result"]["video_file_name"] == f"{task_id}.mp4"


def test_open_task_in_browser_passes_task_url_to_chrome(
    tmp_path: Path,
    fake_single_file: Path,
    fake_failing_yt_dlp: Path,
    fake_chrome: Path,
) -> None:
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        yt_dlp_path=str(fake_failing_yt_dlp),
        chrome_path=str(fake_chrome),
        use_xvfb=False,
    )
    settings.browser_profile_dir.mkdir(parents=True)
    stale_lock = settings.browser_profile_dir / "SingletonLock"
    stale_cookie = settings.browser_profile_dir / "SingletonCookie"
    stale_lock.symlink_to("stale-host-99999999")
    stale_cookie.symlink_to("stale-cookie")
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post(
            "/api/v1/archive-tasks",
            json={"url": "https://www.bilibili.com/video/BV1fjd1BeESp"},
        )
        assert response.status_code == 202
        task_id = response.json()["task_id"]

        open_response = client.post(f"/api/v1/archive-tasks/{task_id}/open-browser")
        assert open_response.status_code == 202
        assert open_response.json()["desktop_url"] == settings.desktop_url

        args = fake_chrome.with_suffix(".args").read_text(encoding="utf-8").splitlines()
        assert "--new-tab" in args
        assert "https://www.bilibili.com/video/BV1fjd1BeESp" in args
        assert f"--user-data-dir={settings.browser_profile_dir}" in args
        assert not stale_lock.exists()
        assert not stale_cookie.exists()


def test_page_archive_failure_keeps_video_download_succeeded(
    tmp_path: Path,
    fake_failing_single_file: Path,
    fake_titled_yt_dlp: Path,
) -> None:
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_failing_single_file),
        yt_dlp_path=str(fake_titled_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post(
            "/api/v1/archive-tasks",
            json={"url": "https://example.com/"},
        )
        assert response.status_code == 202
        task = wait_for_finished(client, response.json()["task_id"])

        assert task["status"] == "succeeded"
        assert task["result"]["file_name"] is None
        assert task["result"]["download_url"] is None
        assert task["result"]["view_url"] == f"/api/v1/archive-tasks/{task['task_id']}/files"
        assert task["result"]["video_file_name"] == f"{task['task_id']}.mp4"
        assert "SingleFile failed" in task["result"]["page_error"]
        assert task["entry_title"] is None
        assert task["display_title"] == "Video title from yt-dlp"


def test_page_title_takes_priority_over_video_title(
    tmp_path: Path,
    fake_single_file: Path,
    fake_titled_yt_dlp: Path,
) -> None:
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        yt_dlp_path=str(fake_titled_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post(
            "/api/v1/archive-tasks",
            json={"url": "https://example.com/"},
        )
        assert response.status_code == 202
        task = wait_for_finished(client, response.json()["task_id"])

        assert task["status"] == "succeeded"
        assert task["entry_title"] == "Saved title for https://example.com/"
        assert task["display_title"] == "Saved title for https://example.com/"

        rename_response = client.patch(
            f"/api/v1/archive-tasks/{task['task_id']}",
            json={"custom_title": "My saved video"},
        )
        assert rename_response.status_code == 200
        assert rename_response.json()["display_title"] == "My saved video"

        video_title_page = list_archive_task_page(client, "?include_read=true&title=yt-dlp")
        assert video_title_page["total"] == 1
        video_title_tasks = video_title_page["items"]
        assert [item["task_id"] for item in video_title_tasks] == [task["task_id"]]


def test_page_and_video_failure_fails_task(
    tmp_path: Path,
    fake_failing_single_file: Path,
    fake_failing_yt_dlp: Path,
) -> None:
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_failing_single_file),
        yt_dlp_path=str(fake_failing_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post(
            "/api/v1/archive-tasks",
            json={"url": "https://example.com/"},
        )
        assert response.status_code == 202
        task = wait_for_finished(client, response.json()["task_id"])

        assert task["status"] == "failed"
        assert task["result"] is None
        assert "网页保存失败" in task["error"]
        assert "视频下载失败" in task["error"]


def test_page_archive_timeout_cleans_up_child_processes(
    tmp_path: Path,
    fake_yt_dlp: Path,
) -> None:
    script = tmp_path / "single-file-orphan"
    script.write_text(
        """#!/usr/bin/env python3
import subprocess
import sys

subprocess.Popen(
    [
        sys.executable,
        "-c",
        "import time; time.sleep(30)",
    ],
    stdout=sys.stdout,
    stderr=sys.stderr,
)
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(script),
        yt_dlp_path=str(fake_yt_dlp),
        use_xvfb=False,
        archive_timeout_seconds=1,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post(
            "/api/v1/archive-tasks",
            json={"url": "https://example.com/"},
        )
        assert response.status_code == 202
        task = wait_for_finished(client, response.json()["task_id"])

    assert task["status"] == "succeeded"
    assert task["result"]["video_file_name"] == f"{task['task_id']}.mp4"
    assert task["result"]["page_error"] == "Archive timed out."


def test_stale_chrome_singleton_files_are_removed(
    tmp_path: Path,
    fake_single_file: Path,
) -> None:
    from app.archiver import SingleFileArchiver

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "SingletonLock").symlink_to("host-999999")
    (profile_dir / "SingletonSocket").symlink_to("/root/not-readable/SingletonSocket")
    settings = Settings(
        browser_profile_dir=profile_dir,
        single_file_path=str(fake_single_file),
        use_xvfb=False,
    )

    SingleFileArchiver(settings)._remove_stale_singleton_files(profile_dir)

    assert not (profile_dir / "SingletonLock").is_symlink()
    assert not (profile_dir / "SingletonSocket").is_symlink()


def test_active_chrome_singleton_files_are_kept(
    tmp_path: Path,
    fake_single_file: Path,
) -> None:
    from app.archiver import SingleFileArchiver

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "SingletonLock").symlink_to(f"host-{os.getpid()}")
    (profile_dir / "SingletonSocket").symlink_to("/tmp/active-singleton-socket")
    settings = Settings(
        browser_profile_dir=profile_dir,
        single_file_path=str(fake_single_file),
        use_xvfb=False,
    )

    SingleFileArchiver(settings)._remove_stale_singleton_files(profile_dir)

    assert (profile_dir / "SingletonLock").is_symlink()
    assert (profile_dir / "SingletonSocket").is_symlink()


def test_singlefile_archive_uses_ephemeral_cache(
    tmp_path: Path,
    fake_yt_dlp: Path,
) -> None:
    from app.archiver import SingleFileArchiver

    script = tmp_path / "single-file-capture"
    script.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys

output_path = pathlib.Path(sys.argv[2])
output_path.write_text("<html><head><title>ok</title></head><body>ok</body></html>", encoding="utf-8")
output_path.with_suffix(".args").write_text("\\n".join(sys.argv[3:]), encoding="utf-8")
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    settings = Settings(
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(script),
        yt_dlp_path=str(fake_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
    )

    asyncio.run(SingleFileArchiver(settings).archive("https://example.com/", "page.html"))

    args = (settings.archive_dir / "page.args").read_text(encoding="utf-8").splitlines()
    assert any(arg.startswith("--browser-arg=--disk-cache-dir=") for arg in args)
    assert "--browser-arg=--disk-cache-size=1" in args
    assert "--browser-arg=--media-cache-size=1" in args
    assert "--browser-arg=--disable-cache" in args
    assert "--browser-arg=--disable-application-cache" in args
    assert "--http-header=Cache-Control=no-cache" not in args
    assert "--http-header=Pragma=no-cache" not in args
    assert "--browser-wait-until=networkIdle" in args
    assert "--browser-wait-until-delay=0" in args
    assert "--browser-wait-until-fallback=false" in args
    assert not any(arg.startswith("--browser-wait-delay=") for arg in args)
    assert "--load-deferred-images=true" in args
    assert "--load-deferred-images-dispatch-scroll-event=true" in args
    assert "--load-deferred-images-max-idle-time=5000" in args
    assert "--load-deferred-images=false" not in args
    assert "--remove-unused-styles=false" in args
    assert "--remove-alternative-medias=false" in args


def test_singlefile_archive_can_use_running_chrome_debug_endpoint(
    tmp_path: Path,
    fake_yt_dlp: Path,
) -> None:
    from app.archiver import SingleFileArchiver

    settings = Settings(
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path="/usr/local/bin/single-file",
        yt_dlp_path=str(fake_yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
        browser_remote_debugging_url="http://127.0.0.1:9222",
    )
    archiver = SingleFileArchiver(settings)

    args = archiver._archive_command(
        "https://example.com/",
        settings.archive_dir / "page.html",
        settings.browser_profile_dir,
        None,
        browser_target_id="reader-tab-1",
        skip_navigation=True,
    )

    assert "--browser-server=http://127.0.0.1:9222" in args
    assert "--browser-target-id=reader-tab-1" in args
    assert "--browser-skip-navigation=true" in args
    assert "--http-header=Cache-Control=no-cache" not in args
    assert "--http-header=Pragma=no-cache" not in args
    assert "--browser-wait-until=networkIdle" in args
    assert "--browser-wait-until-delay=0" in args
    assert "--browser-wait-until-fallback=false" in args
    assert not any(arg.startswith("--browser-wait-delay=") for arg in args)
    assert "--load-deferred-images=true" in args
    assert "--load-deferred-images-dispatch-scroll-event=true" in args
    assert "--load-deferred-images-max-idle-time=5000" in args
    assert "--load-deferred-images=false" not in args
    assert "--remove-unused-styles=false" in args
    assert "--remove-alternative-medias=false" in args
    assert not any(arg.startswith("--browser-arg=--user-data-dir=") for arg in args)
    assert not any(arg.startswith("--browser-executable-path=") for arg in args)


def test_short_error_prefers_actual_error_line() -> None:
    from app.service import ArchiveTaskService

    service = ArchiveTaskService.__new__(ArchiveTaskService)
    error = service._short_error(
        """
[BiliBili] Extracting URL: https://www.bilibili.com/video/example
[BiliBili] Downloading webpage
ERROR: [BiliBili] Unable to download JSON metadata: HTTP Error 412: Precondition Failed
""",
    )

    assert error == (
        "[BiliBili] Unable to download JSON metadata: "
        "HTTP Error 412: Precondition Failed"
    )


def test_short_error_redacts_sensitive_query_values() -> None:
    from app.service import ArchiveTaskService

    service = ArchiveTaskService.__new__(ArchiveTaskService)
    error = service._short_error(
        "Unsupported URL: https://mp.weixin.qq.com/mp/captcha?poc_token=secret-value"
        "&target_url=https%3A%2F%2Fmp.weixin.qq.com%2Fs%2Fexample",
    )

    assert "secret-value" not in error
    assert "poc_token=[已隐藏]" in error


def test_missing_task_returns_404(tmp_path: Path, fake_single_file: Path) -> None:
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.get("/api/v1/archive-tasks/not-found")

    assert response.status_code == 404


def test_frontend_and_app_config_are_served(
    tmp_path: Path,
    fake_single_file: Path,
) -> None:
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        desktop_url="/browser/",
        poll_interval_ms=3000,
        rss_refresh_interval_seconds=600,
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        page_response = client.get("/")
        config_response = client.get("/api/v1/app-config")

    assert page_response.status_code == 200
    assert "Reader Archive" in page_response.text
    assert 'id="root"' in page_response.text
    assert 'type="module"' in page_response.text
    assert config_response.status_code == 200
    assert "Deprecation" not in config_response.headers
    body = config_response.json()
    assert body["desktop_url"] == "/browser/"
    assert body["archive_dir"] == str(tmp_path / "archive")
    assert body["poll_interval_ms"] == 3000
    assert body["rss_refresh_interval_seconds"] == 600
    assert body["semantic_search"]["model_name"] == settings.semantic_model_name
    assert body["semantic_search"]["embedding_dimensions"] == 384
    assert body["semantic_search"]["status"] in {"ready", "unavailable", "disabled"}


def test_admin_can_update_app_config_and_settings_are_persisted(
    tmp_path: Path,
    fake_single_file: Path,
) -> None:
    database_url = make_database_url()
    settings = Settings(
        database_url=database_url,
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        poll_interval_ms=3000,
        rss_refresh_interval_seconds=600,
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        update_response = client.patch(
            "/api/v1/app-config",
            json={"poll_interval_ms": 5000, "rss_refresh_interval_seconds": 1200},
        )
        read_response = client.get("/api/v1/app-config")

    assert update_response.status_code == 200
    assert update_response.json()["poll_interval_ms"] == 5000
    assert update_response.json()["rss_refresh_interval_seconds"] == 1200
    assert read_response.json()["poll_interval_ms"] == 5000
    assert read_response.json()["rss_refresh_interval_seconds"] == 1200

    restarted_settings = Settings(
        database_url=database_url,
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        poll_interval_ms=3000,
        rss_refresh_interval_seconds=600,
        use_xvfb=False,
    )
    restarted_app = create_app(restarted_settings)

    with TestClient(restarted_app) as client:
        login_as_admin(client)
        persisted_response = client.get("/api/v1/app-config")

    assert persisted_response.json()["poll_interval_ms"] == 5000
    assert persisted_response.json()["rss_refresh_interval_seconds"] == 1200


def test_auth_required_for_app_api_and_browser_proxy(
    tmp_path: Path,
    fake_single_file: Path,
) -> None:
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        page_response = client.get("/", follow_redirects=False)
        api_response = client.get("/api/v1/archive-tasks")
        browser_response = client.get("/browser/", follow_redirects=False)

        assert page_response.status_code == 307
        assert page_response.headers["location"].startswith("/login")
        assert api_response.status_code == 401
        assert browser_response.status_code == 307
        assert browser_response.headers["location"].startswith("/login")


def test_login_logout_and_token_are_required(
    tmp_path: Path,
    fake_single_file: Path,
) -> None:
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "change-me"},
        )
        assert login.status_code == 200
        assert login.json()["user"]["role"] == "admin"

        access_token = login.json()["access_token"]
        client.cookies.clear()
        client.headers.update({"Authorization": f"Bearer {access_token}"})
        assert client.get("/api/v1/archive-tasks").status_code == 200

        client.headers.update({"X-CSRF-Token": login.json()["csrf_token"]})
        logout = client.post("/api/v1/auth/logout", json={})
        assert logout.status_code == 204
        client.headers.pop("Authorization", None)
        assert client.get("/api/v1/archive-tasks").status_code == 401
        browser_response = client.get("/browser/", follow_redirects=False)
        assert browser_response.status_code == 307
        assert browser_response.headers["location"].startswith("/login")


def test_admin_can_manage_users_and_user_cannot(
    tmp_path: Path,
    fake_single_file: Path,
) -> None:
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        create_response = client.post(
            "/api/v1/users",
            json={"username": "reader", "password": "reader-pass", "role": "user"},
        )
        assert create_response.status_code == 201
        user_id = create_response.json()["user_id"]

        reset_response = client.post(
            f"/api/v1/users/{user_id}/reset-password",
            json={"password": "reader-new-pass"},
        )
        assert reset_response.status_code == 200

        logout = client.post("/api/v1/auth/logout", json={})
        assert logout.status_code == 204
        client.headers.pop("X-CSRF-Token", None)

        user_login = client.post(
            "/api/v1/auth/login",
            json={"username": "reader", "password": "reader-new-pass"},
        )
        assert user_login.status_code == 200
        client.headers.update({"X-CSRF-Token": user_login.json()["csrf_token"]})
        assert client.get("/api/v1/users").status_code == 403


def test_current_user_can_change_password(
    tmp_path: Path,
    fake_single_file: Path,
) -> None:
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        failed = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "wrong-password", "new_password": "new-change-me"},
        )
        assert failed.status_code == 400

        changed = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "change-me", "new_password": "new-change-me"},
        )
        assert changed.status_code == 200

        logout = client.post("/api/v1/auth/logout", json={})
        assert logout.status_code == 204
        old_login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "change-me"},
        )
        assert old_login.status_code == 400
        new_login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "new-change-me"},
        )
        assert new_login.status_code == 200


def test_admin_can_delete_users_with_safety_checks(
    tmp_path: Path,
    fake_single_file: Path,
) -> None:
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        admin_session = login_as_admin(client)
        admin_id = admin_session["user"]["user_id"]

        self_delete = client.delete(f"/api/v1/users/{admin_id}")
        assert self_delete.status_code == 409

        create_user = client.post(
            "/api/v1/users",
            json={"username": "delete-me", "password": "delete-pass", "role": "user"},
        )
        assert create_user.status_code == 201
        user_id = create_user.json()["user_id"]

        delete_user = client.delete(f"/api/v1/users/{user_id}")
        assert delete_user.status_code == 204
        assert all(user["user_id"] != user_id for user in client.get("/api/v1/users").json())

        create_admin = client.post(
            "/api/v1/users",
            json={"username": "second-admin", "password": "second-pass", "role": "admin"},
        )
        assert create_admin.status_code == 201
        second_admin_id = create_admin.json()["user_id"]
        assert client.delete(f"/api/v1/users/{second_admin_id}").status_code == 204

        last_admin_delete = client.delete(f"/api/v1/users/{admin_id}")
        assert last_admin_delete.status_code == 409


def test_browser_http_proxy_forwards_to_internal_desktop(
    tmp_path: Path,
    fake_single_file: Path,
) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(self.path.encode("utf-8"))

        def log_message(self, format: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        desktop_upstream=f"http://127.0.0.1:{server.server_port}",
        use_xvfb=False,
    )
    app = create_app(settings)

    try:
        with TestClient(app) as client:
            login_as_admin(client)
            response = client.get("/browser/session?x=1")
            assert response.status_code == 200
            assert response.text == "/browser/session?x=1"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_browser_websocket_proxy_forwards_messages(
    tmp_path: Path,
    fake_single_file: Path,
) -> None:
    websockets = pytest.importorskip("websockets")
    ready = threading.Event()
    stop = threading.Event()
    port_holder: dict[str, int] = {}

    async def handler(websocket) -> None:  # type: ignore[no-untyped-def]
        async for message in websocket:
            await websocket.send(f"echo:{message}")

    async def run_server() -> None:
        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port_holder["port"] = server.sockets[0].getsockname()[1]
            ready.set()
            while not stop.is_set():
                await asyncio.sleep(0.05)

    def run_loop() -> None:
        asyncio.run(run_server())

    thread = threading.Thread(target=run_loop)
    thread.daemon = True
    thread.start()
    assert ready.wait(timeout=5)

    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        desktop_upstream=f"http://127.0.0.1:{port_holder['port']}",
        use_xvfb=False,
    )
    app = create_app(settings)

    try:
        with TestClient(app) as client:
            login_as_admin(client)
            with client.websocket_connect("/browser/ws") as websocket:
                websocket.send_text("ping")
                assert websocket.receive_text() == "echo:ping"
    finally:
        stop.set()
        thread.join(timeout=2)




def test_rss_feed_adds_all_current_entries_and_skips_duplicates(
    tmp_path: Path,
    fake_single_file: Path,
    fake_failing_yt_dlp: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed_feed = ParsedFeed(
        title="Example Feed",
        entries=[
            ParsedFeedEntry(
                title="First",
                url="https://example.com/first?utm_source=rss",
                normalized_url="https://example.com/first",
                published_at=None,
            ),
            ParsedFeedEntry(
                title="Second",
                url="https://example.com/second",
                normalized_url="https://example.com/second",
                published_at=None,
            ),
        ],
    )

    class FakeFetcher:
        def __init__(self, timeout_seconds: int) -> None:
            self.timeout_seconds = timeout_seconds

        def fetch(self, url: str) -> ParsedFeed:
            return parsed_feed

    monkeypatch.setattr("app.service.RssFeedFetcher", FakeFetcher)
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        yt_dlp_path=str(fake_failing_yt_dlp),
        use_xvfb=False,
        rss_refresh_interval_seconds=3600,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post(
            "/api/v1/rss-feeds",
            json={"url": "https://example.com/feed.xml"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["discovered_count"] == 2
        assert body["created_task_count"] == 2
        assert body["feed"]["title"] == "Example Feed"
        assert body["feed"]["last_error"] is None

        task_page = list_archive_task_page(client)
        assert task_page["total"] == 2
        tasks = task_page["items"]
        assert len(tasks) == 2
        assert [task["url"] for task in tasks] == [
            "https://example.com/first?utm_source=rss",
            "https://example.com/second",
        ]
        assert [task["entry_title"] for task in tasks] == ["First", "Second"]
        assert {task["source_type"] for task in tasks} == {"rss"}
        assert {task["source_title"] for task in tasks} == {"Example Feed"}
        assert [task["is_read"] for task in tasks] == [False, False]

        refresh_response = client.post(f"/api/v1/rss-feeds/{body['feed']['feed_id']}/refresh")
        assert refresh_response.status_code == 200
        assert refresh_response.json()["created_task_count"] == 0


def test_rss_feed_refresh_skips_existing_normal_url_even_with_published_key(
    tmp_path: Path,
    fake_single_file: Path,
    fake_failing_yt_dlp: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    normalized_url = "https://example.com/already-saved"
    parsed_feed = ParsedFeed(
        title="Normal Feed",
        entries=[
            ParsedFeedEntry(
                title="Already Saved",
                url=normalized_url,
                normalized_url=normalized_url,
                published_at="2026-06-29T00:00:00+00:00",
                entry_key=rss_entry_key(
                    normalized_url=normalized_url,
                    published_at="2026-06-29T00:00:00+00:00",
                    use_published_at=True,
                ),
            )
        ],
    )

    class FakeFetcher:
        def __init__(self, timeout_seconds: int) -> None:
            self.timeout_seconds = timeout_seconds

        def fetch(self, url: str) -> ParsedFeed:
            return parsed_feed

    monkeypatch.setattr("app.service.RssFeedFetcher", FakeFetcher)
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        yt_dlp_path=str(fake_failing_yt_dlp),
        use_xvfb=False,
        rss_refresh_interval_seconds=3600,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        task_response = client.post("/api/v1/archive-tasks", json={"url": normalized_url})
        assert task_response.status_code == 202

        response = client.post(
            "/api/v1/rss-feeds",
            json={"url": "https://example.com/feed.xml"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["discovered_count"] == 1
        assert body["created_task_count"] == 0

        task_page = list_archive_task_page(client)
        assert task_page["total"] == 1
        assert task_page["items"][0]["url"] == normalized_url


def test_rss_feed_refresh_archives_new_dated_entry_with_same_url(
    tmp_path: Path,
    fake_single_file: Path,
    fake_failing_yt_dlp: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    normalized_url = "https://readhub.cn/daily"
    feeds = [
        ParsedFeed(
            title="Readhub 每日早报",
            entries=[
                ParsedFeedEntry(
                    title="Readhub 每日早报",
                    url=normalized_url,
                    normalized_url=normalized_url,
                    published_at="2026-06-28T00:00:00+00:00",
                    entry_key=rss_entry_key(
                        normalized_url=normalized_url,
                        published_at="2026-06-28T00:00:00+00:00",
                        use_published_at=True,
                    ),
                    allow_repeated_url=True,
                )
            ],
        ),
        ParsedFeed(
            title="Readhub 每日早报",
            entries=[
                ParsedFeedEntry(
                    title="Readhub 每日早报",
                    url=normalized_url,
                    normalized_url=normalized_url,
                    published_at="2026-06-29T00:00:00+00:00",
                    entry_key=rss_entry_key(
                        normalized_url=normalized_url,
                        published_at="2026-06-29T00:00:00+00:00",
                        use_published_at=True,
                    ),
                    allow_repeated_url=True,
                )
            ],
        ),
    ]

    class FakeFetcher:
        calls = 0

        def __init__(self, timeout_seconds: int) -> None:
            self.timeout_seconds = timeout_seconds

        def fetch(self, url: str) -> ParsedFeed:
            feed = feeds[min(self.__class__.calls, len(feeds) - 1)]
            self.__class__.calls += 1
            return feed

    monkeypatch.setattr("app.service.RssFeedFetcher", FakeFetcher)
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        yt_dlp_path=str(fake_failing_yt_dlp),
        use_xvfb=False,
        rss_refresh_interval_seconds=3600,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post(
            "/api/v1/rss-feeds",
            json={"url": "https://readhub.cn/daily/rss"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["created_task_count"] == 1

        refresh_response = client.post(f"/api/v1/rss-feeds/{body['feed']['feed_id']}/refresh")
        assert refresh_response.status_code == 200
        assert refresh_response.json()["created_task_count"] == 1

        task_page = list_archive_task_page(client)
        assert task_page["total"] == 2
        assert {task["url"] for task in task_page["items"]} == {normalized_url}


def test_rss_feed_without_entry_title_uses_archived_page_title(
    tmp_path: Path,
    fake_single_file: Path,
    fake_failing_yt_dlp: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed_feed = ParsedFeed(
        title="Example Feed",
        entries=[
            ParsedFeedEntry(
                title=None,
                url="https://example.com/no-title",
                normalized_url="https://example.com/no-title",
                published_at=None,
            ),
        ],
    )

    class FakeFetcher:
        def __init__(self, timeout_seconds: int) -> None:
            self.timeout_seconds = timeout_seconds

        def fetch(self, url: str) -> ParsedFeed:
            return parsed_feed

    monkeypatch.setattr("app.service.RssFeedFetcher", FakeFetcher)
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        yt_dlp_path=str(fake_failing_yt_dlp),
        use_xvfb=False,
        rss_refresh_interval_seconds=3600,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post(
            "/api/v1/rss-feeds",
            json={"url": "https://example.com/feed.xml"},
        )
        assert response.status_code == 201
        task = list_archive_tasks(client)[0]
        task = wait_for_finished(client, task["task_id"])

        assert task["entry_title"] == "Saved title for https://example.com/no-title"


def test_rss_feed_failure_is_recorded(
    tmp_path: Path,
    fake_single_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeFetcher:
        def __init__(self, timeout_seconds: int) -> None:
            self.timeout_seconds = timeout_seconds

        def fetch(self, url: str) -> ParsedFeed:
            raise RuntimeError("feed is unavailable")

    monkeypatch.setattr("app.service.RssFeedFetcher", FakeFetcher)
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        response = client.post(
            "/api/v1/rss-feeds",
            json={"url": "https://example.com/feed.xml"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["created_task_count"] == 0
        assert "feed is unavailable" in body["feed"]["last_error"]

        feeds = client.get("/api/v1/rss-feeds").json()
        assert len(feeds) == 1
        assert "feed is unavailable" in feeds[0]["last_error"]


def test_rss_feed_update_disable_and_delete(
    tmp_path: Path,
    fake_single_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeFetcher:
        def __init__(self, timeout_seconds: int) -> None:
            self.timeout_seconds = timeout_seconds

        def fetch(self, url: str) -> ParsedFeed:
            return ParsedFeed(title="Original Feed", entries=[])

    monkeypatch.setattr("app.service.RssFeedFetcher", FakeFetcher)
    settings = Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(fake_single_file),
        use_xvfb=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login_as_admin(client)
        create_response = client.post(
            "/api/v1/rss-feeds",
            json={"url": "https://example.com/feed.xml"},
        )
        feed_id = create_response.json()["feed"]["feed_id"]

        update_response = client.patch(
            f"/api/v1/rss-feeds/{feed_id}",
            json={"title": "Renamed Feed", "enabled": False},
        )
        assert update_response.status_code == 200
        assert update_response.json()["title"] == "Renamed Feed"
        assert update_response.json()["enabled"] is False

        delete_response = client.delete(f"/api/v1/rss-feeds/{feed_id}")
        assert delete_response.status_code == 204
        assert client.get("/api/v1/rss-feeds").json() == []
