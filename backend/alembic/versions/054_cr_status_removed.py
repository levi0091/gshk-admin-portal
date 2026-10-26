"""CR status removed: a filed case reads 'filed' (Levi 2026-10-17).

Design: `docs/superpowers/specs/2026-10-17-cr-status-removal-and-confirmation-receipt-design.md` §3.

CR will not report a document's status after filing through docStatusEnquiry
("at best we will know that the submission was successful and we get payment
details and receipt"), so the CR status poll, the sixth workflow stage and the
six CR codes are gone. This reverses migrations 043 and 044 on the live schema
and patches the records they left:

  nar1_case_registry (restated)
      052's view with the filed branch reading 'filed' instead of CR's stored
      answer, no `cr_*` columns, `registered` out of the filed stages, and the
      overdue rule's finished list ('filed', 'closed'). Built from 052's own
      `view_sql`, so nothing else can drift.

  tpsi_filings.stage 'registered' -> 'submitted', and the stage CHECK without
      'registered'. The poll was the only writer of that stage.

  trg_set_updated_at on nar1_cases back to unconditional (044 reverted). It is
      rebuilt BEFORE the columns go: its WHEN clause names cr_status_checked_at,
      and DROP COLUMN ... CASCADE would drop the trigger instead.

  nar1_cases.cr_doc_status, cr_doc_status_code, cr_status_checked_at,
      cr_document_ref_no dropped, with 043's CHECK and partial index.

The audit codes 043 seeded (TPSI_DOC_STATUS_CHECKED, NAR1_CR_STATUS_CHANGED)
STAY: rows exist and the trail must keep labelling them. No audit row changes.

DEPLOY ORDER: code first, then this migration (jobs/README.md). The new backend
reads the old view's CR codes as 'filed'; the old one has no label for 'filed'.

REVERSIBLE. The downgrade re-adds the columns (empty), 043's CHECK, index and
comments, 044's trigger, 056's stage list (018's ten and the two it added) and 052's view. It does not turn any
filing back into 'registered': that answer came from the poll, which the
downgraded code would run again.

Revision ID: 054
Revises: 053
"""
import importlib.util
from pathlib import Path

from alembic import op

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None

#: services/nar1_case_status.FILED.
FILED = "filed"

#: services/nar1_cases.CR_FILED_STAGES — `registered` out.
CR_FILED_STAGES = ("submitted", "edrive")

#: Every stage tpsi_filings may hold: 018's list without `registered`, plus the
#: two 056 added. 054 restates the CHECK from a literal list, so leaving them
#: out would make the constraint refuse the very stages the duplicate-submission
#: fix writes (2026-10-27, when the ND2 chain was re-landed on top of 056).
FILING_STAGES = (
    "draft", "validated", "validation_failed", "signed", "signing_failed",
    "submitted", "submission_failed", "superseded", "edrive",
    "submitting", "submission_unknown",
)

_TABLE = "public.nar1_cases"
_TRIGGER = "trg_set_updated_at"


