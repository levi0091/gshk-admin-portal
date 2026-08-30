"""Form status vs workflow status — two separate vocabularies, reported separately.

Levi 2026-08-02: the CR form has its own lifecycle and the G-FlowDesk case has
its own workflow. They are NOT the same thing and must not be collapsed into one
badge. So:

  FORM status      -> tpsi_filings.stage   (this migration)  — where the document
                      is in CR's own process.
  WORKFLOW status  -> nar1_cases + client columns from 017   — where the case is
                      in GSHK's process.

This widens tpsi_filings.stage from 6 values to the 9 the UI reports.

The change that matters beyond naming: the old vocabulary had ONE `failed`, so a
validate failure and a submit failure were indistinguishable without opening
cr_error. That is the difference between "fix your data and retry for free" and
"CR rejected a chargeable submission", and the status has to say which.

  draft              filing opened, XML built, nothing sent to CR
  validated          validateForm passed; CR-signed XML held (snapshot frozen)
  validation_failed  validateForm rejected — free, fix and retry
  signed             verifyPinSigning passed
  signing_failed     verifyPinSigning rejected — free, still recoverable
  submitted          submitForm passed, receipt held — CHARGED, irreversible
  submission_failed  submitForm rejected
  registered         CR confirmed the filing via docStatusEnquiry
  superseded         a Restart discarded this attempt in favour of a newer one

`edrive` is retained as a valid value because services/tpsi/filings.py still
exposes upload_edrive() and CR still supports it, but it is deliberately NOT
offered in the UI (Levi 2026-08-02) and is therefore not one of the nine the
front end reports.

Both tables were empty on DEV when this was written, so no data backfill is
needed. The UPDATE below is kept anyway so the migration is correct on any
environment that does hold rows.
"""
from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None

NEW_STAGES = (
    "draft", "validated", "validation_failed", "signed", "signing_failed",
    "submitted", "submission_failed", "registered", "superseded", "edrive",
)
OLD_STAGES = ("draft", "validated", "signed", "submitted", "edrive", "failed")


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.tpsi_filings "
        "DROP CONSTRAINT IF EXISTS tpsi_filings_stage_check"
    )

    # Old generic 'failed' rows cannot say which step failed. Map to the earliest
    # step that could have produced them rather than inventing a later one: a
    # filing that never reached 'validated' can only have failed validation.
    op.execute("""
        UPDATE public.tpsi_filings
           SET stage = CASE
                 WHEN signed_xml    IS NOT NULL THEN 'submission_failed'
                 WHEN validated_xml IS NOT NULL THEN 'signing_failed'
                 ELSE 'validation_failed'
               END
         WHERE stage = 'failed'
    """)

    values = ", ".join(f"'{s}'" for s in NEW_STAGES)
    op.execute(
        "ALTER TABLE public.tpsi_filings "
        "ADD CONSTRAINT tpsi_filings_stage_check "
        f"CHECK (stage IN ({values}))"
    )

    # The dashboard reports form status beside workflow status, so it is filtered
    # on directly. idx_tpsi_filings_stage (016) already covers stage alone; this
    # covers "the current form status for this case", which is the actual query.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tpsi_filings_case_stage "
        "ON public.tpsi_filings (nar1_case_id, stage) "
        "WHERE nar1_case_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.idx_tpsi_filings_case_stage")
    op.execute(
        "ALTER TABLE public.tpsi_filings "
        "DROP CONSTRAINT IF EXISTS tpsi_filings_stage_check"
    )
    op.execute("""
        UPDATE public.tpsi_filings
           SET stage = CASE
                 WHEN stage IN ('validation_failed','signing_failed','submission_failed')
                   THEN 'failed'
                 WHEN stage = 'registered'  THEN 'submitted'
                 WHEN stage = 'superseded'  THEN 'draft'
                 ELSE stage
               END
         WHERE stage NOT IN ('draft','validated','signed','submitted','edrive')
    """)
    values = ", ".join(f"'{s}'" for s in OLD_STAGES)
    op.execute(
        "ALTER TABLE public.tpsi_filings "
        "ADD CONSTRAINT tpsi_filings_stage_check "
        f"CHECK (stage IN ({values}))"
    )
