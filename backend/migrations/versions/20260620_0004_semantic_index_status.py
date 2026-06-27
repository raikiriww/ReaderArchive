"""Add semantic index status table.

Revision ID: 20260620_0004
Revises: 20260620_0003
Create Date: 2026-06-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260620_0004"
down_revision = "20260620_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reader_archive_semantic_indexes",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Text(),
            sa.ForeignKey("reader_archive_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("text_version", sa.Text(), nullable=False),
        sa.Column("document_hash", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", "model_name", "text_version"),
    )
    op.create_index(
        "ix_reader_archive_semantic_indexes_task_id",
        "reader_archive_semantic_indexes",
        ["task_id"],
    )
    op.create_index(
        "ix_reader_archive_semantic_indexes_model_name",
        "reader_archive_semantic_indexes",
        ["model_name"],
    )
    op.create_index(
        "ix_reader_archive_semantic_indexes_text_version",
        "reader_archive_semantic_indexes",
        ["text_version"],
    )
    op.create_index(
        "ix_reader_archive_semantic_indexes_document_hash",
        "reader_archive_semantic_indexes",
        ["document_hash"],
    )
    op.create_index(
        "ix_reader_archive_semantic_indexes_status",
        "reader_archive_semantic_indexes",
        ["status"],
    )


def downgrade() -> None:
    msg = "Downgrade is intentionally unsupported because it can destroy Reader data."
    raise NotImplementedError(msg)
