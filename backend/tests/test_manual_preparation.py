from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import sleep

from fastapi.testclient import TestClient

from app.main import create_app
from tests.test_archive_api import login_as_admin, wait_for_finished
from tests.test_browser_tab_reuse import fake_chrome_server, make_settings

CODE = "page.prepare_manually"
URL = "https://example.com/interactive-article"


def create_waiting(client):
    response = client.post('/api/v1/archive-tasks', json={'url': URL, 'prepare_manually': True})
    assert response.status_code == 202
    task = wait_for_finished(client, response.json()['task_id'])
    assert task['status'] == 'manual_action_required'
    assert task['manual_actions'][0]['code'] == CODE
    return task['task_id']


def resume(client, task_id):
    return client.post(f'/api/v1/archive-tasks/{task_id}/resume-manual-action', json={'code': CODE})


def test_preparation_waits_without_work_and_does_not_block_queue(tmp_path: Path):
    with fake_chrome_server() as (chrome, browser_url):
        settings = make_settings(tmp_path, browser_url)
        settings.archive_timeout_seconds = 1
        settings.archive_dir.mkdir()
        (settings.archive_dir / 'verified.marker').write_text('ready')
        video_log = tmp_path / 'video.calls'
        Path(settings.yt_dlp_path).write_text(f'#!/bin/sh\necho call >> "{video_log}"\nexit 1\n')
        with TestClient(create_app(settings)) as client:
            login_as_admin(client)
            task_id = create_waiting(client)
            target = next(iter(chrome.tabs))
            assert chrome.tabs[target]['url'] == URL
            sleep(1.1)
            assert client.get(f'/api/v1/archive-tasks/{task_id}').json()['status'] == 'manual_action_required'
            assert not (settings.archive_dir / 'singlefile.calls').exists()
            assert not video_log.exists()
            settings.archive_timeout_seconds = 240
            other = client.post('/api/v1/archive-tasks', json={'url': 'https://example.com/normal'}).json()['task_id']
            assert wait_for_finished(client, other)['status'] == 'succeeded'
            assert target in chrome.tabs
            assert resume(client, task_id).status_code == 202
            assert wait_for_finished(client, task_id)['status'] == 'succeeded'
            calls = (settings.archive_dir / 'singlefile.calls').read_text().splitlines()
            assert len(calls) == 2
            assert f'--browser-target-id={target}' in calls[-1]
            assert '--browser-skip-navigation=true' in calls[-1]
            assert target in chrome.closed


def test_preparation_double_resume_only_saves_once(tmp_path: Path):
    with fake_chrome_server() as (_, browser_url):
        settings = make_settings(tmp_path, browser_url)
        settings.archive_dir.mkdir()
        (settings.archive_dir / 'verified.marker').write_text('ready')
        with TestClient(create_app(settings)) as client:
            login_as_admin(client)
            task_id = create_waiting(client)
            with ThreadPoolExecutor(max_workers=2) as pool:
                codes = list(pool.map(lambda _: resume(client, task_id).status_code, range(2)))
            assert sorted(codes) == [202, 409]
            assert wait_for_finished(client, task_id)['status'] == 'succeeded'
            assert len((settings.archive_dir / 'singlefile.calls').read_text().splitlines()) == 1


def test_preparation_survives_restart_and_requires_explicit_reopen(tmp_path: Path):
    with fake_chrome_server() as (chrome, browser_url):
        settings = make_settings(tmp_path, browser_url)
        with TestClient(create_app(settings)) as client:
            login_as_admin(client)
            task_id = create_waiting(client)
        original = next(iter(chrome.tabs))
        with TestClient(create_app(settings)) as client:
            login_as_admin(client)
            task = client.get(f'/api/v1/archive-tasks/{task_id}').json()
            assert task['status'] == 'manual_action_required'
            assert task['manual_actions'][0]['browser_tab_state'] == 'available'
            assert chrome.new_count == 1
        chrome.tabs.pop(original)
        with TestClient(create_app(settings)) as client:
            login_as_admin(client)
            task = client.get(f'/api/v1/archive-tasks/{task_id}').json()
            assert task['manual_actions'][0]['browser_tab_state'] == 'missing'
            assert resume(client, task_id).status_code == 409
            assert chrome.new_count == 1
            assert client.post(f'/api/v1/archive-tasks/{task_id}/manual-actions/{CODE}/open-browser').status_code == 202
            assert chrome.new_count == 2
            assert client.get(f'/api/v1/archive-tasks/{task_id}').json()['status'] == 'manual_action_required'
            unrelated = chrome.add_tab('https://example.com/unrelated')
            assert client.delete(f'/api/v1/archive-tasks/{task_id}').status_code in (200, 204)
            assert list(chrome.tabs) == [unrelated]


def test_preparation_save_failure_keeps_page_for_repeated_retries(tmp_path: Path):
    with fake_chrome_server() as (chrome, browser_url):
        settings = make_settings(tmp_path, browser_url)
        Path(settings.single_file_path).write_text('''#!/usr/bin/env python3
import pathlib,sys
p=pathlib.Path(sys.argv[2])
if not (p.parent/'allow.marker').exists():
    print('capture failed',file=sys.stderr)
    sys.exit(1)
p.write_text('<html><head><title>Expanded</title></head><body>Full content</body></html>')
''')
        with TestClient(create_app(settings)) as client:
            login_as_admin(client)
            task_id = create_waiting(client)
            target = next(iter(chrome.tabs))
            for _ in range(2):
                assert resume(client, task_id).status_code == 202
                task = wait_for_finished(client, task_id)
                assert task['status'] == 'manual_action_required'
                assert '页面已保留' in task['manual_actions'][0]['message']
                assert target in chrome.tabs
                assert chrome.new_count == 1
            (settings.archive_dir/'allow.marker').write_text('yes')
            assert resume(client, task_id).status_code == 202
            assert wait_for_finished(client, task_id)['status'] == 'succeeded'
            assert target in chrome.closed


def test_preparation_browser_open_failure_can_be_retried(tmp_path: Path):
    with fake_chrome_server() as (chrome, browser_url):
        app = create_app(make_settings(tmp_path, browser_url))
        with TestClient(app) as client:
            login_as_admin(client)
            opener = app.state.archive_task_service.browser_opener
            real_open = opener.open
            async def fail_open(url):
                raise RuntimeError('Browser unavailable')
            opener.open = fail_open
            task_id = create_waiting(client)
            assert not chrome.tabs
            opener.open = real_open
            assert client.post(f'/api/v1/archive-tasks/{task_id}/manual-actions/{CODE}/open-browser').status_code == 202
            assert len(chrome.tabs) == 1


def test_preparation_rejects_browser_without_tab_support(tmp_path: Path):
    settings = make_settings(tmp_path, '')
    settings.browser_remote_debugging_url = None
    with TestClient(create_app(settings)) as client:
        login_as_admin(client)
        response = client.post('/api/v1/archive-tasks', json={'url': URL, 'prepare_manually': True})
        assert response.status_code == 409
        assert '内置浏览器' in response.json()['detail']
