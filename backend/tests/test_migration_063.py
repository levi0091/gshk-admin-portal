"""Migration 063 — who signs an e-Signed ND2A (Levi 2026-11-13).

File-level assertions only; they run everywhere."""
import importlib.util
import os
from unittest.mock import patch

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M063 = "063_nd2a_signing_party.py"


def _migration():
    path = os.path.join(_HERE, "alembic", "versions", M063)
    spec = importlib.util.spec_from_file_location("m063", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _statements(direction: str) -> list[str]:
    m = _migration()
    seen: list[str] = []
    with patch.object(m.op, "execute", side_effect=lambda sql: seen.append(str(sql))):
        getattr(m, direction)()
    return seen


def test_063_revises_062_and_is_the_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    m = _migration()
    assert (m.revision, m.down_revision) == ("063", "062")
    script = ScriptDirectory.from_config(Config(os.path.join(_HERE, "alembic.ini")))
    assert script.get_heads() == ["063"]


def test_both_columns_are_nullable_and_the_party_is_checked():
    sql = " ".join(_statements("upgrade"))
    assert "ADD COLUMN IF NOT EXISTS signing_party text" in sql
    assert "signing_party IN ('gshk', 'director')" in sql
    assert "signing_director_person_id uuid REFERENCES public.persons(id) ON DELETE SET NULL" \
        in sql
    assert "NOT NULL" not in sql.replace("IS NULL OR", "")


def test_an_nd2a_already_validated_is_pinned_to_gshk():
    # The new default must not flip a form CR already checked with GSHK's block.
    sql = " ".join(_statements("upgrade"))
    assert "SET signing_party = 'gshk'" in sql and "form_code = 'Nd2a'" in sql
    assert "'superseded', 'draft', 'validation_failed'" in sql


def test_the_labels_are_seeded_and_the_downgrade_reverses_everything():
    assert _migration().FIELD_LABELS == {"signing_party": "Signed by",
                                         "signing_director_person_id": "Signing director"}
    down = " ".join(_statements("downgrade"))
    assert "DROP COLUMN IF EXISTS signing_party" in down
    assert "DROP COLUMN IF EXISTS signing_director_person_id" in down
    assert "DELETE FROM audit_field_labels" in down
