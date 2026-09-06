"""Closing a case — the eighth workflow status, and the three columns behind it.

Levi 2026-09-05: "we need a way to close a case… when the user no longer wants
to proceed with the case he/she can trigger to close it. closing it will be a
permanent action and the case will not be able to be reopened."

WHY A COLUMN AND NOT A `case_status` VALUE. `nar1_cases.status` is the coarse
Viewpoint-era enum that migration 021 deliberately left alone ("nothing in the
v11 UI reads it"), and adding a value to a shared enum is one of the few schema
changes Postgres cannot take back. Closure needs three facts anyway — WHEN, BY
WHOM and WHY — and a single enum value carries none of them.

WHY `closed_at` AND NOT `is_closed`. The badge is derived, so the DB never
stores it; what it must store is the evidence. A boolean answers "is it closed"
and nothing else, and the first question anyone asks of a closed case six months
later is when it happened. `closed_at IS NOT NULL` is the predicate everywhere —
service, view and route — so there is one fact, not a flag plus a timestamp that
can disagree.

`closed_reason` is NOT NULL-able in practice but is NOT constrained here. The
route requires it (`POST /cases/{id}/close` refuses an empty one), and a NOT
NULL column would additionally forbid a future data repair from recording a
closure whose reason genuinely was not captured — which would be a row nobody
could write rather than a row that says so.

WHY THE VIEW IS REBUILT. `nar1_case_registry` restates
`nar1_case_status._code()` in SQL because the dashboard sorts, counts and
filters on the badge and PostgREST cannot do any of that to an expression. The
Python function gained a 'closed' branch AT THE TOP; the view has to gain the
same branch in the same position, or a closed case reads "Closed" on its own
screen and "Awaiting Client" on the dashboard that lists it.
`tests/test_migration_024.py` drives every reachable state through the live view
and compares with `derive()`, and its `closed` axis is what makes that a claim
rather than a hope.

`workflow_overdue` changes with it: `<> 'completed'` becomes
`NOT IN ('completed','closed')`. An overdue overlay on an abandoned case is an
alarm about work somebody deliberately cancelled, which is the noise closing a
case exists to remove.

DROP AND RECREATE, not CREATE OR REPLACE — 025 and 033 both hit this and both
say so: the view gains columns (`closed_at`, `closed_by`, `closed_by_name`,
`closed_reason`) and Postgres refuses a REPLACE that changes an existing view's
column list. `company_registry` is NOT touched here; only its dependent is, so
there is nothing to restore underneath.

DROP discards grants, so `_CASE_GRANTS` is restated verbatim from 024/025/033.
That is not decoration: Supabase's default privileges GRANT ALL on every new
relation in `public` to anon and authenticated, and a recreate that forgot it
would PUBLISH every case row — client-approval state and statutory receipts
included — through PostgREST.

Additive. No existing data is rewritten: every case already in the book gets
NULL for all three columns, which is exactly "not closed".
"""
from alembic import op

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None

CASE_VIEW = "public.nar1_case_registry"

#: Kept in step with services/nar1_cases.CR_FILED_STAGES, as 024/025/033 are.
CR_FILED_STAGES = ("submitted", "registered", "edrive")

#: Kept in step with the guard in nar1_case_status._code, as 024/025/033 are.
LIVE_STAGES = ("validated", "signed", "signing_failed", "submission_failed")

#: nar1_case_status.FILING_WINDOW_DAYS.
FILING_WINDOW_DAYS = 42

#: One code, seeded WITH an explicit category and origin. The column default is
#: origin='viewpoint', which would file a G-FlowDesk action under inherited
#: Viewpoint history; and there is no FK from audit_log to this table, so an
#: unseeded code does not fail loudly — it writes fine and then renders
#: unlabelled in the trail. Migration 022 exists because exactly that happened.
AUDIT_CODES = [("NAR1_CASE_CLOSED", "NAR1 Case Closed")]


# ── the view ─────────────────────────────────────────────────────────────────

#: Verbatim from 024/025/033 — Python asks `if case.get("manual_receipt")`,
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


