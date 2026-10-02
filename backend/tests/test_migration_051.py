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


def test_the_officer_changes_migration_follows_this_one_in_a_single_line():
    """On `nd2a_nd2b`: 050 was re-pointed to revise 051, so the chain runs
    049 -> 051 -> 050 with ONE head. Two heads would make `alembic upgrade
    head` refuse, and CI's migrations job with it."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(os.path.join(_HERE, "alembic.ini")))
    assert script.get_heads() == ["050"]
    assert script.get_revision("050").down_revision == "051"
    assert script.get_revision("051").down_revision == "049"


def test_the_backfill_runs_with_the_updated_at_trigger_off():
    """Left on, `trg_set_updated_at` would stamp every case ever mailed with the
    moment this migration ran, and the dashboard's Last Updated column would
    rank them by when the schema changed (044's trap, from the other side).

    `upgrade()` runs `_backfill_statements()` and nothing else for the
    backfill, so the DB test below exercises the very statements it runs."""
    m = _migration()
    disable, backfill, enable = m._backfill_statements()
    assert "DISABLE TRIGGER trg_set_updated_at" in disable
    assert backfill is m._BACKFILL
    assert "ENABLE TRIGGER trg_set_updated_at" in enable and "DISABLE" not in enable
    upgrade = _source().split("def upgrade")[1].split("def downgrade")[0]
    assert "for sql in _backfill_statements():" in upgrade
    assert "_BACKFILL" not in upgrade


def test_the_trail_counts_first_and_token_batches_only_without_one():
    """A token batch is written BEFORE its send, so a send that reached nobody
    leaves one behind; counting batches alongside the trail would start a case
    with two real emails at "Rev. 4". Batches stand in only where there is no
    trail at all."""
    sql = _normalise(_migration()._BACKFILL)
    assert "a.action_type = 'EMAIL_SENT'" in sql
    assert "a.entity_type = 'nar1_case'" in sql
    assert "CASE WHEN s.n > 0 THEN s.n ELSE b.n END" in sql
    assert "count(DISTINCT t.sent_at)" in sql
    assert "WHEN c2.verification_sent_at IS NOT NULL THEN 1" in sql


def test_the_trail_is_read_through_its_entity_index():
    """`audit_log` is ~720 MB and `action_type` has no index, while ADD COLUMN
    holds `nar1_cases` locked. Correlating on `entity_id` uses
    idx_audit_log_entity (migration 010) instead of scanning the table."""
    sql = _normalise(_migration()._BACKFILL)
    assert "LEFT JOIN LATERAL" in sql
    assert "a.entity_id = c2.id::text" in sql
    assert "GROUP BY entity_id" not in sql


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
def test_the_backfill_counts_token_batches_when_there_is_no_trail(conn):
    """Audit writes are best-effort; with no trail at all, a batch of tokens is
    the only record of a send."""
    with conn.cursor() as cur:
        case_id = _case(cur)
        _token(cur, case_id, "2026-09-01T00:00:00Z")
        _token(cur, case_id, "2026-09-01T00:00:00Z")   # same send, 2nd director
        _token(cur, case_id, "2026-09-05T00:00:00Z")
        assert _backfilled(cur, case_id) == 2


@db
def test_a_failed_sends_token_batch_does_not_outvote_the_trail(conn):
    """Two real emails on the trail, three token batches — the third from a
    send Resend refused for everybody, whose tokens were written before it
    failed. The client has seen two emails, so the next must be Rev. 3, not 4."""
    with conn.cursor() as cur:
        case_id = _case(cur, verification_sent_at="2026-09-05T00:00:00Z")
        _sent(cur, case_id)
        _sent(cur, case_id)
        for day in ("01", "05", "09"):
            _token(cur, case_id, f"2026-09-{day}T00:00:00Z")
        assert _backfilled(cur, case_id) == 2


#: A date the migration cannot produce — `now()` is the TRANSACTION timestamp,
#: so a test comparing it with itself proves nothing (CLAUDE.md, 044).
_LONG_AGO = "2020-01-15T00:00:00+00:00"


def _seed_mailed_case_dated_long_ago(cur) -> str:
    case_id = _case(cur, verification_sent_at="2026-09-01T00:00:00Z",
                    updated_at=_LONG_AGO)
    _sent(cur, case_id)
    cur.execute("SELECT updated_at FROM nar1_cases WHERE id = %s", (case_id,))
    assert cur.fetchone()[0].year == 2020   # the seed itself held
    cur.execute("UPDATE nar1_cases SET verification_revision = 0 WHERE id = %s "
                "RETURNING 1", (case_id,))
    # That UPDATE fired the trigger; put the old date back with it off, so the
    # backfill below is the only write under test.
    cur.execute("ALTER TABLE nar1_cases DISABLE TRIGGER trg_set_updated_at")
    cur.execute("UPDATE nar1_cases SET updated_at = %s WHERE id = %s",
                (_LONG_AGO, case_id))
    cur.execute("ALTER TABLE nar1_cases ENABLE TRIGGER trg_set_updated_at")
    return case_id


@db
def test_the_backfill_as_upgrade_runs_it_does_not_redate_the_case(conn):
    """The statements `upgrade()` runs, in its order: revision filled in, Last
    Updated untouched."""
    with conn.cursor() as cur:
        case_id = _seed_mailed_case_dated_long_ago(cur)
        for sql in _migration()._backfill_statements():
            cur.execute(sql)
        cur.execute("SELECT verification_revision, updated_at FROM nar1_cases "
                    "WHERE id = %s", (case_id,))
        revision, updated_at = cur.fetchone()
        assert revision == 1
        assert updated_at.year == 2020


@db
def test_without_the_trigger_off_the_same_backfill_WOULD_redate_it(conn):
    """The control that makes the test above mean something: the trigger is
    live and fires on this UPDATE, so its being off is what saved the date."""
    with conn.cursor() as cur:
        case_id = _seed_mailed_case_dated_long_ago(cur)
        cur.execute(_migration()._BACKFILL)
        cur.execute("SELECT updated_at FROM nar1_cases WHERE id = %s", (case_id,))
        assert cur.fetchone()[0].year != 2020


@db
def test_a_case_marked_sent_with_no_record_is_at_least_revision_one(conn):
    with conn.cursor() as cur:
        case_id = _case(cur, verification_sent_at="2026-08-01T00:00:00Z")
        assert _backfilled(cur, case_id) == 1


@db
def test_a_case_never_sent_stays_at_zero(conn):
    with conn.cursor() as cur:
        assert _backfilled(cur, _case(cur)) == 0
