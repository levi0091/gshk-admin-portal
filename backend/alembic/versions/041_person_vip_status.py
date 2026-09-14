"""A client's VIP status — `persons.is_affiliated_agent`, `persons.is_vip_marked`.

GSHK's mock-up feedback of 16 July (G-Flowdesk Design Mock Up.docx, "New
Feedback as of 16 July"):

    "Add a bar at the very top so colleagues can quickly identify whether the
    client is important. For example, VIP clients are those who have more than
    three companies with us, and they may also be our affiliated agents.
    (Agents are considered VIP clients.)"

It was written up as AC-11 of the 2026-07-25 mock-up feedback PBI and drawn on
the person profile in wireframe v9-v11, and never built — the PBI called it
"presentation-only, no migration", which cannot be true of two of its three
inputs (Levi 2026-09-14: "I am unable to set someone as a VIP now").

The rule, wireframe v11: VIP if an AFFILIATED AGENT, OR holding roles in MORE
THAN THREE companies with GSHK, OR MARKED VIP by a colleague.

  * The company count is DERIVED (`routers/persons.vip_status`) from the link
    tables every time. Storing it would be a second copy of the role roll-up
    that goes stale the next time an appointment changes.
  * The other two are facts nobody can derive, so they are stored — and only
    they are. `is_vip` is deliberately NOT a column: a stored verdict would stay
    true after a client dropped to two companies, which is the wrong direction
    to be stale in for a flag telling colleagues to prioritise someone.

NOT NULL DEFAULT false, so every existing row reads as a standard client with
no backfill, and the old code keeps working untouched between the migration and
the deploy (the gap `feedback_deploy_runs_before_migrations` is about).

Revision ID: 041
Revises: 040
"""
from alembic import op
import sqlalchemy as sa

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


#: Without these the audit trail renders the raw column name — there is no FK
#: from audit rows to this table, so an unlabelled field fails silently (the
#: trap migration 022 exists to close). Both are written by PATCH /persons/{id}
#: and audited as PERSON_FIELD_UPDATED, like every other person field.
FIELD_LABELS = {
    "is_affiliated_agent": "Affiliated Agent",
    "is_vip_marked": "Marked as VIP",
}


def upgrade() -> None:
    op.add_column("persons", sa.Column(
        "is_affiliated_agent", sa.Boolean, nullable=False,
        server_default=sa.false()))
    op.add_column("persons", sa.Column(
        "is_vip_marked", sa.Boolean, nullable=False,
        server_default=sa.false()))

    # Same statement as 038's, for the same reasons: ON CONFLICT because the
    # key is the bare field name, and CAST(...) because SQLAlchemy's text()
    # reads `:fields::text[]` as a parameter called `fields:`.
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
    op.drop_column("persons", "is_vip_marked")
    op.drop_column("persons", "is_affiliated_agent")
