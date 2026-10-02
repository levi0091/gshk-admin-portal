"""Migration 052 — Jacqueline's ND2A/ND2B feedback (2026-10-01).

TWO HALVES, like 050's. The pure half pins the SQL text; the DB half
(RUN_DB_TESTS) upgrades a real Postgres and proves the new columns exist and
that the table holding e-consent tokens cannot be read through PostgREST.
"""
import importlib.util
import os
import re

import pytest

from services import audit_events as ev

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M052 = "052_nd2_feedback.py"


def _migration(name: str):
    path = os.path.join(_HERE, "alembic", "versions", name)
    spec = importlib.util.spec_from_file_location(name.split(".")[0], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalise(sql: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", sql)).strip()


m = _migration(M052)
SQL = _normalise(" ".join(m.UPGRADE_SQL))
DOWN_SQL = _normalise(m.DOWNGRADE_GUARD)


def test_052_revises_050():
    assert m.revision == "052" and m.down_revision == "050"


def test_052_adds_every_column():
    for col in ("date_deferred", "send_with_email", "source", "uploaded_by_name",
                "attach_resolution", "registered_id_type", "registered_id_number"):
        assert f"ADD COLUMN IF NOT EXISTS {col}" in SQL, col


def test_052_entry_id_becomes_nullable():
    assert "ALTER COLUMN entry_id DROP NOT NULL" in SQL


def test_052_document_source_is_a_closed_vocabulary():
    assert "source IN ('upload', 'econsent', 'generated')" in SQL


def test_052_registered_id_type_is_hkid_or_passport():
    assert "registered_id_type IS NULL OR registered_id_type IN ('hkid', 'passport')" in SQL


def test_052_consents_table_is_locked_down():
    assert "CREATE TABLE IF NOT EXISTS public.officer_change_consents" in SQL
    assert "token_hash text NOT NULL" in SQL
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_officer_change_consents_token" in SQL
    lock = _normalise(m._lock_down("officer_change_consents"))
    assert "ENABLE ROW LEVEL SECURITY" in lock
    assert "REVOKE ALL ON public.officer_change_consents FROM anon" in lock
    assert "REVOKE ALL ON public.officer_change_consents FROM authenticated" in lock


def test_052_seeds_three_codes_as_g_flowdesk():
    codes = {code for code, _name in m.AUDIT_CODES}
    assert codes == {ev.OFFICER_ECONSENT_LINK_SENT, ev.OFFICER_ECONSENT_SIGNED,
                     ev.OFFICER_CONFIRMATION_WAIVED}
    seed = _normalise(m.audit_seed_sql())
    assert "'officer_changes', 'g_flowdesk'" in seed
    for code in codes:
        assert f"'{code}'" in seed


def test_052_downgrade_refuses_while_data_exists():
    assert "RAISE EXCEPTION" in DOWN_SQL
    assert "officer_change_consents" in DOWN_SQL
    assert "entry_id IS NULL" in DOWN_SQL


# --------------------------------------------------------------------------- #
#  Needs Postgres with migrations applied
# --------------------------------------------------------------------------- #

needs_db = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (set RUN_DB_TESTS=1 + DATABASE_URL)")


@needs_db
def test_052_columns_exist_after_upgrade():
    import psycopg2
    with psycopg2.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute("SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public'")
        cols = {(r[0], r[1]) for r in cur.fetchall()}
        for pair in (("officer_change_entries", "date_deferred"),
                     ("officer_change_documents", "send_with_email"),
                     ("officer_change_documents", "source"),
                     ("officer_change_documents", "uploaded_by_name"),
                     ("nar1_cases", "attach_resolution"),
                     ("person_eservice_credentials", "registered_id_type"),
                     ("person_eservice_credentials", "registered_id_number"),
                     ("officer_change_consents", "token_hash")):
            assert pair in cols, pair
        cur.execute("SELECT is_nullable FROM information_schema.columns WHERE table_name = "
                    "'officer_change_documents' AND column_name = 'entry_id'")
        nullable = cur.fetchone()[0]
        assert nullable == "YES"


@needs_db
def test_052_consents_have_rls_and_no_policy():
    import psycopg2
    with psycopg2.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute("SELECT relrowsecurity FROM pg_class WHERE relname = "
                    "'officer_change_consents'")
        rls = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM pg_policies WHERE tablename = "
                    "'officer_change_consents'")
        policies = cur.fetchone()[0]
        assert rls is True and policies == 0
