"""What CR did with the return AFTER it was filed — the sixth stage.

Levi 2026-09-16, off a live DEV case sitting at Confirmation · IN PROGRESS with
a CR receipt already on screen:

  * "when the workflow is completed and we get a receipt from CR portal, the
    progress bar is still indicating in-progress for confirmation stage."
  * "there should be a new stage (6) called CR Status, where each state is a
    different colour"
  * "completed should not be there.. it should be the steps throughout the
    workflow plus the final CR statuses."

THE DEFECT UNDERNEATH ALL THREE. `submitFormNar1` returning a receipt means CR
RECEIVED the return. It does not mean CR registered it — CR vets a filed
document and can still refuse it. The portal had no way to hold that answer, so
it called a received return "Completed" and drew a green tick on a claim nobody
at CR had made. `tpsi_filings.stage = 'registered'` has existed since migration
018 — whose docstring already says "CR confirmed the filing via
docStatusEnquiry" — and nothing has ever written it, because nothing has ever
enquired.

WHY THE COLUMNS GO ON `nar1_cases` AND NOT ON `tpsi_filings`. D-6 gives CR facts
to `tpsi_filings`, and this is a CR fact — for the e-Sign path. A return signed
on paper and filed off-portal has a CR case number (`manual_receipt->>'caseNo'`)
and NO submitted filing row: its filing is still sitting at 'validated'. Writing
"CR registered it" onto a row whose own stage says it was never sent would be a
record that contradicts itself, and the manual path is not a corner case — it is
half of R1. The case is the one thing both paths have, and `manual_receipt`, CR's
own receipt, is already precedent for a CR fact living there.

`tpsi_filings.stage` is still promoted 'submitted' -> 'registered' by
`services/tpsi/filings.mark_registered`, because that is the e-Sign filing's own
lifecycle and 018 defined the value for exactly this moment.

A CR REJECTION IS NOT `submission_failed`. That stage means `submitFormNar1`
itself refused and NOTHING WAS CHARGED. A rejection after filing means the
opposite: delivered, charged, and then refused. The two must not collapse, so
the rejection lives in `cr_doc_status_code` and the stage stays `submitted`.

THE CODE IS STORED, NOT DERIVED IN SQL. `normalise()` is fuzzy, case-insensitive
word matching over a field CR's own specification declares as `String(20)` and
does not enumerate. Restating that in SQL would be a second implementation free
to drift from the first, and the drifting one would be whichever the dashboard
happened to read. So Python normalises on the single write path
(`services/nar1_cr_status.refresh`) and the view reads a stored fact, exactly as
it reads `filing_stage`. The CHECK constraint is what makes that safe.

WHY THE VIEW IS REBUILT, AGAIN. `nar1_case_registry` restates
`nar1_case_status._code()` in SQL because the dashboard sorts, counts and
filters on the badge and PostgREST cannot do any of that to an expression. The
Python function's two `completed` branches became one CR branch; the view has to
gain the same branch in the same position, or a registered case reads
"Registered by CR" on its own screen and "Completed" on the dashboard that lists
it. `tests/test_migration_024.py` drives every reachable state through the live
view and compares with `derive()`, and its CR axis is what makes that a claim
rather than a hope.

`workflow_overdue` changes with it: `NOT IN ('completed','closed')` becomes
`NOT IN (<the five CR codes>, 'closed')`. Same rule as before — a case that is
finished is not overdue — restated over a vocabulary where "finished" is now
five values instead of one.

DROP AND RECREATE, not CREATE OR REPLACE — 025, 033 and 039 all hit this and all
say so: the view gains columns (`cr_doc_status`, `cr_status_checked_at`) and
Postgres refuses a REPLACE that changes an existing view's column list.

DROP discards grants, so `_CASE_GRANTS` is restated verbatim from 024/025/033/
039. That is not decoration: Supabase's default privileges GRANT ALL on every
new relation in `public` to anon and authenticated, and a recreate that forgot
it would PUBLISH every case row — client-approval state and statutory receipts
included — through PostgREST.

ADDITIVE, AND THE BACKFILL IS DELIBERATELY EMPTY. Every case already filed gets
NULL, which the view reads as 'cr_not_checked' — "filed, and nobody has asked CR
yet", which is precisely true of all of them. Writing anything else would be
inventing a CR answer for a call that has never been made.
"""
from alembic import op

revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None

