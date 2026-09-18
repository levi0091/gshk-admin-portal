"""A case names the year of the annual return it files.

Levi 2026-09-18: "we should be able to file NAR1 multiple times for the same
company, for example if the company has not been filing nar1 for the last 4
years then we should be able to file 4 times (once for 2023, 2024, 2025, 2026).
There should be a field we can send the year we want to file."

That field is CR's `yearAnnualReturn` — the only thing CR takes; it derives the
made-up date itself (see services/nar1_return_year.py for the evidence). Until
now every build passed no year and got the current one, so a company could only
ever file this year's return.

THE COLUMN ALREADY EXISTS. `nar1_cases.ar_period_year` came in with the PBI-38
schema (migration 003) and was never written — the case header and the public
approval page already read it. So this migration adds no column. It does two
things:

1. ONE LIVE CASE PER COMPANY PER YEAR, in Postgres. Four missed years are four
   cases; two cases for the same year is one return filed twice. The router
   checks first and says which case holds the year, but a check is a read and
   two operators can both pass it, so the index is what settles the race.
   Partial on `closed_at IS NULL` — closing a mistaken case gives its year
   back — and on `ar_period_year IS NOT NULL`, because a case that has not
   chosen or fixed a year yet holds nothing. Every row on DEV and PROD is NULL
   today, so creating it cannot fail on existing data.

2. THE DASHBOARD CAN TELL THE FOUR APART. `nar1_case_registry` gains
   `ar_period_year`, appended after `updated_at`. Without it a company filing
   four years reads as four identical rows. The column is a pass-through: the
   badge expression, the overdue flag and every branch are 046's, unchanged —
   `tests/test_migration_024.py`'s parity suite runs against this view as it
   runs against every one before it.

DROP AND RECREATE, not CREATE OR REPLACE, like 025/033/039/043/046, and for the
same reason those give: `coded.*` / `base.*` freeze the column list, and a new
column in the middle is not an append. DROP discards grants, so `_CASE_GRANTS`
is restated verbatim — Supabase's default privileges GRANT ALL on every new
relation in `public` to anon and authenticated, and a recreate that forgot it
would publish every case row through PostgREST.

Revision ID: 047
Revises: 046
"""
from alembic import op

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None

CASE_VIEW = "public.nar1_case_registry"

_YEAR_INDEX = "uq_nar1_cases_entity_live_return_year"

#: Kept in step with services/nar1_cases.CR_FILED_STAGES, as 024..046.
CR_FILED_STAGES = ("submitted", "registered", "edrive")

#: Kept in step with the guard in nar1_case_status._code, as 024..046.
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

#: Verbatim from 024..046 — Python asks `if case.get("manual_receipt")`, which
#: is TRUTH and not NULL-ness.
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


def _case_view_sql(*, with_year: bool) -> str:
    """046's case registry, with or without the return year.

    Parameterised because upgrade and downgrade differ in exactly that one
    line, and two hand-copied definitions would be free to drift — the one that
    drifted being the one nobody runs until a rollback.
    """
    filed = ", ".join(f"'{s}'" for s in CR_FILED_STAGES)
    live = ", ".join(f"'{s}'" for s in LIVE_STAGES)
    finished = ", ".join(f"'{c}'" for c in CR_STATUS_CODES) + ", 'closed'"

    # THE WHOLE MIGRATION'S VIEW CHANGE, in one line.
    year = "              c.ar_period_year,\n" if with_year else ""

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
              WHEN base.manual_receipt_present
                OR base.filing_stage IN ({filed})
                THEN COALESCE(base.cr_doc_status_code, '{CR_NOT_CHECKED}')
              WHEN base.client_approved IS FALSE          THEN 'client_rejected'
              WHEN base.verification_sent_at IS NULL      THEN 'client_verification'
              WHEN base.client_approved IS NULL           THEN 'awaiting_client'
              WHEN base.filing_stage IS NULL
                OR base.filing_stage NOT IN ({live})      THEN 'data_verification'
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
{year}              e.days_to_anniversary,
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


#: 024..046's grant posture, restated because DROP VIEW discards it.
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
    COMMENT ON COLUMN public.nar1_cases.ar_period_year IS
      'The year of the annual return this case files — CR''s yearAnnualReturn, '
      'from which CR derives the made-up date (the incorporation anniversary in '
      'that year). Chosen at Client Verification, or fixed at the first send or '
      'prepare. NULL means not yet fixed; the portal then builds for the current '
      'Hong Kong year. At most one live (not closed) case per company per year '
      '(migration 047).';
"""


def _rebuild(*, with_year: bool) -> None:
    op.execute(f"DROP VIEW IF EXISTS {CASE_VIEW};")
    op.execute(_case_view_sql(with_year=with_year))
    op.execute(_CASE_GRANTS)


def upgrade() -> None:
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {_YEAR_INDEX} "
        "ON public.nar1_cases (entity_id, ar_period_year) "
        "WHERE closed_at IS NULL AND ar_period_year IS NOT NULL"
    )
    op.execute(_COMMENT)
    _rebuild(with_year=True)


def downgrade() -> None:
    # Reversible on purpose: CI's migrations job runs `upgrade head` then
    # `downgrade base`, so an irreversible migration breaks the pipeline. The
    # column itself stays — it is 003's, not this migration's.
    _rebuild(with_year=False)
    op.execute(f"DROP INDEX IF EXISTS public.{_YEAR_INDEX}")
    op.execute("COMMENT ON COLUMN public.nar1_cases.ar_period_year IS NULL")
