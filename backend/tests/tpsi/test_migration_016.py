"""DB-backed migration assertions. Mirrors tests/test_module_permissions_seed.py:
runs only with RUN_DB_TESTS=1 against a database that has had `alembic upgrade
head` applied. Skipped in the mocked unit run."""
import os

import pytest

psycopg2 = pytest.importorskip("psycopg2")

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)

EXPECTED_TPSI = {("tpsi", "read"), ("tpsi", "write"), ("tpsi", "submit")}


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


@pytest.mark.parametrize(
    "table", ["tpsi_presenter_credentials", "tpsi_tokens", "tpsi_filings"]
)
def test_tables_exist(table):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (f"public.{table}",))
        assert cur.fetchone()[0] is not None


def test_check_allows_submit():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'public.role_permissions'::regclass AND contype = 'c'"
        )
        defs = " ".join(r[0] for r in cur.fetchall())
    for level in ("'read'", "'write'", "'delete'", "'submit'"):
        assert level in defs


@requires_super_admin
def test_super_admin_has_tpsi_permissions():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT rp.module, rp.permission FROM role_permissions rp "
            "JOIN roles r ON r.id = rp.role_id "
            "WHERE r.name = 'super_admin' AND rp.module = 'tpsi'"
        )
        assert {(m, p) for m, p in cur.fetchall()} == EXPECTED_TPSI


@requires_super_admin
def test_no_other_role_gets_tpsi():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM role_permissions rp JOIN roles r ON r.id = rp.role_id "
            "WHERE r.name <> 'super_admin' AND rp.module = 'tpsi'"
        )
        assert cur.fetchone()[0] == 0


def test_audit_event_types_seeded():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT code FROM audit_event_types WHERE code LIKE 'TPSI%%'")
        codes = {r[0] for r in cur.fetchall()}
    # TPSI_SUBMIT_SUCCESS was never seeded: the submit-lifecycle events reuse
    # the TPSI_SUBMISSION_* codes migration 012 already seeded, to avoid a
    # near-duplicate family (see AUDIT_CODES comment in 016_pbi42_tpsi.py).
    assert "TPSI_AUTH" in codes
    assert "TPSI_CRED_SET" in codes
    assert "TPSI_SUBMISSION_SUCCESS" in codes  # from migration 012, not 016


def test_tpsi_codes_have_correct_origin_and_category():
    """origin defaults to 'viewpoint' (migration 012's table DDL). Every
    TPSI_* row must explicitly override that to 'g_flowdesk'/'tpsi', or CR's
    own native events get mislabeled as imported Viewpoint events in the
    audit UI. This is the assertion that would have caught the Finding-1
    defect (016 originally inserted only (code, name), silently taking the
    'viewpoint' default)."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT code, origin, category FROM audit_event_types "
            "WHERE code LIKE 'TPSI%%'"
        )
        rows = cur.fetchall()
    assert rows, "expected TPSI audit event types to be seeded"
    for code, origin, category in rows:
        assert origin == "g_flowdesk", f"{code} has origin={origin!r}"
        assert category == "tpsi", f"{code} has category={category!r}"


def test_double_submit_is_blocked_by_partial_unique_index():
    """The double-charge guard: two 'submitted' rows for one filing must be
    impossible at the database level, not merely discouraged in code."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'tpsi_filings' AND indexname = 'uq_tpsi_filings_submitted'"
        )
        row = cur.fetchone()
    assert row is not None
    assert "UNIQUE" in row[0].upper()
    assert "submitted" in row[0]
