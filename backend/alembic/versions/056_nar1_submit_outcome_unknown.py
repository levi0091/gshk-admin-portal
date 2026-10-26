"""A NAR1 submit with no answer from CR is an unknown outcome, never a failure.

THE PROD INCIDENT (2026-10-26). CR wrote to GSHK about ~10 companies whose 2026
annual return had arrived two or three times. Matched copy for copy against
CR's letters from `audit_log`: `submitFormNar1` normally answers in 25-56 s,
the portal read it with a 60 s timeout, and 16 of 160 PROD submits timed out
— while CR, as often as not, went on to lodge the return and charge for it.
Every timeout was stored as `submission_failed`, which `validate` accepts, so
operators re-validated, re-signed and re-submitted the SAME row. Fashion
Hamburg (NAR-2026-0319), 23 October: three submits, two timeouts, three copies
at CR.

This migration gives the fix its schema:

1. TWO STAGES on `tpsi_filings_stage_check` (018's pattern: drop, re-add with
   the full list). `submitting` is a claim — one request has won the right to
   call submitForm for this row. `submission_unknown` is a submit that ended
   without CR saying what happened; nothing can retry it, and an operator
   resolves it from what CR e-Services shows (`POST /tpsi/filings/{id}/resolve`).

2. `submit_started_at`, when the claim was taken. A claim older than 370 s
   belongs to a worker that died mid-call and is read as an unknown outcome.

3. THE REAL DOUBLE-CHARGE GUARD, documented here because migration 016's was
   not one. 016 commented `uq_tpsi_filings_submitted` "A double-clicked submit
   hits this, not CR" — but that index only sees a row once it reaches
   `submitted`, which is after CR has answered, which is after the charge. Two
   requests on one signed row both reached CR before it could object. The
   guard is now the claim in `filings.begin_submit`: one conditional UPDATE,
   `signed -> submitting WHERE stage = 'signed'`, so the second request matches
   no row and is refused before CR is contacted.

   And because a SECOND FILING on the same case is a second copy of the same
   return just as surely, `uq_tpsi_filings_case_locked` allows at most one
   filing per case in a stage where CR has, or may have, the return. The
   application refuses first and by name (`filings.locked_filing_on_case`); this
   index is what settles the race that read cannot.

   `edrive` IS NOT IN THE INDEX, though the application treats it as locked.
   An e-Drive upload is finished in CR's own wizard, and whether DEV or PROD
   carries an e-Drive row beside a submitted one on the same case could not be
   checked from the branch that wrote this; an index that failed to build
   would fail the deploy. The application-level lock covers it.

4. DATA REPAIR. Every `submission_failed` row whose recorded error is a
   transport failure (`cr_error->>'message'` starting `cannot reach TPSI`)
   becomes `submission_unknown`: CR may have filed it. On PROD on 2026-10-26
   that is NAR-2026-0283 and NAR-2026-0116. Only the newest such row per case,
   and only where no other filing on the case already holds the lock — anything
   else would fail the index above. A row left behind is still refused by the
   application's case-level lock, because its sibling holds it.

5. THE CASE REGISTRY VIEW READS A STALE CLAIM BUT NEVER WRITES IT. The view
   shows a `submitting` row older than the cut-off as `submission_unknown`; the
   row itself is only moved by the reads that carry an audit row --
   `GET /tpsi/filings/{id}` and `GET /cases/{id}` -- so a dashboard listing
   cannot rewrite 400 rows or audit on behalf of a list.

   The view (047's, otherwise unchanged) learns both stages: a
   case whose filing is `submitting` or `submission_unknown` is at the
   Submission stage, branch for branch with `nar1_case_status._code`, and a
   stale claim reads as `submission_unknown` in `filing_stage`.

6. AUDIT CODES `TPSI_SUBMISSION_UNKNOWN` and `TPSI_SUBMISSION_RESOLVED`, seeded
   with `origin='g_flowdesk'` and an explicit category (CLAUDE.md: an unseeded
   code writes fine and renders unlabelled).

056, NOT 050 OR 052-055. This is a hotfix on `master`, whose head is 051;
`dev` already uses 050 and 052-055 for the unreleased ND2A/ND2B work. When the
two meet, 056 and dev's 050 both revise 051 — reconciling that (and dev's own
restatement of 047's view) is a merge decision, not this migration's.

Revision ID: 056
Revises: 051
"""
import importlib.util
import os

from alembic import op

revision = "056"
down_revision = "051"
branch_labels = None
depends_on = None

_FILINGS = "public.tpsi_filings"
CASE_VIEW = "public.nar1_case_registry"

#: 018's ten, in its order, then the two this adds.
STAGES_018 = (
    "draft", "validated", "validation_failed", "signed", "signing_failed",
    "submitted", "submission_failed", "registered", "superseded", "edrive",
)
NEW_STAGES = ("submitting", "submission_unknown")
STAGES = STAGES_018 + NEW_STAGES

