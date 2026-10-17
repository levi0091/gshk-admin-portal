"""Migration 054 — CR status removed (Levi 2026-10-17).

The pure half runs in the `unit` job: 054 restates 052's case view with the
filed branch reading 'filed', so the view and `nar1_case_status` keep one rule,
and its statements have to run in an order Postgres accepts (a view and a
trigger both depend on columns it drops). The DB half (RUN_DB_TESTS) proves the
columns are gone, `registered` can no longer be stored, and `updated_at` is
stamped on every update again. The badge parity itself is test_migration_024's.
"""
import importlib.util
import os
import re
from unittest.mock import patch

import pytest

from services import nar1_case_status as st
from services import nar1_cases
from services.tpsi import filings

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M054 = "054_cr_status_removed.py"
M052 = "052_nd2_feedback.py"


def _migration(name: str):
    path = os.path.join(_HERE, "alembic", "versions", name)
    spec = importlib.util.spec_from_file_location(name.split(".")[0], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalise(sql: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", sql)).strip()


def _statements(direction: str) -> list[str]:
    """Every SQL string 054's upgrade/downgrade hands to op.execute, in order."""
    m54 = _migration(M054)
    seen: list[str] = []
    with patch.object(m54.op, "execute", side_effect=lambda sql: seen.append(str(sql))):
        getattr(m54, direction)()
    return seen


def _first(statements: list[str], needle: str) -> int:
    return next(i for i, sql in enumerate(statements) if needle in sql)


# --------------------------------------------------------------------------- #
#  No database needed
# --------------------------------------------------------------------------- #

def test_054_revises_053():
    m54 = _migration(M054)
    assert (m54.revision, m54.down_revision) == ("054", "053")


def test_054_view_files_a_filed_case_as_filed():
    sql = _normalise(_migration(M054).view_sql())
    assert "THEN 'filed'" in sql
    assert "cr_not_checked" not in sql and "COALESCE(base.cr_doc_status_code" not in sql


def test_054_view_selects_no_cr_column():
    sql = _migration(M054).view_sql()
    assert "cr_doc_status" not in sql and "cr_status_checked_at" not in sql


def test_054_view_knows_no_registered_stage():
    sql = _normalise(_migration(M054).view_sql())
    assert "registered" not in sql
    assert sql.count("('submitted', 'edrive')") == 2


def test_054_overdue_ignores_filed_and_closed_only():
    sql = _normalise(_migration(M054).view_sql())
    assert "coded.workflow_status NOT IN ('filed', 'closed')" in sql


def test_054_changes_nothing_else_in_052s_view():
    """Undo exactly 054's three edits and 052's view must come back."""
    m52, m54 = _migration(M052), _migration(M054)
    restored = _normalise(m54.view_sql())
    restored = restored.replace("THEN 'filed'",
                                "THEN COALESCE(base.cr_doc_status_code, 'cr_not_checked')")
    restored = restored.replace("('submitted', 'edrive')",
                                "('submitted', 'registered', 'edrive')")
    restored = restored.replace(
        "coded.workflow_status NOT IN ('filed', 'closed')",
        "coded.workflow_status NOT IN ('cr_not_checked', 'cr_pending', 'cr_approved', "
        "'cr_registered', 'cr_rejected', 'cr_unknown', 'closed')")
    restored = restored.replace(
        "c.closed_reason, f.id",
        "c.closed_reason, c.cr_doc_status, c.cr_doc_status_code, "
        "c.cr_status_checked_at, f.id")
    assert restored == _normalise(m52.view_sql())


def test_054_downgrade_restores_052s_view():
    assert _migration(M054).previous_view_sql() == _migration(M052).view_sql()


def test_054_head_lists_match_the_services():
    """The copies the view is built from. One that drifts silently reclassifies
    every case it covers — the job 046/047/050's tests did until 054."""
    m54 = _migration(M054)
    assert tuple(m54.CR_FILED_STAGES) == tuple(nar1_cases.CR_FILED_STAGES)
    assert m54.FILED == st.FILED
    assert set(m54.FILING_STAGES) == set(filings.FORM_STATUSES) | {filings.STAGE_EDRIVE}


def test_054_view_emits_only_codes_the_services_know():
    sql = _migration(M054).view_sql()
    expression = sql[sql.index("WORKFLOW-STATUS-EXPRESSION-START"):
                     sql.index("WORKFLOW-STATUS-EXPRESSION-END")]
    emitted = set(re.findall(r"THEN '([a-z_]+)'", expression)) | set(
        re.findall(r"ELSE '([a-z_]+)'", expression))
    assert emitted <= set(st.WORKFLOW_STATUSES), emitted - set(st.WORKFLOW_STATUSES)


def test_054_upgrade_patches_registered_before_tightening_the_check():
    statements = _statements("upgrade")
    patch_at = _first(statements, "SET stage = 'submitted'")
    check_at = _first(statements, "ADD CONSTRAINT tpsi_filings_stage_check")
    assert patch_at < check_at
    assert "'registered'" not in statements[check_at]


def test_054_upgrade_frees_the_columns_before_dropping_them():
    """Postgres refuses to drop a column a view selects, and the 044 trigger's
    WHEN clause names `cr_status_checked_at` (DROP ... CASCADE would silently
    drop the trigger instead)."""
    statements = _statements("upgrade")
    drop_at = _first(statements, "DROP COLUMN IF EXISTS cr_status_checked_at")
    assert _first(statements, "CREATE VIEW") < drop_at
    trigger_at = _first(statements, "CREATE TRIGGER trg_set_updated_at")
    assert trigger_at < drop_at
    assert "WHEN" not in statements[trigger_at]
    assert "CASCADE" not in statements[drop_at]


def test_054_downgrade_re_adds_the_columns_before_052s_view_selects_them():
    statements = _statements("downgrade")
    add_at = _first(statements, "ADD COLUMN IF NOT EXISTS cr_doc_status_code")
    assert add_at < _first(statements, "CREATE VIEW")
    trigger_at = _first(statements, "CREATE TRIGGER trg_set_updated_at")
    assert add_at < trigger_at and "WHEN" in statements[trigger_at]
    check_at = _first(statements, "ADD CONSTRAINT tpsi_filings_stage_check")
    assert "'registered'" in statements[check_at]


def test_054_seeds_and_removes_no_audit_code():
    """Levi: leave the audit trail. The CR-status codes stay labelled."""
    for direction in ("upgrade", "downgrade"):
        assert not [s for s in _statements(direction) if "audit_event_types" in s]


# --------------------------------------------------------------------------- #
#  Database
# --------------------------------------------------------------------------- #

psycopg2 = pytest.importorskip("psycopg2")

db = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)


def _conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


@db
def test_the_cr_status_columns_are_gone():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'nar1_cases' "
            "AND column_name IN ('cr_doc_status', 'cr_doc_status_code', "
            "'cr_status_checked_at', 'cr_document_ref_no')")
        assert cur.fetchall() == []


