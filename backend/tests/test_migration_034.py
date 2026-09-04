"""Migration 034 — the audit trail names WHICH record and WHICH module.

DB-backed and RUN_DB_TESTS-gated, per tests/test_migration_021..033.py.

NAMED `test_migration_034.py` ON PURPOSE. `.github/workflows/backend-ci.yml`
runs DB-backed tests as `pytest tests/test_migration_*.py` under RUN_DB_TESTS=1;
a file outside that glob is skipped by the `unit` job and never collected by the
`migrations` job, so it would run nowhere at all.

What these assert, and why each one is here rather than in the unit suite:

  * the four columns exist and `subject_id` is a REAL uuid. Declaring a uuid
    column as text in a filter spec resolves `eq` to `ilike`, and Postgres has
    no `uuid ~~* unknown` operator — the whole listing 500s and the browser
    reports only "Failed to fetch" (see test_migration_033). Every unit test
    mocks PostgREST, so the type only exists where the real column does.
  * the backfill actually resolved the historical rows. A migration that adds
    four nullable columns and fills none of them passes every unit test in the
    repo while leaving the trail exactly as unreadable as before.
  * no row was labelled with a module or kind outside the closed vocabulary the
    filter enums accept — a value the enum will not name is a row unreachable
    from the screen.

Every fixture is rolled back. This runs against DEV on a developer machine and
must leave nothing behind.
"""
import os

import pytest

from routers import audit as audit_router
from services import audit_subject

psycopg2 = pytest.importorskip("psycopg2")

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)

_TYPES_FOR_KIND = {
    "text": {"text", "character varying", "character"},
    "enum": {"text", "character varying", "USER-DEFINED"},
    "uuid": {"uuid"},
    "number": {"integer", "bigint", "smallint", "numeric", "double precision", "real"},
    "date": {"date"},
    "timestamp": {"timestamp with time zone", "timestamp without time zone"},
    "bool": {"boolean"},
}


@pytest.fixture
def conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    c = psycopg2.connect(url)
    try:
        yield c
    finally:
        c.rollback()
        c.close()


def _column_types(cur):
    cur.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'audit_log'
        """
    )
    return dict(cur.fetchall())


# ── the columns ───────────────────────────────────────────────────────────────

def test_the_four_columns_exist_with_the_right_types(conn):
    with conn.cursor() as cur:
        types = _column_types(cur)
    assert types.get("module") == "text"
    assert types.get("subject_kind") == "text"
    assert types.get("subject_ref") == "text"
    # A uuid, and it must stay one — see the module docstring.
    assert types.get("subject_id") == "uuid"


def test_every_audit_filter_column_matches_its_real_type(conn):
    """A filter kind is a claim about a Postgres type, and a wrong claim is a
    500 on a page nobody can use."""
    problems = []
    with conn.cursor() as cur:
        types = _column_types(cur)
    for name, column in audit_router._FILTERABLE.items():
        actual = types.get(name)
        if actual is None:
            problems.append(f"audit_log.{name} does not exist")
            continue
        allowed = _TYPES_FOR_KIND[column.kind]
        if actual not in allowed:
            problems.append(
                f"audit_log.{name} is {actual!r} but is declared "
                f"tf.{column.kind}() (expects one of {sorted(allowed)})"
            )
    assert not problems, "\n".join(problems)


def test_the_filtering_indexes_exist(conn):
    """Without them, every module filter is a sequential scan of 226k+ rows."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = 'public' AND tablename = 'audit_log'"
        )
        names = {r[0] for r in cur.fetchall()}
    for column in ("module", "subject_kind", "subject_id", "subject_ref"):
        assert f"idx_audit_log_{column}" in names, column


# ── the vocabulary, as actually stored ────────────────────────────────────────

