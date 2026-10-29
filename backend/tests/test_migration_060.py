"""Migration 060 -- the multi-signer columns on `nar1_cases` (Levi 2026-10-29,
nd2-multi-signer).

File-level assertions, which run everywhere, in the style of test_migration_059.py.
They are what catches a forgotten CHECK: every unit test mocks PostgREST, so a
NAR1 row carrying `multi_signer = true` would be accepted by every fake and
refused only by Postgres.
"""
import importlib.util
import os
import re
from unittest.mock import patch

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M060 = "060_officer_change_multi_signer.py"


def _migration():
    path = os.path.join(_HERE, "alembic", "versions", M060)
    spec = importlib.util.spec_from_file_location("m060", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _statements(direction: str) -> str:
    m = _migration()
    seen: list[str] = []
    with patch.object(m.op, "execute", side_effect=lambda sql: seen.append(str(sql))):
        getattr(m, direction)()
    return re.sub(r"\s+", " ", " ".join(seen))


def test_060_revises_059_and_is_the_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    m = _migration()
    assert (m.revision, m.down_revision) == ("060", "059")
    script = ScriptDirectory.from_config(Config(os.path.join(_HERE, "alembic.ini")))
    assert script.get_heads() == ["060"]


def test_both_columns_are_added_to_nar1_cases():
    sql = _statements("upgrade")
    assert "ALTER TABLE public.nar1_cases" in sql
    assert "ADD COLUMN IF NOT EXISTS multi_signer boolean NOT NULL DEFAULT false" in sql
    assert "ADD COLUMN IF NOT EXISTS required_signers jsonb" in sql
    # The signer set is NULL until the first send of a round freezes it.
    assert "required_signers jsonb NOT NULL" not in sql


def test_the_check_keeps_the_mode_off_every_nar1_row():
    sql = _statements("upgrade")
    assert ("ADD CONSTRAINT nar1_cases_multi_signer_officer_change_only "
            "CHECK (NOT multi_signer OR form_code IN ('Nd2a', 'Nd2b'))") in sql


def test_the_downgrade_drops_the_constraint_and_both_columns():
    sql = _statements("downgrade")
    assert ("DROP CONSTRAINT IF EXISTS nar1_cases_multi_signer_officer_change_only"
            in sql)
    assert "DROP COLUMN IF EXISTS required_signers" in sql
    assert "DROP COLUMN IF EXISTS multi_signer" in sql
    # The constraint reads the column, so it has to go first.
    assert sql.index("DROP CONSTRAINT") < sql.index("DROP COLUMN IF EXISTS multi_signer")


def test_no_policy_and_no_view_is_touched():
    """The case view (057) lists its columns explicitly, so two new columns on
    the table need no restatement of it; and the table's access rules are not
    this migration's business."""
    for direction in ("upgrade", "downgrade"):
        sql = _statements(direction).upper()
        assert "CREATE POLICY" not in sql
        assert "VIEW" not in sql
