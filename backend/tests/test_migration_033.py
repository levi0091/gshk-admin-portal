"""Migration 033 — the -42 floor is gone, and no filter lies about a column type.

DB-backed and RUN_DB_TESTS-gated, per tests/test_migration_021/022/023/024.py.

NAMED `test_migration_033.py` ON PURPOSE. `.github/workflows/backend-ci.yml`
runs DB-backed tests as `pytest tests/test_migration_*.py` under RUN_DB_TESTS=1;
a file outside that glob is skipped by the `unit` job and never collected by the
`migrations` job, so it would run nowhere at all.

TWO SUBJECTS, one migration's worth of consequence between them.

1. The FLOOR. 019 counted negative only inside the 42-day filing window and then
   jumped to counting down to the next anniversary, so no value below -42 could
   exist and clearing the registry filter's lower bound revealed nothing. These
   tests assert the new rule directly against the view's own arithmetic, using
   companies inserted at known offsets, rather than against whatever the DEV
   book happens to contain today.

2. The COLUMN KINDS. The reason `created_by` broke the whole dashboard is that a
   `uuid` column was declared `tf.text()`, and text resolves `eq` to `ilike` —
   for which Postgres has no `uuid ~~* unknown` operator. Nothing in the unit
   suite could catch that: every unit test mocks the PostgREST client, so the
   mismatch only exists where the real type does. `test_every_filterable_column_
   matches_its_real_type` closes that hole for all three routers at once, which
   is worth more than the one-line fix that prompted it.

Every test rolls its fixtures back. This runs against DEV on a developer machine
and must leave nothing behind.
"""
import os
import uuid

import pytest

from routers import companies as companies_router
from routers import persons as persons_router
from services import nar1_cases

psycopg2 = pytest.importorskip("psycopg2")

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)

FILING_WINDOW_DAYS = 42

#: The Postgres types each filter kind may legitimately be declared for.
#:
#: `enum` covers both a real enum type (`entity_status`) and the text a view
#: casts one to (`c.status::text`), which is why USER-DEFINED and text are both
#: allowed there. `uuid` allows ONLY uuid: that is the whole point of the file.
_TYPES_FOR_KIND = {
    "text": {"text", "character varying", "character"},
    "enum": {"text", "character varying", "USER-DEFINED"},
    "uuid": {"uuid"},
    "number": {"integer", "bigint", "smallint", "numeric", "double precision", "real"},
    "date": {"date"},
    "timestamp": {"timestamp with time zone", "timestamp without time zone"},
    "bool": {"boolean"},
}

#: Which relation each router filters. Pseudo-columns (`flag`, `role`,
#: `workflow_status`) never enter a `_FILTERABLE` spec, so every name below is a
#: real column and a missing one is itself a failure worth reporting.
_SPECS = [
    ("company_registry", companies_router._FILTERABLE),
    ("person_registry", persons_router._FILTERABLE),
    ("nar1_case_registry", nar1_cases._FILTERABLE),
]


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


def _column_types(cur, relation):
    cur.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (relation,),
    )
    return dict(cur.fetchall())


# ── 1. the column kinds ───────────────────────────────────────────────────────

def test_every_filterable_column_matches_its_real_type(conn):
    """A filter kind is a claim about a Postgres type, and a wrong claim is a
    500 on a page nobody can use.

    `created_by` was declared text; it is uuid; `eq` on text is an `ilike`;
    Postgres has no `uuid ~~* unknown`. The dashboard filtered itself to the
    signed-in user by default, so the FIRST request every user made was the
    broken one, and the only symptom was the browser's own "Failed to fetch".
    """
    problems = []
    with conn.cursor() as cur:
        for relation, spec in _SPECS:
            types = _column_types(cur, relation)
            assert types, f"{relation} is missing — did a migration not run?"
            for name, column in spec.items():
                actual = types.get(name)
                if actual is None:
                    problems.append(f"{relation}.{name} does not exist")
                    continue
                allowed = _TYPES_FOR_KIND[column.kind]
                if actual not in allowed:
                    problems.append(
                        f"{relation}.{name} is {actual!r} but is declared "
                        f"tf.{column.kind}() (expects one of {sorted(allowed)})"
                    )
    assert not problems, "\n".join(problems)


