"""The name CR holds for a user's e-Service account — `eservice_person_name`.

A NAR1 signed on behalf of a BODY CORPORATE carries the signing human in
`associatedPersonName`, and CR VALIDATES it against the e-Service account named
in `associatedPersonId`. Verified against CR's test register on 2026-09-16: the
correct name is accepted, and a wrong one is refused with

    efiling.eform.signatory.error — The signatory <id> is not authorized to
    sign the document.

which reads as an authorisation problem and sends you hunting the wrong thing.
An omitted one is refused outright with "Please input the associatedPersonName".

It cannot be derived. `users.display_name` is what a colleague typed when the
account was created ("Brian Yiu"); CR holds the name on the e-Service account,
in CR's own register form. Those agree only by luck, and where they disagree
every filing by that user fails at CR with a message about authorisation. So it
is stored beside the e-Service id it belongs to, on the per-user credential,
and entered on the CR Credentials screen by the person who owns the account.

NOT on `persons`: this is a fact about a G-FlowDesk USER's CR login, not about a
client's director. `persons.eservice_user_id` exists and is populated in 0 of
7,302 PROD rows, with no screen that writes it — a second, emptier home for the
same idea.

Nullable, no backfill and no default: nobody has this value yet, and a blank is
the honest reading until someone enters it. `nar1_mapper` refuses to build a
body-corporate return without one rather than filing a guess.

Revision ID: 042
Revises: 041
"""
from alembic import op
import sqlalchemy as sa

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tpsi_presenter_credentials",
        sa.Column("eservice_person_name", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tpsi_presenter_credentials", "eservice_person_name")
