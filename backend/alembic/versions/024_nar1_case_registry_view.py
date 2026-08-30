"""BE-7: the case-level dashboard relation.

One row per CASE, not per company (wireframe_v11 s2): a company with two open
cases is two rows, and clicking one opens that case's workflow directly. That is
the whole difference between this and `company_registry` (019), which the
Companies listing already uses and which this view REUSES rather than restates.

WHY A VIEW RATHER THAN ASSEMBLING ROWS IN PYTHON. The dashboard paginates and
sorts. Sorting the 50 rows the server happened to return answers the wrong
question -- "the case closest to its deadline on page 1" is not "the case
closest to its deadline". PostgREST cannot sort or filter on an expression, so
the expression has to become a relation. Same reasoning as 009 and 019.

DUPLICATION, ACKNOWLEDGED. The workflow CASE below mirrors
services/nar1_case_status.py. That is the same trade 019 made between
company_registry and frontend/src/lib/anniversary.js, and it carries the same
obligation: tests/test_migration_024.py drives all 240 reachable
(stage x sent x approved x manual) states through this view and asserts each one
equals derive()'s WHOLE answer -- code, off_portal and overdue. If that test ever
fails, one of the two moved and the dashboard is sorting on a different rule than
the case detail displays. The test is named `test_migration_024` so the CI
`migrations` job's `tests/test_migration_*.py` glob actually runs it.

days_to_anniversary is NOT recomputed here. It is read from company_registry
(019), which already pins it to Asia/Hong_Kong. A second definition would be free
to drift, and for the first eight hours of every HK working day the two would
disagree.

WHICH FILING A ROW IS ABOUT -- a deliberate departure from current_filing().
`services/nar1_cases.current_filing()` returns the newest non-superseded filing,
and NOTHING in the codebase ever writes 'superseded'. So a second
POST /tpsi/filings/prepare against an already-submitted case opens a fresh
'draft' that sorts first, and composite() then reports Data Verification for a
return CR has already registered. That is a live Task 5/6 defect, logged for the
whole-branch review and not fixed here -- but the dashboard must not inherit it.
The LATERAL below applies `nar1_cases.blocking_filing()`'s rule instead, which is
the codebase's own existing answer to this hazard: a filing CR is holding wins,
newest non-superseded otherwise. It invents no third rule.

SECURITY. Supabase's default privileges GRANT ALL on every new relation in
`public` to anon and authenticated (measured on DEV: `anon=arwdDxtm/postgres` in
pg_default_acl), so creating this view PUBLISHES it through PostgREST unless the
migration takes it back. Two guards, both stated rather than inherited:
  1. security_invoker = true, so the caller's RLS on nar1_cases / entities /
     tpsi_filings applies. Without it the view runs as its owner and hands every
     case to every role that can reach PostgREST.
  2. The default grants are REVOKED from anon and authenticated and SELECT is
     granted to service_role alone. The backend is the only consumer and connects
     as service_role (db/supabase.py reads SUPABASE_SERVICE_ROLE_KEY); CLAUDE.md
     makes it a rule that the frontend never talks to Supabase directly. Relying
     on (1) alone would mean case data stays private only by accident of which
     RLS policies nar1_cases happens to carry today.
This is deliberately TIGHTER than 019's company_registry, which grants SELECT to
anon. Case rows carry client-approval state and the existence of a statutory
receipt; the company list does not.

Read-only and additive. No table is altered, no data is written.

Applied to DEV ONLY. Nothing applied to PROD.
"""
from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None

VIEW = "public.nar1_case_registry"

#: Stages that mean CR already holds the return. Kept in step with
#: services/nar1_cases.CR_FILED_STAGES (test_migration_024 parametrises over that
#: constant, so widening one without the other fails).
CR_FILED_STAGES = ("submitted", "registered", "edrive")

#: Stages past which the client-facing half of the workflow is live. Mirrors the
#: guard in nar1_case_status._code: anything else -- including validation_failed,
#: which is free to fix and retry -- is still data verification.
LIVE_STAGES = ("validated", "signed", "signing_failed", "submission_failed")

#: nar1_case_status.FILING_WINDOW_DAYS.
FILING_WINDOW_DAYS = 42

#: Python asks `if case.get("manual_receipt")` -- TRUTH, not NULL-ness. `{}` and
#: JSON `null` are both non-NULL and both falsy in Python, so a mirror written as
#: `manual_receipt IS NOT NULL` would call an empty receipt a completed statutory
#: filing while the case detail still showed Data Verification. Neither value is
#: reachable through validate_receipt() today; mirroring exactly costs six lines
#: and removes the question.
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


