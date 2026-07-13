"""Unify browser login and verification as manual actions.

Revision ID: 20260713_0006
Revises: 20260629_0005
Create Date: 2026-07-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260713_0006"
down_revision = "20260629_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("reader_archive_tasks")}

    if "manual_actions" not in columns:
        op.add_column(
            "reader_archive_tasks",
            sa.Column(
                "manual_actions",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
        )

    op.execute(
        """
        UPDATE reader_archive_tasks
        SET status = 'manual_action_required',
            current_step = 'manual_action',
            manual_actions = jsonb_build_array(
                jsonb_build_object(
                    'code', 'video_browser_login',
                    'kind', 'login',
                    'target', 'video',
                    'message', COALESCE(video_error, '请在浏览器完成登录后继续下载视频。'),
                    'resume', 'continue_video',
                    'rule_id', 'video.browser_login'
                )
            ),
            updated_at = NOW()
        WHERE status = 'browser_login_required'
        """
    )


def downgrade() -> None:
    msg = "Downgrade is intentionally unsupported because it can destroy Reader data."
    raise NotImplementedError(msg)
