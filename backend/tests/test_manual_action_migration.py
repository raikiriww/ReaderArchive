from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.core.db import get_engine, run_migrations
from tests.test_archive_api import make_database_url


def test_browser_login_tasks_are_migrated_to_manual_actions() -> None:
    database_url = make_database_url()
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260629_0005")

    with get_engine(database_url).begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO reader_archive_tasks (
                    id, url, status, video_error, created_at, current_step,
                    is_read, source_type, updated_at
                ) VALUES (
                    'legacy-login-task', 'https://example.com/video',
                    'browser_login_required',
                    '请先登录：https://example.com/?poc_token=secret-value&target=video',
                    NOW(), 'browser_login',
                    FALSE, 'manual', NOW()
                )
                """
            )
        )

    run_migrations(database_url)

    with get_engine(database_url).connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT status, current_step, manual_actions
                FROM reader_archive_tasks
                WHERE id = 'legacy-login-task'
                """
            )
        ).mappings().one()

    assert row["status"] == "manual_action_required"
    assert row["current_step"] == "manual_action"
    assert row["manual_actions"] == [
        {
            "code": "video_browser_login",
            "kind": "login",
            "target": "video",
            "message": "请先登录：https://example.com/?poc_token=[已隐藏]&target=video",
            "resume": "continue_video",
            "rule_id": "video.browser_login",
        }
    ]
    with get_engine(database_url).connect() as connection:
        video_error = connection.execute(
            text(
                "SELECT video_error FROM reader_archive_tasks "
                "WHERE id = 'legacy-login-task'"
            )
        ).scalar_one()
    assert "secret-value" not in video_error
    assert "poc_token=[已隐藏]" in video_error
    with get_engine(database_url).connect() as connection:
        binding = connection.execute(
            text(
                "SELECT target, browser_target_id, state "
                "FROM reader_archive_browser_tabs "
                "WHERE task_id = 'legacy-login-task'"
            )
        ).mappings().one()
    assert binding == {
        "target": "video",
        "browser_target_id": None,
        "state": "missing",
    }