def upgrade() -> None:
    filed = ", ".join(f"'{s}'" for s in CR_FILED_STAGES)
    live = ", ".join(f"'{s}'" for s in LIVE_STAGES)

    # Three nesting levels so each derived value is written ONCE and the next
    # one can refer to it: a SELECT list cannot reference its own output
    # columns, and repeating the receipt CASE inside the status CASE inside the
    # overdue predicate is three places for them to drift apart.
    #   base -> the join + the filing pick + manual_receipt_present
    #   coded -> + workflow_status
    #   outer -> + workflow_overdue (which needs workflow_status)
    op.execute(f"""
        CREATE OR REPLACE VIEW {VIEW}
        WITH (security_invoker = true) AS
        SELECT
          coded.*,
          -- An overlay, never a stage: a case can be overdue at any step, and
          -- the question is meaningless once filed.
          --
          -- NOTE, and it is a defect this view MIRRORS rather than fixes:
          -- migration 019 clamps days_to_anniversary at -{FILING_WINDOW_DAYS}
          -- (past the window it stops counting up and starts counting down to
          -- the NEXT anniversary), so this predicate can never be true.
          -- Measured on DEV: min = -42, zero rows below, 5,998 companies.
          -- derive() carries the identical dead branch. Diverging here would be
          -- the worse defect -- the dashboard would flag cases the case detail
          -- called fine. See test_the_overdue_flag_is_unreachable_by_construction.
          (
            coded.workflow_status <> 'completed'
            AND coded.days_to_anniversary IS NOT NULL
            AND coded.days_to_anniversary < -{FILING_WINDOW_DAYS}
          ) AS workflow_overdue
        FROM (
          SELECT
            base.*,
            -- WORKFLOW-STATUS-EXPRESSION-START
            -- Branch for branch, in order, with nar1_case_status._code.
            CASE
              -- Off-portal completion FIRST: the manual path never calls CR, so
              -- its filing is still sitting at 'validated' while the case is
              -- genuinely finished. Testing the stage first would report a
              -- finished case as still Signing.
              WHEN base.manual_receipt_present            THEN 'completed'
              WHEN base.filing_stage IN ({filed})         THEN 'completed'
              -- Nothing validated -> the data is still being worked on.
              -- validation_failed lands here too: it is free to fix and retry,
              -- and that IS data verification.
              WHEN base.filing_stage IS NULL
                OR base.filing_stage NOT IN ({live})      THEN 'data_verification'
              WHEN base.client_approved IS FALSE          THEN 'client_rejected'
              WHEN base.verification_sent_at IS NULL      THEN 'client_verification'
              WHEN base.client_approved IS NULL           THEN 'awaiting_client'
              -- Approved. Which side of the signature are we on?
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
              -- e-Drive is terminal for TPSI and finished in CR's Web Guided
              -- Wizard, so the case is complete but not by us. The UI has no
              -- badge for it (Levi 2026-08-02), hence a flag beside the code --
              -- exactly as derive() does. COALESCE because a case with no filing
              -- is not off-portal, and a NULL here would read as "unknown".
              COALESCE(f.stage = 'edrive', false) AS workflow_off_portal
            FROM public.nar1_cases c
            -- company_registry, NOT entities: days_to_anniversary is defined
            -- there, once, pinned to Asia/Hong_Kong. Inner join is safe --
            -- entity_id is NOT NULL with an FK, and 019 keeps every entity row.
            JOIN public.company_registry e ON e.id = c.entity_id
            LEFT JOIN LATERAL (
              -- The filing this row's badge is about. blocking_filing()'s rule:
              -- a filing CR already holds outranks a newer attempt, because
              -- nothing writes 'superseded' and a fresh draft would otherwise
              -- hide a registered return. Newest-first below that, which is
              -- current_filing()'s rule. `id DESC` only so two filings created
              -- in the same microsecond order deterministically.
              SELECT tf.id, tf.stage
              FROM public.tpsi_filings tf
              WHERE tf.nar1_case_id = c.id
                AND tf.stage <> 'superseded'
              ORDER BY (tf.stage IN ({filed})) DESC, tf.created_at DESC, tf.id DESC
              LIMIT 1
            ) f ON true
          ) base
        ) coded;
    """)

    # Every role touched is guarded on existence, so this also applies to the
    # vanilla Postgres the CI `migrations` job runs (which creates
    # `authenticated` and nothing else). Same idiom as 009 and 019 -- but a
    # REVOKE, not a GRANT, for the two browser-facing roles.
    op.execute("""
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
    """)


def downgrade() -> None:
    # Reversible on purpose: CI's migrations job runs `upgrade head` then
    # `downgrade base`, so an irreversible migration breaks the pipeline.
    op.execute(f"DROP VIEW IF EXISTS {VIEW};")
