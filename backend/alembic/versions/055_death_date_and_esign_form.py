"""Date of death on a cessation; the e-Sign route's signed form on the case.

Revision ID: 055
Revises: 054
Create Date: 2026-10-18

Levi 2026-10-18, two follow-ups to the ND2A / ND2B release:

  * "There's no Date of Death field ... we will need to enable a date of death
    field in the workflow, and then store it in natural person profile once the
    workflow is confirmed." `officer_change_entries.date_of_death` holds what
    the operator entered on a Deceased cessation; filing writes it to
    `persons.date_of_death` (`services/officer_changes/apply`), and Undo puts
    the profile's previous value back. CR's ND2A has no box for it.
  * "On the e-Sign route, the signed ND2A isn't saved to the company's
    documents." `nar1_cases.filed_form_document_id / _version` point at the
    copy saved there after an e-Sign filing — the pair, as 023 keeps the manual
    route's upload, because `upload_document` versions one row per company and
    type.

Nullable columns only, no backfill: an entry added before this has no date of
death and files without writing one, and a case filed before this has no saved
form, which the Confirmation stage offers to save. Additive, so it may run
before or after the code that uses it deploys — but the code refuses to add a
Deceased cessation without it, so run it first.
"""
from alembic import op

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.officer_change_entries "
               "ADD COLUMN IF NOT EXISTS date_of_death date")
    op.execute("ALTER TABLE public.nar1_cases "
               "ADD COLUMN IF NOT EXISTS filed_form_document_id uuid "
               "REFERENCES public.documents(id), "
               "ADD COLUMN IF NOT EXISTS filed_form_document_version integer")


def downgrade() -> None:
    op.execute("ALTER TABLE public.nar1_cases "
               "DROP COLUMN IF EXISTS filed_form_document_version, "
               "DROP COLUMN IF EXISTS filed_form_document_id")
    op.execute("ALTER TABLE public.officer_change_entries "
               "DROP COLUMN IF EXISTS date_of_death")
