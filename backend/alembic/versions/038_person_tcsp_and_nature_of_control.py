"""A natural person's TCSP licence, and a beneficial owner's nature of control.

Two columns, both because a screen was asking for a fact the schema had nowhere
to put.

`persons.tcsp_licence_no` / `persons.tcsp_exemption_reason`
-----------------------------------------------------------
The Company Secretary tile printed "TCSP Licence No." off
`corporate_entity.tcsp_licence_no`, which is null for every secretary who is a
NATURAL PERSON -- so the row rendered an em dash and there was no field anywhere
in the portal that would fill it. A licensed individual is not exotic: the AMLO
licenses individuals as trust or company service providers exactly as it
licenses bodies corporate, and GSHK's own staff secretaries are people.

Mirroring `entities` rather than inventing a shape: both columns already exist
on `entities` with these names, the Corporate Party tile already reads them, and
one name for one fact means the secretary tile can fall back from the corporate
party to the person without a translation layer.

`beneficial_owners.nature_of_control`
-------------------------------------
Levi 2026-09-04. The Significant Controllers Register asks *how* control is
held, and the Companies Ordinance s.653D gives the two conditions this portal
actually needs to record: a holding over 25%, or the right to exercise (or the
actual exercise of) significant influence or control. `percent_interest` and
`percent_vote` were standing in for that and could not express the second one at
all -- a controller with no shares and a veto is significant, and the two
numeric columns render that as 0/0, which reads as "not a controller".

THE TWO NUMERIC COLUMNS ARE KEPT, not dropped. They are off the screen (see
CompanyProfilePage / LinkPartyModal) but they hold ETL'd Viewpoint values on
real rows, and neither CR form reads either of them -- `contract.py` maps no
NAR1 or NNC1 field to `beneficial_owners.*`, so nothing that is filed changes.
Dropping data to tidy a form is not reversible; hiding it is.

No CHECK constraint on the value. The vocabulary is served from
`services/cr_forms/control_nature.py` and enforced on write in
`routers/companies.py`, the same way CR's own vocabularies are: a constraint
would make a wording revision a migration, and 34 legacy rows already carry
free text that a constraint would refuse on an unrelated edit.

Revision ID: 038
Revises: 037
"""
from alembic import op
import sqlalchemy as sa

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


#: Without these the audit trail renders the raw column name. There is no FK
#: from audit rows to this table, so an unlabelled field fails silently -- the
#: same trap migration 022 exists to close.
FIELD_LABELS = {
    "tcsp_licence_no": "TCSP Licence No.",
    "tcsp_exemption_reason": "TCSP Exemption Reason",
    "nature_of_control": "Nature of Control",
}


def upgrade() -> None:
    op.add_column("persons", sa.Column("tcsp_licence_no", sa.Text, nullable=True))
    op.add_column("persons", sa.Column("tcsp_exemption_reason", sa.Text, nullable=True))
    op.add_column("beneficial_owners",
                  sa.Column("nature_of_control", sa.Text, nullable=True))

    # ON CONFLICT, not bulk_insert: `field` is the primary key and the label is
    # per FIELD NAME rather than per table, so a future migration labelling
    # `entities.tcsp_licence_no` (same name, carried since migration 007) would
    # otherwise turn this into a duplicate-key failure on a fresh database.
    # CAST(...) rather than PostgreSQL's `::text[]`: SQLAlchemy's `text()`
    # scans for `:name` bind parameters and reads `:fields::text[]` as a
    # parameter called `fields:`, which fails at compile time with "doesn't
    # define a bound parameter named 'fields'".
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
    op.drop_column("beneficial_owners", "nature_of_control")
    op.drop_column("persons", "tcsp_exemption_reason")
    op.drop_column("persons", "tcsp_licence_no")
