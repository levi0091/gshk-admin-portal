"""Migration 059 -- `officer_change_signatures`, a director's drawn signature
(Levi 2026-10-29, e-signature-nd2).

File-level assertions, which run everywhere, and DB-backed ones gated on
RUN_DB_TESTS in the style of test_migration_058.py. The file-level half is what
catches a missing UNIQUE or a forgotten RLS: every unit test mocks PostgREST, so
neither would fail anywhere else -- and a signature table with RLS off is
readable with the public anon key.
"""
import importlib.util
import os
import re
from unittest.mock import patch

import pytest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M059 = "059_officer_change_signatures.py"


def _migration():
    path = os.path.join(_HERE, "alembic", "versions", M059)
    spec = importlib.util.spec_from_file_location("m059", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _statements(direction: str) -> str:
    m = _migration()
    seen: list[str] = []
    with patch.object(m.op, "execute", side_effect=lambda sql: seen.append(str(sql))):
        getattr(m, direction)()
    return re.sub(r"\s+", " ", " ".join(seen))


def test_059_revises_058_and_is_the_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    m = _migration()
    assert (m.revision, m.down_revision) == ("059", "058")
    script = ScriptDirectory.from_config(Config(os.path.join(_HERE, "alembic.ini")))
    assert script.get_heads() == ["060"]


def test_the_table_has_the_spec_columns():
    sql = _statements("upgrade")
    assert "CREATE TABLE public.officer_change_signatures" in sql
    for column in ("id uuid PRIMARY KEY DEFAULT gen_random_uuid()",
                   "case_id uuid NOT NULL",
                   "approval_id uuid NOT NULL",
                   "person_id uuid NOT NULL",
                   "revision integer NOT NULL",
                   # text, not bytea: PostgREST exchanges bytea as \x<hex>.
                   "image_b64 text NOT NULL",
                   "signed_at timestamptz NOT NULL DEFAULT now()"):
        assert column in sql, column
    assert "bytea" not in sql.lower()


def test_the_foreign_keys_name_the_case_and_the_approval_row():
    sql = _statements("upgrade")
    assert "REFERENCES public.nar1_cases(id) ON DELETE CASCADE" in sql
    assert "REFERENCES public.nar1_client_approvals(id)" in sql


def test_one_signature_per_press_is_unique_on_the_approval():
    sql = _statements("upgrade")
    assert "approval_id uuid NOT NULL UNIQUE" in sql


def test_rls_is_on_and_no_policy_is_created():
    """Service role only, as the approval tokens table: with RLS on and no
    policy, anon and authenticated read nothing."""
    sql = _statements("upgrade")
    assert ("ALTER TABLE public.officer_change_signatures "
            "ENABLE ROW LEVEL SECURITY") in sql
    assert "CREATE POLICY" not in sql.upper()


def test_anon_and_authenticated_keep_no_grant():
    """Drawn signatures are personal data: locked down as migration 050 does,
    so a stray policy later cannot expose them through PostgREST either."""
    sql = _statements("upgrade")
    assert "REVOKE ALL ON public.officer_change_signatures FROM anon" in sql
    assert "REVOKE ALL ON public.officer_change_signatures FROM authenticated" in sql


def test_the_downgrade_drops_the_table():
    assert "DROP TABLE IF EXISTS public.officer_change_signatures" in _statements("downgrade")


_db = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)


@pytest.fixture
def conn():
    psycopg2 = pytest.importorskip("psycopg2")
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    c = psycopg2.connect(url)
    try:
        yield c
    finally:
        c.rollback()
        c.close()


@_db
def test_db_rls_enabled_and_no_policies(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT relrowsecurity FROM pg_class "
                    "WHERE oid = 'public.officer_change_signatures'::regclass")
        assert cur.fetchone() == (True,)
        cur.execute("SELECT count(*) FROM pg_policies "
                    "WHERE tablename = 'officer_change_signatures'")
        assert cur.fetchone() == (0,)


@_db
def test_db_approval_id_is_unique(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM pg_indexes WHERE tablename = "
                    "'officer_change_signatures' AND indexdef ILIKE '%UNIQUE%' "
                    "AND indexdef ILIKE '%(approval_id)%'")
        assert cur.fetchone()[0] >= 1
