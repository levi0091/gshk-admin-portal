"""A body corporate's own email address — `entities.email`.

WHY THIS EXISTS. CR raised a discrepancy notice against GET STARTED HK LIMITED
as company secretary: its database holds `DATARESOURCES@GETSTARTED.HK` and the
AR e-form we filed carried the element EMPTY. That was not an operator's
mistake. `corpSec/corpEmailAddr` and `corpDir/corpEmailAddr` were both
`unsourced` in the CR form contract — "no entity-level Email column in Entity,
CR_Entity or RefMaster" — `nar1_mapper._corporate()` emitted no such node, and
`company_secretaries` has no email column either. So the box was blank on EVERY
return GSHK has filed, and would have gone on being blank on every future one.

WHY ON `entities` AND NOT ON `company_secretaries`. The corporate secretary
block already reads `corpBrNo` and `corpTcspNo` off the secretary's OWN entity
row: `nar1_source._resolve_secretary_entities` matches each
`company_secretaries` row by name to a company in the Body Corporate Registry
and attaches that company's address, BR number and Chinese name. The email is
the same kind of fact about the same party, so it belongs in the same place.

A column on `company_secretaries` would have reached only ONE of the two code
paths — the secretary register — leaving corporate DIRECTORS blank, and it
would have to be typed once per client company (5,930 of them) instead of once
on the body corporate itself. Here, GSHK's own profile is edited once and every
return naming GSHK as secretary carries the address from then on.

NULLABLE, AND NOT BACKFILLED. CR marks both fields `Mandatory = N`, so an empty
one blocks nothing and `_corporate()` omits the node entirely rather than
sending an empty element. There is no value to backfill from: Viewpoint never
had this column, which is why the contract called it unsourced in the first
place. GSHK's own address is typed in through the company profile after this
deploys — see the note in the PR.

NOT A CR-VALIDATED VOCABULARY, so it is not in `cr_vocabularies` and must never
be seeded into `lookup_values`. It is free text with CR's own 60-character
ceiling, which the profile screen reads from `/form-contract` rather than
hardcoding.

Revision ID: 045
Revises: 044
"""
from alembic import op

revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS: the column name is an obvious one and this migration must
    # be safely re-runnable against a database where a repair script or an
    # earlier hand-edit got there first.
    op.execute("ALTER TABLE public.entities ADD COLUMN IF NOT EXISTS email text")


def downgrade() -> None:
    # Reversible on purpose: CI's migrations job runs `upgrade head` then
    # `downgrade base`, so an irreversible migration breaks the pipeline.
    #
    # It still DESTROYS every address typed since the upgrade, which exist
    # nowhere else — Viewpoint never had this column and CR will not hand them
    # back. Do not run this against a database anyone has typed into.
    op.execute("ALTER TABLE public.entities DROP COLUMN IF EXISTS email")