def test_no_stored_module_is_outside_the_filter_enum(conn):
    """A module the filter cannot name is a row unreachable from the screen."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT module FROM public.audit_log "
                    "WHERE module IS NOT NULL")
        stored = {r[0] for r in cur.fetchall()}
    assert stored <= set(audit_subject.MODULES), sorted(stored - set(audit_subject.MODULES))


def test_no_stored_subject_kind_is_outside_the_filter_enum(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT subject_kind FROM public.audit_log "
                    "WHERE subject_kind IS NOT NULL")
        stored = {r[0] for r in cur.fetchall()}
    assert stored <= set(audit_subject.SUBJECT_KINDS), sorted(stored)


# ── the backfill actually ran ─────────────────────────────────────────────────

def test_the_viewpoint_history_was_resolved(conn):
    """The imported rows are the bulk of the trail. If the backfill did not run,
    every one of them still renders with a raw Viewpoint key and no module —
    which is the complaint this migration exists to answer.

    A tolerance rather than 100%: some KeyCodes name records that were never
    imported (deleted parties, non-client entities), and inventing a subject for
    those would be worse than leaving them blank.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT count(*) FILTER (WHERE subject_kind IS NOT NULL), count(*)
            FROM public.audit_log
            WHERE source = 'viewpoint_import' AND source_keycode IS NOT NULL
        """)
        resolved, total = cur.fetchone()
    if not total:
        pytest.skip("no Viewpoint history in this database")
    assert resolved / total > 0.8, f"only {resolved}/{total} imported rows resolved"


def test_person_scoped_viewpoint_events_resolve_to_people(conn):
    """The specific miss: a KeyCode that is a person's RefCode was only ever
    looked up in `entities`, so it fell through to printing the raw key."""
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM public.persons WHERE vp_source_key IS NOT NULL")
        if not cur.fetchone()[0]:
            pytest.skip("no imported people in this database")
        cur.execute("""
            SELECT count(*) FROM public.audit_log
            WHERE source = 'viewpoint_import' AND subject_kind = 'person'
        """)
        assert cur.fetchone()[0] > 0


def test_no_subject_id_points_at_a_record_of_THE_WRONG_KIND(conn):
    """The invariant that is actually checkable, and the one a bug would break.

    A DANGLING id is legitimate and expected: there is no FK on `subject_id`,
    because the trail has to survive the record being deleted — which is the
    same reason `company_name` is denormalized. DEV proves it: 104 rows name
    NAR1 cases that were created and deleted during testing, and the right
    behaviour is to keep showing the name and let the link 404.

    A MISCLASSIFIED id is a bug, and this is the shape of the one real data
    caught. A person's address edit writes the PERSON id into `case_id`
    (routers/persons.py), so a backfill that reads "case_id is not null" as
    "this is about a company" labels the row 'company', points `subject_id` at
    a person, and renders a Company chip over a human being's name.
    """
    problems = []
    with conn.cursor() as cur:
        cur.execute("""
            SELECT count(*) FROM public.audit_log a
            WHERE a.subject_kind = 'company'
              AND EXISTS (SELECT 1 FROM public.persons p WHERE p.id = a.subject_id)
        """)
        if cur.fetchone()[0]:
            problems.append("rows labelled 'company' whose subject is a person")
        cur.execute("""
            SELECT count(*) FROM public.audit_log a
            WHERE a.subject_kind = 'person'
              AND EXISTS (SELECT 1 FROM public.entities e WHERE e.id = a.subject_id)
        """)
        if cur.fetchone()[0]:
            problems.append("rows labelled 'person' whose subject is a company")
        cur.execute("""
            SELECT count(*) FROM public.audit_log a
            WHERE a.subject_kind = 'case'
              AND EXISTS (SELECT 1 FROM public.entities e WHERE e.id = a.subject_id)
        """)
        if cur.fetchone()[0]:
            problems.append("rows labelled 'case' whose subject is a company "
                            "(the tpsi_filing id-space mix-up)")
    assert not problems, "; ".join(problems)


def test_no_imported_row_claims_a_module_viewpoint_never_had(conn):
    """Viewpoint recorded no NAR1 case workflow, no document store and no CR
    e-Filing. Labelling an imported row with one of those would be an invention,
    and the instruction was to leave it blank instead."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT module FROM public.audit_log
            WHERE source = 'viewpoint_import' AND module IS NOT NULL
        """)
        stored = {r[0] for r in cur.fetchall()}
    assert stored <= {"body_corporate", "natural_person"}, sorted(stored)


def test_the_backfill_is_idempotent(conn):
    """Re-running 034's UPDATEs changes nothing. Every one is guarded on
    `IS NULL`, which is what makes a partially-applied run safe to finish."""
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE public.audit_log a
            SET subject_kind = 'company', subject_id = e.id, subject_ref = e.br_number,
                module = 'body_corporate'
            FROM public.entities e
            WHERE a.source = 'viewpoint_import'
              AND a.subject_kind IS NULL
              AND a.source_keycode = e.vp_source_key
        """)
        assert cur.rowcount == 0
    conn.rollback()
