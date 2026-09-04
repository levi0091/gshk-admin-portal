"""Migration 035 — every filter the audit screen can send actually runs.

DB-backed and RUN_DB_TESTS-gated, per tests/test_migration_021..034.py.

WHY THIS FILE EXISTS AT ALL. Every unit test in this repo mocks PostgREST, so
none of them can tell a filter that works from one the database refuses. The
audit log's search box was timing out on DEV before any of this work started,
and nothing in the suite noticed, because a mock answers instantly whatever the
query would have cost. These tests run the real queries against the real table.

They assert PLANS, not wall-clock times. A timing assertion on a shared DEV
database is a flake generator; "does this use the trigram index" is the fact
that actually decides whether the page loads, and it is stable.
"""
import os

import pytest

from routers import audit as audit_router

psycopg2 = pytest.importorskip("psycopg2")

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)

#: Mirrors migration 035. Named here rather than imported because the migration
#: module is not importable as a package path on every checkout.
TRIGRAM_COLUMNS = [
    "company_name", "subject_ref", "action_label", "user_display_name",
    "event_code", "created_by", "new_value", "old_value",
]

#: The eight terms routers/audit.py ORs together for the search box.
SEARCH_COLUMNS = [
    "company_name", "subject_ref", "action_label", "event_code",
    "user_display_name", "created_by", "old_value", "new_value",
]


@pytest.fixture
def conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    c = psycopg2.connect(url)
    c.autocommit = True
    try:
        yield c
    finally:
        c.close()


#: Below this, a query plan says nothing. CI runs these against an EMPTY
#: `audit_log` (the `migrations` job applies the whole chain to a fresh
#: Postgres), and on a table of a few rows the planner correctly prefers a
#: sequential scan over any index — so asserting "it used the trigram index"
#: there would fail on a database where nothing is wrong. The index-EXISTENCE
#: tests still run everywhere; only the plan assertions need real rows, and DEV
#: has 226k of them.
_PLAN_MIN_ROWS = 5_000


@pytest.fixture
def plan(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM public.audit_log")
        rows = cur.fetchone()[0]
    if rows < _PLAN_MIN_ROWS:
        pytest.skip(
            f"audit_log has {rows} rows; a plan over fewer than "
            f"{_PLAN_MIN_ROWS} is a sequential scan whatever the indexes are. "
            f"Run against DEV to exercise these."
        )

    def run(sql):
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '60s'")
            cur.execute("EXPLAIN (FORMAT TEXT) " + sql)
            return "\n".join(line for (line,) in cur.fetchall())

    return run


def test_pg_trgm_is_installed(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM pg_extension WHERE extname = 'pg_trgm'")
        assert cur.fetchone()[0] == 1, "pg_trgm is not installed — did 035 run?"


def test_every_trigram_index_exists(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT indexname FROM pg_indexes "
                    "WHERE schemaname='public' AND tablename='audit_log'")
        names = {r[0] for r in cur.fetchall()}
    missing = [c for c in TRIGRAM_COLUMNS if f"trgm_audit_log_{c}" not in names]
    assert not missing, f"no trigram index on {missing}"
    assert "idx_audit_log_module_kind_created" in names


def test_every_search_column_has_a_trigram_index(conn):
    """The search box ORs eight `ilike`s. One unindexed column in that OR is a
    sequential scan of the whole table, and the operator sees only the
    browser's own "Failed to fetch"."""
    with conn.cursor() as cur:
        cur.execute("SELECT indexname FROM pg_indexes "
                    "WHERE schemaname='public' AND tablename='audit_log'")
        names = {r[0] for r in cur.fetchall()}
    missing = [c for c in SEARCH_COLUMNS if f"trgm_audit_log_{c}" not in names]
    assert not missing, f"search ORs an unindexed ilike on {missing}"


@pytest.mark.parametrize("column", TRIGRAM_COLUMNS)
def test_a_contains_filter_uses_its_trigram_index(plan, column):
    out = plan(f"SELECT * FROM public.audit_log "
               f"WHERE {column} ILIKE '%zqx%' "
               f"ORDER BY created_at DESC LIMIT 100")
    assert f"trgm_audit_log_{column}" in out, out


def test_the_search_box_never_falls_back_to_a_sequential_scan(plan):
    """The whole eight-term OR, exactly as routers/audit.py builds it.

    One unindexed column in that OR is enough to scan the whole table, which is
    how the box came to time out on a real BRN while a common word worked.
    """
    terms = " OR ".join(f"{c} ILIKE '%T0001138%'" for c in SEARCH_COLUMNS)
    out = plan(f"SELECT * FROM public.audit_log WHERE {terms} "
               f"ORDER BY created_at DESC LIMIT 100")
    assert "Seq Scan on audit_log" not in out, out


def test_two_enum_filters_that_match_nothing_return_immediately(plan):
    """The pathological case for a paginated listing: with separate indexes,
    Postgres walks the whole table in date order to prove the answer is empty —
    25 seconds to render "no rows"."""
    out = plan("SELECT * FROM public.audit_log "
               "WHERE module = 'body_corporate' AND subject_kind = 'person' "
               "ORDER BY created_at DESC LIMIT 100")
    assert "idx_audit_log_module_kind_created" in out, out


def test_every_filterable_text_column_the_router_offers_is_indexed(conn):
    """The list that must not drift.

    A column added to `_FILTERABLE` as `tf.text()` accepts `contains`, and
    without a trigram index that filter is a sequential scan. This ties the
    router's own spec to the indexes rather than to a comment.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT indexname FROM pg_indexes "
                    "WHERE schemaname='public' AND tablename='audit_log'")
        names = {r[0] for r in cur.fetchall()}
    unindexed = [
        name for name, column in audit_router._FILTERABLE.items()
        if column.kind == "text" and f"trgm_audit_log_{name}" not in names
    ]
    assert not unindexed, (
        f"routers/audit._FILTERABLE offers `contains` on {unindexed} with no "
        f"trigram index — add them to migration 035's TRIGRAM_COLUMNS"
    )
