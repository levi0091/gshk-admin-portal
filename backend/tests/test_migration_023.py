"""Migration 023 — nar1_cases.manual_signed_document_version.

DB-backed, per tests/test_migration_021.py and tests/test_migration_022.py: runs
only with RUN_DB_TESTS=1 against a database that has had `alembic upgrade head`
applied. Skipped in the mocked unit run.

RED is reproducible here, unlike 022's: the column genuinely does not exist on
DEV before this migration runs, so this suite fails against DEV at revision 022
and passes at 023.
"""
import os

import pytest

psycopg2 = pytest.importorskip("psycopg2")

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)

COLUMN = "manual_signed_document_version"


def _conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def _column() -> tuple | None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'nar1_cases' "
            "AND column_name = %s",
            (COLUMN,),
        )
        return cur.fetchone()


def test_the_version_column_exists():
    assert _column() is not None, f"nar1_cases.{COLUMN} was not created"


def test_the_version_column_is_an_integer():
    """A version NUMBER. Stored as text it would sort '10' before '2' in every
    query that tries to find the latest evidence."""
    assert _column()[0] == "integer"


def test_the_version_column_is_nullable():
    """NULL means 'signed before this column existed'. NOT NULL would have
    forced a backfill inventing a version for rows this migration cannot verify,
    and would break every case that never went down the manual path at all."""
    assert _column()[1] == "YES"


def test_the_pair_it_forms_resolves_against_document_versions():
    """The whole point: (manual_signed_document_id, manual_signed_document_version)
    must be the key document_versions is actually stored under, or the pointer is
    still unresolvable."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'document_versions' "
            "AND column_name IN ('document_id', 'version_number')"
        )
        found = {row[0] for row in cur.fetchall()}
    assert found == {"document_id", "version_number"}


def test_a_version_can_actually_be_written_and_read_back():
    """information_schema says the column is declared; this says the database
    accepts a value in it. A CHECK or a trigger could still refuse one."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT id, {COLUMN} FROM nar1_cases LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            pytest.skip("no nar1_cases rows in this database to round-trip")
        case_id, original = row
        cur.execute(
            f"UPDATE nar1_cases SET {COLUMN} = 7 WHERE id = %s RETURNING {COLUMN}",
            (case_id,),
        )
        assert cur.fetchone()[0] == 7
        # Insert-only tables are audit_log's rule, not this one -- put the row
        # back exactly as it was rather than leaving a fabricated version behind.
        cur.execute(
            f"UPDATE nar1_cases SET {COLUMN} = %s WHERE id = %s",
            (original, case_id),
        )