def _case_view_sql(*, closable: bool) -> str:
    """The case registry, with or without the closure branch.

    Parameterised because upgrade and downgrade differ in exactly that — two
    hand-copied definitions would be free to drift, and the one that drifted
    would be the one nobody runs until a rollback.
    """
    filed = ", ".join(f"'{s}'" for s in CR_FILED_STAGES)
    live = ", ".join(f"'{s}'" for s in LIVE_STAGES)

    # FIRST branch, matching nar1_case_status._code. A closed case that also
    # carries a filed stage is not reachable through the portal — the close
    # route refuses one CR already holds — but if a repair ever writes one,
    # 'closed' is the honest answer and the stage must not overrule it.
    closed_branch = (
        "              WHEN base.closed_at IS NOT NULL             THEN 'closed'\n"
        if closable else ""
    )
    closed_cols = (
        "              c.closed_at,\n"
        "              c.closed_by,\n"
        # The readable half, joined the same way `created_by_name` is: a
        # dashboard column showing a uuid is a column nobody can read.
        "              cu.display_name                 AS closed_by_name,\n"
        "              c.closed_reason,\n"
        if closable else ""
    )
    closed_join = (
        "            LEFT JOIN public.users cu ON cu.id = c.closed_by\n"
        if closable else ""
    )
    # A closed case is not waiting for anybody, so it is not overdue either.
    not_finished = ("coded.workflow_status NOT IN ('completed', 'closed')"
                    if closable else "coded.workflow_status <> 'completed'")

    return f"""
        CREATE VIEW {CASE_VIEW}
        WITH (security_invoker = true) AS
        SELECT
          coded.*,
          -- An overlay, never a stage: a case can be overdue at any step, and
          -- the question is meaningless once the case is finished — filed
          -- (migration 033) or closed (039).
          (
            {not_finished}
            AND coded.days_to_anniversary IS NOT NULL
            AND coded.days_to_anniversary < -{FILING_WINDOW_DAYS}
          ) AS workflow_overdue
        FROM (
          SELECT
            base.*,
            -- WORKFLOW-STATUS-EXPRESSION-START
            -- Branch for branch, in order, with nar1_case_status._code.
            CASE
{closed_branch}              WHEN base.manual_receipt_present            THEN 'completed'
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
{closed_cols}              f.id                            AS filing_id,
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
{closed_join}            LEFT JOIN LATERAL (
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


#: 024/025/033's grant posture, restated because DROP VIEW discards it. Tighter
#: than company_registry's on purpose: case rows carry client-approval state,
#: the existence of a statutory receipt and now the reason a client walked away.
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
    COMMENT ON COLUMN public.nar1_cases.closed_at IS
      'When this case was permanently closed. NULL means open. There is no route '
      'back: closing is irreversible by design (migration 039).';
    COMMENT ON COLUMN public.nar1_cases.closed_by IS
      'The portal user who closed it. Kept even if that account is later '
      'deactivated — the trail must still name who made the decision.';
    COMMENT ON COLUMN public.nar1_cases.closed_reason IS
      'Why the client is not proceeding, in the operator''s own words. Required '
      'by POST /cases/{id}/close; the one fact nobody can reconstruct later.';
"""


def _rebuild(*, closable: bool) -> None:
    op.execute(f"DROP VIEW IF EXISTS {CASE_VIEW};")
    op.execute(_case_view_sql(closable=closable))
    op.execute(_CASE_GRANTS)


def upgrade() -> None:
    op.execute("""
        ALTER TABLE public.nar1_cases
          ADD COLUMN IF NOT EXISTS closed_at     timestamptz,
          ADD COLUMN IF NOT EXISTS closed_by     uuid REFERENCES public.users(id),
          ADD COLUMN IF NOT EXISTS closed_reason text;
    """)
    # Partial: closed cases are the minority and the only question ever asked of
    # this column is "which ones are closed" (the dashboard's own badge filter
    # runs through the view, which reads it on every row).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_nar1_cases_closed_at "
        "ON public.nar1_cases (closed_at) WHERE closed_at IS NOT NULL"
    )
    _rebuild(closable=True)
    op.execute(_COMMENTS)

    values = ", ".join(f"('{c}', '{n}', 'nar1', 'g_flowdesk')" for c, n in AUDIT_CODES)
    op.execute(
        f"INSERT INTO public.audit_event_types (code, name, category, origin) "
        f"VALUES {values} ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    # CI's migrations job runs `upgrade head` then `downgrade base`, so this
    # path is exercised on every push. Back to 033's view, grants included, and
    # the view goes FIRST: the columns below are a hard dependency of it, and
    # Postgres will not drop a column another object selects.
    codes = ", ".join(f"'{c}'" for c, _ in AUDIT_CODES)
    op.execute(f"DELETE FROM public.audit_event_types WHERE code IN ({codes})")
    _rebuild(closable=False)
    op.execute("DROP INDEX IF EXISTS public.ix_nar1_cases_closed_at")
    op.execute("""
        ALTER TABLE public.nar1_cases
          DROP COLUMN IF EXISTS closed_reason,
          DROP COLUMN IF EXISTS closed_by,
          DROP COLUMN IF EXISTS closed_at;
    """)
