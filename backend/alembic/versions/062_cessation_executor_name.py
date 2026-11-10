"""A deceased director's cessation can name the administrator / executor —
`officer_change_entries.executor_name`.

Revision ID: 062
Revises: 061
Create Date: 2026-11-10

Jacqueline Koh, UAT 2026-11-10 (PBI-59, TC-112), on the written resolution's
line for a director who has died ("Name: / For and on behalf of the estate of
<name> (deceased) / Administrator / Executor"): "can we also add the name via
the system while preparing the documents?" The portal knew nobody in that role,
so "Name:" printed blank. This column holds the name typed on the cessation,
and the resolution prints it after "Name:".

OPTIONAL and FREE TEXT: the administrator or executor is often not a person the
portal has on record, and is never asked to e-sign (the line still carries no
person id). Only a cessation whose reason is Deceased keeps a value; the code
clears it otherwise. Nullable with no default, so existing rows need no backfill
and the old code is untouched between the migration and the deploy. Capped at
120 characters by a CHECK, the same limit the code applies, so the column cannot
hold what the resolution's two-column block was never laid out for.

The audit label is seeded for the reason 058 seeded its own: an entry edit is
audited as OFFICER_CHANGE_UPDATED with the changed columns, and an unlabelled
column renders in the trail as its raw name. No new audit action code.

Apply to DEV, then PROD, BEFORE the code deploys: the new code writes the column.
REVERSIBLE: the downgrade drops the column and the label.
"""
import sqlalchemy as sa
from alembic import op

revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None

MAX_LENGTH = 120

FIELD_LABELS = {
    "executor_name": "Administrator / executor",
}


def upgrade() -> None:
    op.execute("ALTER TABLE public.officer_change_entries "
               "ADD COLUMN IF NOT EXISTS executor_name text")
    op.execute("ALTER TABLE public.officer_change_entries "
               "DROP CONSTRAINT IF EXISTS officer_change_entries_executor_name_len")
    op.execute("ALTER TABLE public.officer_change_entries "
               "ADD CONSTRAINT officer_change_entries_executor_name_len "
               f"CHECK (executor_name IS NULL OR char_length(executor_name) <= {MAX_LENGTH})")
    # Same statement as 058's.
    op.execute(
        sa.text(
            "INSERT INTO audit_field_labels (field, label) "
            "SELECT * FROM unnest(CAST(:fields AS text[]), CAST(:labels AS text[])) "
            "ON CONFLICT (field) DO NOTHING"
        ).bindparams(
            sa.bindparam("fields", list(FIELD_LABELS), type_=sa.ARRAY(sa.Text)),
            sa.bindparam("labels", list(FIELD_LABELS.values()), type_=sa.ARRAY(sa.Text)),
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM audit_field_labels WHERE field = ANY(:fields)")
        .bindparams(sa.bindparam("fields", list(FIELD_LABELS), type_=sa.ARRAY(sa.Text)))
    )
    op.execute("ALTER TABLE public.officer_change_entries "
               "DROP CONSTRAINT IF EXISTS officer_change_entries_executor_name_len")
    op.execute("ALTER TABLE public.officer_change_entries "
               "DROP COLUMN IF EXISTS executor_name")
