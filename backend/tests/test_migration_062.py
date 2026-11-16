"""Migration 062 — a deceased director's cessation can name the administrator /
executor (Jacqueline, UAT 2026-11-10, PBI-59).

File-level assertions, which run everywhere, and DB-backed ones gated on
RUN_DB_TESTS in the style of test_migration_058.py.
"""
import importlib.util
import os
from unittest.mock import patch

import pytest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M062 = "062_cessation_executor_name.py"


def _migration():
    path = os.path.join(_HERE, "alembic", "versions", M062)
    spec = importlib.util.spec_from_file_location("m062", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _statements(direction: str) -> list[str]:
    m = _migration()
    seen: list[str] = []
    with patch.object(m.op, "execute", side_effect=lambda sql: seen.append(str(sql))):
        getattr(m, direction)()
    return seen


def test_062_revises_061_and_is_the_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    m = _migration()
    assert (m.revision, m.down_revision) == ("062", "061")
    script = ScriptDirectory.from_config(Config(os.path.join(_HERE, "alembic.ini")))
    assert script.get_heads() == ["063"]


def test_the_column_is_nullable_text_with_a_length_check():
    sql = " ".join(_statements("upgrade"))
    assert "ADD COLUMN IF NOT EXISTS executor_name text" in sql
    assert "NOT NULL" not in sql.split("CHECK")[0] and "DEFAULT" not in sql
    assert "char_length(executor_name) <= 120" in sql
    assert "UPDATE public" not in sql


def test_the_code_and_the_check_share_one_limit():
    from services.officer_changes import cases
    assert cases.EXECUTOR_NAME_MAX == _migration().MAX_LENGTH


def test_the_audit_label_is_seeded_and_idempotent():
    sql = " ".join(_statements("upgrade"))
    assert "INSERT INTO audit_field_labels" in sql and "ON CONFLICT (field) DO NOTHING" in sql
    assert _migration().FIELD_LABELS == {"executor_name": "Administrator / executor"}


def test_the_downgrade_drops_the_column_the_check_and_the_label():
    sql = " ".join(_statements("downgrade"))
    assert "DELETE FROM audit_field_labels" in sql
    assert "DROP CONSTRAINT IF EXISTS officer_change_entries_executor_name_len" in sql
    assert "DROP COLUMN IF EXISTS executor_name" in sql


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
def test_db_column_is_nullable_text_with_the_length_check(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT data_type, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'officer_change_entries' "
                    "AND column_name = 'executor_name'")
        assert cur.fetchone() == ("text", "YES")
        cur.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'officer_change_entries_executor_name_len'")
        assert "120" in cur.fetchone()[0]


@_db
def test_db_label_is_seeded(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT label FROM audit_field_labels WHERE field = 'executor_name'")
        assert cur.fetchone() == ("Administrator / executor",)