#: services/tpsi/filings.CASE_LOCK_INDEX, and the stages it covers. `edrive`
#: deliberately absent — see the docstring.
CASE_LOCK_INDEX = "uq_tpsi_filings_case_locked"
CASE_LOCK_STAGES = ("submitting", "submission_unknown", "submitted", "registered")

#: services/tpsi/filings.STALE_CLAIM_SECONDS, which is DERIVED there: 30 s start
#: delay + authenticate (15 connect + 15 write + 60 read + 5 pool) + submitForm
#: (15 + 15 + 180 + 5) + 30 s margin = 370, every httpx phase counted. A test
#: keeps the two equal (code review 01 B1.1, 02 N-7); it was 240, then 330,
#: before the unnamed phases were counted.
STALE_CLAIM_SECONDS = 370

#: What `TpsiClient` writes for a call that never completed — the one message
#: that proves CR's answer was never read.
TRANSPORT_FAILURE_PREFIX = "cannot reach TPSI"

AUDIT_CODES = [
    ("TPSI_SUBMISSION_UNKNOWN", "TPSI Submission Outcome Unknown", "tpsi"),
    ("TPSI_SUBMISSION_RESOLVED", "TPSI Submission Outcome Resolved", "tpsi"),
]

_REPAIR = f"""
    UPDATE {_FILINGS} f
       SET stage = 'submission_unknown'
      FROM (
        SELECT id,
               row_number() OVER (PARTITION BY nar1_case_id
                                  ORDER BY created_at DESC, id DESC) AS rn
          FROM {_FILINGS}
         WHERE stage = 'submission_failed'
           AND starts_with(cr_error->>'message', '{TRANSPORT_FAILURE_PREFIX}')
      ) candidate
     WHERE f.id = candidate.id
       AND (candidate.rn = 1 OR f.nar1_case_id IS NULL)
       AND NOT EXISTS (
         SELECT 1 FROM {_FILINGS} other
          WHERE other.nar1_case_id = f.nar1_case_id
            AND other.id <> f.id
            AND other.stage IN ({", ".join(f"'{s}'" for s in CASE_LOCK_STAGES)})
       )
"""

_COMMENTS = f"""
    COMMENT ON COLUMN {_FILINGS}.submit_started_at IS
      'When a request claimed this filing to call submitForm (stage '
      '''submitting''). A claim older than {STALE_CLAIM_SECONDS} s has no live '
      'request behind it and is read as submission_unknown. Migration 056.';
    COMMENT ON INDEX public.{CASE_LOCK_INDEX} IS
      'At most one filing per NAR1 case in a stage where CR has, or may have, '
      'the return. The real guard against filing one annual return twice, with '
      'the conditional claim in filings.begin_submit. Migration 056.';
"""


def _m047():
    """047's module, for its exact view on the way back down."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "047_nar1_case_return_year.py")
    spec = importlib.util.spec_from_file_location("m047", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: 047's lists, with the two stages added where `nar1_case_status._code` adds
#: them: both are LIVE (past Data Verification) and both are AT SUBMISSION.
LIVE_STAGES = ("validated", "signed", "signing_failed", "submission_failed",
               "submitting", "submission_unknown")
SUBMISSION_STAGES = ("signed", "submission_failed", "submitting",
                     "submission_unknown")


def case_view_sql() -> str:
    """047's case registry with the two stages taught to it.

    Four differences from 047 and no others, each pinned by
    tests/test_migration_056.py: LIVE_STAGES, the Submission branch, the stale
    claim read as `submission_unknown`, and the filing pick preferring a row CR
    may hold (as it already preferred a filed one).
    """
    m = _m047()
    filed = ", ".join(f"'{s}'" for s in m.CR_FILED_STAGES)
    locked = ", ".join(f"'{s}'" for s in m.CR_FILED_STAGES + NEW_STAGES)
    live = ", ".join(f"'{s}'" for s in LIVE_STAGES)
    at_submission = ", ".join(f"'{s}'" for s in SUBMISSION_STAGES)
    finished = ", ".join(f"'{c}'" for c in m.CR_STATUS_CODES) + ", 'closed'"

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
            AND coded.days_to_anniversary < -{m.FILING_WINDOW_DAYS}
          ) AS workflow_overdue
        FROM (
          SELECT
            base.*,
            -- WORKFLOW-STATUS-EXPRESSION-START
            -- Branch for branch, in order, with nar1_case_status._code.
            CASE
              WHEN base.closed_at IS NOT NULL             THEN 'closed'
              WHEN base.manual_receipt_present
                OR base.filing_stage IN ({filed})
                THEN COALESCE(base.cr_doc_status_code, '{m.CR_NOT_CHECKED}')
              WHEN base.client_approved IS FALSE          THEN 'client_rejected'
              WHEN base.verification_sent_at IS NULL      THEN 'client_verification'
              WHEN base.client_approved IS NULL           THEN 'awaiting_client'
              WHEN base.filing_stage IS NULL
                OR base.filing_stage NOT IN ({live})      THEN 'data_verification'
              WHEN base.filing_stage IN ({at_submission}) THEN 'submission'
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
              c.ar_period_year,
              e.days_to_anniversary,
              {m._RECEIPT_PRESENT}              AS manual_receipt_present,
              COALESCE(f.stage = 'edrive', false) AS workflow_off_portal
            FROM public.nar1_cases c
            JOIN public.company_registry e ON e.id = c.entity_id
            LEFT JOIN public.users u ON u.id = c.created_by
            LEFT JOIN public.users cu ON cu.id = c.closed_by
            LEFT JOIN LATERAL (
              SELECT tf.id,
                     -- A claim no live request can answer reads as the
                     -- unknown outcome it is (filings.is_stale_claim).
                     CASE
                       WHEN tf.stage = 'submitting'
                        AND (tf.submit_started_at IS NULL
                             OR tf.submit_started_at
                                < now() - interval '{STALE_CLAIM_SECONDS} seconds')
                       THEN 'submission_unknown'
                       ELSE tf.stage
                     END AS stage
              FROM public.tpsi_filings tf
              WHERE tf.nar1_case_id = c.id
                AND tf.stage <> 'superseded'
              ORDER BY (tf.stage IN ({locked})) DESC, tf.created_at DESC, tf.id DESC
              LIMIT 1
            ) f ON true
          ) base
        ) coded;
    """


