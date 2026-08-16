"""Migration 021 — the NAR1 case workflow schema.

DB-backed, per tests/tpsi/test_migration_016.py: runs only with RUN_DB_TESTS=1
against a database that has had `alembic upgrade head` applied. Skipped in the
mocked unit run.
"""
import os
from pathlib import Path

import pytest

psycopg2 = pytest.importorskip("psycopg2")

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)

MANUAL_CODES = {
    "NAR1_MANUAL_SIGN_UPLOADED",
    "NAR1_MANUAL_SUBMISSION_RECORDED",
    "NAR1_MANUAL_RECEIPT_ENTERED",
}


def _conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def _has_super_admin() -> bool:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM roles WHERE name = 'super_admin'")
        return cur.fetchone() is not None


requires_super_admin = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS") or not _has_super_admin(),
    reason="no super_admin role in this database",
)


@pytest.mark.parametrize("column", [
    "case_no", "aml_cleared", "aml_cleared_at", "accounts_ready",
    "accounts_ready_at", "signing_method", "manual_signed_document_id",
    "manual_receipt", "manual_submitted_at", "created_by",
])
def test_case_gains_the_workflow_columns(column):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'nar1_cases' AND column_name = %s", (column,)
        )
        assert cur.fetchone() is not None


def test_annual_return_is_a_usable_case_type():
    """nar1_type shipped with director appointment/resignation values only --
    none describe an annual return, which is what Form NAR1 actually is. The
    column is NOT NULL, so without this a case cannot be created honestly."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 'annual_return'::nar1_type")
        assert cur.fetchone()[0] == "annual_return"


def test_case_no_is_unique():
    """NAR-2026-0041 identifies a case to a human. Two of them would not."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'nar1_cases' AND indexname = 'uq_nar1_cases_case_no'"
        )
        row = cur.fetchone()
    assert row is not None
    assert "UNIQUE" in row[0].upper()


def test_case_numbers_are_consecutive_and_never_repeat():
    """The property that matters, exercised rather than asserted about: the
    allocator is one atomic statement, so successive calls cannot collide."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT public.next_case_no('TEST-0000') FROM generate_series(1, 3)"
        )
        issued = [r[0] for r in cur.fetchall()]
        conn.rollback()
    assert issued == ["TEST-0000-0001", "TEST-0000-0002", "TEST-0000-0003"]


def test_signing_method_rejects_a_value_that_is_neither_channel():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'public.nar1_cases'::regclass AND contype = 'c'"
        )
        defs = " ".join(r[0] for r in cur.fetchall())
    assert "'esign'" in defs
    assert "'manual'" in defs


@requires_super_admin
def test_super_admin_has_the_nar1_module():
    """OQ-B: case-workflow endpoints get their own module, not companies:*."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT rp.permission FROM role_permissions rp "
            "JOIN roles r ON r.id = rp.role_id "
            "WHERE r.name = 'super_admin' AND rp.module = 'nar1'"
        )
        assert {r[0] for r in cur.fetchall()} == {"read", "write"}


@requires_super_admin
def test_no_other_role_gets_nar1():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM role_permissions rp JOIN roles r ON r.id = rp.role_id "
            "WHERE r.name <> 'super_admin' AND rp.module = 'nar1'"
        )
        assert cur.fetchone()[0] == 0


def test_manual_codes_are_seeded_as_g_flowdesk_events():
    """origin defaults to 'viewpoint' (migration 012's DDL). A manual-flow event
    left on that default is mislabeled as an imported Viewpoint event in the
    audit UI -- the exact defect migration 016 shipped with once."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT code, origin, category FROM audit_event_types "
            "WHERE code LIKE 'NAR1_MANUAL%%'"
        )
        rows = cur.fetchall()
    assert {r[0] for r in rows} == MANUAL_CODES
    for code, origin, category in rows:
        assert origin == "g_flowdesk", f"{code} has origin={origin!r}"
        assert category == "nar1", f"{code} has category={category!r}"


def test_downgrade_does_not_try_to_remove_an_enum_value():
    """The one source-text assertion in this file, because the fact lives
    nowhere else: Postgres cannot DROP an enum value, and a downgrade that
    attempts it fails halfway and leaves the schema in neither state. Nothing in
    an applied schema can show that the downgrade DOESN'T do something."""
    src = (
        Path(__file__).resolve().parents[1]
        / "alembic" / "versions" / "021_nar1_case_workflow.py"
    ).read_text(encoding="utf8")
    down = src.split("def downgrade()")[1]
    assert "DROP VALUE" not in down