CASE_VIEW = "public.nar1_case_registry"

#: Kept in step with services/nar1_cases.CR_FILED_STAGES, as 024/025/033/039 are.
CR_FILED_STAGES = ("submitted", "registered", "edrive")

#: Kept in step with the guard in nar1_case_status._code, as 024/025/033/039 are.
LIVE_STAGES = ("validated", "signed", "signing_failed", "submission_failed")

#: nar1_case_status.FILING_WINDOW_DAYS.
FILING_WINDOW_DAYS = 42

#: services/tpsi/doc_status.CR_STATUS_CODES, in the same order. The CHECK
#: constraint below is the guarantee the view's COALESCE relies on: without it a
#: stray value would render as an unlabelled badge, which is the failure mode
#: migration 022 exists because of.
CR_STATUS_CODES = (
    "cr_not_checked", "cr_pending", "cr_approved", "cr_registered",
    "cr_rejected", "cr_unknown",
)

#: services/tpsi/doc_status.NOT_CHECKED — the answer for a filed case nobody has
#: asked CR about.
CR_NOT_CHECKED = "cr_not_checked"

#: Seeded WITH an explicit category and origin. The column default is
#: origin='viewpoint', which would file a G-FlowDesk action under inherited
#: Viewpoint history; and there is no FK from audit_log to this table, so an
#: unseeded code does not fail loudly — it writes fine and then renders
#: unlabelled in the trail. Migration 022 exists because exactly that happened.
AUDIT_CODES = [
    ("TPSI_DOC_STATUS_CHECKED", "CR Document Status Checked", "tpsi"),
    ("NAR1_CR_STATUS_CHANGED", "CR Document Status Changed", "nar1"),
]


# ── the view ─────────────────────────────────────────────────────────────────

#: Verbatim from 024/025/033/039 — Python asks `if case.get("manual_receipt")`,
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


