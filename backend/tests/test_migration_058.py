"""Migration 058 — a person's email can be kept off the forms (Levi 2026-10-29).

File-level assertions, which run everywhere, and DB-backed ones gated on
RUN_DB_TESTS in the style of test_migration_041.py. The file-level half is what
catches a column added without its default, or a label that was never seeded:
every unit test mocks PostgREST, so neither would fail anywhere else.
"""
import importlib.util
import os
from unittest.mock import patch

import pytest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M058 = "058_person_hide_email_on_forms.py"


def _migration():
    path = os.path.join(_HERE, "alembic", "versions", M058)
    spec = importlib.util.spec_from_file_location("m058", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _statements(direction: str) -> list[str]:
    m = _migration()
    seen: list[str] = []
    with patch.object(m.op, "execute", side_effect=lambda sql: seen.append(str(sql))):
        getattr(m, direction)()
    return seen


def test_058_revises_057_and_is_the_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    m = _migration()
    assert (m.revision, m.down_revision) == ("058", "057")
    script = ScriptDirectory.from_config(Config(os.path.join(_HERE, "alembic.ini")))
    assert script.get_heads() == ["058"]


def test_the_column_is_a_non_null_boolean_defaulting_to_false():
    sql = " ".join(_statements("upgrade"))
    assert "ALTER TABLE public.persons" in sql
    assert "ADD COLUMN IF NOT EXISTS hide_email_on_forms boolean NOT NULL DEFAULT false" in sql
    assert "UPDATE" not in sql and "DROP" not in sql


def test_the_audit_label_is_seeded_and_idempotent():
    sql = " ".join(_statements("upgrade"))
    assert "INSERT INTO audit_field_labels" in sql
    assert "ON CONFLICT (field) DO NOTHING" in sql
    assert _migration().FIELD_LABELS == {"hide_email_on_forms": "Email hidden on forms"}


def test_the_downgrade_drops_the_column_and_the_label():
    sql = " ".join(_statements("downgrade"))
    assert "DELETE FROM audit_field_labels" in sql
    assert "DROP COLUMN IF EXISTS hide_email_on_forms" in sql


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
def test_db_column_exists_not_null_default_false(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT data_type, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_schema = 'public' "
            "AND table_name = 'persons' AND column_name = 'hide_email_on_forms'")
        data_type, nullable, default = cur.fetchone()
    assert data_type == "boolean" and nullable == "NO"
    assert "false" in str(default).lower()


@_db
def test_db_label_is_seeded(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT label FROM audit_field_labels WHERE field = 'hide_email_on_forms'")
        assert cur.fetchone() == ("Email hidden on forms",)
