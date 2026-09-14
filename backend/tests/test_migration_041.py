"""Migration 041 — a client's VIP status.

DB-backed and RUN_DB_TESTS-gated, per tests/test_migration_021..038.py, and
named `test_migration_*.py` so the CI `migrations` job collects it.

What each assertion is here for, rather than in the unit suite:

  * the two columns exist, are boolean and NOT NULL DEFAULT false. Every unit
    test mocks PostgREST, so a column that was never added passes them all and
    then 500s the first VIP toggle.
  * there is NO `is_vip` column. The verdict is derived from the company count
    on every read; a stored one would stay true after a client dropped below
    the threshold.
  * the audit labels are seeded — an unlabelled field renders as a raw column
    name in the trail, silently.

Every fixture is rolled back. This runs against DEV on a developer machine and
must leave nothing behind.
"""
import os

import pytest

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


def _column(cur, name):
    cur.execute(
        """
        SELECT data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'persons'
          AND column_name = %s
        """,
        (name,),
    )
    return cur.fetchone()


@pytest.mark.parametrize("name", ["is_affiliated_agent", "is_vip_marked"])
def test_the_stored_inputs_are_non_null_booleans_defaulting_to_false(conn, name):
    with conn.cursor() as cur:
        data_type, nullable, default = _column(cur, name)
    assert data_type == "boolean"
    assert nullable == "NO"
    assert "false" in str(default).lower()


def test_the_verdict_itself_is_not_stored(conn):
    """Derived on read, so it cannot go stale in the direction that matters."""
    with conn.cursor() as cur:
        assert _column(cur, "is_vip") is None


def test_an_existing_person_reads_as_a_standard_client(conn):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO persons (full_name) VALUES ('Migration 041 Probe') "
            "RETURNING is_affiliated_agent, is_vip_marked")
        assert cur.fetchone() == (False, False)
    conn.rollback()


def test_the_new_fields_are_labelled_in_the_audit_trail(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT field, label FROM audit_field_labels WHERE field = ANY(%s)",
            (["is_affiliated_agent", "is_vip_marked"],),
        )
        labels = dict(cur.fetchall())
    assert labels == {"is_affiliated_agent": "Affiliated Agent",
                      "is_vip_marked": "Marked as VIP"}
