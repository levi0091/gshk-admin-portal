"""Client Verification becomes stage 1, and the return they saw is kept.

Levi 2026-09-17: "we need client validation to be 1st step ... meaning users
send the email way ahead of time to the client and then make the necessary
changes ... before validating with CR portal after that first step."

WHAT THE OLD ORDER WAS FOR, SO THAT REVERSING IT IS A DECISION AND NOT A
FORGETTING. Client Verification sat SECOND because the client approved
`validated_xml` — the exact bytes CR had just accepted — so nobody was ever
asked to sign off a form CR would refuse minutes later. That property is real
and it is now gone: what the client approves is `request_xml`, built from the
company record by the same mapper and rendered into CR's own Form NAR1, which
CR has not seen.

What it cost was the calendar. The client is the slow party — they read the
return, notice a director's address is stale, ask for changes — and putting
them last meant that conversation started only AFTER the data work was
finished, and then invalidated it. Sending early means their corrections arrive
before the return is prepared for filing rather than after.

A CR VALIDATION FAILURE DOES NOT SEND THE CASE BACK (Levi's answer, same day).
The approval stands, the operator fixes the record, re-validates, and mails the
client by hand if the correction warrants it. So an approved case can legally
move away from what was approved — which is why `verification_xml` exists.

`nar1_cases.verification_xml` HOLDS THE BYTES THAT WERE MAILED. Not a hash: the
case screen names WHICH fields have changed since the client approved, and a
hash can only say that something did. It is written by
`cases.send_verification` and cleared when verification is restarted, so it
always answers "what is the client looking at in their inbox". The comparison
it feeds is NON-BLOCKING — it warns, it never refuses. The pre-submit drift
gate is untouched and still compares `request_xml` against the live record,
which is a different question and still the right one.

THE VIEW IS REBUILT BECAUSE THE BRANCH ORDER IS THE CHANGE. `nar1_case_registry`
restates `nar1_case_status._code()` in SQL — the dashboard sorts, counts and
filters on the badge and PostgREST cannot do any of that to an expression — so
the three client branches have to move above the `data_verification` branch
here as well. If they do not, a case reads "Client Verification" on its own
screen and "Data Verification" on the dashboard that listed it.
`tests/test_migration_024.py` drives every reachable state through the live view
and compares with `derive()`; that is what makes this a claim rather than a
hope.

NO ROW CHANGES, AND EVERY IN-FLIGHT CASE RELABELS. The badge is derived, so this
migration writes no case data at all — but a case sitting at Data Verification
with no verification email sent will read Client Verification from the moment
the view is replaced. That is the intended meaning of the new order (nobody has
asked the client yet, so that is the outstanding work), and it is a bulk visible
change on the dashboard rather than a silent one.

DROP AND RECREATE, not CREATE OR REPLACE — 025, 033, 039 and 043 all hit this
and all say so. DROP discards grants, so `_CASE_GRANTS` is restated verbatim.
That is not decoration: Supabase's default privileges GRANT ALL on every new
relation in `public` to anon and authenticated, and a recreate that forgot it
would PUBLISH every case row — client-approval state and statutory receipts
included — through PostgREST.

Revision ID: 046
Revises: 045
"""
from alembic import op

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None

CASE_VIEW = "public.nar1_case_registry"

#: Kept in step with services/nar1_cases.CR_FILED_STAGES, as 024/025/033/039/043.
CR_FILED_STAGES = ("submitted", "registered", "edrive")

#: Kept in step with the guard in nar1_case_status._code, as 024/025/033/039/043.
LIVE_STAGES = ("validated", "signed", "signing_failed", "submission_failed")

#: nar1_case_status.FILING_WINDOW_DAYS.
FILING_WINDOW_DAYS = 42

#: services/tpsi/doc_status.CR_STATUS_CODES, in the same order.
CR_STATUS_CODES = (
    "cr_not_checked", "cr_pending", "cr_approved", "cr_registered",
    "cr_rejected", "cr_unknown",
)

#: services/tpsi/doc_status.NOT_CHECKED.
CR_NOT_CHECKED = "cr_not_checked"

#: Verbatim from 024/025/033/039/043 — Python asks `if case.get("manual_receipt")`,
#: which is TRUTH and not NULL-ness.
_RECEIPT_PRESENT = """
          CASE jsonb_typeof(c.manual_receipt)
            WHEN 'null'    THEN false
            WHEN 'object'  THEN c.manual_receipt <> '{}'::jsonb
            WHEN 'array'   THEN c.manual_receipt <> '[]'::jsonb
            WHEN 'string'  THEN c.manual_receipt <> '""'::jsonb
            WHEN 'number'  THEN c.manual_receipt <> '0'::jsonb
            WHEN 'boolean' THEN c.manual_receipt = 'true'::jsonb
            ELSE false
          END
"""


