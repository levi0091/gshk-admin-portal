"""Migration 039 — closing a case: the columns, the view branch, the audit code.

DB-backed and RUN_DB_TESTS-gated, per tests/test_migration_021..038.py.

NAMED `test_migration_039.py` ON PURPOSE. `.github/workflows/backend-ci.yml`
runs DB-backed tests as `pytest tests/test_migration_*.py` under RUN_DB_TESTS=1;
a file outside that glob is skipped by the `unit` job and never collected by the
`migrations` job, so it would run nowhere at all.

The BADGE parity — that the view's `closed` branch sits in the same place as
`nar1_case_status._code`'s — is asserted in `test_migration_024.py`, which drives
all 480 reachable (stage x sent x approved x manual x closed) states through the
live view. This file asserts the things that test cannot see:

  * the three columns exist, with the types the service writes. Every unit test
    mocks PostgREST, so a column that was never added passes the whole mocked
    suite and then 500s the first close.
  * `closed_by` is a real FK to `users`, so a closure names an account that
    exists — the trail's only answer to "who ended this case".
  * the view carries `closed_by_name`. `nar1_cases` holds a uuid; a Closed
    banner naming a uuid is one nobody can read.
  * the audit code is seeded WITH an explicit category and origin. There is no
    FK from `audit_log` to `audit_event_types`, so an unseeded code does not
    fail — it writes fine and then renders unlabelled in the trail, which is
    the silent failure migration 022 exists to close. The column default is
    `origin='viewpoint'`, which would file a G-FlowDesk action under inherited
    Viewpoint history.
  * `nar1_case_registry` is not readable by `anon` or `authenticated`. DROP VIEW
    discards grants and Supabase's default privileges GRANT ALL on every new
    relation in `public`, so a recreate that forgot to restate them would
    PUBLISH every case row through PostgREST — client-approval state, statutory
    receipts, and now the reason a client walked away.

Every fixture is rolled back. This runs against DEV on a developer machine and
must leave nothing behind.
"""
import os
import uuid

import pytest

psycopg2 = pytest.importorskip("psycopg2")

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)


def _a_portal_user(cur) -> tuple[str, str]:
    """(id, display_name) of a `public.users` row this fixture may point at.

    Prefers one that already exists, and creates one only when there is none.
    `public.users.id` is a foreign key to `auth.users(id)` — Supabase's table,
    not ours — so manufacturing a user means writing a row into the auth schema.
    On DEV there are real accounts and doing that is both unnecessary and rude;
    on the vanilla Postgres the CI `migrations` job runs, `auth.users` is the
    two-column stand-in the workflow bootstraps and nothing has ever inserted
    into it (migration 027 seeds `public.users` FROM `auth.users`, so an empty
    auth table seeds nothing).

    Everything written here is rolled back with the rest of the fixture.
    """
    cur.execute("SELECT id, display_name FROM public.users "
                "WHERE display_name IS NOT NULL ORDER BY created_at LIMIT 1")
    row = cur.fetchone()
    if row:
        return str(row[0]), row[1]

    import uuid as _uuid
    user_id, role_id = str(_uuid.uuid4()), str(_uuid.uuid4())
    cur.execute("INSERT INTO auth.users (id) VALUES (%s)", (user_id,))
    # `users.role_id` is NOT NULL and references `roles`, so the fixture brings
    # its own role rather than borrowing whichever one happens to exist.
    cur.execute("INSERT INTO public.roles (id, name) VALUES (%s, %s)",
                (role_id, f"closure-fixture-{role_id[:8]}"))
    cur.execute(
        "INSERT INTO public.users (id, display_name, email, role_id) "
        "VALUES (%s, 'Levi Z.', %s, %s)",
        (user_id, f"closure-{user_id[:8]}@example.test", role_id),
    )
    return user_id, "Levi Z."


@pytest.fixture
def conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    connection = psycopg2.connect(url)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


# --------------------------------------------------------------------------- #
#  The columns
# --------------------------------------------------------------------------- #

def test_the_three_closure_columns_exist_with_the_types_the_service_writes(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='nar1_cases' "
            "  AND column_name IN ('closed_at','closed_by','closed_reason') "
            "ORDER BY column_name"
        )
        found = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    assert found["closed_at"][0] == "timestamp with time zone"
    assert found["closed_by"][0] == "uuid"
    assert found["closed_reason"][0] == "text"
    # NULLABLE, all three. NULL is what "not closed" means, and it is the state
    # every one of the 30-odd existing cases is in.
    assert {v[1] for v in found.values()} == {"YES"}


def test_closed_by_references_users(conn):
    """The trail's only answer to "who ended this case". A free uuid column
    would let a closure name an account that never existed."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT ccu.table_name, ccu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON kcu.constraint_name = tc.constraint_name
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_name = 'nar1_cases'
              AND kcu.column_name = 'closed_by'
        """)
        assert cur.fetchall() == [("users", "id")]


