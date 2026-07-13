from __future__ import annotations

import asyncio
import json
import os
import signal
import tempfile
from contextlib import nullcontext, suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from app.core.config import Settings


class BrowserLoginRequiredError(RuntimeError):
    pass


class BrowserTabNotFoundError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrowserTab:
    target_id: str
    url: str
    title: str = ""


class BrowserOpener:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def open(self, url: str) -> BrowserTab | None:
        if self.settings.browser_remote_debugging_url:
            return await asyncio.to_thread(self._open_remote_tab, url)

        profile_dir = self.settings.browser_profile_dir
        home_dir = self._browser_home_dir(profile_dir)
        home_dir.mkdir(parents=True, exist_ok=True)
        profile_dir.mkdir(parents=True, exist_ok=True)
        self._remove_stale_singleton_files(profile_dir)

        command = self._command_prefix() + [
            self.settings.chrome_path,
            "--new-tab",
            url,
            f"--user-data-dir={profile_dir}",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ]
        environment = {
            **os.environ,
            "HOME": str(home_dir),
            "XDG_CONFIG_HOME": str(home_dir / ".config"),
        }
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5)
        except TimeoutError:
            return None

        if process.returncode != 0:
            output = "\n".join(
                text
                for text in (
                    stdout.decode(errors="replace").strip(),
                    stderr.decode(errors="replace").strip(),
                )
                if text
            )
            msg = output[-1000:] if output else "Chrome failed to open the URL."
            raise RuntimeError(msg)
        return None

    async def list_tabs(self) -> list[BrowserTab]:
        if not self.settings.browser_remote_debugging_url:
            return []
        return await asyncio.to_thread(self._list_remote_tabs)

    async def get(self, target_id: str) -> BrowserTab | None:
        tabs = await self.list_tabs()
        return next((tab for tab in tabs if tab.target_id == target_id), None)

    async def activate(self, target_id: str) -> BrowserTab:
        if not self.settings.browser_remote_debugging_url:
            msg = "Chrome remote debugging endpoint is unavailable."
            raise RuntimeError(msg)
        tab = await self.get(target_id)
        if tab is None:
            raise BrowserTabNotFoundError("The browser tab is no longer open.")
        await asyncio.to_thread(self._remote_command, "activate", target_id)
        return tab

    async def close(self, target_id: str) -> bool:
        if not self.settings.browser_remote_debugging_url:
            return False
        if await self.get(target_id) is None:
            return False
        await asyncio.to_thread(self._remote_command, "close", target_id)
        return True

    def _open_remote_tab(self, url: str) -> BrowserTab:
        remote_url = self.settings.browser_remote_debugging_url
        assert remote_url is not None
        endpoint = f"{remote_url.rstrip('/')}/json/new?{quote(url, safe='')}"
        request = Request(endpoint, method="PUT")
        try:
            with urlopen(request, timeout=5) as response:
                value = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            msg = "Chrome remote debugging endpoint is unavailable."
            raise RuntimeError(msg) from exc
        tab = self._tab_from_value(value)
        if tab is None:
            msg = "Chrome did not return the new browser tab."
            raise RuntimeError(msg)
        return tab

    def _list_remote_tabs(self) -> list[BrowserTab]:
        remote_url = self.settings.browser_remote_debugging_url
        assert remote_url is not None
        request = Request(f"{remote_url.rstrip('/')}/json/list")
        try:
            with urlopen(request, timeout=5) as response:
                values = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            msg = "Chrome remote debugging endpoint is unavailable."
            raise RuntimeError(msg) from exc
        if not isinstance(values, list):
            return []
        return [
            tab
            for value in values
            if isinstance(value, dict)
            and value.get("type") == "page"
            and (tab := self._tab_from_value(value)) is not None
        ]

    def _remote_command(self, command: str, target_id: str) -> None:
        remote_url = self.settings.browser_remote_debugging_url
        assert remote_url is not None
        endpoint = f"{remote_url.rstrip('/')}/json/{command}/{quote(target_id, safe='')}"
        try:
            with urlopen(Request(endpoint), timeout=5) as response:
                response.read()
        except Exception as exc:
            if command in {"activate", "close"}:
                raise BrowserTabNotFoundError("The browser tab is no longer open.") from exc
            msg = "Chrome remote debugging endpoint is unavailable."
            raise RuntimeError(msg) from exc

    def _tab_from_value(self, value: object) -> BrowserTab | None:
        if not isinstance(value, dict):
            return None
        target_id = value.get("id")
        url = value.get("url")
        title = value.get("title")
        if not isinstance(target_id, str) or not isinstance(url, str):
            return None
        return BrowserTab(
            target_id=target_id,
            url=url,
            title=title if isinstance(title, str) else "",
        )

    def _browser_home_dir(self, profile_dir: Path) -> Path:
        if profile_dir.parent.name == ".config":
            return profile_dir.parent.parent
        return profile_dir.parent

    def _remove_stale_singleton_files(self, profile_dir: Path) -> None:
        singleton_files = list(profile_dir.glob("Singleton*"))
        if not singleton_files:
            return
        singleton_lock = profile_dir / "SingletonLock"
        if self._singleton_lock_is_active(singleton_lock):
            return
        for path in singleton_files:
            path.unlink(missing_ok=True)

    def _singleton_lock_is_active(self, singleton_lock: Path) -> bool:
        if not singleton_lock.is_symlink():
            return False
        try:
            target = os.readlink(singleton_lock)
        except OSError:
            return False
        try:
            pid = int(target.rsplit("-", maxsplit=1)[1])
        except (IndexError, ValueError):
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _command_prefix(self) -> list[str]:
        if self.settings.browser_display:
            return ["env", f"DISPLAY={self.settings.browser_display}"]
        if not self.settings.use_xvfb:
            return ["env", "DISPLAY="]
        return ["xvfb-run", "-a"]


