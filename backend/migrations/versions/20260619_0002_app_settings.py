"""No-op placeholder for existing migration history.

Revision ID: 20260619_0002
Revises: 20260619_0001
Create Date: 2026-06-19
"""

from __future__ import annotations

revision = "20260619_0002"
down_revision = "20260619_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    return


def downgrade() -> None:
    msg = "Downgrade is intentionally unsupported because it can destroy Reader data."
    raise NotImplementedError(msg)
