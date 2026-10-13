"""List filters (source / status groups / tags_match), summaries, PATCH is_read and versions."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import sleep

import pytest
from database_support import make_database_url
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import Settings
from app.core.db import get_engine
from app.main import create_app
from app.models import ArchiveSearchDocument, ArchiveTask


@pytest.fixture(autouse=True)
def isolate_browser_remote_debugging_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("READER_BROWSER_REMOTE_DEBUGGING_URL", raising=False)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    single_file = tmp_path / "single-file"
    single_file.write_text(
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
    single_file.chmod(0o755)
    yt_dlp = tmp_path / "yt-dlp-fail"
    yt_dlp.write_text(
        "#!/usr/bin/env python3\nimport sys\nprint('no video formats found', file=sys.stderr)\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    yt_dlp.chmod(0o755)
    return Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(single_file),
        yt_dlp_path=str(yt_dlp),
        chrome_path="/bin/true",
        use_xvfb=False,
    )


def login(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "change-me"}
    )
    assert response.status_code == 200
    client.headers.update({"X-CSRF-Token": response.json()["csrf_token"]})


def wait_for_finished(client: TestClient, task_id: str) -> dict:
    for _ in range(80):
        task = client.get(f"/api/v1/archive-tasks/{task_id}").json()
        if task["status"] in {"succeeded", "failed", "manual_action_required"}:
            return task
        sleep(0.05)
    pytest.fail("Archive task did not finish.")


def create_finished(client: TestClient, url: str) -> dict:
    response = client.post("/api/v1/archive-tasks", json={"url": url})
    assert response.status_code == 202
    return wait_for_finished(client, response.json()["task_id"])


def set_columns(settings: Settings, task_id: str, **values: object) -> None:
    with Session(get_engine(settings.database_url)) as session:
        task = session.get(ArchiveTask, task_id)
        assert task is not None
        for key, value in values.items():
            setattr(task, key, value)
        session.add(task)
        session.commit()


def ids(client: TestClient, query: str) -> list[str]:
    response = client.get(f"/api/v1/archive-tasks{query}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == len(body["items"])
    return [item["task_id"] for item in body["items"]]


def test_list_filters_source_status_and_tags_match(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        login(client)
        names = ["manual", "rss", "failed", "manual_action", "queued", "running"]
        tasks = {name: create_finished(client, f"https://example.com/{name}") for name in names}
        base = datetime.now(UTC)
        # Newest first in list output: manual, rss, failed, manual_action, queued, running.
        for index, name in enumerate(names):
            set_columns(settings, tasks[name]["task_id"], created_at=base - timedelta(minutes=index))
        set_columns(settings, tasks["rss"]["task_id"], source_type="rss")
        set_columns(settings, tasks["failed"]["task_id"], status="failed")
        set_columns(settings, tasks["manual_action"]["task_id"], status="manual_action_required")
        set_columns(settings, tasks["queued"]["task_id"], status="queued")
        set_columns(settings, tasks["running"]["task_id"], status="running")
        tid = {name: task["task_id"] for name, task in tasks.items()}

        assert client.patch(
            f"/api/v1/archive-tasks/{tid['manual']}", json={"tags": ["alpha", "beta"]}
        ).status_code == 200
        assert client.patch(
            f"/api/v1/archive-tasks/{tid['rss']}", json={"tags": ["alpha"]}
        ).status_code == 200
        assert client.patch(
            f"/api/v1/archive-tasks/{tid['failed']}", json={"tags": ["beta"]}
        ).status_code == 200

        all_ids = [tid[name] for name in names]
        # Defaults are unchanged.
        assert ids(client, "") == all_ids
        assert ids(client, "?status=running") == [tid["manual_action"], tid["queued"], tid["running"]]
        assert ids(client, "?status=failed") == [tid["failed"]]

        # B1 source
        assert ids(client, "?source=rss") == [tid["rss"]]
        assert ids(client, "?source=manual") == [t for t in all_ids if t != tid["rss"]]
        assert client.get("/api/v1/archive-tasks?source=other").status_code == 422

        # B2 status groups
        assert ids(client, "?status=attention") == [
            tid["failed"], tid["manual_action"], tid["queued"], tid["running"],
        ]
        assert ids(client, "?status=problem") == [tid["failed"], tid["manual_action"]]
        assert ids(client, "?status=succeeded") == [tid["manual"], tid["rss"]]
        assert ids(client, "?status=succeeded&source=manual") == [tid["manual"]]
        assert client.get("/api/v1/archive-tasks?status=bogus").status_code == 422

        # B3 tags_match
        assert ids(client, "?tags=alpha&tags=beta") == [tid["manual"], tid["rss"], tid["failed"]]
        assert ids(client, "?tags=alpha&tags=beta&tags_match=any") == [
            tid["manual"], tid["rss"], tid["failed"],
        ]
        assert ids(client, "?tags=alpha&tags=beta&tags_match=all") == [tid["manual"]]
        assert ids(client, "?tag=ALPHA&tags=beta&tags_match=all") == [tid["manual"]]
        assert ids(client, "?tags=alpha&tags_match=all") == [tid["manual"], tid["rss"]]
        assert client.get("/api/v1/archive-tasks?tags_match=some").status_code == 422

        # Query path (search_archive) honours source and tags_match too.
        assert set(ids(client, "?q=Saved%20title&tags=alpha&tags=beta")) == {
            tid["manual"], tid["rss"], tid["failed"],
        }
        assert ids(client, "?q=Saved%20title&tags=alpha&tags=beta&tags_match=all") == [tid["manual"]]
        assert ids(client, "?q=Saved%20title&source=rss") == [tid["rss"]]
        assert ids(client, "?title=Saved%20title&source=rss&include_read=true") == [tid["rss"]]

        # Read state still respected by new filters.
        client.post(f"/api/v1/archive-tasks/{tid['failed']}/mark-read")
        assert ids(client, "?status=problem") == [tid["manual_action"]]
        assert ids(client, "?status=problem&include_read=true") == [
            tid["failed"], tid["manual_action"],
        ]


def test_patch_is_read_does_not_touch_title_or_tags(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        login(client)
        task_id = create_finished(client, "https://example.com/read-state")["task_id"]
        updated = client.patch(
            f"/api/v1/archive-tasks/{task_id}",
            json={"custom_title": "Mine", "tags": ["keep"]},
        ).json()
        assert updated["is_read"] is False

        marked = client.patch(f"/api/v1/archive-tasks/{task_id}", json={"is_read": True})
        assert marked.status_code == 200
        body = marked.json()
        assert body["is_read"] is True
        assert body["custom_title"] == "Mine"
        assert body["tags"] == ["keep"]
        assert ids(client, "") == []

        unmarked = client.patch(f"/api/v1/archive-tasks/{task_id}", json={"is_read": False}).json()
        assert unmarked["is_read"] is False
        assert unmarked["custom_title"] == "Mine"
        assert unmarked["tags"] == ["keep"]
        assert ids(client, "") == [task_id]

        # Explicit null means unchanged; custom_title null still clears the title.
        nulled = client.patch(
            f"/api/v1/archive-tasks/{task_id}", json={"is_read": None, "custom_title": None}
        ).json()
        assert nulled["is_read"] is False
        assert nulled["custom_title"] is None
        assert nulled["tags"] == ["keep"]

        # Title-only updates leave read state alone.
        client.patch(f"/api/v1/archive-tasks/{task_id}", json={"is_read": True})
        renamed = client.patch(f"/api/v1/archive-tasks/{task_id}", json={"custom_title": "x"}).json()
        assert renamed["is_read"] is True

        missing = client.patch("/api/v1/archive-tasks/missing", json={"is_read": True})
        assert missing.status_code == 404


def test_file_route_does_not_mark_read_but_index_does(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        login(client)
        task = create_finished(client, "https://example.com/snapshot")
        task_id = task["task_id"]
        file_name = task["result"]["file_name"]
        assert file_name

        response = client.get(f"/api/v1/archive-tasks/{task_id}/files/{file_name}")
        assert response.status_code == 200
        assert client.get(f"/api/v1/archive-tasks/{task_id}").json()["is_read"] is False

        index = client.get(f"/api/v1/archive-tasks/{task_id}/files")
        assert index.status_code == 200
        assert client.get(f"/api/v1/archive-tasks/{task_id}").json()["is_read"] is True


def test_versions_endpoint(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        login(client)
        first = create_finished(client, "https://example.com/article")["task_id"]
        second = create_finished(client, "https://example.com/article")["task_id"]
        other = create_finished(client, "https://example.com/other")["task_id"]
        lone = create_finished(client, "https://example.com/lone")["task_id"]
        base = datetime.now(UTC)
        set_columns(settings, first, created_at=base - timedelta(hours=1))
        set_columns(settings, second, created_at=base)
        set_columns(settings, lone, normalized_url=None)

        for task_id in (first, second):
            response = client.get(f"/api/v1/archive-tasks/{task_id}/versions")
            assert response.status_code == 200
            assert [item["task_id"] for item in response.json()] == [second, first]

        other_versions = client.get(f"/api/v1/archive-tasks/{other}/versions").json()
        assert [item["task_id"] for item in other_versions] == [other]
        lone_versions = client.get(f"/api/v1/archive-tasks/{lone}/versions").json()
        assert [item["task_id"] for item in lone_versions] == [lone]

        assert client.get("/api/v1/archive-tasks/missing/versions").status_code == 404


def test_list_items_include_whitespace_collapsed_summary(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        login(client)
        base = datetime.now(UTC)
        long_body = "First   line\n\n  second\tline " + "x" * 400
        with Session(get_engine(settings.database_url)) as session:
            # No output_file, so the background indexer leaves these rows alone.
            with_doc = ArchiveTask(url="https://example.com/a", status="succeeded", created_at=base)
            no_doc = ArchiveTask(
                url="https://example.com/b", status="succeeded", created_at=base - timedelta(minutes=1)
            )
            pending = ArchiveTask(
                url="https://example.com/c", status="succeeded", created_at=base - timedelta(minutes=2)
            )
            session.add_all([with_doc, no_doc, pending])
            session.commit()
            session.add(ArchiveSearchDocument(task_id=with_doc.id, file_name="a.html",
                content=long_body, document_hash="h1"))
            session.add(ArchiveSearchDocument(task_id=pending.id, file_name="c.html",
                content="not ready", document_hash="h2", status="unavailable"))
            session.commit()
            task_ids = (with_doc.id, no_doc.id, pending.id)

        response = client.get("/api/v1/archive-tasks")
        assert response.status_code == 200, response.text
        items = {item["task_id"]: item for item in response.json()["items"]}
        summary = items[task_ids[0]]["summary"]
        assert summary.startswith("First line second line xxx")
        assert len(summary) == 200
        assert items[task_ids[1]]["summary"] is None
        assert items[task_ids[2]]["summary"] is None

        # Single-task reads are unaffected.
        single = client.get(f"/api/v1/archive-tasks/{task_ids[0]}").json()
        assert single["summary"] is None
