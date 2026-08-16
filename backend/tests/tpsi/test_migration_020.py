"""Migration 020 — the shared presenter credential schema.

DB-backed, per tests/tpsi/test_migration_016.py: runs only with RUN_DB_TESTS=1
against a database that has had `alembic upgrade head` applied. Skipped in the
mocked unit run.

Every test that writes rolls back — this runs against DEV on a developer machine
and must leave nothing behind.
"""
import os

import pytest

psycopg2 = pytest.importorskip("psycopg2")

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)


def _conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def test_the_shared_presenter_table_exists():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.tpsi_shared_presenter')")
        assert cur.fetchone()[0] is not None


@pytest.mark.parametrize("column", [
    "presentor_account_id", "tpsi_password_enc", "deposit_account_no",
    "tpsi_password_expires_at", "is_test", "last_rotated_at", "updated_by",
])
def test_it_carries_the_presenter_identity(column):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'tpsi_shared_presenter' AND column_name = %s",
            (column,),
        )
        assert cur.fetchone() is not None


def test_a_second_shared_credential_cannot_be_inserted():
    """The singleton property, exercised rather than asserted about: one GSHK
    filing identity, enforced by the schema rather than by hope."""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tpsi_shared_presenter "
                "(presentor_account_id, tpsi_password_enc) VALUES ('A', 'enc')"
            )
            with pytest.raises(psycopg2.errors.UniqueViolation):
                cur.execute(
                    "INSERT INTO tpsi_shared_presenter "
                    "(presentor_account_id, tpsi_password_enc) VALUES ('B', 'enc')"
                )
    finally:
        conn.rollback()
        conn.close()


def test_the_row_can_never_be_anything_but_the_singleton():
    """id is a boolean PK that must be true, so there is no second slot to
    insert into — not even by naming it explicitly."""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute(
                    "INSERT INTO tpsi_shared_presenter "
                    "(id, presentor_account_id, tpsi_password_enc) "
                    "VALUES (false, 'A', 'enc')"
                )
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.parametrize("column", ["presentor_account_id", "tpsi_password_enc"])
def test_the_per_user_credential_is_now_signing_only(column):
    """A user who only SIGNS must not be forced to hold a CR login password:
    since BE-5 the CR login is the shared record, and this table holds only the
    personal e-Service signing credential."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = 'tpsi_presenter_credentials' AND column_name = %s",
            (column,),
        )
        assert cur.fetchone()[0] == "YES"


def test_the_shared_config_code_is_seeded_as_a_g_flowdesk_event():
    """origin defaults to 'viewpoint' (migration 012's DDL). A code left on that
    default is mislabeled as an imported Viewpoint event in the audit UI — the
    exact defect migration 016 shipped with once."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT name, category, origin FROM audit_event_types "
            "WHERE code = 'TPSI_CRED_CONFIG'"
        )
        row = cur.fetchone()
    assert row is not None
    name, category, origin = row
    assert name == "CR Shared Presenter Configured"
    assert category == "tpsi"
    assert origin == "g_flowdesk"
