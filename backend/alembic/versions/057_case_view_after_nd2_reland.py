"""The case registry after ND2A/ND2B met the duplicate-submission fix.

WHY THIS MIGRATION EXISTS. Two lines of work each restated `nar1_case_registry`
from a different ancestor, and `CREATE VIEW` takes the whole definition:

  * 056 (master, the PROD hotfix of 2026-10-26) rebuilt 047's view so a case
    whose filing is `submitting` or `submission_unknown` is at Submission, a
    stale claim reads as `submission_unknown`, and the filing pick prefers a row
    CR may hold.
  * 050, 052 and 054 (the ND2A/ND2B work, re-landed on top of 056) rebuilt
    047's view again, from 047's text, for the officer-change columns, the
    e-Sign branch and the removal of the CR status. Run after 056, each of them
    silently dropped 056's four differences.

This restates the ND2 view as it stands after 054 -- built from 054's own
`view_sql()`, so nothing else can drift -- with 056's four differences put back,
and with the e-Sign Signing branch taught the two new stages as well (a case
whose submit is in flight is AT Submission, not back at Signing).

The four differences from 054's view and no others, each pinned by
tests/test_migration_057.py:

  1. LIVE_STAGES gains `submitting` and `submission_unknown`.
  2. The Submission branch gains the same two.
  3. A `submitting` claim older than 370 s (or with no start time) reads as
     `submission_unknown` in `filing_stage`. Read only; the row itself is moved
     by the reads that carry an audit row, never by a listing.
  4. The filing pick prefers a row CR may hold, as it already preferred a filed
     one.

plus the e-Sign branch's list of live stages, which mirrors
`nar1_case_status._code` (parity is tests/test_migration_024.py).

The stage CHECK is NOT restated here: 054 restates it, and 054 includes
`submitting` and `submission_unknown`.

Nothing is written to any row. REVERSIBLE: the downgrade restores 054's view.

Revision ID: 057
Revises: 055
"""
import importlib.util
from pathlib import Path

from alembic import op

revision = "057"
down_revision = "055"
branch_labels = None
depends_on = None

NEW_STAGES = ("submitting", "submission_unknown")

#: 050's lists as 054 inherits them, and the lists they become.
OLD_LIVE = ("validated", "signed", "signing_failed", "submission_failed")
LIVE_STAGES = OLD_LIVE + NEW_STAGES
OLD_AT_SUBMISSION = ("signed", "submission_failed")
SUBMISSION_STAGES = OLD_AT_SUBMISSION + NEW_STAGES

#: 054's filed stages (`registered` is gone with the CR status poll).
FILED_STAGES = ("submitted", "edrive")

#: services/tpsi/filings.STALE_CLAIM_SECONDS -- derived there from every httpx
#: timeout phase, mirrored in 056, and kept equal by a test.
STALE_CLAIM_SECONDS = 370


def _load(name: str):
    """A sibling migration's module, loaded by path: the versions directory is
    not a package."""
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(f"m{name[:3]}_for_057", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _m054():
    return _load("054_cr_status_removed.py")


def _m050():
    return _load("050_officer_changes_nd2a_nd2b.py")


def _quoted(stages) -> str:
    return ", ".join(f"'{s}'" for s in stages)


def _swap(sql: str, old: str, new: str, count: int) -> str:
    if sql.count(old) != count:
        raise RuntimeError(
            f"054's view no longer has {count} x {old!r} where 057 expects it")
    return sql.replace(old, new)


def previous_view_sql() -> str:
    """054's case registry -- the downgrade target."""
    return _m054().view_sql()


def view_sql() -> str:
    sql = previous_view_sql()

    # 1. LIVE_STAGES, in the data-verification branch.
    sql = _swap(sql, f"filing_stage NOT IN ({_quoted(OLD_LIVE)})",
                f"filing_stage NOT IN ({_quoted(LIVE_STAGES)})", 1)

    # 2. The Submission branch.
    sql = _swap(
        sql,
        "WHEN base.filing_stage IN ('signed',\n"
        "                                         'submission_failed') THEN 'submission'",
        f"WHEN base.filing_stage IN ({_quoted(SUBMISSION_STAGES)}) THEN 'submission'",
        1)

    # The e-Sign branch's list of stages in which a live filing exists.
    sql = _swap(
        sql,
        "AND (base.filing_stage IS NULL\n"
        "                    OR base.filing_stage NOT IN ('validated', 'signed',\n"
        "                                                 'signing_failed',\n"
        "                                                 'submission_failed')) THEN 'signing'",
        "AND (base.filing_stage IS NULL\n"
        f"                    OR base.filing_stage NOT IN ({_quoted(LIVE_STAGES)})) THEN 'signing'",
        1)

    # 3. A stale claim reads as the unknown outcome it is.
    sql = _swap(
        sql,
        "SELECT tf.id, tf.stage\n",
        "SELECT tf.id,\n"
        "                     -- A claim no live request can answer reads as the\n"
        "                     -- unknown outcome it is (filings.is_stale_claim).\n"
        "                     CASE\n"
        "                       WHEN tf.stage = 'submitting'\n"
        "                        AND (tf.submit_started_at IS NULL\n"
        "                             OR tf.submit_started_at\n"
        f"                                < now() - interval '{STALE_CLAIM_SECONDS} seconds')\n"
        "                       THEN 'submission_unknown'\n"
        "                       ELSE tf.stage\n"
        "                     END AS stage\n",
        1)

    # 4. The filing pick prefers a row CR may hold.
    sql = _swap(sql, f"ORDER BY (tf.stage IN ({_quoted(FILED_STAGES)})) DESC",
                f"ORDER BY (tf.stage IN ({_quoted(FILED_STAGES + NEW_STAGES)})) DESC", 1)
    return sql


def _rebuild_view(sql: str) -> None:
    m50 = _m050()
    op.execute(f"DROP VIEW IF EXISTS {m50.CASE_VIEW};")
    op.execute(sql)
    op.execute(m50._CASE_GRANTS)


def upgrade() -> None:
    _rebuild_view(view_sql())


def downgrade() -> None:
    _rebuild_view(previous_view_sql())