class SingleFileArchiver:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def archive(
        self,
        url: str,
        output_file: str,
        *,
        browser_target_id: str | None = None,
        skip_navigation: bool = False,
    ) -> None:
        archive_dir = self.settings.archive_dir
        profile_dir = self.settings.browser_profile_dir
        home_dir = self._browser_home_dir(profile_dir)
        archive_dir.mkdir(parents=True, exist_ok=True)
        home_dir.mkdir(parents=True, exist_ok=True)
        profile_dir.mkdir(parents=True, exist_ok=True)
        self._remove_stale_singleton_files(profile_dir)

        output_path = archive_dir / output_file
        cache_context = (
            nullcontext()
            if self.settings.browser_remote_debugging_url
            else tempfile.TemporaryDirectory(prefix="reader-singlefile-cache-")
        )
        with cache_context as cache_dir:
            command = self._archive_command(
                url,
                output_path,
                profile_dir,
                cache_dir,
                browser_target_id=browser_target_id,
                skip_navigation=skip_navigation,
            )
            environment = {
                **os.environ,
                "HOME": str(home_dir),
                "XDG_CONFIG_HOME": str(home_dir / ".config"),
            }

            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
                start_new_session=True,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.settings.archive_timeout_seconds,
                )
            except TimeoutError as exc:
                await self._stop_process_tree(process)
                msg = "Archive timed out."
                raise RuntimeError(msg) from exc

        if process.returncode != 0:
            output = "\n".join(
                text
                for text in (
                    stdout.decode(errors="replace").strip(),
                    stderr.decode(errors="replace").strip(),
                )
                if text
            )
            msg = output[-1000:] if output else "SingleFile failed."
            raise RuntimeError(msg)

        if not output_path.exists():
            msg = "SingleFile finished without creating an archive file."
            raise RuntimeError(msg)

    def _archive_command(
        self,
        url: str,
        output_path: Path,
        profile_dir: Path,
        cache_dir: str | None,
        *,
        browser_target_id: str | None = None,
        skip_navigation: bool = False,
    ) -> list[str]:
        command = self._command_prefix() + [
            self.settings.single_file_path,
            url,
            str(output_path),
            "--browser-wait-until=networkIdle",
            "--browser-wait-until-delay=0",
            "--browser-wait-until-fallback=false",
            f"--browser-load-max-time={self.settings.browser_load_max_time_ms}",
            f"--browser-capture-max-time={self.settings.browser_capture_max_time_ms}",
            "--load-deferred-images=true",
            "--load-deferred-images-dispatch-scroll-event=true",
            "--load-deferred-images-max-idle-time=5000",
            "--remove-unused-styles=false",
            "--remove-alternative-medias=false",
            "--filename-conflict-action=overwrite",
        ]
        if self.settings.browser_remote_debugging_url:
            command.append(f"--browser-server={self.settings.browser_remote_debugging_url}")
            if browser_target_id:
                command.append(f"--browser-target-id={browser_target_id}")
                if skip_navigation:
                    command.append("--browser-skip-navigation=true")
            return command

        if browser_target_id:
            msg = "Saving an existing browser tab requires Chrome remote debugging."
            raise RuntimeError(msg)

        command.extend(
            [
                f"--browser-executable-path={self.settings.chrome_path}",
                "--browser-headless=false",
                "--browser-arg=--remote-debugging-address=127.0.0.1",
                f"--browser-arg=--user-data-dir={profile_dir}",
                f"--browser-arg=--disk-cache-dir={cache_dir}",
                "--browser-arg=--disk-cache-size=1",
                "--browser-arg=--media-cache-size=1",
                "--browser-arg=--disable-cache",
                "--browser-arg=--disable-application-cache",
                "--browser-arg=--no-sandbox",
                "--browser-arg=--disable-dev-shm-usage",
                "--browser-arg=--disable-gpu",
                "--browser-arg=--disable-crash-reporter",
                "--browser-arg=--disable-crashpad",
            ],
        )
        return command

    def _remove_stale_singleton_files(self, profile_dir: Path) -> None:
        singleton_files = list(profile_dir.glob("Singleton*"))
        if not singleton_files:
            return
        singleton_lock = profile_dir / "SingletonLock"
        if self._singleton_lock_is_active(singleton_lock):
            return
        for path in singleton_files:
            path.unlink(missing_ok=True)

    def _singleton_lock_is_active(self, singleton_lock: Path) -> bool:
        if not singleton_lock.is_symlink():
            return False
        try:
            target = os.readlink(singleton_lock)
        except OSError:
            return False
        try:
            pid = int(target.rsplit("-", maxsplit=1)[1])
        except (IndexError, ValueError):
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _browser_home_dir(self, profile_dir: Path) -> Path:
        if profile_dir.parent.name == ".config":
            return profile_dir.parent.parent
        return profile_dir.parent

    def _command_prefix(self) -> list[str]:
        if self.settings.browser_display:
            return ["env", f"DISPLAY={self.settings.browser_display}"]
        if not self.settings.use_xvfb:
            return ["env", "DISPLAY="]
        return ["xvfb-run", "-a"]

    async def _stop_process_tree(
        self,
        process: asyncio.subprocess.Process,
    ) -> None:
        self._signal_process_group(process, signal.SIGTERM)
        try:
            await asyncio.wait_for(process.communicate(), timeout=5)
            return
        except TimeoutError:
            self._signal_process_group(process, signal.SIGKILL)
        with suppress(TimeoutError, ProcessLookupError):
            await asyncio.wait_for(process.communicate(), timeout=5)

    def _signal_process_group(
        self,
        process: asyncio.subprocess.Process,
        sig: signal.Signals,
    ) -> None:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, sig)


