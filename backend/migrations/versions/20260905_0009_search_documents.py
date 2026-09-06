"""Keep searchable original text independent from semantic embeddings."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260905_0009"
down_revision = "20260713_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reader_archive_search_documents",
        sa.Column("task_id", sa.String(), primary_key=True),
        sa.Column("file_name", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("document_hash", sa.String(), nullable=False),
        sa.Column("text_version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["reader_archive_tasks.id"], ondelete="CASCADE"),
    )
    # Preserve existing literal coverage while complete documents are extracted in
    # the background. This never removes or rewrites the previous vector index.
    op.execute("""
        INSERT INTO reader_archive_search_documents
            (task_id, file_name, content, document_hash, text_version, status, updated_at)
        SELECT task.id, task.output_file, legacy.content, md5(legacy.content),
               'legacy-v1', 'ready', CURRENT_TIMESTAMP
        FROM reader_archive_tasks task
        JOIN (
            SELECT DISTINCT ON (task_id) task_id, content
            FROM (
                SELECT task_id, model_name,
                    string_agg(content, E'\\n\\n' ORDER BY chunk_index) AS content,
                    max(updated_at) AS updated_at
                FROM reader_archive_semantic_chunks GROUP BY task_id, model_name
            ) versions ORDER BY task_id, updated_at DESC, model_name
        ) legacy ON legacy.task_id = task.id
        WHERE task.output_file IS NOT NULL AND task.page_error IS NULL
        ON CONFLICT (task_id) DO NOTHING
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrade is unsupported because it can destroy Reader data.")
