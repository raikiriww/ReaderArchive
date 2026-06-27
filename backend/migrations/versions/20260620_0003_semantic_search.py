"""Add local semantic search chunks.

Revision ID: 20260620_0003
Revises: 20260619_0002
Create Date: 2026-06-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260620_0003"
down_revision = "20260619_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "reader_archive_semantic_chunks",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Text(),
            sa.ForeignKey("reader_archive_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("document_hash", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("embedding", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", "model_name", "chunk_index"),
    )
    op.execute(
        "ALTER TABLE reader_archive_semantic_chunks "
        "ALTER COLUMN embedding TYPE vector(384) USING embedding::vector(384)"
    )
    op.create_index(
        "ix_reader_archive_semantic_chunks_task_id",
        "reader_archive_semantic_chunks",
        ["task_id"],
    )
    op.create_index(
        "ix_reader_archive_semantic_chunks_content_hash",
        "reader_archive_semantic_chunks",
        ["content_hash"],
    )
    op.create_index(
        "ix_reader_archive_semantic_chunks_document_hash",
        "reader_archive_semantic_chunks",
        ["document_hash"],
    )
    op.create_index(
        "ix_reader_archive_semantic_chunks_model_name",
        "reader_archive_semantic_chunks",
        ["model_name"],
    )
    op.execute(
        "CREATE INDEX ix_reader_archive_semantic_chunks_embedding_hnsw "
        "ON reader_archive_semantic_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    msg = "Downgrade is intentionally unsupported because it can destroy Reader data."
    raise NotImplementedError(msg)
