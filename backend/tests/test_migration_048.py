"""Migration 048 — person_registry is no longer readable with the anon key.

The pure half pins the SQL. The DB half (RUN_DB_TESTS, collected by the
`tests/test_migration_*.py` glob in backend-ci.yml) asks Postgres itself, which
is the only answer that counts: CI creates all three Supabase role stand-ins, so
`has_table_privilege` is a real check there, not a skip.
"""
import importlib.util
import os

import pytest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M048 = "048_person_registry_not_public.py"


def _migration():
    path = os.path.join(_HERE, "alembic", "versions", M048)
    spec = importlib.util.spec_from_file_location("m048", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_both_client_roles_lose_everything_and_the_service_role_keeps_select():
    sql = _migration()._LOCK_DOWN
    assert "REVOKE ALL ON public.person_registry FROM anon" in sql
    assert "REVOKE ALL ON public.person_registry FROM authenticated" in sql
    assert "GRANT SELECT ON public.person_registry TO service_role" in sql
    assert "GRANT SELECT ON public.person_registry TO anon" not in sql
    assert "TO authenticated" not in sql


def test_the_downgrade_never_republishes_the_view():
    """A faithful reversal would GRANT anon again. It must not."""
    src = open(os.path.join(_HERE, "alembic", "versions", M048),
               encoding="utf-8").read()
    body = src.split("def downgrade", 1)[1]
    assert "GRANT" not in body


db = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)


@pytest.fixture
def conn():
    psycopg2 = pytest.importorskip("psycopg2")
    connection = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


@db
@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_no_client_role_can_select_the_view(conn, role):
    with conn.cursor() as cur:
        cur.execute("SELECT has_table_privilege(%s, 'public.person_registry', "
                    "'SELECT')", (role,))
        assert cur.fetchone()[0] is False


@db
def test_the_view_runs_with_the_callers_rights(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT reloptions FROM pg_class "
                    "WHERE oid = 'public.person_registry'::regclass")
        assert "security_invoker=true" in (cur.fetchone()[0] or [])


@db
def test_no_public_view_bypasses_rls_for_a_client_role(conn):
    """The sweep that found this, kept as a guard for the next VIEW.

    A view that is not security_invoker, and that anon or authenticated can
    SELECT, is readable with the key the frontend ships.

    VIEWS ONLY, deliberately. The sweep on DEV and PROD also covered tables and
    found them all protected -- but RLS on several of them (lookup_values,
    audit_field_labels, entity_record_locations) was switched on in Supabase,
    not by a migration, so CI's vanilla Postgres has it off. A table assertion
    here tested a configuration this database does not reproduce, and turned
    Backend CI red on the commit that closed the leak.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.relname
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind IN ('v', 'm')
              AND (has_table_privilege('anon', c.oid, 'SELECT')
                   OR has_table_privilege('authenticated', c.oid, 'SELECT'))
              AND NOT coalesce('security_invoker=true' = ANY (c.reloptions), false)
        """)
        assert [r[0] for r in cur.fetchall()] == []
