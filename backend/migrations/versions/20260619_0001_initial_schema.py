"""Create Reader PostgreSQL schema.

Revision ID: 20260619_0001
Revises:
Create Date: 2026-06-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260619_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.create_table(
        "reader_users",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("username", postgresql.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_reader_users_username", "reader_users", ["username"])
    op.create_index("ix_reader_users_role", "reader_users", ["role"])

    op.create_table(
        "reader_login_tokens",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("reader_users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_reader_login_tokens_token_hash", "reader_login_tokens", ["token_hash"])
    op.create_index("ix_reader_login_tokens_user_id", "reader_login_tokens", ["user_id"])

    op.create_table(
        "reader_archive_tasks",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("normalized_url", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("output_file", sa.Text()),
        sa.Column("video_file", sa.Text()),
        sa.Column("video_error", sa.Text()),
        sa.Column("page_error", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("current_step", sa.Text()),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_feed_id", sa.Text()),
        sa.Column("source_title", sa.Text()),
        sa.Column("entry_title", sa.Text()),
        sa.Column("video_title", sa.Text()),
        sa.Column("custom_title", sa.Text()),
        sa.Column("created_by_id", sa.Text(), sa.ForeignKey("reader_users.id")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_reader_archive_tasks_normalized_url", "reader_archive_tasks", ["normalized_url"])
    op.create_index("ix_reader_archive_tasks_status", "reader_archive_tasks", ["status"])
    op.create_index("ix_reader_archive_tasks_created_at", "reader_archive_tasks", ["created_at"])
    op.create_index("ix_reader_archive_tasks_is_read", "reader_archive_tasks", ["is_read"])
    op.create_index("ix_reader_archive_tasks_source_type", "reader_archive_tasks", ["source_type"])
    op.create_index("ix_reader_archive_tasks_source_feed_id", "reader_archive_tasks", ["source_feed_id"])

    op.create_table(
        "reader_archive_files",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("task_id", sa.Text(), sa.ForeignKey("reader_archive_tasks.id"), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", "file_name"),
    )
    op.create_index("ix_reader_archive_files_task_id", "reader_archive_files", ["task_id"])
    op.create_index("ix_reader_archive_files_file_name", "reader_archive_files", ["file_name"])

    op.create_table(
        "reader_tags",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_reader_tags_name", "reader_tags", ["name"])

    op.create_table(
        "reader_archive_task_tags",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("task_id", sa.Text(), sa.ForeignKey("reader_archive_tasks.id"), nullable=False),
        sa.Column("tag_id", sa.Text(), sa.ForeignKey("reader_tags.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", "tag_id"),
    )
    op.create_index("ix_reader_archive_task_tags_task_id", "reader_archive_task_tags", ["task_id"])
    op.create_index("ix_reader_archive_task_tags_tag_id", "reader_archive_task_tags", ["tag_id"])

    op.create_table(
        "reader_rss_sources",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.UniqueConstraint("url"),
    )
    op.create_index("ix_reader_rss_sources_url", "reader_rss_sources", ["url"])
    op.create_index("ix_reader_rss_sources_is_enabled", "reader_rss_sources", ["is_enabled"])

    op.create_table(
        "reader_rss_entries",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("source_id", sa.Text(), sa.ForeignKey("reader_rss_sources.id"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("published_at", sa.Text()),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archive_task_id", sa.Text(), sa.ForeignKey("reader_archive_tasks.id"), nullable=False),
        sa.UniqueConstraint("normalized_url"),
    )
    op.create_index("ix_reader_rss_entries_source_id", "reader_rss_entries", ["source_id"])
    op.create_index("ix_reader_rss_entries_normalized_url", "reader_rss_entries", ["normalized_url"])
    op.create_index("ix_reader_rss_entries_archive_task_id", "reader_rss_entries", ["archive_task_id"])

    op.create_table(
        "reader_app_settings",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("key"),
    )
    op.create_index("ix_reader_app_settings_key", "reader_app_settings", ["key"])


def downgrade() -> None:
    msg = "Downgrade is intentionally unsupported because it can destroy Reader data."
    raise NotImplementedError(msg)