def _case_view_sql(*, client_first: bool) -> str:
    """The case registry, with the client branches first or last.

    Parameterised because upgrade and downgrade differ in exactly that — two
    hand-copied definitions would be free to drift, and the one that drifted
    would be the one nobody runs until a rollback. 043 is the shape this
    restores to.
    """
    filed = ", ".join(f"'{s}'" for s in CR_FILED_STAGES)
    live = ", ".join(f"'{s}'" for s in LIVE_STAGES)

    data_branch = (
        "              WHEN base.filing_stage IS NULL\n"
        f"                OR base.filing_stage NOT IN ({live})      THEN 'data_verification'\n"
    )
    client_branches = (
        "              WHEN base.client_approved IS FALSE          THEN 'client_rejected'\n"
        "              WHEN base.verification_sent_at IS NULL      THEN 'client_verification'\n"
        "              WHEN base.client_approved IS NULL           THEN 'awaiting_client'\n"
    )
    # THE WHOLE MIGRATION, in two lines. Everything else here is the surrounding
    # view restated so that DROP/CREATE has something to create.
    middle = (client_branches + data_branch if client_first
              else data_branch + client_branches)

    filed_branch = (
        "              WHEN base.manual_receipt_present\n"
        f"                OR base.filing_stage IN ({filed})\n"
        f"                THEN COALESCE(base.cr_doc_status_code, '{CR_NOT_CHECKED}')\n"
    )
    finished = ", ".join(f"'{c}'" for c in CR_STATUS_CODES) + ", 'closed'"

    return f"""
        CREATE VIEW {CASE_VIEW}
        WITH (security_invoker = true) AS
        SELECT
          coded.*,
          -- An overlay, never a stage: a case can be overdue at any step, and
          -- the question is meaningless once the case is finished — filed
          -- (033), closed (039), or answered for by CR (043).
          (
            coded.workflow_status NOT IN ({finished})
            AND coded.days_to_anniversary IS NOT NULL
            AND coded.days_to_anniversary < -{FILING_WINDOW_DAYS}
          ) AS workflow_overdue
        FROM (
          SELECT
            base.*,
            -- WORKFLOW-STATUS-EXPRESSION-START
            -- Branch for branch, in order, with nar1_case_status._code.
            CASE
              WHEN base.closed_at IS NOT NULL             THEN 'closed'
{filed_branch}{middle}              WHEN base.filing_stage IN ('signed',
                                         'submission_failed') THEN 'submission'
              ELSE 'signing'
            END AS workflow_status
            -- WORKFLOW-STATUS-EXPRESSION-END
          FROM (
            SELECT
              c.id,
              c.case_no,
              c.entity_id,
              e.company_name,
              e.company_name_zh,
              e.br_number,
              e.cr_number,
              'NAR1'::text                    AS case_type,
              c.nar1_type::text               AS nar1_type,
              c.status::text                  AS case_status,
              c.signing_method,
              c.assigned_to,
              c.created_by,
              u.display_name                  AS created_by_name,
              c.closed_at,
              c.closed_by,
              cu.display_name                 AS closed_by_name,
              c.closed_reason,
              c.cr_doc_status,
              c.cr_doc_status_code,
              c.cr_status_checked_at,
              f.id                            AS filing_id,
              f.stage                         AS filing_stage,
              c.verification_sent_at,
              c.client_response_at,
              c.client_approved,
              c.manual_submitted_at,
              c.created_at,
              c.updated_at,
              e.days_to_anniversary,
              {_RECEIPT_PRESENT}              AS manual_receipt_present,
              COALESCE(f.stage = 'edrive', false) AS workflow_off_portal
            FROM public.nar1_cases c
            JOIN public.company_registry e ON e.id = c.entity_id
            LEFT JOIN public.users u ON u.id = c.created_by
            LEFT JOIN public.users cu ON cu.id = c.closed_by
            LEFT JOIN LATERAL (
              SELECT tf.id, tf.stage
              FROM public.tpsi_filings tf
              WHERE tf.nar1_case_id = c.id
                AND tf.stage <> 'superseded'
              ORDER BY (tf.stage IN ({filed})) DESC, tf.created_at DESC, tf.id DESC
              LIMIT 1
            ) f ON true
          ) base
        ) coded;
    """


#: 024/025/033/039/043's grant posture, restated because DROP VIEW discards it.
_CASE_GRANTS = """
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON public.nar1_case_registry FROM anon;
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON public.nar1_case_registry FROM authenticated;
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT SELECT ON public.nar1_case_registry TO service_role;
      END IF;
    END $$;
"""

_COMMENT = """
    COMMENT ON COLUMN public.nar1_cases.verification_xml IS
      'The return as it was MAILED to the client for approval — the exact '
      'request_xml rendered into the PDF they were sent. Kept so the case can '
      'name which fields have changed since they approved it, which a hash '
      'could not. Cleared when verification is restarted. Non-blocking: the '
      'pre-submit drift gate is a separate check against the live record '
      '(migration 046).';
"""


def _rebuild(*, client_first: bool) -> None:
    op.execute(f"DROP VIEW IF EXISTS {CASE_VIEW};")
    op.execute(_case_view_sql(client_first=client_first))
    op.execute(_CASE_GRANTS)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.nar1_cases "
        "ADD COLUMN IF NOT EXISTS verification_xml text"
    )
    op.execute(_COMMENT)
    _rebuild(client_first=True)


def downgrade() -> None:
    # Reversible on purpose: CI's migrations job runs `upgrade head` then
    # `downgrade base`, so an irreversible migration breaks the pipeline.
    _rebuild(client_first=False)
    op.execute(
        "ALTER TABLE public.nar1_cases DROP COLUMN IF EXISTS verification_xml"
    )
