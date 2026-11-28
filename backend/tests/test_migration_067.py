"""Migration 067 — which address a person's forms print (Levi 2026-11-28).

File-level assertions run everywhere; the DB-backed ones are gated on
RUN_DB_TESTS, in the style of test_migration_058.py.
"""
import importlib.util
import os
from unittest.mock import patch

import pytest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M067 = "067_person_address_on_forms.py"


def _migration():
    path = os.path.join(_HERE, "alembic", "versions", M067)
    spec = importlib.util.spec_from_file_location("m067", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _statements(direction: str) -> list[str]:
    m = _migration()
    seen: list[str] = []
    with patch.object(m.op, "execute", side_effect=lambda sql: seen.append(str(sql))):
        getattr(m, direction)()
    return seen


def test_067_revises_066_and_is_the_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    m = _migration()
    assert (m.revision, m.down_revision) == ("067", "066")
    script = ScriptDirectory.from_config(Config(os.path.join(_HERE, "alembic.ini")))
    assert script.get_heads() == ["067"]


def test_the_column_defaults_to_correspondence_and_allows_only_two_values():
    sql = " ".join(_statements("upgrade"))
    assert ("ADD COLUMN IF NOT EXISTS address_on_forms text "
            "NOT NULL DEFAULT 'correspondence'") in sql
    assert "CHECK (address_on_forms IN ('correspondence', 'residential'))" in sql
    assert "INSERT INTO audit_field_labels" in sql


def test_the_audit_label_is_seeded():
    assert _migration().FIELD_LABELS == {"address_on_forms": "Address shown on forms"}


def test_the_downgrade_drops_the_column_and_label():
    sql = " ".join(_statements("downgrade"))
    assert "DELETE FROM audit_field_labels" in sql
    assert "DROP COLUMN IF EXISTS address_on_forms" in sql


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
def test_db_column_exists_not_null_default_correspondence(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT data_type, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_schema = 'public' "
            "AND table_name = 'persons' AND column_name = 'address_on_forms'")
        data_type, nullable, default = cur.fetchone()
    assert data_type == "text" and nullable == "NO"
    assert "correspondence" in str(default)


@_db
def test_db_label_is_seeded(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT label FROM audit_field_labels WHERE field = 'address_on_forms'")
        assert cur.fetchone() == ("Address shown on forms",)
