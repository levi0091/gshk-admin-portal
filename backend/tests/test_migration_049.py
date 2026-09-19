"""Migration 049 — soft delete of companies and natural persons.

TWO HALVES, like every `test_migration_*.py`. The pure half pins the SQL: 049
RESTATES two views to add a filter, and a restatement is exactly where an
unrelated line drifts. With the filter off, each must be the view it replaces,
byte for byte once comments and whitespace are gone. The DB half (RUN_DB_TESTS,
collected by the glob in backend-ci.yml) proves what only Postgres can.
"""
import importlib.util
import os
import re
import uuid

import pytest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VERSIONS = os.path.join(_HERE, "alembic", "versions")

M009 = "009_pbi39_person_registry_view.py"
M033 = "033_anniversary_no_floor_at_42.py"
M049 = "049_soft_delete_entities_and_persons.py"


def _migration(name: str):
    spec = importlib.util.spec_from_file_location(
        "m" + name.split("_")[0], os.path.join(_VERSIONS, name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source(name: str) -> str:
    with open(os.path.join(_VERSIONS, name), encoding="utf-8") as fh:
        return fh.read()


def _normalise(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", "", sql)
    return re.sub(r"\s+", " ", sql).strip().rstrip(";").strip()


def _as_created(sql: str) -> str:
    """049 replaces where 009/033 created, and names the option 009 lacked."""
    return (_normalise(sql)
            .replace("CREATE OR REPLACE VIEW", "CREATE VIEW")
            .replace(" WITH (security_invoker = true)", ""))


# --------------------------------------------------------------------------- #
#  No database needed
# --------------------------------------------------------------------------- #

def test_without_the_filter_the_company_view_is_033s_exactly():
    m33, m49 = _migration(M033), _migration(M049)
    assert _as_created(m49._company_view(["*"], hide_deleted=False)) == \
        _as_created(m33._company_view(m33._NEAREST))


def test_the_company_filter_is_one_where_clause_and_nothing_else():
    m49 = _migration(M049)
    on = _normalise(m49._company_view(["id", "company_name"], hide_deleted=True))
    off = _normalise(m49._company_view(["id", "company_name"], hide_deleted=False))
    assert on == off + " WHERE e.deleted_at IS NULL"


def test_without_the_filter_the_person_view_is_009s_exactly():
    sql_009 = _source(M009).split('op.execute("""', 1)[1].split('""")', 1)[0]
    assert _as_created(_migration(M049)._person_view(hide_deleted=False)) == \
        _as_created(sql_009)


def test_the_person_filter_hides_the_person_and_roles_at_deleted_companies():
    sql = _normalise(_migration(M049)._person_view(hide_deleted=True))
    assert sql.endswith("WHERE p.deleted_at IS NULL")
    # One live-company test per role subquery: director, shareholder, the two
    # secretary sources, beneficial owner.
    assert sql.count("le.deleted_at IS NULL") == 5
    for alias in ("o", "s", "cs", "b"):
        assert f"le.id = {alias}.entity_id" in sql


def test_both_views_are_restated_as_security_invoker():
    """A replace that omits WITH resets the option, which for person_registry
    would undo 048 and publish it to the anon key again."""
    m49 = _migration(M049)
    for hide in (True, False):
        assert "WITH (security_invoker = true)" in m49._company_view(["id"], hide_deleted=hide)
        assert "WITH (security_invoker = true)" in m49._person_view(hide_deleted=hide)


def test_the_audit_codes_match_the_service_and_are_g_flowdesk_native():
    from services import audit_events

    codes = {c: (n, cat) for c, n, cat in _migration(M049).AUDIT_CODES}
    assert codes == {
        audit_events.GF_COMPANY_DELETED: ("Company Deleted", "entity"),
        audit_events.GF_COMPANY_RESTORED: ("Company Restored", "entity"),
        audit_events.GF_PERSON_DELETED: ("Person Deleted", "party"),
        audit_events.GF_PERSON_RESTORED: ("Person Restored", "party"),
    }
    assert "'g_flowdesk')" in _source(M049)


def test_the_new_level_is_delete_on_companies_and_persons_only():
    assert _migration(M049).PERMISSIONS == [("companies", "delete"),
                                            ("persons", "delete")]


def test_the_downgrade_replaces_the_views_before_it_drops_their_columns():
    body = _source(M049).split("def downgrade", 1)[1]
    assert body.index("_company_view(") < body.index("DROP COLUMN")
    assert body.index("_person_view(") < body.index("DROP COLUMN")


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
        (entity_id, "DELETE FIXTURE LIMITED", f"DL-{entity_id[:8]}"))
    return entity_id


def _person(cur) -> str:
    person_id = str(uuid.uuid4())
    cur.execute("INSERT INTO persons (id, full_name) VALUES (%s, %s)",
                (person_id, "DELETE FIXTURE PERSON"))
    return person_id


def _delete(cur, table, row_id):
    cur.execute(f"UPDATE {table} SET deleted_at = now(), deleted_reason = 'test' "
                f"WHERE id = %s", (row_id,))


def _count(cur, sql, *args):
    cur.execute(sql, args)
    return cur.fetchone()[0]


@db
def test_a_deletion_without_a_reason_is_refused(conn):
    import psycopg2

    with conn.cursor() as cur:
        entity_id = _company(cur)
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("UPDATE entities SET deleted_at = now() WHERE id = %s",
                        (entity_id,))


@db
def test_a_deleted_company_and_its_cases_leave_the_registries(conn):
    with conn.cursor() as cur:
        entity_id = _company(cur)
        cur.execute("INSERT INTO nar1_cases (id, entity_id, nar1_type, case_no) "
                    "VALUES (%s, %s, 'annual_return', %s)",
                    (str(uuid.uuid4()), entity_id, f"DL-{entity_id[:8]}"))
        assert _count(cur, "SELECT count(*) FROM company_registry WHERE id = %s", entity_id) == 1
        assert _count(cur, "SELECT count(*) FROM nar1_case_registry WHERE entity_id = %s", entity_id) == 1
        _delete(cur, "entities", entity_id)
        assert _count(cur, "SELECT count(*) FROM company_registry WHERE id = %s", entity_id) == 0
        assert _count(cur, "SELECT count(*) FROM nar1_case_registry WHERE entity_id = %s", entity_id) == 0
        # Still there underneath.
        assert _count(cur, "SELECT count(*) FROM entities WHERE id = %s", entity_id) == 1


@db
def test_a_deleted_person_leaves_the_registry_and_a_deleted_company_makes_nobody_a_director(conn):
    with conn.cursor() as cur:
        entity_id, person_id = _company(cur), _person(cur)
        cur.execute("INSERT INTO entity_officers (entity_id, person_id, role) "
                    "VALUES (%s, %s, 'director')", (entity_id, person_id))
        assert _count(cur, "SELECT count(*) FROM person_registry "
                           "WHERE id = %s AND is_director", person_id) == 1
        _delete(cur, "entities", entity_id)
        assert _count(cur, "SELECT count(*) FROM person_registry "
                           "WHERE id = %s AND is_director", person_id) == 0
        _delete(cur, "persons", person_id)
        assert _count(cur, "SELECT count(*) FROM person_registry WHERE id = %s", person_id) == 0


@db
def test_the_views_keep_their_columns_and_their_mode(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'company_registry' "
                    "ORDER BY ordinal_position")
        cols = [r[0] for r in cur.fetchall()]
        assert "deleted_at" not in cols
        assert cols[-3:] == ["last_anniversary", "next_anniversary", "days_to_anniversary"]
        for view in ("company_registry", "person_registry"):
            cur.execute("SELECT reloptions FROM pg_class WHERE oid = %s::regclass",
                        (f"public.{view}",))
            assert "security_invoker=true" in (cur.fetchone()[0] or [])
        assert _count(cur, "SELECT count(*) FROM information_schema.columns "
                           "WHERE table_schema = 'public' "
                           "AND table_name = 'person_registry'") == 16


@db
def test_the_audit_codes_are_seeded_as_g_flowdesk(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT code, origin FROM audit_event_types WHERE code IN "
                    "('GF_COMPANY_DELETED', 'GF_COMPANY_RESTORED', "
                    "'GF_PERSON_DELETED', 'GF_PERSON_RESTORED')")
        rows = dict(cur.fetchall())
    assert len(rows) == 4 and set(rows.values()) == {"g_flowdesk"}
