"""DB-backed migration assertions (PBI-39 Block 0 — module permission seed).

Runs only when RUN_DB_TESTS=1 and DATABASE_URL point at a Postgres that has had
`alembic upgrade head` applied (the CI `migrations` job). Skipped in the mocked
unit run — the local dev box cannot resolve the direct Supabase DB host.
"""
import os

import pytest

psycopg2 = pytest.importorskip("psycopg2")

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (set RUN_DB_TESTS=1 + DATABASE_URL)",
)

EXPECTED_SUPER_ADMIN = {
    ("companies", "read"), ("companies", "write"),
    ("persons", "read"), ("persons", "write"),
    ("documents", "read"), ("documents", "write"), ("documents", "delete"),
}


def _conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def _has_super_admin() -> bool:
    """The super_admin role is seeded outside Alembic, so a fresh CI database
    has no roles at all. Migration 008 is role-existence-guarded and seeds
    nothing there — these assertions only apply where the role exists (DEV)."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM roles WHERE name = 'super_admin'")
        return cur.fetchone() is not None


requires_super_admin = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS") or not _has_super_admin(),
    reason="no super_admin role in this database (fresh CI DB — seeded outside Alembic)",
)


def test_check_allows_delete():
    """documents:delete requires the permission CHECK to accept 'delete'."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'public.role_permissions'::regclass AND contype = 'c'"
        )
        defs = " ".join(r[0] for r in cur.fetchall())
    assert "'delete'" in defs
    assert "'read'" in defs and "'write'" in defs


@requires_super_admin
def test_super_admin_new_modules_seeded():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT rp.module, rp.permission "
            "FROM role_permissions rp JOIN roles r ON r.id = rp.role_id "
            "WHERE r.name = 'super_admin' "
            "AND rp.module IN ('companies', 'persons', 'documents')"
        )
        got = {(m, p) for m, p in cur.fetchall()}
    assert got == EXPECTED_SUPER_ADMIN


@requires_super_admin
def test_non_super_admin_roles_have_no_new_modules():
    """nar1_write / all_access were intentionally NOT granted the new modules."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) "
            "FROM role_permissions rp JOIN roles r ON r.id = rp.role_id "
            "WHERE r.name <> 'super_admin' "
            "AND rp.module IN ('companies', 'persons', 'documents')"
        )
        assert cur.fetchone()[0] == 0


def test_person_registry_view_role_flags_match_distinct_persons():
    """Migration 009: the view's role flags must equal DISTINCT person counts.

    Counting link-table rows over-counts (one person, many companies), which is
    exactly why the view exists.
    """
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM person_registry WHERE is_director")
        view_directors = cur.fetchone()[0]
        cur.execute(
            "SELECT count(DISTINCT person_id) FROM entity_officers "
            "WHERE person_id IS NOT NULL AND role = 'director'"
        )
        assert view_directors == cur.fetchone()[0]

        cur.execute("SELECT count(*) FROM person_registry WHERE is_shareholder")
        view_shareholders = cur.fetchone()[0]
        cur.execute(
            "SELECT count(DISTINCT person_id) FROM shareholdings WHERE person_id IS NOT NULL"
        )
        assert view_shareholders == cur.fetchone()[0]

        # one row per person, no fan-out from the joins
        cur.execute("SELECT count(*) FROM person_registry")
        rows = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM persons")
        assert rows == cur.fetchone()[0]


def test_audit_entity_id_is_indexed():
    """Migration 010: person-scoped audit events carry case_id=NULL and
    entity_id=<person id>. Without an index on entity_id that read seq-scans the
    whole audit_log (226k rows) and hits the statement timeout.

    TWO ASSERTIONS, and only one of them is about a plan. The index either
    exists or it does not, and that is checkable anywhere. Whether the PLANNER
    reaches for it depends on the table having enough rows to be worth an index
    — which CI's `audit_log` does not, being empty.

    This used to assert the plan unconditionally and pass in CI, but only by
    accident: with no statistics at all Postgres falls back to a default
    estimate of a large table and picks the index. Migration 035 runs `ANALYZE`
    (it must, or DEV keeps the plans it chose before its indexes existed), the
    empty table then honestly reported 0 rows, and the planner correctly chose a
    sequential scan — failing a test on a database where nothing was wrong.
    """
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM pg_indexes WHERE schemaname = 'public' "
            "AND tablename = 'audit_log' AND indexname LIKE 'idx_audit_log_entity%'"
        )
        assert cur.fetchone()[0] >= 1, "migration 010's entity_id index is missing"

        cur.execute("SELECT count(*) FROM audit_log")
        if cur.fetchone()[0] < 5_000:
            pytest.skip("audit_log is too small for its plan to mean anything")

        cur.execute(
            "EXPLAIN SELECT * FROM audit_log "
            "WHERE entity_id = 'probe' ORDER BY created_at DESC"
        )
        plan = " ".join(r[0] for r in cur.fetchall())
    assert "idx_audit_log_entity" in plan, plan
    assert "Seq Scan" not in plan, plan


@requires_super_admin
def test_seed_is_idempotent():
    """Re-inserting the seed must not create duplicates (ON CONFLICT DO NOTHING)."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.role_permissions (role_id, module, permission)
            SELECT r.id, m.module, m.permission
            FROM public.roles r
            CROSS JOIN (VALUES
                ('companies', 'read'), ('companies', 'write'),
                ('persons', 'read'), ('persons', 'write'),
                ('documents', 'read'), ('documents', 'write'), ('documents', 'delete')
            ) AS m(module, permission)
            WHERE r.name = 'super_admin'
            ON CONFLICT (role_id, module, permission) DO NOTHING
            """
        )
        conn.commit()
        cur.execute(
            "SELECT count(*) "
            "FROM role_permissions rp JOIN roles r ON r.id = rp.role_id "
            "WHERE r.name = 'super_admin' "
            "AND rp.module IN ('companies', 'persons', 'documents')"
        )
        assert cur.fetchone()[0] == len(EXPECTED_SUPER_ADMIN)
