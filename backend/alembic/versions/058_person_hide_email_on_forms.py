"""A person's email can be kept off the forms — `persons.hide_email_on_forms`.

Revision ID: 058
Revises: 057
Create Date: 2026-10-29

Levi 2026-10-29 (ND2A / ND2B change requests, request 1): a checkbox on a
natural person's profile which, when ticked, keeps that person's email off every
form we file or print -- NAR1, ND2A and ND2B. The email stays on the profile and
is still used to SEND mail (verification, receipts); the flag is about forms
only, and CR marks every one of those email boxes Mandatory = N, so leaving it
out cannot cause a refusal.

NOT NULL DEFAULT false, so every existing row reads as "print it" with no
backfill and the old code keeps working untouched between the migration and the
deploy. Natural persons only: a body corporate's email is the company's own.

The audit label is seeded here for the reason 041 seeded its two: there is no FK
from audit rows to `audit_field_labels`, so an unlabelled field renders in the
trail as the raw column name and nothing fails. The flag is written by
PATCH /persons/{id} and audited as a person field edit like any other; no new
audit action code is introduced.

Apply to DEV, then PROD, BEFORE the code deploys: the new code PATCHes the column.
REVERSIBLE: the downgrade drops the column and the label.
"""
import sqlalchemy as sa
from alembic import op

revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None

FIELD_LABELS = {
    "hide_email_on_forms": "Email hidden on forms",
}


def upgrade() -> None:
    op.execute("ALTER TABLE public.persons "
               "ADD COLUMN IF NOT EXISTS hide_email_on_forms boolean "
               "NOT NULL DEFAULT false")
    # Same statement as 041's: ON CONFLICT because the key is the bare field
    # name, CAST(...) because text() reads `:fields::text[]` as a parameter
    # called `fields:`.
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
    op.execute("ALTER TABLE public.persons DROP COLUMN IF EXISTS hide_email_on_forms")
