"""Migration 051 — every verification email carries its revision number.

TWO HALVES, as 047. The pure half pins what the SQL must and must not do; the
DB half (RUN_DB_TESTS, like every `test_migration_*.py`) proves what only
Postgres can: the constraints, the backfill's arithmetic, and that the backfill
does not re-date the cases it touches.

NAMED `test_migration_051.py` ON PURPOSE: `.github/workflows/backend-ci.yml`
collects the DB-backed assertions by that glob.
"""
import importlib.util
import os
import re
import uuid

import pytest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M051 = "051_verification_revision.py"


def _migration():
    path = os.path.join(_HERE, "alembic", "versions", M051)
    spec = importlib.util.spec_from_file_location("m051", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source() -> str:
    with open(os.path.join(_HERE, "alembic", "versions", M051),
              encoding="utf-8") as fh:
        return fh.read()


def _normalise(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


# --------------------------------------------------------------------------- #
#  No database needed
# --------------------------------------------------------------------------- #

def test_it_revises_049_leaving_050_to_the_officer_changes_branch():
    """050 is the ND2A/ND2B migration on `nd2a_nd2b`, applied nowhere yet; it
    is re-pointed to revise 051 there. If this ever revised 050 instead, `dev`
    would name a parent it does not contain and `alembic upgrade` would fail."""
    m = _migration()
    assert m.revision == "051"
    assert m.down_revision == "049"


def test_the_backfill_runs_with_the_updated_at_trigger_off():
    """Left on, `trg_set_updated_at` would stamp every case ever mailed with the
    moment this migration ran, and the dashboard's Last Updated column would
    rank them by when the schema changed (044's trap, from the other side)."""
    m = _migration()
    calls = re.findall(r"op\.execute\(([^\n]+)", _source().split("def upgrade")[1]
                       .split("def downgrade")[0])
    order = [c.strip() for c in calls]
    disable = next(i for i, c in enumerate(order) if "DISABLE TRIGGER" in c)
    backfill = order.index("_BACKFILL)")
    # "ENABLE TRIGGER" is a substring of "DISABLE TRIGGER", hence the second test.
    enable = next(i for i, c in enumerate(order)
                  if "ENABLE TRIGGER" in c and "DISABLE" not in c)
    assert disable < backfill < enable
    assert m._TRIGGER == "trg_set_updated_at"


def test_the_backfill_takes_the_most_the_record_supports():
    sql = _normalise(_migration()._BACKFILL)
    # The trail, the token batches, and "sent at least once".
    assert "action_type = 'EMAIL_SENT'" in sql
    assert "entity_type = 'nar1_case'" in sql
    assert "count(DISTINCT sent_at)" in sql
    assert "WHEN c2.verification_sent_at IS NOT NULL THEN 1" in sql
    assert "GREATEST(" in sql


def test_legacy_links_are_not_given_a_guessed_revision():
    """A guess one too low would refuse a director's current link. NULL means
    the lock does not apply — see nar1_approvals.is_stale."""
    upgrade = _source().split("def upgrade")[1].split("def downgrade")[0]
    assert "UPDATE public.nar1_client_approvals" not in upgrade
    assert "dense_rank" not in upgrade.lower()


def test_the_case_view_is_not_touched():
    """`nar1_case_registry` lists its columns, so nothing here needs it — and
    restating it would collide with 050's byte-for-byte restatement of 047's."""
    body = _source().split('"""', 2)[2]
    assert "nar1_case_registry" not in body
    assert "VIEW" not in body


def test_the_downgrade_drops_exactly_what_the_upgrade_added():
    down = _source().split("def downgrade")[1]
    assert "DROP COLUMN IF EXISTS revision" in down
    assert "DROP COLUMN IF EXISTS verification_revision" in down


def test_the_code_reads_the_columns_this_creates():
    from jobs import auto_approve_nar1
    import inspect

    assert "revision" in inspect.getsource(auto_approve_nar1.due_tokens)


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


def _case(cur, **cols) -> str:
    entity_id, case_id = str(uuid.uuid4()), str(uuid.uuid4())
    cur.execute(
        "INSERT INTO entities (id, company_name, br_number) VALUES (%s, %s, %s)",
        (entity_id, "REVISION FIXTURE LIMITED", f"RV-{entity_id[:8]}"))
    names = ["id", "entity_id", "nar1_type", "case_no", *cols]
    values = [case_id, entity_id, "annual_return", f"RV-{case_id[:8]}",
              *cols.values()]
    cur.execute(
        f"INSERT INTO nar1_cases ({', '.join(names)}) "
        f"VALUES ({', '.join(['%s'] * len(values))})", values)
    return case_id


def _token(cur, case_id, sent_at, revision=None):
    cur.execute(
        "INSERT INTO nar1_client_approvals (nar1_case_id, recipient_email, "
        "token_hash, sent_at, expires_at, revision) "
        "VALUES (%s, 'a@example.com', %s, %s, %s::timestamptz + interval '7 days', %s)",
        (case_id, uuid.uuid4().hex, sent_at, sent_at, revision))


def _sent(cur, case_id):
    cur.execute(
        "INSERT INTO audit_log (user_display_name, action_type, entity_type, "
        "entity_id) VALUES ('Levi', 'EMAIL_SENT', 'nar1_case', %s)", (case_id,))


def _backfilled(cur, case_id) -> int:
    cur.execute("UPDATE nar1_cases SET verification_revision = 0 WHERE id = %s",
                (case_id,))
    cur.execute(_migration()._BACKFILL)
    cur.execute("SELECT verification_revision FROM nar1_cases WHERE id = %s",
                (case_id,))
    return cur.fetchone()[0]


@db
def test_a_new_case_has_sent_nothing(conn):
    with conn.cursor() as cur:
        case_id = _case(cur)
        cur.execute("SELECT verification_revision FROM nar1_cases WHERE id = %s",
                    (case_id,))
        assert cur.fetchone()[0] == 0


@db
def test_a_revision_cannot_go_negative_and_a_link_cannot_be_rev_zero(conn):
    import psycopg2

    with conn.cursor() as cur:
        case_id = _case(cur)
        cur.execute("SAVEPOINT s")
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("UPDATE nar1_cases SET verification_revision = -1 "
                        "WHERE id = %s", (case_id,))
        cur.execute("ROLLBACK TO SAVEPOINT s")
        with pytest.raises(psycopg2.errors.CheckViolation):
            _token(cur, case_id, "2026-09-01T00:00:00Z", revision=0)


@db
def test_the_backfill_counts_every_send_on_the_trail(conn):
    with conn.cursor() as cur:
        case_id = _case(cur, verification_sent_at="2026-09-01T00:00:00Z")
        for _ in range(3):
            _sent(cur, case_id)
        assert _backfilled(cur, case_id) == 3


@db
def test_the_backfill_counts_token_batches_when_the_trail_is_short(conn):
    """Audit writes are best-effort; a batch of tokens is a send all the same."""
    with conn.cursor() as cur:
        case_id = _case(cur)
        _token(cur, case_id, "2026-09-01T00:00:00Z")
        _token(cur, case_id, "2026-09-01T00:00:00Z")   # same send, 2nd director
        _token(cur, case_id, "2026-09-05T00:00:00Z")
        assert _backfilled(cur, case_id) == 2


@db
def test_a_case_marked_sent_with_no_record_is_at_least_revision_one(conn):
    with conn.cursor() as cur:
        case_id = _case(cur, verification_sent_at="2026-08-01T00:00:00Z")
        assert _backfilled(cur, case_id) == 1


@db
def test_a_case_never_sent_stays_at_zero(conn):
    with conn.cursor() as cur:
        assert _backfilled(cur, _case(cur)) == 0
