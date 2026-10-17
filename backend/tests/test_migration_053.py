"""Migration 053 — identification and addresses per company (Levi 2026-10-05)."""
import importlib.util
import os
import re

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _migration():
    path = os.path.join(_HERE, "alembic", "versions", "053_particulars_per_company.py")
    spec = importlib.util.spec_from_file_location("m053", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _n(sql: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", sql)).strip()


m = _migration()
SQL = _n(" ".join(m.UPGRADE_SQL))


def test_053_revises_052():
    assert m.revision == "053" and m.down_revision == "052"


def test_053_adds_the_address_book():
    assert "CREATE TABLE IF NOT EXISTS public.person_addresses" in SQL
    assert "kind IN ('residential', 'correspondence')" in SQL
    assert "UNIQUE (person_id, address_id, kind)" in SQL


def test_053_links_each_appointment():
    assert ("ADD COLUMN IF NOT EXISTS residential_address_id uuid REFERENCES "
            "public.addresses(id) ON DELETE SET NULL") in SQL
    assert ("ADD COLUMN IF NOT EXISTS identity_document_id uuid REFERENCES "
            "public.person_identity_documents(id) ON DELETE SET NULL") in SQL


def test_053_backfills_from_what_exists():
    assert "SELECT id, residential_address_id, 'residential' FROM public.persons" in SQL
    assert "correspondence_address_id, 'correspondence' FROM public.entity_officers" in SQL


def test_053_locks_the_new_table_down():
    lock = _n(m.LOCK_DOWN)
    assert "ENABLE ROW LEVEL SECURITY" in lock and "REVOKE ALL ON public.person_addresses" in lock


def test_053_downgrade_refuses_while_a_link_is_set():
    guard = _n(m.DOWNGRADE_GUARD)
    assert "RAISE EXCEPTION" in guard
    assert "residential_address_id IS NOT NULL" in guard
    assert "identity_document_id IS NOT NULL" in guard
