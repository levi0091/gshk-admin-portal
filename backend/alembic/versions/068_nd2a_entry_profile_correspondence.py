"""An ND2A appointment names a correspondence address FROM THE PROFILE —
`officer_change_entries.correspondence_address_id`.

Revision ID: 068
Revises: 067
Create Date: 2026-11-28

Levi 2026-11-28: "please remove the confusing section in ND2A appoint director.
you should follow the selection in natural person profile with the same logic
as the other forms". The appointment drawer used to ask "Correspondence address
is the same as the residential address" and, unticked, made staff re-type an
address the person's profile already held — and the filing then saved the
re-typed copy as a second address row.

An ND2A now prints what the profile says (`persons.address_on_forms`, 067): the
person's correspondence address, or the residential one when the profile asks
for it or holds no correspondence address. A NEW company has no appointment
link yet, so the correspondence address is the one the person's other
companies already use, or the only one recorded on the profile.

This column exists for the one case that rule cannot settle: the profile holds
SEVERAL different correspondence addresses. The drawer then asks which one —
a pick from the profile, never a typed address — and stores its id here. NULL
everywhere else, so no backfill. ON DELETE SET NULL: an address removed from
the profile drops the choice, and the form falls back to the rule (and asks
again if it is still ambiguous) rather than failing on a dangling id.

`correspondence_same_as_residential` / `correspondence_address` stay on the
table (filed entries carry them as history) but are no longer read or written
for new work. No audit code: entries are already audited as entry edits.

Apply to DEV, then PROD, BEFORE the code deploys: the new code reads the column.
REVERSIBLE: the downgrade drops the column.
"""
from alembic import op

revision = "068"
down_revision = "067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.officer_change_entries "
               "ADD COLUMN IF NOT EXISTS correspondence_address_id uuid "
               "REFERENCES public.addresses(id) ON DELETE SET NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE public.officer_change_entries "
               "DROP COLUMN IF EXISTS correspondence_address_id")