@db
def test_a_registered_stage_can_no_longer_be_stored():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO public.entities (id, company_name) "
                    "VALUES (gen_random_uuid(), 'STAGE FIXTURE') RETURNING id")
        entity_id = cur.fetchone()[0]
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("INSERT INTO public.tpsi_filings (entity_id, form_code, stage) "
                        "VALUES (%s, 'Nar1', 'registered')", (entity_id,))
        conn.rollback()


@db
def test_every_update_stamps_updated_at_again():
    """044's WHEN clause is gone with the heartbeat it existed for. Seeded years
    back, because `now()` is the transaction's and would equal itself."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO public.entities (id, company_name) "
                    "VALUES (gen_random_uuid(), 'TRIGGER FIXTURE') RETURNING id")
        entity_id = cur.fetchone()[0]
        cur.execute("INSERT INTO public.nar1_cases (entity_id, nar1_type, updated_at) "
                    "VALUES (%s, 'annual_return', TIMESTAMPTZ '2020-01-01') "
                    "RETURNING id", (entity_id,))
        case_id = cur.fetchone()[0]
        cur.execute("UPDATE public.nar1_cases SET verification_sent_at = now() WHERE id = %s",
                    (case_id,))
        cur.execute("SELECT updated_at > TIMESTAMPTZ '2021-01-01' "
                    "FROM public.nar1_cases WHERE id = %s", (case_id,))
        assert cur.fetchone()[0] is True
        cur.execute("SELECT pg_get_triggerdef(t.oid) FROM pg_trigger t "
                    "JOIN pg_class c ON c.oid = t.tgrelid "
                    "WHERE c.relname = 'nar1_cases' AND t.tgname = 'trg_set_updated_at'")
        assert "WHEN" not in cur.fetchone()[0]
        conn.rollback()
