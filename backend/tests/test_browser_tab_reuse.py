from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from time import sleep
from urllib.parse import unquote, urlparse

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.test_archive_api import login_as_admin, make_database_url, wait_for_finished


@dataclass
class FakeChromeState:
    tabs: dict[str, dict[str, str]] = field(default_factory=dict)
    new_count: int = 0
    activated: list[str] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)

    def add_tab(self, url: str) -> str:
        self.new_count += 1
        target_id = f"tab-{self.new_count}"
        self.tabs[target_id] = {
            "id": target_id,
            "type": "page",
            "url": url,
            "title": url,
            "webSocketDebuggerUrl": f"ws://127.0.0.1/devtools/page/{target_id}",
        }
        return target_id


@contextmanager
def fake_chrome_server():
    state = FakeChromeState()

    class Handler(BaseHTTPRequestHandler):
        def do_PUT(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/json/new":
                self.send_error(404)
                return
            target_id = state.add_tab(unquote(parsed.query))
            self._json(state.tabs[target_id])

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/json/list":
                self._json(list(state.tabs.values()))
                return
            if self.path.startswith("/json/activate/"):
                target_id = unquote(self.path.removeprefix("/json/activate/"))
                if target_id not in state.tabs:
                    self.send_error(404)
                    return
                state.activated.append(target_id)
                self._json({"activated": target_id})
                return
            if self.path.startswith("/json/close/"):
                target_id = unquote(self.path.removeprefix("/json/close/"))
                if target_id not in state.tabs:
                    self.send_error(404)
                    return
                state.tabs.pop(target_id)
                state.closed.append(target_id)
                self._json({"closed": target_id})
                return
            self.send_error(404)

        def _json(self, value: object) -> None:
            payload = json.dumps(value).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def write_fake_single_file(path: Path) -> Path:
    script = path / "single-file-existing-tab"
    script.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys

output = pathlib.Path(sys.argv[2])
calls = output.parent / "singlefile.calls"
with calls.open("a", encoding="utf-8") as stream:
    stream.write("\\t".join(sys.argv[1:]) + "\\n")
marker = output.parent / "verified.marker"
if marker.exists():
    output.write_text(
        "<html><head><title>验证后的文章</title></head>"
        "<body><article id='js_content'>正文内容</article></body></html>",
        encoding="utf-8",
    )
else:
    output.write_text(
        "<html><head><title>Weixin Official Accounts Platform</title></head>"
        "<body><h2>环境异常</h2><p>完成验证后即可继续访问。</p>"
        "<a id='js_verify'>去验证</a></body></html>",
        encoding="utf-8",
    )
    marker.write_text("ready", encoding="utf-8")
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def write_failing_yt_dlp(path: Path) -> Path:
    script = path / "yt-dlp-fail"
    script.write_text(
        "#!/bin/sh\necho 'ERROR: no video' >&2\nexit 1\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def make_settings(tmp_path: Path, browser_url: str) -> Settings:
    return Settings(
        database_url=make_database_url(),
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(write_fake_single_file(tmp_path)),
        yt_dlp_path=str(write_failing_yt_dlp(tmp_path)),
        chrome_path="/bin/true",
        use_xvfb=False,
        browser_remote_debugging_url=browser_url,
        semantic_search_enabled=False,
    )


def wait_for_tab_state(client: TestClient, task_id: str, state: str) -> dict:
    for _ in range(40):
        task = client.get(f"/api/v1/archive-tasks/{task_id}").json()
        if task["manual_actions"][0]["browser_tab_state"] == state:
            return task
        sleep(0.05)
    raise AssertionError(f"Browser tab state did not become {state}")


def test_manual_action_saves_the_same_browser_tab(tmp_path: Path) -> None:
    original_url = "https://mp.weixin.qq.com/s/example"
    with fake_chrome_server() as (chrome, browser_url):
        app = create_app(make_settings(tmp_path, browser_url))
        with TestClient(app) as client:
            login_as_admin(client)
            response = client.post("/api/v1/archive-tasks", json={"url": original_url})
            task_id = response.json()["task_id"]
            task = wait_for_finished(client, task_id)

            assert task["status"] == "manual_action_required"
            assert task["manual_actions"][0]["browser_tab_state"] == "available"
            assert chrome.new_count == 1
            target_id = next(iter(chrome.tabs))

            open_response = client.post(
                f"/api/v1/archive-tasks/{task_id}/manual-actions/"
                "wechat_article_verification/open-browser"
            )
            assert open_response.status_code == 202
            assert chrome.new_count == 1
            assert chrome.activated == [target_id]

            chrome.tabs[target_id]["url"] = "https://example.org/completely-different"
            resume = client.post(
                f"/api/v1/archive-tasks/{task_id}/resume-manual-action",
                json={"code": "wechat_article_verification"},
            )
            assert resume.status_code == 202
            task = wait_for_finished(client, task_id)

            assert task["status"] == "succeeded"
            assert chrome.new_count == 1
            assert chrome.closed == [target_id]
            calls = (tmp_path / "archive" / "singlefile.calls").read_text(
                encoding="utf-8"
            ).splitlines()
            assert len(calls) == 2
            assert all(f"--browser-target-id={target_id}" in call for call in calls)
            assert "--browser-skip-navigation=true" not in calls[0]
            assert "--browser-skip-navigation=true" in calls[1]


def test_closed_tab_requires_explicit_reopen(tmp_path: Path) -> None:
    original_url = "https://mp.weixin.qq.com/s/example"
    with fake_chrome_server() as (chrome, browser_url):
        app = create_app(make_settings(tmp_path, browser_url))
        with TestClient(app) as client:
            login_as_admin(client)
            response = client.post("/api/v1/archive-tasks", json={"url": original_url})
            task_id = response.json()["task_id"]
            wait_for_finished(client, task_id)
            original_target = next(iter(chrome.tabs))
            chrome.tabs.pop(original_target)

            resume = client.post(
                f"/api/v1/archive-tasks/{task_id}/resume-manual-action",
                json={"code": "wechat_article_verification"},
            )
            assert resume.status_code == 409
            task = wait_for_tab_state(client, task_id, "missing")
            assert task["status"] == "manual_action_required"
            assert chrome.new_count == 1

            reopened = client.post(
                f"/api/v1/archive-tasks/{task_id}/manual-actions/"
                "wechat_article_verification/open-browser"
            )
            assert reopened.status_code == 202
            assert chrome.new_count == 2
            new_target = next(iter(chrome.tabs))
            assert chrome.tabs[new_target]["url"] == original_url
            task = wait_for_tab_state(client, task_id, "available")
            assert task["status"] == "manual_action_required"


def test_missing_binding_never_recovers_by_url(tmp_path: Path) -> None:
    original_url = "https://mp.weixin.qq.com/s/example"
    with fake_chrome_server() as (chrome, browser_url):
        app = create_app(make_settings(tmp_path, browser_url))
        with TestClient(app) as client:
            login_as_admin(client)
            response = client.post("/api/v1/archive-tasks", json={"url": original_url})
            task_id = response.json()["task_id"]
            wait_for_finished(client, task_id)
            chrome.tabs.clear()
            chrome.add_tab(original_url)
            chrome.add_tab(original_url)
            before = chrome.new_count

            resume = client.post(
                f"/api/v1/archive-tasks/{task_id}/resume-manual-action",
                json={"code": "wechat_article_verification"},
            )
            assert resume.status_code == 409
            task = wait_for_tab_state(client, task_id, "missing")
            assert task["status"] == "manual_action_required"
            assert chrome.new_count == before

            open_response = client.post(
                f"/api/v1/archive-tasks/{task_id}/manual-actions/"
                "wechat_article_verification/open-browser"
            )
            assert open_response.status_code == 202
            assert chrome.new_count == before + 1
            task = wait_for_tab_state(client, task_id, "available")
            assert task["status"] == "manual_action_required"
