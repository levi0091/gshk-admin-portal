"""Registry field fidelity: the columns NAR1 and NNC1 need and the profiles lacked.

Every column here is one CR asks for on a form. What each is worth naming:

`share_classes.issued_amount` is the one that was a defect rather than a gap.
CR's section 11 keeps three separate columns -- Total Number (a COUNT of
shares), Total Amount (what they are WORTH) and Total Amount Paid Up -- and
`share_classes` held the count and the paid-up figure with nowhere for the
value. Filling the form therefore meant assuming count == value, which is true
for the common $1 ordinary share and silently wrong otherwise. Viewpoint had
it all along as `ShareCapital.StatedCap`, populated on 5,715 of 5,736 rows and
DIFFERING FROM the count on 60 of them; `etl/extract/checkpoint_b.py` simply
never selected it.

`entity_officers.correspondence_address_id` separates the address a director
gives the company from where they live. It sits on the APPOINTMENT, not the
person, because that is how the law works -- a director may give company A and
company B different addresses. Viewpoint's most populated address type is
exactly this (`RC`, 13,864 assignments), unimported until now while the NAR1
mapper filed the residential address into CR's correspondence slot.

`entity_record_locations` is NAR1 s16 -- where each statutory register is kept.
One row per register rather than ~15 columns on `entities`, because CR's list
grows and a table absorbs that without a migration.

`business_nature_code` ships EMPTY and stays that way until someone types it:
Viewpoint's `BusNames.BusNature` is null on all 5,028 rows in all four of its
business-name tables. `business_nature_desc` is denormalised from the code (CR
derives it the same way) so the generated facsimile can print it.

NOT here, deliberately -- CR wants them, nothing has them, and PRD D7 says
record rather than build: `remainUnpaid`, `particluarOfRights`, company-level
email, alternate-director fields. `hkidChkDtg` is absent for a different
reason: the check digit is already inside the stored id_number ("A1234567(8)")
and is parsed out, which is also what makes it verifiable.

Revision ID: 028
Revises: 027
"""
from alembic import op
import sqlalchemy as sa

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


#: Labels for the audit trail. There is no FK from audit rows to this table, so
#: an unlabelled field does not fail -- it renders as a raw column name in the
#: trail, which is the same silent failure migration 022 exists to fix.
FIELD_LABELS = {
    "business_nature_code": "Business Nature Code",
    "business_nature_desc": "Business Nature Description",
    "mortgages_total": "Mortgages and Charges",
    "issued_amount": "Total Amount",
    "alias_en": "Alias (English)",
    "alias_zh": "Alias (Chinese)",
    "former_name_zh": "Previous Names (Chinese)",
    "correspondence_address_id": "Correspondence Address",
}


def upgrade() -> None:
    # --- The company -----------------------------------------------------
    op.add_column("entities", sa.Column("business_nature_code", sa.Text, nullable=True))
    op.add_column("entities", sa.Column("business_nature_desc", sa.Text, nullable=True))
    # Text, not numeric: CR accepts "Nil", and the overwhelming majority of
    # GSHK's book files exactly that. A numeric column would force a 0 that
    # reads as "none registered" rather than "nothing to declare".
    op.add_column("entities", sa.Column("mortgages_total", sa.Text, nullable=True))

    # --- Share capital ---------------------------------------------------
    op.add_column(
        "share_classes",
        sa.Column("issued_amount", sa.Numeric(20, 4), nullable=True),
    )

    # --- People ----------------------------------------------------------
    # `former_name` already holds the English one; this is its Chinese pair.
    op.add_column("persons", sa.Column("former_name_zh", sa.Text, nullable=True))
    op.add_column("persons", sa.Column("alias_en", sa.Text, nullable=True))
    op.add_column("persons", sa.Column("alias_zh", sa.Text, nullable=True))

    # --- Appointments ----------------------------------------------------
    op.add_column(
        "entity_officers",
        sa.Column("correspondence_address_id", sa.Uuid, nullable=True),
    )
    op.create_foreign_key(
        "entity_officers_correspondence_address_fkey",
        "entity_officers", "addresses",
        ["correspondence_address_id"], ["id"],
    )

    # --- NAR1 s16: where the statutory registers are kept -----------------
    op.create_table(
        "entity_record_locations",
        sa.Column("id", sa.Uuid, primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("entity_id", sa.Uuid, nullable=False),
        # CR's register vocabulary, carried as Viewpoint's address-type code
        # (SO, SM, SQ, SH, SG, ...). No CHECK: CR owns the list and a
        # constraint would make a CR revision a migration.
        sa.Column("record_type", sa.Text, nullable=False),
        sa.Column("address_id", sa.Uuid, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["address_id"], ["addresses.id"]),
        # One location per register per company; re-pointing updates in place.
        sa.UniqueConstraint("entity_id", "record_type",
                            name="entity_record_locations_unique"),
    )
    op.create_index(
        "idx_entity_record_locations_entity",
        "entity_record_locations", ["entity_id"],
    )

    op.bulk_insert(
        sa.table("audit_field_labels",
                 sa.column("field", sa.Text), sa.column("label", sa.Text)),
        [{"field": f, "label": lbl} for f, lbl in FIELD_LABELS.items()],
    )

    # Supabase-only roles; CI runs vanilla Postgres where they do not exist.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                GRANT SELECT ON entity_record_locations TO authenticated;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
                GRANT ALL ON entity_record_locations TO service_role;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM audit_field_labels WHERE field = ANY(:fields)")
        .bindparams(sa.bindparam("fields", list(FIELD_LABELS), type_=sa.ARRAY(sa.Text)))
    )
    op.drop_index("idx_entity_record_locations_entity",
                  table_name="entity_record_locations")
    op.drop_table("entity_record_locations")
    op.drop_constraint("entity_officers_correspondence_address_fkey",
                       "entity_officers", type_="foreignkey")
    op.drop_column("entity_officers", "correspondence_address_id")
    op.drop_column("persons", "alias_zh")
    op.drop_column("persons", "alias_en")
    op.drop_column("persons", "former_name_zh")
    op.drop_column("share_classes", "issued_amount")
    op.drop_column("entities", "mortgages_total")
    op.drop_column("entities", "business_nature_desc")
    op.drop_column("entities", "business_nature_code")
