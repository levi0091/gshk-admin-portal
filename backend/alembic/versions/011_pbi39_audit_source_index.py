"""PBI-39: index audit_log.source (Audit Log source filter)

Revision ID: 011
Revises: 010
Create Date: 2026-07-11

The Audit Log lets you split native G-FlowDesk events from the 226k rows
imported from the Viewpoint EventLog. `source` was unindexed, so filtering to
the handful of native events seq-scanned the whole table (~8s).

Composite (source, created_at DESC): the audit log is always read newest-first,
so this serves the filter and the sort in one index. Purely additive.
"""
from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_log_source_created "
        "ON public.audit_log (source, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.idx_audit_log_source_created")
