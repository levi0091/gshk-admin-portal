"""Who opened the case — `created_by` and `created_by_name` on the dashboard.

`nar1_cases.created_by` has been written on every case since migration 021
(`services/nar1_cases.create_case` sets it), but it was never exposed: the
dashboard reads `nar1_case_registry` (024) and that view did not select it. So
the fact existed in the database and nowhere on screen.

WHY THE NAME IS RESOLVED HERE rather than in Python. The alternative is a second
query per page — 50 rows, N distinct authors, another PostgREST round trip at
~200ms (the measurement behind the same decision in routers/companies.py) — and,
worse, a column the dashboard cannot SORT on. `nar1_cases._SORTABLE` whitelists
what may reach PostgREST's order clause, and PostgREST can only order by a
column that exists in the relation. "Sort by who opened it" has to be a column
or it cannot be offered at all.

LEFT JOIN, deliberately. `created_by` is NULLable and there are already rows
with NULL on DEV (cases opened before 021 landed), and `users` rows can be
deleted. An inner join would make a case DISAPPEAR from the dashboard because
of who opened it — a filing deadline hidden by a bookkeeping fact.

WHY DROP AND RECREATE rather than CREATE OR REPLACE. The new columns belong
inside the innermost SELECT, which `coded.*` expands into the middle of the
output list; Postgres refuses a REPLACE that renames or reorders an existing
view column. The whole definition is therefore restated below, unchanged apart
from the three added lines. `tests/test_migration_024.py` drives all 240
reachable (stage x sent x approved x manual) states through the live view and
asserts each equals `nar1_case_status.derive()`, so a copy that drifted from 024
fails there rather than silently sorting the dashboard on a different rule.

DROP also drops the grants, so the REVOKE/GRANT block from 024 is repeated. It
is not decoration: Supabase's default privileges GRANT ALL on every new relation
in `public` to anon and authenticated, so a recreate that forgot this block
would PUBLISH every case row — client-approval state and statutory receipts
included — through PostgREST.

Read-only and additive. No table is altered, no data is written.

Applied to DEV ONLY. Nothing applied to PROD.
"""
from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None

VIEW = "public.nar1_case_registry"

#: Kept in step with services/nar1_cases.CR_FILED_STAGES, as 024 is.
CR_FILED_STAGES = ("submitted", "registered", "edrive")

#: Kept in step with the guard in nar1_case_status._code, as 024 is.
LIVE_STAGES = ("validated", "signed", "signing_failed", "submission_failed")

#: nar1_case_status.FILING_WINDOW_DAYS.
FILING_WINDOW_DAYS = 42

#: Verbatim from 024 — Python asks `if case.get("manual_receipt")`, which is
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


def _view_sql(with_author: bool) -> str:
    """024's view, optionally carrying the two author columns.

    Parameterised so `downgrade` restores 024's exact shape from the same text
    that `upgrade` extends — two hand-copied definitions would be free to drift,
    and the one that drifted would be the one nobody runs until a rollback.
    """
    filed = ", ".join(f"'{s}'" for s in CR_FILED_STAGES)
    live = ", ".join(f"'{s}'" for s in LIVE_STAGES)
    author_cols = """
              c.created_by,
              u.display_name                  AS created_by_name,
    """ if with_author else ""
    author_join = """
            LEFT JOIN public.users u ON u.id = c.created_by
    """ if with_author else ""

    return f"""
        CREATE VIEW {VIEW}
        WITH (security_invoker = true) AS
        SELECT
          coded.*,
          -- An overlay, never a stage: a case can be overdue at any step, and
          -- the question is meaningless once filed.
          --
          -- NOTE, and it is a defect this view MIRRORS rather than fixes:
          -- migration 019 clamps days_to_anniversary at -{FILING_WINDOW_DAYS},
          -- so this predicate can never be true. derive() carries the identical
          -- dead branch; diverging here would be the worse defect.
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
              {author_cols}
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
            {author_join}
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


#: 024's grant posture, restated because DROP VIEW discards it. Tighter than
#: 019's company_registry on purpose: case rows carry client-approval state and
#: the existence of a statutory receipt.
_GRANTS = """
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


def upgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {VIEW};")
    op.execute(_view_sql(with_author=True))
    op.execute(_GRANTS)


def downgrade() -> None:
    # Back to 024's exact shape, grants included — CI's migrations job runs
    # `upgrade head` then `downgrade base`, so this path is exercised on every
    # push and an irreversible migration breaks the pipeline.
    op.execute(f"DROP VIEW IF EXISTS {VIEW};")
    op.execute(_view_sql(with_author=False))
    op.execute(_GRANTS)
