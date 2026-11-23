"""Migration 066 — the company's own Business Name for NAR1 s2 (GSHK 2026-11-23).

File-level assertions only; they run everywhere."""
import importlib.util
import os
from unittest.mock import patch

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M066 = "066_entity_business_name.py"


def _migration():
    path = os.path.join(_HERE, "alembic", "versions", M066)
    spec = importlib.util.spec_from_file_location("m066", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _statements(direction: str) -> list[str]:
    m = _migration()
    seen: list[str] = []
    with patch.object(m.op, "execute", side_effect=lambda sql: seen.append(str(sql))):
        getattr(m, direction)()
    return seen


def test_066_revises_065_and_is_the_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    m = _migration()
    assert (m.revision, m.down_revision) == ("066", "065")
    script = ScriptDirectory.from_config(Config(os.path.join(_HERE, "alembic.ini")))
    assert script.get_heads() == ["066"]


def test_the_column_starts_empty_for_every_company():
    """"Please do not default it": no DEFAULT, and nothing copied in from
    Viewpoint's BR record, which mostly repeats the company's own name."""
    sql = " ".join(_statements("upgrade"))
    assert "ADD COLUMN IF NOT EXISTS business_name text" in sql
    assert "DEFAULT" not in sql.upper().split("BUSINESS_NAME TEXT")[1].split(";")[0]
    assert "business_names" not in sql


def test_the_field_is_labelled_for_the_audit_trail():
    assert _migration().FIELD_LABELS == {"business_name": "Business Name"}
    assert any("audit_field_labels" in s for s in _statements("upgrade"))


def test_downgrade_drops_the_column_and_the_label():
    sql = " ".join(_statements("downgrade"))
    assert "DROP COLUMN IF EXISTS business_name" in sql
    assert "DELETE FROM audit_field_labels" in sql
