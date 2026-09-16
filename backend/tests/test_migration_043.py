"""Migration 043 — the CR document status, and the view it rebuilds.

TWO HALVES, AND ONLY ONE NEEDS A DATABASE.

The pure half is the one that matters most and is the cheapest to get wrong:
043 restates migration 039's view for its own downgrade, by hand, in a second
parameterised copy of the same SQL builder. Two hand-copied definitions are free
to drift, and the one that drifts is the one nobody runs until a rollback —
which is precisely when a silent difference becomes a production incident. That
check needs no Postgres and runs in the `unit` job.

The DB half is RUN_DB_TESTS-gated as every other test_migration_*.py is. The
badge parity itself lives in tests/test_migration_024.py, which drives every
reachable state through the live view; this file only pins what 043 ADDS.

NAMED `test_migration_043.py` ON PURPOSE. `.github/workflows/backend-ci.yml`
collects DB-backed assertions as `tests/test_migration_*.py`; a file outside
that glob would never run in the `migrations` job.
"""
import importlib.util
import os
import re

import pytest

from services.tpsi import doc_status as ds

VIEW = "nar1_case_registry"
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _migration(name: str):
    path = os.path.join(_HERE, "alembic", "versions", name)
    spec = importlib.util.spec_from_file_location(name.split(".")[0], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalise(sql: str) -> str:
    """Comments and whitespace out — what Postgres would actually be asked."""
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", sql)).strip()


# --------------------------------------------------------------------------- #
#  No database needed — and these are the ones a rollback depends on
# --------------------------------------------------------------------------- #

def test_the_downgrade_restores_039s_view_exactly():
    """Byte for byte, once comments and whitespace are out.

    043's `_case_view_sql(cr_status=False)` is a hand-restatement of 039's
    `_case_view_sql(closable=True)`. If they ever differ, `alembic downgrade`
    leaves a view that is nearly — but not quite — what the rest of the system
    expects, and nothing would notice until somebody needed the rollback.
    """
    m43, m39 = _migration("043_nar1_cr_document_status.py"), \
        _migration("039_nar1_case_closure.py")
    assert _normalise(m43._case_view_sql(cr_status=False)) == \
        _normalise(m39._case_view_sql(closable=True))


def test_the_migrations_code_list_matches_doc_statuss():
    """The CHECK constraint, the COALESCE fallback and the overdue predicate are
    all written from this tuple. A code added to `doc_status` without being
    added here would be refused by the constraint at write time — on a nightly
    job, at 01:13, with nobody watching."""
    m43 = _migration("043_nar1_cr_document_status.py")
    assert tuple(m43.CR_STATUS_CODES) == ds.CR_STATUS_CODES
    assert m43.CR_NOT_CHECKED == ds.NOT_CHECKED


def test_every_cr_code_is_excluded_from_the_overdue_predicate():
    """A filed return is not work waiting to be filed, whatever CR has since
    said about it. The predicate is built from the same tuple, so this is really
    a check that the rendering did not drop one."""
    m43 = _migration("043_nar1_cr_document_status.py")
    sql = m43._case_view_sql(cr_status=True)
    overdue = sql.split("AS workflow_overdue")[0]
    for code in ds.CR_STATUS_CODES:
        assert f"'{code}'" in overdue, code
    assert "'closed'" in overdue


def test_the_filed_branch_sits_below_closure_and_above_every_stage():
    """Branch ORDER is the whole contract with `nar1_case_status._code`.

    Closed beats everything, including a filed return. The CR branch beats every
    stage branch — otherwise a case CR has registered reads as Data
    Verification, which is what `test_a_filing_cr_already_holds_wins_over_a_
    newer_draft` exists to catch at the other end.
    """
    sql = _migration("043_nar1_cr_document_status.py")._case_view_sql(cr_status=True)
    expression = sql.split("WORKFLOW-STATUS-EXPRESSION-START")[1] \
                    .split("WORKFLOW-STATUS-EXPRESSION-END")[0]
    closed = expression.index("closed_at IS NOT NULL")
    filed = expression.index("manual_receipt_present")
    stage = expression.index("'data_verification'")
    assert closed < filed < stage


def test_the_audit_codes_are_seeded_with_an_explicit_origin_and_category():
    """The column default is origin='viewpoint', which would file a G-FlowDesk
    action under inherited Viewpoint history — and there is no FK from audit_log
    to this table, so an unseeded code writes fine and then renders unlabelled.
    Migration 022 exists because exactly that happened."""
    m43 = _migration("043_nar1_cr_document_status.py")
    codes = {c for c, _, _ in m43.AUDIT_CODES}
    assert codes == {"TPSI_DOC_STATUS_CHECKED", "NAR1_CR_STATUS_CHANGED"}
    for code, name, category in m43.AUDIT_CODES:
        assert name and category
    assert "'g_flowdesk'" in "".join(
        f"('{c}', '{n}', '{cat}', 'g_flowdesk')" for c, n, cat in m43.AUDIT_CODES)


# --------------------------------------------------------------------------- #
#  Against a real database
# --------------------------------------------------------------------------- #

psycopg2 = pytest.importorskip("psycopg2")

db = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)


def _conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


@db
@pytest.mark.parametrize("code", ds.CR_STATUS_CODES)
def test_the_constraint_accepts_every_code_the_normaliser_can_produce(code):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT %s::text = ANY (ARRAY["
                    "'cr_not_checked','cr_pending','cr_approved',"
                    "'cr_registered','cr_rejected','cr_unknown'])", (code,))
        assert cur.fetchone()[0] is True
        cur.execute(
            "INSERT INTO public.entities (id, company_name) "
            "VALUES (gen_random_uuid(), 'CR STATUS FIXTURE') RETURNING id")
        entity_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO public.nar1_cases (entity_id, nar1_type, cr_doc_status_code) "
            "VALUES (%s, 'annual_return', %s)", (entity_id, code))
        conn.rollback()


@db
def test_the_constraint_refuses_a_code_that_is_not_one_of_ours():
    """Loud, not silent. A stray value would render as an unlabelled badge —
    the failure mode migration 022 exists because of."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO public.entities (id, company_name) "
            "VALUES (gen_random_uuid(), 'CR STATUS FIXTURE') RETURNING id")
        entity_id = cur.fetchone()[0]
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                "INSERT INTO public.nar1_cases (entity_id, nar1_type, "
                "cr_doc_status_code) VALUES (%s, 'annual_return', 'whatever')",
                (entity_id,))
        conn.rollback()


@db
def test_null_is_allowed_because_it_is_the_state_every_case_starts_in():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'nar1_cases' AND column_name = 'cr_doc_status_code' "
            "AND is_nullable = 'YES'")
        assert cur.fetchone()[0] == 1


@db
def test_the_two_audit_codes_are_in_the_registry_with_the_right_origin():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT code, origin, category FROM public.audit_event_types "
            "WHERE code IN ('TPSI_DOC_STATUS_CHECKED', 'NAR1_CR_STATUS_CHANGED') "
            "ORDER BY code")
        rows = cur.fetchall()
    assert len(rows) == 2
    for _code, origin, category in rows:
        assert origin == "g_flowdesk"
        assert category in ("tpsi", "nar1")


@db
def test_the_pollers_index_exists_so_the_nightly_query_is_not_a_seq_scan():
    """5,900 companies, a query every night, and the terminal rows are the ones
    that accumulate — hence the partial index."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT indexdef FROM pg_indexes "
                    "WHERE indexname = 'ix_nar1_cases_cr_status_open'")
        row = cur.fetchone()
    assert row is not None
    assert "cr_registered" in row[0] and "cr_rejected" in row[0]
