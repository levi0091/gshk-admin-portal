"""days_to_anniversary stops bottoming out at -42.

Levi 2026-09-04, on both the Body Corporate Registry and the Post-incorporation
dashboard: "we should not floor the days to anniversary at -42" — clearing the
filter's lower bound revealed nothing, because nothing below -42 existed.

WHAT 019 DID. It counted UP from the last anniversary (negative) only while the
return was inside the 42-day statutory window, and switched to counting DOWN to
the NEXT one past that. So a company 43 days past its anniversary read +322, not
-43: the value did not clamp so much as jump the fence, and the entire
population whose filing window had already shut was filed away among the
companies with most of a year in hand. Measured on DEV before this change: 5,930
client companies, range exactly [-42, 322], 515 of them negative.

WHAT IT DOES NOW — the NEAREST anniversary, signed:

    negative  when the last anniversary is closer than the next
    positive  otherwise

so the switch happens at the midpoint of the year rather than at day 42, and the
range becomes about [-182, +182]. On DEV, 2,785 of 5,454 datable companies read
negative under this rule — 2,262 of them below -42, where previously there were
none. Nothing about those 2,262 companies changed: their anniversary really did
pass that many days ago. Only the arithmetic that was hiding it changed.

WHY NOT COUNT NEGATIVE FOREVER. Then every company reads "N days ago" on all but
one day of the year, and "days to anniversary" names a column that never counts
to anything. The midpoint is the one cut that needs no information we do not
have.

WHAT THIS STILL DOES NOT CLAIM — exactly what 019 did not claim: whether a NAR1
was filed. DEV carries a filed_date on 2 of 7,959 rows, so "overdue" remains a
judgement this view cannot make. -120 means "the anniversary was 120 days ago"
and nothing more. The FRONTEND keeps its carrot highlight for the -42..0 window
alone (`anniversary.js`, `labelForDays`), precisely so that widening the range
does not turn 2,262 ordinary rows into an alarm.

SIDE EFFECT, AND IT IS THE POINT. `nar1_case_registry.workflow_overdue` tests
`days_to_anniversary < -42` and has been dead since 024, which says so in its own
body ("a defect this view MIRRORS rather than fixes") and again in
`nar1_case_status.derive` ("the change is to the CLAMP in migration 019, not to
this comparison"). This is that change. The predicate can now fire — on cases
that are not complete and whose anniversary passed more than 42 days ago, which
is what an overdue badge was always meant to mean. None of DEV's 30 cases match
today. 024's stale note is corrected in the body restated below.

WHY DROP AND RECREATE, not CREATE OR REPLACE — the same trap 025 hit and
documented. `company_registry` selects `e.*`, which expanded to the 30 columns
`entities` had in 019; migration 028 has since added three more
(`business_nature_code`, `business_nature_desc`, `mortgages_total`). A REPLACE
re-expands `e.*`, landing those three ahead of `last_anniversary`, and Postgres
refuses a REPLACE that renames or reorders an existing view column. Verified
against DEV before writing this: view 33 columns, entities 33 columns, three
present in the table and absent from the view. They join the view here as a
consequence; every consumer selects columns by name, so nothing reads them
by position.

DROP CASCADE is NOT used: `nar1_case_registry` is the only dependent, and
dropping it by name means this migration fails loudly if a second dependent
appears, rather than silently taking it with us.

DROP also discards grants. Both grant blocks are therefore restated — not
decoration: Supabase's default privileges GRANT ALL on every new relation in
`public` to anon and authenticated, so a recreate that forgot the second block
would PUBLISH every case row, client-approval state and statutory receipts
included, through PostgREST.

`tests/test_migration_024.py` drives all 240 reachable (stage x sent x approved
x manual) states through the live view and asserts each equals
`nar1_case_status.derive()`, so the copy of 025's definition below fails there
if it has drifted rather than quietly sorting the dashboard on another rule.

The frontend mirrors the new expression in `signedDaysToAnniversary`. The two
must agree, or the number a row prints and the number the server sorted it by
come from different rules.

Read-only and additive. No table is altered, no data is written.
"""
from alembic import op

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None

CASE_VIEW = "public.nar1_case_registry"

#: Kept in step with services/nar1_cases.CR_FILED_STAGES, as 024 and 025 are.
CR_FILED_STAGES = ("submitted", "registered", "edrive")

#: Kept in step with the guard in nar1_case_status._code, as 024 and 025 are.
LIVE_STAGES = ("validated", "signed", "signing_failed", "submission_failed")

#: nar1_case_status.FILING_WINDOW_DAYS.
FILING_WINDOW_DAYS = 42


# ── company_registry ──────────────────────────────────────────────────────────

#: 019's expression, kept verbatim so `downgrade` restores the floor exactly.
_FLOORED = f"""
          CASE
            WHEN a.last_on IS NULL THEN NULL
            WHEN (public.hk_today() - a.last_on) <= {FILING_WINDOW_DAYS}
              THEN -(public.hk_today() - a.last_on)
            ELSE (a.next_on - public.hk_today())
          END::int AS days_to_anniversary
"""

