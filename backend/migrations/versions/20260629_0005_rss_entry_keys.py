"""Track RSS entries by feed-specific entry keys.

Revision ID: 20260629_0005
Revises: 20260620_0004
Create Date: 2026-06-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260629_0005"
down_revision = "20260620_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("reader_rss_entries")}
    unique_constraints = inspector.get_unique_constraints("reader_rss_entries")
    indexes = {index["name"] for index in inspector.get_indexes("reader_rss_entries")}

    if "entry_key" not in columns:
        op.add_column("reader_rss_entries", sa.Column("entry_key", sa.Text(), nullable=True))
        op.execute(
            """
            UPDATE reader_rss_entries
            SET entry_key = CASE
                WHEN published_at IS NOT NULL AND published_at != ''
                    THEN 'published:' || normalized_url || '|' || published_at
                WHEN title IS NOT NULL AND title != ''
                    THEN 'title:' || normalized_url || '|' || title
                ELSE 'url:' || normalized_url
            END
            """
        )
        op.alter_column("reader_rss_entries", "entry_key", nullable=False)

    for constraint in unique_constraints:
        if constraint.get("column_names") == ["normalized_url"]:
            op.drop_constraint(
                constraint["name"],
                "reader_rss_entries",
                type_="unique",
            )

    if "ix_reader_rss_entries_entry_key" not in indexes:
        op.create_index("ix_reader_rss_entries_entry_key", "reader_rss_entries", ["entry_key"])

    has_source_entry_constraint = any(
        constraint.get("column_names") == ["source_id", "entry_key"]
        for constraint in unique_constraints
    )
    if not has_source_entry_constraint:
        op.create_unique_constraint(
            "uq_reader_rss_entries_source_entry_key",
            "reader_rss_entries",
            ["source_id", "entry_key"],
        )


def downgrade() -> None:
    msg = "Downgrade is intentionally unsupported because it can destroy Reader data."
    raise NotImplementedError(msg)