def test_nothing_already_in_the_book_was_closed_by_this_migration(conn):
    """Additive, and the claim is worth checking rather than trusting: every
    case that existed before 039 must still be open."""
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM nar1_cases WHERE closed_at IS NOT NULL")
        assert cur.fetchone()[0] == 0


# --------------------------------------------------------------------------- #
#  The view
# --------------------------------------------------------------------------- #

def test_the_registry_names_the_closer_and_carries_the_reason(conn):
    """`closed_by_name` is joined from `users` for the same reason
    `created_by_name` is: the case row holds only the uuid."""
    entity_id, case_id = str(uuid.uuid4()), str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO entities (id, company_name) VALUES (%s, 'CLOSURE FIXTURE')",
            (entity_id,),
        )
        user_id, display_name = _a_portal_user(cur)
        cur.execute(
            "INSERT INTO nar1_cases (id, entity_id, nar1_type, closed_at, "
            "closed_by, closed_reason) VALUES (%s, %s, 'annual_return', "
            "now(), %s, 'client is dissolving the company')",
            (case_id, entity_id, user_id),
        )
        cur.execute(
            "SELECT workflow_status, workflow_overdue, closed_by_name, "
            "       closed_reason, closed_at "
            "FROM nar1_case_registry WHERE id = %s", (case_id,),
        )
        status, overdue, name, reason, closed_at = cur.fetchone()

    assert status == "closed"
    assert overdue is False
    assert name == display_name
    assert reason == "client is dissolving the company"
    assert closed_at is not None


def test_a_closed_case_is_not_overdue_however_far_past_its_anniversary(conn):
    """Migration 033 made `workflow_overdue` live; 039 excludes closed cases
    from it. An alarm about a return nobody is going to file is exactly the
    noise closing a case exists to remove.

    The company is dated so `days_to_anniversary` lands well below -42, which is
    the only way this assertion is about the closure rather than about the date.
    """
    entity_id = str(uuid.uuid4())
    open_id, closed_id = str(uuid.uuid4()), str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO entities (id, company_name, incorporation_date) "
            "VALUES (%s, 'OVERDUE FIXTURE', "
            "        public.hk_today() - INTERVAL '100 days')",
            (entity_id,),
        )
        cur.execute(
            "INSERT INTO nar1_cases (id, entity_id, nar1_type) "
            "VALUES (%s, %s, 'annual_return')", (open_id, entity_id),
        )
        cur.execute(
            "INSERT INTO nar1_cases (id, entity_id, nar1_type, closed_at, "
            "closed_reason) VALUES (%s, %s, 'annual_return', now(), 'stopped')",
            (closed_id, entity_id),
        )
        cur.execute(
            "SELECT id, days_to_anniversary, workflow_overdue "
            "FROM nar1_case_registry WHERE entity_id = %s", (entity_id,),
        )
        rows = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    days_open, overdue_open = rows[open_id]
    days_closed, overdue_closed = rows[closed_id]
    # The precondition: both are the same company, both well outside the window.
    assert days_open == days_closed < -42
    # The open one flags. The closed one does not. Same days, different answer.
    assert overdue_open is True
    assert overdue_closed is False


def test_the_registry_is_still_invisible_to_anon_and_authenticated(conn):
    """DROP VIEW discards grants, and Supabase's default privileges GRANT ALL on
    every new relation in `public`. A recreate that forgot to restate the REVOKE
    would publish every case row through PostgREST.

    Skipped on the vanilla Postgres the CI `migrations` job runs against, where
    neither role exists — the migration guards the same way.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT rolname FROM pg_roles "
                    "WHERE rolname IN ('anon','authenticated','service_role')")
        roles = {r[0] for r in cur.fetchall()}
        if not {"anon", "authenticated"} & roles:
            pytest.skip("Supabase roles absent (vanilla Postgres)")

        for role in ("anon", "authenticated"):
            cur.execute(
                "SELECT has_table_privilege(%s, 'public.nar1_case_registry', "
                "'SELECT')", (role,),
            )
            assert cur.fetchone()[0] is False, role

        if "service_role" in roles:
            cur.execute("SELECT has_table_privilege('service_role', "
                        "'public.nar1_case_registry', 'SELECT')")
            assert cur.fetchone()[0] is True


# --------------------------------------------------------------------------- #
#  The audit registry
# --------------------------------------------------------------------------- #

def test_the_close_event_is_seeded_with_an_explicit_category_and_origin(conn):
    """There is no FK from `audit_log` to this table, so an unseeded code does
    not fail loudly — it writes fine and renders unlabelled in the trail. And
    the `origin` default is 'viewpoint', which would file a G-FlowDesk action
    under inherited Viewpoint history."""
    with conn.cursor() as cur:
        cur.execute("SELECT name, category, origin FROM audit_event_types "
                    "WHERE code = 'NAR1_CASE_CLOSED'")
        row = cur.fetchone()

    assert row is not None, "NAR1_CASE_CLOSED is not seeded"
    assert row == ("NAR1 Case Closed", "nar1", "g_flowdesk")
