"""Migration 052 — Jacqueline's ND2A/ND2B feedback (2026-10-01).

TWO HALVES, like 050's. The pure half pins the SQL text; the DB half
(RUN_DB_TESTS) upgrades a real Postgres and proves the new columns exist and
that entry_id became nullable.
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
    for col in ("date_deferred", "send_with_email",
                "registered_id_type", "registered_id_number"):
        assert f"ADD COLUMN IF NOT EXISTS {col}" in SQL, col


def test_052_entry_id_becomes_nullable():
    assert "ALTER COLUMN entry_id DROP NOT NULL" in SQL


def test_052_registered_id_type_is_hkid_or_passport():
    assert "registered_id_type IS NULL OR registered_id_type IN ('hkid', 'passport')" in SQL


def test_052_carries_no_in_portal_consent():
    """Levi 2026-10-05: CR's consent signature IS the consent (TPSI API
    v1.0.14 section 7.1.2), so nothing of the in-portal consent survives."""
    for gone in ("officer_change_consents", "token_hash", "uploaded_by_name",
                 "econsent", "ADD COLUMN IF NOT EXISTS source",
                 # Levi 2026-10-05: the resolution always goes; no toggle.
                 "attach_resolution"):
        assert gone not in SQL, gone
    assert "officer_change_consents" not in DOWN_SQL
    assert not any("ECONSENT" in code for code, _ in m.AUDIT_CODES)


def test_052_seeds_the_waiver_code_as_g_flowdesk():
    codes = {code for code, _name in m.AUDIT_CODES}
    assert codes == {ev.OFFICER_CONFIRMATION_WAIVED}
    seed = _normalise(m.audit_seed_sql())
    assert "'officer_changes', 'g_flowdesk'" in seed
    for code in codes:
        assert f"'{code}'" in seed


def test_052_downgrade_refuses_while_data_exists():
    assert "RAISE EXCEPTION" in DOWN_SQL
    assert "entry_id IS NULL" in DOWN_SQL


M050 = _migration("050_officer_changes_nd2a_nd2b.py")


def test_052_restates_the_case_view_with_the_esign_checked_branch():
    """Review finding 6: an e-Sign case marked checked (a date deferred to
    Signing) reads 'signing' on the dashboard as on the badge."""
    view = _normalise(m.view_sql())
    branch = _normalise(m.ESIGN_CHECKED_BRANCH)
    assert branch in view
    assert "base.signing_method = 'esign'" in branch
    assert "base.data_checked_at IS NOT NULL" in branch and "THEN 'signing'" in branch
    # After the manual branch, before the filing-stage tests.
    assert view.index("base.signing_method = 'manual'") < view.index(branch) < \
        view.index("WHEN base.filing_stage IS NULL")


def test_052_changes_nothing_else_in_050s_view():
    restated = _normalise(_normalise(m.view_sql()).replace(
        _normalise(m.ESIGN_CHECKED_BRANCH), ""))
    assert restated == _normalise(M050._case_view_sql(officer_changes=True))


def test_052_downgrade_restores_050s_view():
    assert _normalise(m.previous_view_sql()) == _normalise(
        M050._case_view_sql(officer_changes=True))


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
                     ("person_eservice_credentials", "registered_id_type"),
                     ("person_eservice_credentials", "registered_id_number")):
            assert pair in cols, pair
        cur.execute("SELECT is_nullable FROM information_schema.columns WHERE table_name = "
                    "'officer_change_documents' AND column_name = 'entry_id'")
        nullable = cur.fetchone()[0]
        assert nullable == "YES"
