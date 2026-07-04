"""PBI-38 ETL: vp_source_key idempotency indexes

Revision ID: 004
Revises: 003
Create Date: 2026-07-04

Migration 003 added `vp_source_key text` to most Viewpoint-sourced tables but
no uniqueness constraint, so `INSERT ... ON CONFLICT (vp_source_key)` has no
target to conflict on. This migration adds partial unique indexes (partial so
native G-FlowDesk rows with vp_source_key IS NULL are unaffected) for every
table Checkpoint A loads into, and adds the missing vp_source_key column to
company_secretaries (no vp_source_key existed there in 003; ETL needs one to
dedupe re-runs since secretary rows are derived from Officers).
"""
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None

TABLES_WITH_EXISTING_COLUMN = [
    "addresses", "persons", "person_identity_documents", "entities",
    "entity_officers", "beneficial_owners",
]


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.company_secretaries ADD COLUMN IF NOT EXISTS vp_source_key text;"
    )
    for t in TABLES_WITH_EXISTING_COLUMN + ["company_secretaries"]:
        op.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{t}_vp_source_key ON public.{t} (vp_source_key) "
            f"WHERE vp_source_key IS NOT NULL;"
        )


def downgrade() -> None:
    for t in TABLES_WITH_EXISTING_COLUMN + ["company_secretaries"]:
        op.execute(f"DROP INDEX IF EXISTS ux_{t}_vp_source_key;")
    op.execute(
        "ALTER TABLE public.company_secretaries DROP COLUMN IF EXISTS vp_source_key;"
    )