_NEAREST = """
          CASE
            -- No incorporation date -> no anniversary to measure against. The
            -- LEFT JOIN leaves last_on NULL for exactly those rows.
            WHEN a.last_on IS NULL THEN NULL
            -- The anniversary behind us is the closer one: count UP, negative.
            WHEN (public.hk_today() - a.last_on) <= (a.next_on - public.hk_today())
              THEN -(public.hk_today() - a.last_on)
            -- The one ahead is closer: count DOWN, positive.
            ELSE (a.next_on - public.hk_today())
          END::int AS days_to_anniversary
"""


def _company_view(days_expr: str) -> str:
    """019's view with one expression swapped.

    Parameterised because upgrade and downgrade differ in exactly that
    expression — two hand-copied definitions would be free to drift, and the one
    that drifted would be the one nobody runs until a rollback.
    """
    return f"""
        CREATE VIEW public.company_registry
        WITH (security_invoker = true) AS
        SELECT
          e.*,
          a.last_on AS last_anniversary,
          a.next_on AS next_anniversary,
          {days_expr.strip()}
        FROM public.entities e
        LEFT JOIN LATERAL (
          SELECT
            CASE WHEN y.this_yr <= public.hk_today() THEN y.this_yr
                 ELSE public.anniversary_in(e.incorporation_date,
                        EXTRACT(YEAR FROM public.hk_today())::int - 1)
            END AS last_on,
            CASE WHEN y.this_yr >= public.hk_today() THEN y.this_yr
                 ELSE public.anniversary_in(e.incorporation_date,
                        EXTRACT(YEAR FROM public.hk_today())::int + 1)
            END AS next_on
          FROM (
            SELECT public.anniversary_in(e.incorporation_date,
                     EXTRACT(YEAR FROM public.hk_today())::int) AS this_yr
          ) y
        ) a ON e.incorporation_date IS NOT NULL;
    """


#: 019's grant posture, restated because DROP VIEW discards it. Guarded so the
#: migration also applies to the vanilla Postgres the CI `migrations` job runs.
_COMPANY_GRANTS = """
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        GRANT SELECT ON public.company_registry TO anon;
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        GRANT SELECT ON public.company_registry TO authenticated;
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT SELECT ON public.company_registry TO service_role;
      END IF;
    END $$;
"""


# ── nar1_case_registry ────────────────────────────────────────────────────────

#: Verbatim from 024/025 — Python asks `if case.get("manual_receipt")`, which is
#: TRUTH and not NULL-ness.
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


def _case_view_sql() -> str:
    """025's view, unchanged apart from the `workflow_overdue` comment.

    The predicate itself is byte-identical to 024's and 025's. Only the note
    above it changed, because the note now says the opposite of the truth.
    """
    filed = ", ".join(f"'{s}'" for s in CR_FILED_STAGES)
    live = ", ".join(f"'{s}'" for s in LIVE_STAGES)

    return f"""
        CREATE VIEW {CASE_VIEW}
        WITH (security_invoker = true) AS
        SELECT
          coded.*,
          -- An overlay, never a stage: a case can be overdue at any step, and
          -- the question is meaningless once filed.
          --
          -- LIVE since migration 033. It was dead under 019, which floored
          -- days_to_anniversary at -{FILING_WINDOW_DAYS} so this could never hold; 033 removed
          -- the floor, and a case that is not complete more than {FILING_WINDOW_DAYS} days after
          -- its anniversary now flags here. Whether it was filed LATE is a
          -- different question, and still not one this view can answer.
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
              WHEN base.manual_receipt_present            THEN 'completed'
              WHEN base.filing_stage IN ({filed})         THEN 'completed'
              WHEN base.filing_stage IS NULL
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


#: 024/025's grant posture. Tighter than company_registry's on purpose: case rows
#: carry client-approval state and the existence of a statutory receipt.
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

_COLUMN_COMMENT = """
    COMMENT ON COLUMN public.company_registry.days_to_anniversary IS
      'Signed whole days to the NEAREST incorporation anniversary, Asia/Hong_Kong: '
      'negative when the last one is closer than the next, positive otherwise. '
      'Range approximately -182..182. Says nothing about whether a return was filed. '
      'Migration 033 removed the -42 floor.';
"""


def _rebuild(days_expr: str) -> None:
    """Drop both views and put them back, with one expression chosen."""
    op.execute(f"DROP VIEW IF EXISTS {CASE_VIEW};")
    op.execute("DROP VIEW IF EXISTS public.company_registry;")
    op.execute(_company_view(days_expr))
    op.execute(_COMPANY_GRANTS)
    op.execute(_case_view_sql())
    op.execute(_CASE_GRANTS)


def upgrade() -> None:
    _rebuild(_NEAREST)
    op.execute(_COLUMN_COMMENT)


def downgrade() -> None:
    # CI's migrations job runs `upgrade head` then `downgrade base`, so this
    # path is exercised on every push and an irreversible migration breaks the
    # pipeline. Back to 019's floor and 025's view, grants included.
    _rebuild(_FLOORED)
