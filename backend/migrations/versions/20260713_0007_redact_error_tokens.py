"""Redact sensitive query values from stored task messages.

Revision ID: 20260713_0007
Revises: 20260713_0006
Create Date: 2026-07-13
"""

from __future__ import annotations

from alembic import op

revision = "20260713_0007"
down_revision = "20260713_0006"
branch_labels = None
depends_on = None

TOKEN_PATTERN = (
    r"([?&](access_token|auth|key|poc_token|sig|signature|token)=)[^&[:space:]]+"
)
TOKEN_REPLACEMENT = r"\1[已隐藏]"


def upgrade() -> None:
    for column in ("video_error", "page_error", "error"):
        op.execute(
            f"""
            UPDATE reader_archive_tasks
            SET {column} = regexp_replace(
                {column},
                '{TOKEN_PATTERN}',
                '{TOKEN_REPLACEMENT}',
                'gi'
            )
            WHERE {column} IS NOT NULL
            """
        )
    op.execute(
        f"""
        UPDATE reader_archive_tasks
        SET manual_actions = regexp_replace(
            manual_actions::text,
            '{TOKEN_PATTERN}',
            '{TOKEN_REPLACEMENT}',
            'gi'
        )::jsonb
        WHERE manual_actions != '[]'::jsonb
        """
    )


def downgrade() -> None:
    msg = "Downgrade is intentionally unsupported because redacted values cannot be restored."
    raise NotImplementedError(msg)
