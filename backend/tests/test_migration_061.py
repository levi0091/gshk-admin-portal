"""Migration 061 -- alternate directors (PBI-70 revived) and the
`approval_receipt` document type.

File-level assertions, which run everywhere, in the style of test_migration_060:
every unit test mocks PostgREST, so a forgotten CHECK or a missing column would
fail nowhere else.
"""
import importlib.util
import os
import re
from unittest.mock import patch

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M061 = "061_alternate_directors_and_receipt_doc_type.py"


def _migration():
    path = os.path.join(_HERE, "alembic", "versions", M061)
    spec = importlib.util.spec_from_file_location("m061", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _statements(direction: str) -> str:
    m = _migration()
    seen: list[str] = []
    with patch.object(m.op, "execute", side_effect=lambda sql: seen.append(str(sql))):
        getattr(m, direction)()
    return re.sub(r"\s+", " ", " ".join(seen))


def test_061_revises_060_and_is_the_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    m = _migration()
    assert (m.revision, m.down_revision) == ("061", "060")
    script = ScriptDirectory.from_config(Config(os.path.join(_HERE, "alembic.ini")))
    assert script.get_heads() == ["063"]


def test_the_role_enum_gains_alternate_director_idempotently():
    sql = _statements("upgrade")
    assert "ALTER TYPE officer_role ADD VALUE IF NOT EXISTS 'alternate_director'" in sql


def test_the_entry_capacity_check_accepts_the_new_capacity():
    sql = _statements("upgrade")
    assert "DROP CONSTRAINT IF EXISTS officer_change_entries_capacity_valid" in sql
    assert ("ADD CONSTRAINT officer_change_entries_capacity_valid CHECK (capacity IN "
            "('director', 'company_secretary', 'alternate_director'))") in sql


def test_both_tables_get_the_nullable_link_to_the_director():
    sql = _statements("upgrade")
    for table in ("entity_officers", "officer_change_entries"):
        assert (f"ALTER TABLE public.{table} ADD COLUMN IF NOT EXISTS "
                "alternate_to_officer_id uuid REFERENCES public.entity_officers(id) "
                "ON DELETE SET NULL") in sql, table
    # Nullable, and no CHECK tying the capacity to it: SET NULL would then make
    # deleting a director row impossible while an alternate pointed at it.
    assert "alternate_to_officer_id uuid NOT NULL" not in sql
    assert "CHECK (capacity <> 'alternate_director'" not in sql


def test_the_foreign_keys_are_indexed():
    sql = _statements("upgrade")
    assert "CREATE INDEX IF NOT EXISTS ix_entity_officers_alternate_to" in sql
    assert "CREATE INDEX IF NOT EXISTS ix_officer_change_entries_alternate_to" in sql


def test_the_receipt_document_type_is_seeded_like_050():
    sql = _statements("upgrade")
    assert "INSERT INTO public.document_types" in sql
    assert ("('approval_receipt', 'Client Approval Receipt', 'government_form', "
            "'company', false, 15, true)") in sql
    assert "ON CONFLICT (code) DO UPDATE SET" in sql


def test_downgrade_restores_the_narrow_check_and_drops_what_it_added():
    sql = _statements("downgrade")
    assert "DROP COLUMN IF EXISTS alternate_to_officer_id" in sql
    assert ("ADD CONSTRAINT officer_change_entries_capacity_valid CHECK (capacity IN "
            "('director', 'company_secretary'))") in sql
    assert "DELETE FROM public.document_types WHERE code = 'approval_receipt'" in sql
    # Referenced documents deactivate the type instead of orphaning them.
    assert "UPDATE public.document_types SET is_active = false" in sql


def test_downgrade_refuses_while_alternates_exist_and_says_the_enum_stays():
    sql = _statements("downgrade")
    assert "RAISE EXCEPTION" in sql
    assert "role::text = 'alternate_director'" in sql
    assert "DROP VALUE" not in sql  # PostgreSQL has none
    assert "CANNOT remove the enum value" in " ".join(_migration().__doc__.split())
