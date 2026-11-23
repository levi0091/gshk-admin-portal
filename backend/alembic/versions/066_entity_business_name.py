"""NAR1 s2: the company's Business Name, entered by GSHK (`entities.business_name`).

Revision ID: 066
Revises: 065
Create Date: 2026-11-23

GSHK, 2026-11-23, on the draft NAR1: "Please do not default it. This is an
optional column that we only fill in in the NAR1 form when the company has a
business name ... the business name does not have to be the same as the
company name."

Box 2 used to be filled from `business_names`, Viewpoint's Business
Registration record. On DEV 4,878 of its 5,028 rows are simply the company's
own name -- every Hong Kong company is BR-registered under it -- and many of
the rest are names the company used to have. Neither is a business name in
CR's sense, so the draft printed one for nearly every company. Viewpoint holds
no field that means what box 2 means, so this column starts EMPTY for every
company and is filled only by somebody who knows the company has one. It is
deliberately not backfilled from `business_names`.

Nullable text, no length CHECK: CR's 150 is enforced by the form contract's
highlighting and by the mapper omitting anything longer, the same way every
other optional CR field is handled. Empty prints "N/A", as CR's own filed
return does.

A field label is seeded for the CASE_FIELD_UPDATED trail. No new action code.

Apply to DEV, then PROD, BEFORE the code deploys: the profile reads and writes
the column. REVERSIBLE: the downgrade drops the column and the label.
"""
import sqlalchemy as sa
from alembic import op

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None

FIELD_LABELS = {
    "business_name": "Business Name",
}


def upgrade() -> None:
    op.execute("ALTER TABLE public.entities "
               "ADD COLUMN IF NOT EXISTS business_name text")
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
    op.execute("ALTER TABLE public.entities DROP COLUMN IF EXISTS business_name")
