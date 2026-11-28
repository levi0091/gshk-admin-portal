"""Which of a person's addresses the forms print — `persons.address_on_forms`.

Revision ID: 067
Revises: 066
Create Date: 2026-11-28

Levi 2026-11-28: "there should be an option in Natural Person profile for user
to select whether to use correspondence address or residential address. By
default this flag should be set to correspondence address. if user choose to
change it to residential address then only the NAR1, ND2A and ND2B will include
the residential address. Also if the profile has correspondence address
selected but there is actually no correspondence address then the NAR1, ND2B,
ND2A will use residential address". Clients often do not want their home
address on a public register, so correspondence is the default.

'correspondence'  each company files the correspondence address that person's
                  appointment THERE links to (`entity_officers.
                  correspondence_address_id`), and the residential address only
                  where there is none. This is what the code did already
                  (2026-11-26) for the officer boxes, and now also for the
                  person's Schedule 1 (register of members) line.
'residential'     every company files the residential address in those boxes,
                  whatever correspondence address is linked.

NOT NULL DEFAULT 'correspondence', so every existing row reads as today's
behaviour with no backfill. Natural persons only: a body corporate has one
address. A CHECK rather than an enum type, as `person_addresses.kind` (053).

The audit label is seeded for the reason 058 seeded its own; the flag is
written by PATCH /persons/{id} and audited as a person field edit, so no new
audit action code is introduced.

Apply to DEV, then PROD, BEFORE the code deploys: the new code reads the column.
REVERSIBLE: the downgrade drops the column and the label.
"""
import sqlalchemy as sa
from alembic import op

revision = "067"
down_revision = "066"
branch_labels = None
depends_on = None

FIELD_LABELS = {
    "address_on_forms": "Address shown on forms",
}


def upgrade() -> None:
    op.execute("ALTER TABLE public.persons "
               "ADD COLUMN IF NOT EXISTS address_on_forms text "
               "NOT NULL DEFAULT 'correspondence' "
               "CONSTRAINT ck_persons_address_on_forms "
               "CHECK (address_on_forms IN ('correspondence', 'residential'))")
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
    op.execute("ALTER TABLE public.persons DROP COLUMN IF EXISTS address_on_forms")
