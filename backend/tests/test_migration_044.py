"""Migration 044 — the CR heartbeat stops resetting Last Updated.

The behaviour under test is a DATABASE behaviour and cannot be checked from
Python alone: the thing that was wrong was a trigger silently overriding a
correct application patch, and only Postgres can say whether it still does.

NAMED `test_migration_044.py` ON PURPOSE. `.github/workflows/backend-ci.yml`
collects DB-backed assertions as `tests/test_migration_*.py`; a file outside
that glob would never run in the `migrations` job.
"""
import importlib.util
import os

import pytest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _migration():
    path = os.path.join(_HERE, "alembic", "versions",
                        "044_updated_at_ignores_the_cr_heartbeat.py")
    spec = importlib.util.spec_from_file_location("m044", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
#  No database needed
# --------------------------------------------------------------------------- #

def test_it_changes_the_trigger_and_never_the_shared_function():
    """`set_updated_at()` is shared by ~30 tables (003, 016, 020). Editing it to
    fix one table would change every one of them."""
    m = _migration()
    assert m._TABLE == "public.nar1_cases"
    assert "CREATE OR REPLACE FUNCTION" not in m._WHEN
    assert "cr_status_checked_at" in m._WHEN


def test_the_downgrade_restores_the_unconditional_trigger():
    """003's form is no WHEN clause at all — every update stamps."""
    m = _migration()
    assert m.down_revision == "043"
    calls = []
    m.op = type("op", (), {"execute": staticmethod(lambda sql: calls.append(sql))})
    m.downgrade()
    created = [c for c in calls if "CREATE TRIGGER" in c]
    assert len(created) == 1
    assert "WHEN" not in created[0]
    assert "EXECUTE FUNCTION set_updated_at()" in created[0]


# --------------------------------------------------------------------------- #
#  The real thing
# --------------------------------------------------------------------------- #

psycopg2 = pytest.importorskip("psycopg2")

db = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)


def _conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


#: A baseline that cannot be confused with "the trigger fired".
#:
#: `set_updated_at()` uses `now()`, which in Postgres is the TRANSACTION
#: timestamp and is therefore CONSTANT for every statement in this test. So
#: comparing a post-update `updated_at` against the one the INSERT produced
#: proves nothing at all: a trigger that fired and a trigger that was skipped
#: both leave exactly the same value, and the first draft of these tests passed
#: for that reason rather than for the right one. Seeding a date from years ago
#: is what makes "was it stamped?" answerable.
_SEED = "2020-01-01 00:00:00+00"


def _fixture_case(cur):
    """A case whose `updated_at` is old, and the trigger left alone.

    The seeding UPDATE has to carry `cr_status_checked_at` precisely BECAUSE
    044 suppresses the trigger for those — it is the only way to write
    `updated_at` by hand at all, which is itself a demonstration of what the
    migration does.
    """
    cur.execute("INSERT INTO public.entities (id, company_name) "
                "VALUES (gen_random_uuid(), 'UPDATED_AT FIXTURE') RETURNING id")
    entity_id = cur.fetchone()[0]
    cur.execute("INSERT INTO public.nar1_cases (entity_id, nar1_type) "
                "VALUES (%s, 'annual_return') RETURNING id", (entity_id,))
    case_id = cur.fetchone()[0]
    # `cr_status_checked_at` is seeded to the SAME old instant, and that matters
    # for the same transaction-timestamp reason: a later `SET
    # cr_status_checked_at = now()` inside this transaction must be DISTINCT
    # from what is already stored, or the WHEN clause reads the heartbeat as
    # "unchanged", fires, and the test measures the opposite of what it claims.
    # In production each run writes a fresh `datetime.now()` minutes apart, so
    # they always differ; seeding now() here would have made them identical.
    cur.execute("UPDATE public.nar1_cases "
                "   SET updated_at = %s, cr_status_checked_at = %s "
                " WHERE id = %s RETURNING updated_at", (_SEED, _SEED, case_id))
    seeded = cur.fetchone()[0]
    assert seeded.year == 2020, "the seed itself was stamped — 044 is not applied"
    return case_id, seeded


@db
def test_a_heartbeat_alone_does_not_touch_updated_at():
    """The whole point. Ninety-six polls a day must not reset the column an
    operator sorts by to find the case that actually moved."""
    with _conn() as conn, conn.cursor() as cur:
        case_id, before = _fixture_case(cur)
        cur.execute("UPDATE public.nar1_cases SET cr_status_checked_at = now() "
                    "WHERE id = %s RETURNING updated_at", (case_id,))
        after = cur.fetchone()[0]
        assert after == before and after.year == 2020
        conn.rollback()


@db
def test_a_real_cr_answer_still_moves_updated_at_when_the_patch_says_so():
    """`refresh()` sets `updated_at` itself when CR's answer changed. With the
    trigger suppressed, that explicit value has to be the one that lands."""
    with _conn() as conn, conn.cursor() as cur:
        case_id, before = _fixture_case(cur)
        cur.execute(
            "UPDATE public.nar1_cases "
            "   SET cr_status_checked_at = now(), cr_doc_status = 'Registered',"
            "       cr_doc_status_code = 'cr_registered',"
            "       updated_at = now() "
            " WHERE id = %s RETURNING updated_at", (case_id,))
        after = cur.fetchone()[0]
        assert after > before and after.year != 2020
        conn.rollback()


@db
def test_every_other_edit_still_gets_stamped_automatically():
    """Nothing else about the table changes. An ordinary edit that never
    mentions `updated_at` must still be stamped, as it has been since 003."""
    with _conn() as conn, conn.cursor() as cur:
        case_id, before = _fixture_case(cur)
        # A plain text column, deliberately: `status` is the `case_status` ENUM
        # and pinning one of its labels here would make this test fail the day
        # somebody renames a workflow state, for a reason that has nothing to
        # do with what it checks.
        cur.execute("UPDATE public.nar1_cases SET director_full_name = 'EDITED' "
                    "WHERE id = %s RETURNING updated_at", (case_id,))
        after = cur.fetchone()[0]
        assert after > before and after.year != 2020
        conn.rollback()


@db
def test_the_trigger_carries_the_when_clause_on_this_table_only():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT pg_get_triggerdef(t.oid)
              FROM pg_trigger t
             WHERE t.tgrelid = 'public.nar1_cases'::regclass
               AND NOT t.tgisinternal AND t.tgname = 'trg_set_updated_at'
        """)
        definition = cur.fetchone()[0]
        assert "cr_status_checked_at" in definition

        # A neighbouring table that shares the function keeps the plain form.
        cur.execute("""
            SELECT pg_get_triggerdef(t.oid)
              FROM pg_trigger t
             WHERE t.tgrelid = 'public.tpsi_filings'::regclass
               AND NOT t.tgisinternal AND t.tgname = 'trg_set_updated_at'
        """)
        row = cur.fetchone()
        if row:                       # only if that table carries one
            assert "WHEN" not in row[0]
