"""PBI-38 ETL Checkpoint C: vp_source_key idempotency keys

Revision ID: 006
Revises: 005
Create Date: 2026-07-05

Checkpoint C loads the last seven Viewpoint-sourced tables. Five of them
(form_filings, contacts, charges, address_assignments, tasks) already carry a
vp_source_key column from migration 003 and only need the partial-unique index.
audit_log and audit_form_filings never had the column — this migration adds it
(a purely additive DDL change; audit_log's insert-only rule concerns row DML,
not schema) plus the same partial-unique indexes.

audit_log's index backs `INSERT ... ON CONFLICT (vp_source_key) DO NOTHING` —
the insert-only-compatible idempotency used for imported Viewpoint history
(re-runs skip already-imported rows instead of updating them).
"""
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None

TABLES_NEEDING_COLUMN = ["audit_log", "audit_form_filings"]
CHECKPOINT_C_TABLES = [
    "audit_log", "audit_form_filings", "form_filings",
    "contacts", "charges", "address_assignments", "tasks",
]


def upgrade() -> None:
    for t in TABLES_NEEDING_COLUMN:
        op.execute(f"ALTER TABLE public.{t} ADD COLUMN IF NOT EXISTS vp_source_key text;")
    for t in CHECKPOINT_C_TABLES:
        op.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{t}_vp_source_key "
            f"ON public.{t} (vp_source_key) WHERE vp_source_key IS NOT NULL;"
        )


def downgrade() -> None:
    for t in CHECKPOINT_C_TABLES:
        op.execute(f"DROP INDEX IF EXISTS ux_{t}_vp_source_key;")
    for t in TABLES_NEEDING_COLUMN:
        op.execute(f"ALTER TABLE public.{t} DROP COLUMN IF EXISTS vp_source_key;")
