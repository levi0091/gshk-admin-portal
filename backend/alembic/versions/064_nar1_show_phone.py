"""NAR1 s8: whether the company's phone goes on the annual return
(`entities.nar1_show_phone`).

Revision ID: 064
Revises: 063
Create Date: 2026-11-21

GSHK, 2026-11-21, on the draft NAR1: the Hong Kong Contact Telephone Number
should "default to 'Not use', but allow the option to choose whether it shows
on the NAR1 form". CR marks `telNo` Mandatory = N, and the number on the
profile is often the one GSHK calls rather than the one the client wants on a
public register, so printing it is a choice per company, off until somebody
makes it.

NOT NULL DEFAULT false, so every existing company stays exactly as it files
today (no phone), and nobody has to backfill anything.

A field label is seeded because a PATCH is audited as CASE_FIELD_UPDATED with
the field name, and an unlabelled field renders as its raw column name. No new
audit action code.

Apply to DEV, then PROD, BEFORE the code deploys: the profile reads and writes
the column. REVERSIBLE: the downgrade drops the column and the label.
"""
import sqlalchemy as sa
from alembic import op

revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None

FIELD_LABELS = {
    "nar1_show_phone": "Show phone on NAR1",
}


def upgrade() -> None:
    op.execute("ALTER TABLE public.entities "
               "ADD COLUMN IF NOT EXISTS nar1_show_phone boolean NOT NULL DEFAULT false")
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
    op.execute("ALTER TABLE public.entities DROP COLUMN IF EXISTS nar1_show_phone")
