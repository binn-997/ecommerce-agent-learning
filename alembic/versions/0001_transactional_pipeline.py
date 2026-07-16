"""transactional pipeline tables

Revision ID: 0001
Revises:
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    init_sql = Path(__file__).resolve().parents[2] / "sql" / "init.sql"
    op.execute(init_sql.read_text(encoding="utf-8"))


def downgrade() -> None:
    for table in (
        "audit_events",
        "human_reviews",
        "advertising_metrics",
        "sync_cursors",
        "raw_imports",
        "alerts",
        "daily_metrics",
        "orders",
        "sku_master",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