def _case_view_sql(*, cr_status: bool) -> str:
    """The case registry, with or without the CR-status branch.

    Parameterised because upgrade and downgrade differ in exactly that — two
    hand-copied definitions would be free to drift, and the one that drifted
    would be the one nobody runs until a rollback. 039 is the shape this
    restores to.
    """
    filed = ", ".join(f"'{s}'" for s in CR_FILED_STAGES)
    live = ", ".join(f"'{s}'" for s in LIVE_STAGES)

    # The two `completed` branches of 039 collapse into ONE, in the same
    # position: "CR has this return" is one condition arrived at two ways, and
    # what it resolves to is now CR's own answer rather than a word of ours.
    if cr_status:
        filed_branch = (
            "              WHEN base.manual_receipt_present\n"
            f"                OR base.filing_stage IN ({filed})\n"
            f"                THEN COALESCE(base.cr_doc_status_code, '{CR_NOT_CHECKED}')\n"
        )
    else:
        filed_branch = (
            "              WHEN base.manual_receipt_present            THEN 'completed'\n"
            f"              WHEN base.filing_stage IN ({filed})         THEN 'completed'\n"
        )

    cr_cols = (
        "              c.cr_doc_status,\n"
        "              c.cr_doc_status_code,\n"
        "              c.cr_status_checked_at,\n"
        if cr_status else ""
    )

    # A finished case is not overdue. "Finished" was one value; it is now five
    # CR answers plus closed. `cr_rejected` IS here: the red badge is the alarm,
    # and an overdue marker on top of it says the same thing twice while
    # implying the filing never happened.
    finished = (
        ", ".join(f"'{c}'" for c in CR_STATUS_CODES) + ", 'closed'"
        if cr_status else "'completed', 'closed'"
    )

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
{filed_branch}              WHEN base.filing_stage IS NULL
                OR base.filing_stage NOT IN ({live})      THEN 'data_verification'
              WHEN base.client_approved IS FALSE          THEN 'client_rejected'
              WHEN base.verification_sent_at IS NULL      THEN 'client_verification'
              WHEN base.client_approved IS NULL           THEN 'awaiting_client'
              WHEN base.filing_stage IN ('signed',
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
{cr_cols}              f.id                            AS filing_id,
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


#: 024/025/033/039's grant posture, restated because DROP VIEW discards it.
#: Tighter than company_registry's on purpose: case rows carry client-approval
#: state, the existence of a statutory receipt, the reason a client walked away
#: — and now what CR has decided about a filed return.
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

_COMMENTS = """
    COMMENT ON COLUMN public.nar1_cases.cr_doc_status IS
      'What CR''s docStatusEnquiry last said about this return, in CR''s own '
      'words. NULL means CR has not been asked. Shown verbatim beside the '
      'badge — on an unrecognised status it is the only informative thing '
      'there is (migration 043).';
    COMMENT ON COLUMN public.nar1_cases.cr_doc_status_code IS
      'The normalised treatment of cr_doc_status, written ONLY by '
      'services/nar1_cr_status.refresh(). NULL means never checked and reads '
      'as cr_not_checked. The dashboard filters, counts and sorts on this.';
    COMMENT ON COLUMN public.nar1_cases.cr_status_checked_at IS
      'When CR last answered. The screen shows it, because a green badge from '
      'three weeks ago and one from this morning are not the same claim.';
    COMMENT ON COLUMN public.nar1_cases.cr_document_ref_no IS
      'CR''s own documentRefNo for this return, learnt from the first '
      'successful enquiry. Makes every later enquiry unambiguous when one CR '
      'case number carries more than one document.';
"""


def _rebuild(*, cr_status: bool) -> None:
    op.execute(f"DROP VIEW IF EXISTS {CASE_VIEW};")
    op.execute(_case_view_sql(cr_status=cr_status))
    op.execute(_CASE_GRANTS)


def upgrade() -> None:
    codes = ", ".join(f"'{c}'" for c in CR_STATUS_CODES)
    op.execute(f"""
        ALTER TABLE public.nar1_cases
          ADD COLUMN IF NOT EXISTS cr_doc_status        text,
          ADD COLUMN IF NOT EXISTS cr_doc_status_code   text,
          ADD COLUMN IF NOT EXISTS cr_status_checked_at timestamptz,
          ADD COLUMN IF NOT EXISTS cr_document_ref_no   text;
    """)
    # NULL-tolerant on purpose: NULL is "never checked", which is the state
    # every row starts in and the state the view reads as cr_not_checked.
    op.execute(
        "ALTER TABLE public.nar1_cases "
        "DROP CONSTRAINT IF EXISTS nar1_cases_cr_doc_status_code_check"
    )
    op.execute(
        f"ALTER TABLE public.nar1_cases "
        f"ADD CONSTRAINT nar1_cases_cr_doc_status_code_check "
        f"CHECK (cr_doc_status_code IS NULL OR cr_doc_status_code IN ({codes}))"
    )
    # The poller's selection: filed cases CR has not finished with. Partial,
    # because the terminal rows are the ones that accumulate and the query never
    # wants them.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_nar1_cases_cr_status_open "
        "ON public.nar1_cases (cr_status_checked_at NULLS FIRST) "
        "WHERE closed_at IS NULL "
        "  AND (cr_doc_status_code IS NULL "
        "       OR cr_doc_status_code NOT IN ('cr_registered', 'cr_rejected'))"
    )
    _rebuild(cr_status=True)
    op.execute(_COMMENTS)

    values = ", ".join(
        f"('{code}', '{name}', '{category}', 'g_flowdesk')"
        for code, name, category in AUDIT_CODES
    )
    op.execute(
        f"INSERT INTO public.audit_event_types (code, name, category, origin) "
        f"VALUES {values} ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    # CI's migrations job runs `upgrade head` then `downgrade base`, so this
    # path is exercised on every push. Back to 039's view, grants included, and
    # the view goes FIRST: the columns below are a hard dependency of it, and
    # Postgres will not drop a column another object selects.
    codes = ", ".join(f"'{c}'" for c, _, _ in AUDIT_CODES)
    op.execute(f"DELETE FROM public.audit_event_types WHERE code IN ({codes})")
    _rebuild(cr_status=False)
    op.execute("DROP INDEX IF EXISTS public.ix_nar1_cases_cr_status_open")
    op.execute(
        "ALTER TABLE public.nar1_cases "
        "DROP CONSTRAINT IF EXISTS nar1_cases_cr_doc_status_code_check"
    )
    op.execute("""
        ALTER TABLE public.nar1_cases
          DROP COLUMN IF EXISTS cr_document_ref_no,
          DROP COLUMN IF EXISTS cr_status_checked_at,
          DROP COLUMN IF EXISTS cr_doc_status_code,
          DROP COLUMN IF EXISTS cr_doc_status;
    """)
