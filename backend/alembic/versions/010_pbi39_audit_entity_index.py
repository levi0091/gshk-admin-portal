"""PBI-39 Block 3: index audit_log.entity_id (person/entity-scoped audit reads)

Revision ID: 010
Revises: 009
Create Date: 2026-07-11

audit_log was indexed on case_id, created_at and user_id only. Entity-scoped
events resolve through case_id, but PERSON-scoped events (PERSON_CREATED,
PERSON_FIELD_UPDATED) carry case_id = NULL and entity_id = <person id> — there
is no case to hang them off. Reading a person's audit trail therefore filtered
an unindexed TEXT column and seq-scanned the whole table (226k rows and growing
after the PBI-38 EventLog import), which hits the Postgres statement timeout.

Composite (entity_id, created_at DESC) because every audit read is "this
record's events, newest first" — it serves the filter and the sort together.
Purely additive: an index, no data or schema change.
"""
from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_log_entity "
        "ON public.audit_log (entity_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.idx_audit_log_entity")
