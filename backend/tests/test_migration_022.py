"""Migration 022 — seeds CASE_STATUS_CHANGED / CASE_FIELD_UPDATED into
audit_event_types.

DB-backed, per tests/test_migration_021.py: runs only with RUN_DB_TESTS=1
against a database that has had `alembic upgrade head` applied. Skipped in the
mocked unit run.

RED is not reproducible against DEV: DEV already carries both rows (that is
the whole reason this migration exists — see 022's docstring), so this suite
passes there whether or not 022 is applied. The real RED/GREEN distinction is
on a FRESH database — CI's `migrations` job builds one from revision 1 and
applies every migration in order, so it is the only place these two rows are
ever actually absent before this migration runs.
"""
import os

import pytest

psycopg2 = pytest.importorskip("psycopg2")

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)

EXPECTED = {
    "CASE_STATUS_CHANGED": ("Status Changed", "entity", "g_flowdesk"),
    "CASE_FIELD_UPDATED": ("Company Details Changed", "entity", "g_flowdesk"),
}


def _conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


@pytest.mark.parametrize("code", sorted(EXPECTED))
def test_case_event_code_is_seeded(code):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT name, category, origin FROM audit_event_types WHERE code = %s",
            (code,),
        )
        row = cur.fetchone()
    assert row is not None, f"{code} is not seeded in audit_event_types"
    assert row == EXPECTED[code]


def test_neither_code_defaulted_to_the_viewpoint_origin():
    """origin defaults to 'viewpoint' (migration 012's DDL). A native
    G-FlowDesk event left on that default is mislabeled as an imported
    Viewpoint event in the audit UI -- the exact defect migration 016 shipped
    with once, and the reason 016/020/021 all set origin explicitly."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT code, origin FROM audit_event_types "
            "WHERE code IN ('CASE_STATUS_CHANGED', 'CASE_FIELD_UPDATED')"
        )
        rows = cur.fetchall()
    assert len(rows) == 2
    for code, origin in rows:
        assert origin == "g_flowdesk", f"{code} has origin={origin!r}"