def test_ilike_on_a_uuid_really_does_raise(conn):
    """The premise of the test above, stated once against the real database so
    it cannot rot into folklore."""
    with conn.cursor() as cur:
        with pytest.raises(psycopg2.errors.UndefinedFunction):
            cur.execute("SELECT 1 FROM public.nar1_cases WHERE created_by ILIKE 'x'")
    conn.rollback()


def test_eq_on_a_uuid_is_fine(conn):
    """And the replacement works — otherwise the fix trades one 500 for another."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM public.nar1_cases WHERE created_by = %s",
            (str(uuid.uuid4()),),
        )
        assert cur.fetchone()[0] == 0


# ── 2. the floor ──────────────────────────────────────────────────────────────

def _insert_company(cur, days_since_anniversary):
    """A company whose last anniversary was exactly N days ago, in HK terms.

    Built from `hk_today()` rather than a literal so the row means the same
    thing whenever the suite runs, including during the eight hours a day when
    UTC and Hong Kong disagree about the date.
    """
    eid = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO public.entities (id, company_name, status, incorporation_date)
        VALUES (%s, %s, 'live',
                (public.hk_today() - make_interval(days => %s))::date
                  - make_interval(years => 5))
        """,
        (eid, f"zz-033-{eid[:8]}", days_since_anniversary),
    )
    return eid


def _days(cur, eid):
    cur.execute(
        "SELECT days_to_anniversary FROM public.company_registry WHERE id = %s",
        (eid,),
    )
    return cur.fetchone()[0]


@pytest.mark.parametrize("since", [0, 1, 41, 42, 43, 90, 181])
def test_a_passed_anniversary_counts_negative_past_42(conn, since):
    """The change Levi asked for. Under 019 anything past 42 flipped to a large
    POSITIVE number and the whole late population hid among the companies with
    most of a year in hand."""
    with conn.cursor() as cur:
        eid = _insert_company(cur, since)
        assert _days(cur, eid) == -since
    conn.rollback()


def test_the_switch_happens_at_the_midpoint_not_at_42(conn):
    """Past the halfway mark the NEXT anniversary is the nearer fact, so the
    column counts down again. Without this the number would run to -364 and
    "days to anniversary" would name something that never counts to anything."""
    with conn.cursor() as cur:
        eid = _insert_company(cur, 300)
        d = _days(cur, eid)
        assert d > 0, f"300 days past should count down to the next one, got {d}"
        assert 60 <= d <= 70, d
    conn.rollback()


def test_no_incorporation_date_still_means_null(conn):
    """Unchanged from 019, and the reason the CASE has three branches."""
    with conn.cursor() as cur:
        eid = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO public.entities (id, company_name, status) "
            "VALUES (%s, %s, 'live')",
            (eid, f"zz-033-{eid[:8]}"),
        )
        assert _days(cur, eid) is None
    conn.rollback()


def test_the_case_registry_inherits_the_new_range(conn):
    """nar1_case_registry selects e.days_to_anniversary straight through. If the
    rebuild in 033 dropped that join the dashboard would silently lose the
    column rather than fail."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='public' AND table_name='nar1_case_registry'
              AND column_name IN ('days_to_anniversary','workflow_overdue',
                                  'created_by','created_by_name')
        """)
        found = {r[0] for r in cur.fetchall()}
    assert found == {"days_to_anniversary", "workflow_overdue",
                     "created_by", "created_by_name"}


def test_workflow_overdue_is_no_longer_dead(conn):
    """024 and 025 shipped this predicate knowing it could never fire, and said
    so in their own bodies. Removing the floor is what makes it mean something,
    so assert the arithmetic can actually reach the branch."""
    with conn.cursor() as cur:
        eid = _insert_company(cur, 90)
        assert _days(cur, eid) < -FILING_WINDOW_DAYS
    conn.rollback()


def test_the_view_still_keeps_anon_out_of_the_case_registry(conn):
    """DROP VIEW discards grants. Supabase's default privileges then hand anon
    and authenticated ALL on any new relation in `public`, so a rebuild that
    forgot 024's REVOKE block would publish every case — client approvals and
    statutory receipts included — through PostgREST."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'anon'")
        if not cur.fetchone():
            pytest.skip("no `anon` role — vanilla Postgres, not Supabase")
        cur.execute("""
            SELECT has_table_privilege('anon', 'public.nar1_case_registry', 'SELECT')
        """)
        assert cur.fetchone()[0] is False
