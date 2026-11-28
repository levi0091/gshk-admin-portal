"""Migration 068 — an ND2A appointment's correspondence address is picked from
the profile (Levi 2026-11-28).

File-level assertions run everywhere; the DB-backed ones are gated on
RUN_DB_TESTS, in the style of test_migration_067.py.
"""
import importlib.util
import os
from unittest.mock import patch

import pytest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M068 = "068_nd2a_entry_profile_correspondence.py"


def _migration():
    path = os.path.join(_HERE, "alembic", "versions", M068)
    spec = importlib.util.spec_from_file_location("m068", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _statements(direction: str) -> list[str]:
    m = _migration()
    seen: list[str] = []
    with patch.object(m.op, "execute", side_effect=lambda sql: seen.append(str(sql))):
        getattr(m, direction)()
    return seen


def test_068_revises_067_and_is_the_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    m = _migration()
    assert (m.revision, m.down_revision) == ("068", "067")
    script = ScriptDirectory.from_config(Config(os.path.join(_HERE, "alembic.ini")))
    assert script.get_heads() == ["068"]


def test_the_column_is_a_nullable_address_link_that_clears_on_delete():
    sql = " ".join(_statements("upgrade"))
    assert "ALTER TABLE public.officer_change_entries" in sql
    assert "ADD COLUMN IF NOT EXISTS correspondence_address_id uuid" in sql
    assert "REFERENCES public.addresses(id) ON DELETE SET NULL" in sql
    assert "NOT NULL" not in sql


def test_the_downgrade_drops_the_column():
    sql = " ".join(_statements("downgrade"))
    assert "DROP COLUMN IF EXISTS correspondence_address_id" in sql


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
def test_db_column_exists_and_is_nullable_uuid(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'officer_change_entries' "
            "AND column_name = 'correspondence_address_id'")
        assert cur.fetchone() == ("uuid", "YES")