class YtDlpDownloader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def download(self, url: str, output_stem: str) -> list[str]:
        archive_dir = self.settings.archive_dir
        archive_dir.mkdir(parents=True, exist_ok=True)
        output_template = archive_dir / f"{output_stem}%(playlist_index&.{{}}|)s.%(ext)s"
        existing_files = set(archive_dir.glob(f"{output_stem}.*"))

        command = [
            self.settings.yt_dlp_path,
            "--no-playlist",
            "--js-runtimes",
            "node",
            "--cookies-from-browser",
            f"chrome:{self.settings.browser_profile_dir}",
            "--no-progress",
            "--no-part",
            "--restrict-filenames",
            "--format",
            "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
            "--merge-output-format",
            "mp4",
            "--remux-video",
            "mp4",
            "--no-keep-video",
            "--write-description",
            "--write-info-json",
            "--write-subs",
            "--write-thumbnail",
            "--output",
            str(output_template),
            url,
        ]
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.settings.video_download_timeout_seconds,
            )
        except TimeoutError as exc:
            await self._stop_process_tree(process)
            self._remove_created_files(archive_dir, output_stem, existing_files)
            msg = "Video download timed out."
            raise RuntimeError(msg) from exc

        if process.returncode != 0:
            self._remove_created_files(archive_dir, output_stem, existing_files)
            output = "\n".join(
                text
                for text in (
                    stdout.decode(errors="replace").strip(),
                    stderr.decode(errors="replace").strip(),
                )
                if text
            )
            msg = output[-1000:] if output else "yt-dlp failed."
            if self._is_browser_login_error(msg):
                raise BrowserLoginRequiredError(self._browser_login_message(msg))
            raise RuntimeError(msg)

        created_files = [
            path
            for path in archive_dir.glob(f"{output_stem}.*")
            if (
                path not in existing_files
                and path.is_file()
                and path.suffix not in {".part", ".ytdl"}
                and not self._is_user_uploaded_file(output_stem, path)
            )
        ]
        if not created_files:
            msg = "yt-dlp finished without creating a video file."
            raise RuntimeError(msg)
        return [path.name for path in sorted(created_files, key=lambda path: path.name)]

    def _remove_created_files(
        self,
        archive_dir: Path,
        output_stem: str,
        existing_files: set[Path],
    ) -> None:
        for path in archive_dir.glob(f"{output_stem}.*"):
            if (
                path not in existing_files
                and path.is_file()
                and path.suffix != ".html"
                and not self._is_user_uploaded_file(output_stem, path)
            ):
                path.unlink(missing_ok=True)

    def _is_user_uploaded_file(self, output_stem: str, path: Path) -> bool:
        return path.name.startswith(f"{output_stem}.upload-")

    def _is_browser_login_error(self, output: str) -> bool:
        lowered = output.lower()
        authentication_statuses = (401, 403)
        if any(
            f"http error {code}" in lowered
            or f"httperror {code}" in lowered
            or f"status code {code}" in lowered
            for code in authentication_statuses
        ):
            return True

        return "[bilibili]" in lowered and any(
            marker in lowered
            for marker in (
                "http error 412",
                "httperror 412",
                "status code 412",
            )
        )

    def _browser_login_message(self, output: str) -> str:
        lines = [" ".join(line.split()) for line in output.splitlines() if line.strip()]
        selected = next(
            (
                line
                for line in reversed(lines)
                if "HTTP Error 4" in line or "HTTPError 4" in line
            ),
            lines[-1] if lines else "",
        )
        cleaned = selected.removeprefix("ERROR:").strip()
        if len(cleaned) > 140:
            cleaned = f"{cleaned[:140]}..."
        if cleaned:
            return f"浏览器登录需手动确认：{cleaned}"
        return "浏览器登录需手动确认"

    async def _stop_process_tree(
        self,
        process: asyncio.subprocess.Process,
    ) -> None:
        self._signal_process_group(process, signal.SIGTERM)
        try:
            await asyncio.wait_for(process.communicate(), timeout=5)
            return
        except TimeoutError:
            self._signal_process_group(process, signal.SIGKILL)
        with suppress(TimeoutError, ProcessLookupError):
            await asyncio.wait_for(process.communicate(), timeout=5)

    def _signal_process_group(
        self,
        process: asyncio.subprocess.Process,
        sig: signal.Signals,
    ) -> None:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, sig)
