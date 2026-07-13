"""Track browser tabs used by manual archive actions.

Revision ID: 20260713_0008
Revises: 20260713_0007
Create Date: 2026-07-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260713_0008"
down_revision = "20260713_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reader_archive_browser_tabs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("target", sa.String(), nullable=False),
        sa.Column("browser_target_id", sa.String(), nullable=True),
        sa.Column("original_url", sa.String(), nullable=False),
        sa.Column("last_url", sa.String(), nullable=True),
        sa.Column("owned_by_reader", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("state", sa.String(), nullable=False, server_default="available"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["reader_archive_tasks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "target"),
    )
    op.create_index(
        "ix_reader_archive_browser_tabs_task_id",
        "reader_archive_browser_tabs",
        ["task_id"],
    )
    op.create_index(
        "ix_reader_archive_browser_tabs_target",
        "reader_archive_browser_tabs",
        ["target"],
    )
    op.create_index(
        "ix_reader_archive_browser_tabs_browser_target_id",
        "reader_archive_browser_tabs",
        ["browser_target_id"],
    )
    op.create_index(
        "ix_reader_archive_browser_tabs_state",
        "reader_archive_browser_tabs",
        ["state"],
    )

    # Older waiting tasks could not retain their tabs. Mark those bindings as
    # missing so the UI asks for an explicit reopen instead of retrying a URL.
    op.execute(
        """
        INSERT INTO reader_archive_browser_tabs (
            id,
            task_id,
            target,
            browser_target_id,
            original_url,
            last_url,
            owned_by_reader,
            state,
            created_at,
            updated_at
        )
        SELECT
            md5(task.id || ':' || ((action.value::jsonb)->>'target')),
            task.id,
            (action.value::jsonb)->>'target',
            NULL,
            task.url,
            NULL,
            FALSE,
            'missing',
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM reader_archive_tasks AS task
        CROSS JOIN LATERAL jsonb_array_elements(task.manual_actions) AS action(value)
        WHERE task.status = 'manual_action_required'
          AND (action.value::jsonb)->>'target' IN ('page', 'video')
        ON CONFLICT (task_id, target) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reader_archive_browser_tabs_state",
        table_name="reader_archive_browser_tabs",
    )
    op.drop_index(
        "ix_reader_archive_browser_tabs_browser_target_id",
        table_name="reader_archive_browser_tabs",
    )
    op.drop_index(
        "ix_reader_archive_browser_tabs_target",
        table_name="reader_archive_browser_tabs",
    )
    op.drop_index(
        "ix_reader_archive_browser_tabs_task_id",
        table_name="reader_archive_browser_tabs",
    )
    op.drop_table("reader_archive_browser_tabs")
