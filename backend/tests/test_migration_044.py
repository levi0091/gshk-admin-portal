"""Migration 044 — the CR heartbeat stops resetting Last Updated.

The behaviour under test is a DATABASE behaviour and cannot be checked from
Python alone: the thing that was wrong was a trigger silently overriding a
correct application patch, and only Postgres can say whether it still does.

NAMED `test_migration_044.py` ON PURPOSE. `.github/workflows/backend-ci.yml`
collects DB-backed assertions as `tests/test_migration_*.py`; a file outside
that glob would never run in the `migrations` job.
"""
import importlib.util
import os

import pytest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _migration():
    path = os.path.join(_HERE, "alembic", "versions",
                        "044_updated_at_ignores_the_cr_heartbeat.py")
    spec = importlib.util.spec_from_file_location("m044", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
#  No database needed
# --------------------------------------------------------------------------- #

def test_it_changes_the_trigger_and_never_the_shared_function():
    """`set_updated_at()` is shared by ~30 tables (003, 016, 020). Editing it to
    fix one table would change every one of them."""
    m = _migration()
    assert m._TABLE == "public.nar1_cases"
    assert "CREATE OR REPLACE FUNCTION" not in m._WHEN
    assert "cr_status_checked_at" in m._WHEN


def test_the_downgrade_restores_the_unconditional_trigger():
    """003's form is no WHEN clause at all — every update stamps."""
    m = _migration()
    assert m.down_revision == "043"
    calls = []
    m.op = type("op", (), {"execute": staticmethod(lambda sql: calls.append(sql))})
    m.downgrade()
    created = [c for c in calls if "CREATE TRIGGER" in c]
    assert len(created) == 1
    assert "WHEN" not in created[0]
    assert "EXECUTE FUNCTION set_updated_at()" in created[0]


# The DB half asserted the WHEN clause on the head schema. Migration 054
# reverted the trigger to unconditional with the CR status poll it existed for
# (Levi 2026-10-17); tests/test_migration_054.py asserts that instead.
