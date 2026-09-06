"""Migration 031 — users.must_change_password.

DB-backed, per tests/test_migration_021.py onwards: runs only with
RUN_DB_TESTS=1 against a database that has had `alembic upgrade head` applied.
Skipped in the mocked unit run.

The failure this file is written to catch is not a missing column — that shows
up immediately — but a column with the WRONG DEFAULT. `must_change_password`
defaulting to TRUE would lock every existing user out of the portal on the
morning this deploys, including the only super_admin, and the only way back in
would be a manual UPDATE against production.
"""
import os

import pytest

psycopg2 = pytest.importorskip("psycopg2")

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)

COLUMN = "must_change_password"


def _conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def _column() -> tuple | None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'users' "
            "AND column_name = %s",
            (COLUMN,),
        )
        return cur.fetchone()


def test_the_column_exists():
    assert _column() is not None, f"users.{COLUMN} was not created"


def test_it_is_a_boolean_and_never_null():
    """A three-state flag would make "unset" a state the middleware has to
    decide about, and the safe reading of unset is not obvious."""
    data_type, is_nullable, _ = _column()
    assert data_type == "boolean"
    assert is_nullable == "NO"


def test_it_defaults_to_FALSE():
    """THE ONE THAT MATTERS. TRUE would lock every existing user out of the
    portal the moment this deploys — including the only super_admin, whose
    account is the one that would have to fix it."""
    _, _, default = _column()
    assert default is not None
    assert "false" in default.lower()


def test_no_existing_user_was_flipped_by_the_migration():
    """The backfill is deliberately absent. Those users chose or were given a
    password under the old flow and have been signing in with it."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM users WHERE {COLUMN} IS TRUE "
                    "AND created_at < now() - interval '1 day'")
        assert cur.fetchone()[0] == 0


def test_the_flag_can_be_written_and_read_back():
    """information_schema says the column is declared; this says the database
    accepts a value in it."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT id, {COLUMN} FROM users LIMIT 1")
        row = cur.fetchone()
        if row is None:
            pytest.skip("no users rows in this database to round-trip")
        user_id, original = row
        cur.execute(
            f"UPDATE users SET {COLUMN} = true WHERE id = %s RETURNING {COLUMN}",
            (user_id,),
        )
        assert cur.fetchone()[0] is True
        # Put it back exactly as it was — leaving a real account flagged would
        # lock that person out of the portal.
        cur.execute(f"UPDATE users SET {COLUMN} = %s WHERE id = %s",
                    (original, user_id))
