"""Migration 047 — a case names the year of the return it files.

TWO HALVES. The pure half pins the SQL text: 047 restates 046's view to append
one column, and a restatement is exactly where an unrelated line drifts —
nothing about a drifted view fails loudly, it just disagrees with the Python
that badges the same case. The DB half (RUN_DB_TESTS, like every
`test_migration_*.py`) proves the two things only Postgres can: the index
refuses a second live case for one company-year, and the view carries the
column the dashboard now selects.

NAMED `test_migration_047.py` ON PURPOSE: `.github/workflows/backend-ci.yml`
collects the DB-backed assertions by that glob.
"""
import importlib.util
import os
import re
import uuid

import pytest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

M046 = "046_client_verification_is_the_first_stage.py"
M047 = "047_nar1_case_return_year.py"


def _migration(name: str):
    path = os.path.join(_HERE, "alembic", "versions", name)
    spec = importlib.util.spec_from_file_location(name.split(".")[0], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalise(sql: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", sql)).strip()


# --------------------------------------------------------------------------- #
#  No database needed
# --------------------------------------------------------------------------- #

def test_without_the_year_the_view_is_046s_exactly():
    """The downgrade target, and the proof the restatement changed nothing but
    the one line: comments and whitespace out, byte for byte."""
    assert _normalise(_migration(M047)._case_view_sql(with_year=False)) == \
        _normalise(_migration(M046)._case_view_sql(client_first=True))


def test_the_upgrade_adds_exactly_one_column():
    m47 = _migration(M047)
    with_year = _normalise(m47._case_view_sql(with_year=True))
    without = _normalise(m47._case_view_sql(with_year=False))
    assert with_year.replace("c.ar_period_year, ", "", 1) == without
    assert with_year.count("ar_period_year") == 1


def test_the_index_is_one_live_case_per_company_per_year():
    """Partial on BOTH conditions: a closed case gives its year back, and a case
    that has not fixed a year yet holds nothing."""
    src = _normalise(open(os.path.join(_HERE, "alembic", "versions", M047),
                          encoding="utf-8").read())
    assert ('ON public.nar1_cases (entity_id, ar_period_year) " '
            '"WHERE closed_at IS NULL AND ar_period_year IS NOT NULL"') in src
    assert _migration(M047)._YEAR_INDEX == "uq_nar1_cases_entity_live_return_year"
    assert "DROP INDEX IF EXISTS public.{_YEAR_INDEX}" in src


def test_the_recreate_restates_the_grants():
    m47 = _migration(M047)
    assert "REVOKE ALL ON public.nar1_case_registry FROM anon" in m47._CASE_GRANTS
    assert ("REVOKE ALL ON public.nar1_case_registry FROM authenticated"
            in m47._CASE_GRANTS)
    assert ("GRANT SELECT ON public.nar1_case_registry TO service_role"
            in m47._CASE_GRANTS)


def test_the_stage_lists_match_the_services():
    from services import nar1_case_status as ncs, nar1_cases

    m47 = _migration(M047)
    assert tuple(m47.CR_FILED_STAGES) == tuple(nar1_cases.CR_FILED_STAGES)
    assert m47.FILING_WINDOW_DAYS == ncs.FILING_WINDOW_DAYS


def test_the_dashboard_selects_the_column_the_view_now_carries():
    from services import nar1_cases

    assert "ar_period_year" in nar1_cases._LIST_COLS


# --------------------------------------------------------------------------- #
#  Against Postgres (RUN_DB_TESTS=1 + DATABASE_URL), every write rolled back
# --------------------------------------------------------------------------- #

db = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)


@pytest.fixture
def conn():
    psycopg2 = pytest.importorskip("psycopg2")
    connection = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def _company(cur) -> str:
    entity_id = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO entities (id, company_name, br_number, incorporation_date) "
        "VALUES (%s, %s, %s, DATE '2019-10-09')",
        (entity_id, "YEAR FIXTURE LIMITED", f"YR-{entity_id[:8]}"))
    return entity_id


def _case(cur, entity_id, year, *, closed=False) -> str:
    case_id = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO nar1_cases (id, entity_id, nar1_type, case_no, "
        "ar_period_year, closed_at) VALUES (%s, %s, 'annual_return', %s, %s, %s)",
        (case_id, entity_id, f"YR-{case_id[:8]}", year,
         "2026-09-01" if closed else None))
    return case_id


@db
def test_four_missed_years_are_four_live_cases(conn):
    with conn.cursor() as cur:
        entity_id = _company(cur)
        for year in (2023, 2024, 2025, 2026):
            _case(cur, entity_id, year)
        cur.execute("SELECT count(*) FROM nar1_cases WHERE entity_id = %s",
                    (entity_id,))
        assert cur.fetchone()[0] == 4


@db
def test_a_second_live_case_for_the_same_year_is_refused(conn):
    import psycopg2

    with conn.cursor() as cur:
        entity_id = _company(cur)
        _case(cur, entity_id, 2024)
        with pytest.raises(psycopg2.errors.UniqueViolation):
            _case(cur, entity_id, 2024)


@db
def test_a_closed_case_gives_its_year_back(conn):
    with conn.cursor() as cur:
        entity_id = _company(cur)
        _case(cur, entity_id, 2024, closed=True)
        _case(cur, entity_id, 2024)        # no error


@db
def test_cases_that_have_not_fixed_a_year_do_not_collide(conn):
    with conn.cursor() as cur:
        entity_id = _company(cur)
        _case(cur, entity_id, None)
        _case(cur, entity_id, None)        # no error


@db
def test_the_view_carries_each_cases_year(conn):
    with conn.cursor() as cur:
        entity_id = _company(cur)
        case_id = _case(cur, entity_id, 2025)
        cur.execute("SELECT ar_period_year FROM public.nar1_case_registry "
                    "WHERE id = %s", (case_id,))
        assert cur.fetchone()[0] == 2025
