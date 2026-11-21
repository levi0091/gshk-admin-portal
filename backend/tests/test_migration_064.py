"""Migration 064 — whether the company's phone goes on the NAR1 (GSHK 2026-11-21).

File-level assertions only; they run everywhere."""
import importlib.util
import os
from unittest.mock import patch

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M064 = "064_nar1_show_phone.py"


def _migration():
    path = os.path.join(_HERE, "alembic", "versions", M064)
    spec = importlib.util.spec_from_file_location("m064", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _statements(direction: str) -> list[str]:
    m = _migration()
    seen: list[str] = []
    with patch.object(m.op, "execute", side_effect=lambda sql: seen.append(str(sql))):
        getattr(m, direction)()
    return seen


def test_064_revises_063_and_is_the_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    m = _migration()
    assert (m.revision, m.down_revision) == ("064", "063")
    script = ScriptDirectory.from_config(Config(os.path.join(_HERE, "alembic.ini")))
    assert script.get_heads() == ["065"]


def test_the_phone_is_off_for_every_company_until_somebody_turns_it_on():
    sql = " ".join(_statements("upgrade"))
    assert "nar1_show_phone boolean NOT NULL DEFAULT false" in sql


def test_the_field_is_labelled_for_the_audit_trail():
    assert _migration().FIELD_LABELS == {"nar1_show_phone": "Show phone on NAR1"}
    assert any("audit_field_labels" in s for s in _statements("upgrade"))


def test_downgrade_drops_the_column_and_the_label():
    sql = " ".join(_statements("downgrade"))
    assert "DROP COLUMN IF EXISTS nar1_show_phone" in sql
    assert "DELETE FROM audit_field_labels" in sql