def _load(name: str):
    """A sibling migration's module, loaded by path: the versions directory is
    not a package."""
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(f"m{name[:3]}_for_054", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _m052():
    return _load("052_nd2_feedback.py")


def _m043():
    return _load("043_nar1_cr_document_status.py")


def _m044():
    return _load("044_updated_at_ignores_the_cr_heartbeat.py")


def _m056():
    """056's full list: 018's ten (with `registered`) and its two."""
    return _load("056_nar1_submit_outcome_unknown.py")


def _swap(sql: str, old: str, new: str, count: int) -> str:
    if sql.count(old) != count:
        raise RuntimeError(f"052's view no longer has {count} x {old!r} where 054 expects it")
    return sql.replace(old, new)


def previous_view_sql() -> str:
    """052's case registry — the downgrade target."""
    return _m052().view_sql()


def view_sql() -> str:
    """052's case registry, CR status removed, nothing else changed."""
    m50 = _m052()._m050()
    sql = previous_view_sql()
    sql = _swap(sql, f"THEN COALESCE(base.cr_doc_status_code, '{m50.CR_NOT_CHECKED}')",
                f"THEN '{FILED}'", 1)
    old_filed = ", ".join(f"'{s}'" for s in m50.CR_FILED_STAGES)
    sql = _swap(sql, f"({old_filed})", "(" + ", ".join(f"'{s}'" for s in CR_FILED_STAGES) + ")", 2)
    old_finished = ", ".join(f"'{c}'" for c in m50.CR_STATUS_CODES) + ", 'closed'"
    sql = _swap(sql, f"coded.workflow_status NOT IN ({old_finished})",
                f"coded.workflow_status NOT IN ('{FILED}', 'closed')", 1)
    for column in ("cr_doc_status", "cr_doc_status_code", "cr_status_checked_at"):
        sql = _swap(sql, f"              c.{column},\n", "", 1)
    return sql


def _rebuild_view(sql: str) -> None:
    m50 = _m052()._m050()
    op.execute(f"DROP VIEW IF EXISTS {m50.CASE_VIEW};")
    op.execute(sql)
    op.execute(m50._CASE_GRANTS)


def _trigger(when: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON {_TABLE};")
    op.execute(f"CREATE TRIGGER {_TRIGGER} BEFORE UPDATE ON {_TABLE} "
               f"FOR EACH ROW {when} EXECUTE FUNCTION set_updated_at();")


def _stage_check(stages) -> None:
    op.execute("ALTER TABLE public.tpsi_filings "
               "DROP CONSTRAINT IF EXISTS tpsi_filings_stage_check")
    values = ", ".join(f"'{s}'" for s in stages)
    op.execute("ALTER TABLE public.tpsi_filings "
               "ADD CONSTRAINT tpsi_filings_stage_check "
               f"CHECK (stage IN ({values}))")


def upgrade() -> None:
    # The view first: it selects the columns dropped below.
    _rebuild_view(view_sql())
    op.execute("UPDATE public.tpsi_filings SET stage = 'submitted' "
               "WHERE stage = 'registered'")
    _stage_check(FILING_STAGES)
    # Unconditional again, before the column its WHEN clause names is dropped.
    _trigger("")
    op.execute("DROP INDEX IF EXISTS public.ix_nar1_cases_cr_status_open")
    op.execute("ALTER TABLE public.nar1_cases "
               "DROP CONSTRAINT IF EXISTS nar1_cases_cr_doc_status_code_check")
    op.execute("""
        ALTER TABLE public.nar1_cases
          DROP COLUMN IF EXISTS cr_document_ref_no,
          DROP COLUMN IF EXISTS cr_status_checked_at,
          DROP COLUMN IF EXISTS cr_doc_status_code,
          DROP COLUMN IF EXISTS cr_doc_status;
    """)


def downgrade() -> None:
    m43 = _m043()
    codes = ", ".join(f"'{c}'" for c in m43.CR_STATUS_CODES)
    op.execute("""
        ALTER TABLE public.nar1_cases
          ADD COLUMN IF NOT EXISTS cr_doc_status        text,
          ADD COLUMN IF NOT EXISTS cr_doc_status_code   text,
          ADD COLUMN IF NOT EXISTS cr_status_checked_at timestamptz,
          ADD COLUMN IF NOT EXISTS cr_document_ref_no   text;
    """)
    op.execute("ALTER TABLE public.nar1_cases "
               "DROP CONSTRAINT IF EXISTS nar1_cases_cr_doc_status_code_check")
    op.execute("ALTER TABLE public.nar1_cases "
               "ADD CONSTRAINT nar1_cases_cr_doc_status_code_check "
               f"CHECK (cr_doc_status_code IS NULL OR cr_doc_status_code IN ({codes}))")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_nar1_cases_cr_status_open "
        "ON public.nar1_cases (cr_status_checked_at NULLS FIRST) "
        "WHERE closed_at IS NULL "
        "  AND (cr_doc_status_code IS NULL "
        "       OR cr_doc_status_code NOT IN ('cr_registered', 'cr_rejected'))"
    )
    op.execute(m43._COMMENTS)
    _trigger(_m044()._WHEN)
    _stage_check(_m056().STAGES)
    _rebuild_view(previous_view_sql())
