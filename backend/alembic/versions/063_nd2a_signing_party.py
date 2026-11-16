"""ND2A: who signs the form at e-Sign — GSHK's e-Service account or a director's
own e-Registry account (`nar1_cases.signing_party`, `signing_director_person_id`).

Revision ID: 063
Revises: 062
Create Date: 2026-11-13

Levi, 2026-11-13: on an ND2A that changes the company secretary, GSHK is not yet
related to the company when the form is signed, so the overall signature cannot
come from the GSHK staff member's e-Service account (CR Credentials). It must
come from a current director's e-Registry account, stored on that director's
natural-person profile (`person_eservice_credentials`, the account the consent
signatures already use).

  * `signing_party` — 'gshk' | 'director'. NULL means "not chosen": the portal
    then applies the default (director when the ND2A changes the secretary and a
    director's account is complete, otherwise GSHK). Validating with CR STORES
    the party it validated, so the form CR checked and the account that signs it
    cannot disagree.
  * `signing_director_person_id` — the director who signs when the party is
    'director'. ON DELETE SET NULL: a deleted person leaves "choose a director"
    rather than a dangling id.

BACKFILL. Every ND2A that already has a live CR filing (validated or further)
was validated with GSHK as the signer, so it is pinned to 'gshk'. Without that,
the new default could flip an already-validated secretary change to director
and sign a form whose signatory block names somebody else.

Field labels are seeded for the reason 058 and 062 seeded theirs: a PATCH is
audited as CASE_FIELD_UPDATED with the field name, and an unlabelled field
renders as its raw column name. No new audit action code.

Apply to DEV, then PROD, BEFORE the code deploys: the new code reads and writes
the columns. REVERSIBLE: the downgrade drops both columns and the labels.
"""
import sqlalchemy as sa
from alembic import op

revision = "063"
down_revision = "062"
branch_labels = None
depends_on = None

FIELD_LABELS = {
    "signing_party": "Signed by",
    "signing_director_person_id": "Signing director",
}


def upgrade() -> None:
    op.execute("ALTER TABLE public.nar1_cases "
               "ADD COLUMN IF NOT EXISTS signing_party text")
    op.execute("ALTER TABLE public.nar1_cases "
               "DROP CONSTRAINT IF EXISTS nar1_cases_signing_party_check")
    op.execute("ALTER TABLE public.nar1_cases "
               "ADD CONSTRAINT nar1_cases_signing_party_check "
               "CHECK (signing_party IS NULL OR signing_party IN ('gshk', 'director'))")
    op.execute("ALTER TABLE public.nar1_cases "
               "ADD COLUMN IF NOT EXISTS signing_director_person_id uuid "
               "REFERENCES public.persons(id) ON DELETE SET NULL")
    op.execute(
        "UPDATE public.nar1_cases c SET signing_party = 'gshk' "
        "WHERE c.form_code = 'Nd2a' AND c.signing_party IS NULL AND EXISTS ("
        "  SELECT 1 FROM public.tpsi_filings f WHERE f.nar1_case_id = c.id "
        "  AND f.stage NOT IN ('superseded', 'draft', 'validation_failed'))"
    )
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
    op.execute("ALTER TABLE public.nar1_cases DROP COLUMN IF EXISTS signing_director_person_id")
    op.execute("ALTER TABLE public.nar1_cases "
               "DROP CONSTRAINT IF EXISTS nar1_cases_signing_party_check")
    op.execute("ALTER TABLE public.nar1_cases DROP COLUMN IF EXISTS signing_party")