def _stage_check(stages) -> str:
    values = ", ".join(f"'{s}'" for s in stages)
    return (f"ALTER TABLE {_FILINGS} ADD CONSTRAINT tpsi_filings_stage_check "
            f"CHECK (stage IN ({values}))")


def upgrade() -> None:
    op.execute(f"ALTER TABLE {_FILINGS} DROP CONSTRAINT IF EXISTS "
               "tpsi_filings_stage_check")
    op.execute(_stage_check(STAGES))
    op.execute(f"ALTER TABLE {_FILINGS} ADD COLUMN IF NOT EXISTS "
               "submit_started_at timestamptz")

    # BEFORE the index: the repair moves rows INTO a locked stage, and its own
    # guards are what keep the index buildable.
    op.execute(_REPAIR)

    stages = ", ".join(f"'{s}'" for s in CASE_LOCK_STAGES)
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {CASE_LOCK_INDEX} "
        f"ON {_FILINGS} (nar1_case_id) "
        f"WHERE nar1_case_id IS NOT NULL AND stage IN ({stages})"
    )
    op.execute(_COMMENTS)

    m = _m047()
    op.execute(f"DROP VIEW IF EXISTS {CASE_VIEW};")
    op.execute(case_view_sql())
    op.execute(m._CASE_GRANTS)

    values = ", ".join(
        f"('{code}', '{name}', '{category}', 'g_flowdesk')"
        for code, name, category in AUDIT_CODES
    )
    op.execute(
        f"INSERT INTO public.audit_event_types (code, name, category, origin) "
        f"VALUES {values} ON CONFLICT (code) DO NOTHING"
    )


_REFUSAL = ("migration 056 cannot be downgraded: tpsi_filings rows are "
            "submitting or submission_unknown, and each is a NAR1 that CR may "
            "have filed. Resolve them first (POST /tpsi/filings/<id>/resolve).")

#: Refuses rather than rewrites. A row in either new stage is a return CR may
#: hold; mapping it back onto 018's vocabulary would mean calling it
#: `submission_failed` — the exact mislabel this migration exists to remove —
#: and the retry path would reopen on it.
_REFUSE_DOWNGRADE = f"""
    DO $$
    DECLARE n integer;
    BEGIN
      SELECT count(*) INTO n FROM {_FILINGS}
       WHERE stage IN ({", ".join(f"'{s}'" for s in NEW_STAGES)});
      IF n > 0 THEN
        -- One literal, no `%` placeholder: the statement goes through
        -- SQLAlchemy's text(), and a percent sign there is a driver concern.
        RAISE EXCEPTION '{_REFUSAL}' USING DETAIL = n::text || ' row(s)';
      END IF;
    END $$;
"""


def downgrade() -> None:
    op.execute(_REFUSE_DOWNGRADE)
    codes = ", ".join(f"'{c}'" for c, _, _ in AUDIT_CODES)
    op.execute(f"DELETE FROM public.audit_event_types WHERE code IN ({codes})")

    m = _m047()
    op.execute(f"DROP VIEW IF EXISTS {CASE_VIEW};")
    op.execute(m._case_view_sql(with_year=True))
    op.execute(m._CASE_GRANTS)

    op.execute(f"DROP INDEX IF EXISTS public.{CASE_LOCK_INDEX}")
    op.execute(f"ALTER TABLE {_FILINGS} DROP COLUMN IF EXISTS submit_started_at")
    op.execute(f"ALTER TABLE {_FILINGS} DROP CONSTRAINT IF EXISTS "
               "tpsi_filings_stage_check")
    op.execute(_stage_check(STAGES_018))
