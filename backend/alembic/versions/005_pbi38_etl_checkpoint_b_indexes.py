"""PBI-38 ETL Checkpoint B: vp_source_key idempotency indexes

Revision ID: 005
Revises: 004
Create Date: 2026-07-05

Migration 004 added partial-unique vp_source_key indexes for the Checkpoint A
tables so `INSERT ... ON CONFLICT (vp_source_key)` has a target. Checkpoint B
loads six more Viewpoint-sourced tables (share_classes, shareholdings,
share_transactions, share_certificates, business_names, entity_name_changes),
all of which already carry a vp_source_key column (from migration 003) but no
uniqueness constraint. This adds the same partial-unique indexes for them.
Partial (WHERE vp_source_key IS NOT NULL) so any native rows are unaffected.
"""
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None

CHECKPOINT_B_TABLES = [
    "share_classes", "shareholdings", "share_transactions",
    "share_certificates", "business_names", "entity_name_changes",
]


def upgrade() -> None:
    for t in CHECKPOINT_B_TABLES:
        op.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{t}_vp_source_key "
            f"ON public.{t} (vp_source_key) WHERE vp_source_key IS NOT NULL;"
        )


def downgrade() -> None:
    for t in CHECKPOINT_B_TABLES:
        op.execute(f"DROP INDEX IF EXISTS ux_{t}_vp_source_key;")
