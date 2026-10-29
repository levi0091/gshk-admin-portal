"""Migration 055 — the date of death on a cessation, and the e-Sign route's
signed form on the case (Levi 2026-10-18).

Both are nullable columns added and nothing else: an entry added before 055 has
no date of death and files without one, and a case filed by e-Sign before 055
has no saved form, which the Confirmation stage offers to save.
"""
import importlib.util
import os
from unittest.mock import patch

import pytest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M055 = "055_death_date_and_esign_form.py"


def _migration():
    path = os.path.join(_HERE, "alembic", "versions", M055)
    spec = importlib.util.spec_from_file_location("m055", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _statements(direction: str) -> list[str]:
    m = _migration()
    seen: list[str] = []
    with patch.object(m.op, "execute", side_effect=lambda sql: seen.append(str(sql))):
        getattr(m, direction)()
    return seen


def test_055_revises_054_and_057_follows_it():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    m = _migration()
    assert (m.revision, m.down_revision) == ("055", "054")
    script = ScriptDirectory.from_config(Config(os.path.join(_HERE, "alembic.ini")))
    assert script.get_heads() == ["060"]
    assert script.get_revision("057").down_revision == "055"


def test_055_only_adds_nullable_columns():
    sql = " ".join(_statements("upgrade"))
    assert "officer_change_entries" in sql and "date_of_death date" in sql
    assert "filed_form_document_id uuid REFERENCES public.documents(id)" in sql
    assert "filed_form_document_version integer" in sql
    assert "NOT NULL" not in sql and "DROP" not in sql and "UPDATE" not in sql


def test_055_downgrade_drops_exactly_what_it_added():
    sql = " ".join(_statements("downgrade"))
    for column in ("date_of_death", "filed_form_document_id", "filed_form_document_version"):
        assert f"DROP COLUMN IF EXISTS {column}" in sql


psycopg2 = pytest.importorskip("psycopg2")

db = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)


@db
def test_the_columns_exist_and_take_null():
    with psycopg2.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT table_name, column_name, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name IN "
            "('date_of_death', 'filed_form_document_id', 'filed_form_document_version') "
            "AND table_name IN ('officer_change_entries', 'nar1_cases') ORDER BY 1, 2")
        assert cur.fetchall() == [
            ("nar1_cases", "filed_form_document_id", "YES"),
            ("nar1_cases", "filed_form_document_version", "YES"),
            ("officer_change_entries", "date_of_death", "YES")]
