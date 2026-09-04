"""Migration 037 — a document is filed under its OWNER's module.

DB-backed and RUN_DB_TESTS-gated, per tests/test_migration_021..036.py.

NAMED `test_migration_037.py` ON PURPOSE. `.github/workflows/backend-ci.yml`
runs DB-backed tests as `pytest tests/test_migration_*.py` under RUN_DB_TESTS=1;
a file outside that glob is skipped by the `unit` job and never collected by the
`migrations` job, so it would run nowhere at all.

WHY THIS IS DB-BACKED AND NOT A UNIT TEST. Every unit test in this repo mocks
PostgREST, so none of them can see a stored row. The complaint was about rows
already in the table — an id scan on Brian YIU sitting under "Documents" while
an edit to Brian YIU sat under "Natural Person" — and the only place that is
observable is the database. The unit suite covers what the WRITER does from
here on (tests/test_documents.py, tests/test_audit_subject.py); this covers
what happened to the 15 rows that were already there.

Every fixture is rolled back.
"""
import os

import pytest

from services import audit_subject

psycopg2 = pytest.importorskip("psycopg2")

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)


@pytest.fixture
def conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    c = psycopg2.connect(url)
    try:
        yield c
    finally:
        c.rollback()
        c.close()


def test_no_row_is_labelled_with_the_documents_module(conn):
    """The migration's whole job. `documents` is not in the vocabulary any more,
    so a row still carrying it is unreachable from the Module filter — it would
    render a label the enum cannot offer and match no filter value at all."""
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM audit_log WHERE module = 'documents'")
    assert cur.fetchone()[0] == 0


def test_every_module_in_the_table_is_one_the_filter_offers(conn):
    """A module the enum will not name is a row the screen cannot filter to.
    NULL is allowed and expected — it is what an imported Viewpoint row whose
    subject never resolved honestly has."""
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT module FROM audit_log WHERE module IS NOT NULL")
    stored = {r[0] for r in cur.fetchall()}
    assert stored <= set(audit_subject.MODULES), stored - set(audit_subject.MODULES)


def test_a_document_row_agrees_with_its_own_subject_kind(conn):
    """The rule, stated as an invariant rather than as a count: whatever the row
    is ABOUT decides which module it is filed under. This is what makes
    "everything that happened to this director" answerable in one filter."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT subject_kind, module, count(*)
        FROM audit_log
        WHERE source = 'g_flowdesk' AND entity_type = 'document'
          AND subject_kind IS NOT NULL
        GROUP BY 1, 2
        """
    )
    expected = {
        "person": audit_subject.NATURAL_PERSON,
        "company": audit_subject.BODY_CORPORATE,
        "case": audit_subject.POST_INCORPORATION,
    }
    rows = cur.fetchall()
    assert rows, "no document audit rows at all — the backfill proved nothing"
    for kind, module, count in rows:
        assert module == expected[kind], f"{count} document rows: {kind} -> {module}"


def test_a_document_lands_where_that_records_other_edits_land(conn):
    """The complaint, as a query. For every person who has BOTH a document event
    and an ordinary edit, the two must carry the same module — that split was
    the bug, and a count of correctly-labelled rows would not have caught it."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT subject_id, array_agg(DISTINCT module) AS modules
        FROM audit_log
        WHERE source = 'g_flowdesk' AND subject_kind = 'person'
          AND subject_id IS NOT NULL AND module IS NOT NULL
        GROUP BY subject_id
        HAVING count(DISTINCT module) > 1
        """
    )
    split = cur.fetchall()
    assert not split, f"one person's history is spread across modules: {split}"
