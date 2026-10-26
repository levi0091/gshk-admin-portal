"""Migration 056 — a NAR1 submit with no answer from CR is an unknown outcome.

TWO HALVES, as 047 and 051. The pure half pins that the migration and the code
agree — on the stage list, the lock, the stale-claim cut-off and the audit
codes — so neither can move without the other. The DB half (RUN_DB_TESTS, like
every `test_migration_*.py`) proves what only Postgres can: the CHECK, the
case-level index refusing a direct write, the seeded codes, the data repair,
and the view's reading of the two new stages. Every DB write is rolled back.

NAMED `test_migration_056.py` ON PURPOSE: `.github/workflows/backend-ci.yml`
collects the DB-backed assertions by that glob.
"""
import importlib.util
import os
import re
import uuid

import pytest

from services import audit_events, nar1_case_status
from services.tpsi import filings

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M056 = "056_nar1_submit_outcome_unknown.py"


def _migration():
    path = os.path.join(_HERE, "alembic", "versions", M056)
    spec = importlib.util.spec_from_file_location("m056", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source() -> str:
    with open(os.path.join(_HERE, "alembic", "versions", M056),
              encoding="utf-8") as fh:
        return fh.read()


def _normalise(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


# --------------------------------------------------------------------------- #
#  No database needed
# --------------------------------------------------------------------------- #

def test_it_revises_master_head_and_reuses_no_number_dev_holds():
    """`dev` uses 050 and 052-055 for unreleased ND2A/ND2B work; this hotfix
    goes onto master, whose head is 051."""
    m = _migration()
    assert m.revision == "056"
    assert m.down_revision == "051"


def test_the_check_constraint_allows_exactly_the_stages_the_code_writes():
    m = _migration()
    # 056's own CHECK still holds `registered` (018's list): 054 removes it, and
    # restates the list WITH 056's two stages -- tests/test_migration_054.py.
    assert set(m.STAGES) == (
        set(filings.FORM_STATUSES) | {filings.STAGE_EDRIVE, filings.LEGACY_REGISTERED})
    assert set(m.NEW_STAGES) == {filings.STAGE_SUBMITTING,
                                 filings.STAGE_SUBMISSION_UNKNOWN}


def test_the_index_is_the_one_the_code_translates_and_covers_locked_stages():
    from tests.tpsi import fake_store

    m = _migration()
    assert m.CASE_LOCK_INDEX == filings.CASE_LOCK_INDEX == fake_store.CASE_LOCK_INDEX
    assert set(m.CASE_LOCK_STAGES) <= set(filings.LOCKED_STAGES)
    # edrive is locked by the application but deliberately not by the index.
    assert set(filings.LOCKED_STAGES) - set(m.CASE_LOCK_STAGES) == {"edrive"}
    assert tuple(fake_store.CASE_LOCK_STAGES) == tuple(m.CASE_LOCK_STAGES)


def test_the_stale_claim_cut_off_is_the_codes():
    assert _migration().STALE_CLAIM_SECONDS == filings.STALE_CLAIM_SECONDS


@pytest.mark.parametrize("stage", _migration().STAGES)
def test_the_views_branches_agree_with_the_python_for_every_stage(stage):
    """The full parity truth table is test_migration_024's (DB-backed). This is
    the part of it that needs no database: an approved, sent case, at every
    stage, lands in the same branch of the view's CASE as of `_code`."""
    m = _migration()
    case = {"verification_sent_at": "2026-10-01T00:00:00Z",
            "client_approved": True}
    code = nar1_case_status.derive(case, {"stage": stage})["code"]
    if stage in ("submitted", "registered", "edrive"):
        assert code == nar1_case_status.FILED
    elif stage not in m.LIVE_STAGES:
        assert code == "data_verification"
    elif stage in m.SUBMISSION_STAGES:
        assert code == "submission"
    else:
        assert code == "signing"


def test_the_view_teaches_047s_registry_the_two_stages_and_nothing_else():
    m = _migration()
    sql = _normalise(m.case_view_sql())
    old = _normalise(m._m047()._case_view_sql(with_year=True))
    # Both are LIVE: past Data Verification, as `_code` has it.
    assert ("base.filing_stage NOT IN ('validated', 'signed', 'signing_failed', "
            "'submission_failed', 'submitting', 'submission_unknown') "
            "THEN 'data_verification'") in sql
    assert ("WHEN base.filing_stage IN ('signed', 'submission_failed', "
            "'submitting', 'submission_unknown') THEN 'submission'") in sql
    assert f"interval '{filings.STALE_CLAIM_SECONDS} seconds'" in sql
    assert "THEN 'submission_unknown' ELSE tf.stage END AS stage" in sql
    # Same columns, in the same order, as 047: a view is DROP + CREATE here, and
    # the dashboard and the parity test read these names.
    columns = lambda s: re.findall(r"AS (\w+)", s)  # noqa: E731
    # (`stage` is the lateral's own alias for the stale-claim CASE; 047 read
    # `tf.stage` bare there.)
    assert [c for c in columns(sql) if c != "stage"] == columns(old)
    assert "security_invoker = true" in sql


def test_the_view_is_recreated_with_047s_grants():
    upgrade = _source().split("def upgrade")[1].split("def downgrade")[0]
    assert "m._CASE_GRANTS" in upgrade
    downgrade = _source().split("def downgrade")[1]
    assert "m._case_view_sql(with_year=True)" in downgrade
    assert "m._CASE_GRANTS" in downgrade


def test_the_new_audit_codes_are_seeded_as_g_flowdesk_with_a_category():
    m = _migration()
    seeded = {code for code, _name, _category in m.AUDIT_CODES}
    assert seeded == {audit_events.TPSI_SUBMISSION_UNKNOWN,
                      audit_events.TPSI_SUBMISSION_RESOLVED}
    assert all(category for _c, _n, category in m.AUDIT_CODES)
    upgrade = _source().split("def upgrade")[1].split("def downgrade")[0]
    assert "'g_flowdesk')" in upgrade
    assert "audit_event_types (code, name, category, origin)" in upgrade


def test_the_repair_matches_the_message_the_client_writes_for_a_lost_call():
    """If `TpsiClient` ever words a transport failure differently, the repair
    would silently match nothing."""
    import inspect

    from services.tpsi import client

    prefix = _migration().TRANSPORT_FAILURE_PREFIX
    assert f'f"{prefix}: {{exc}}"' in inspect.getsource(client)


def test_the_repair_runs_before_the_index_is_built():
    upgrade = _source().split("def upgrade")[1].split("def downgrade")[0]
    assert upgrade.index("_REPAIR") < upgrade.index("CREATE UNIQUE INDEX")


def test_the_downgrade_refuses_while_a_row_is_in_a_new_stage():
    m = _migration()
    refuse = _normalise(m._REFUSE_DOWNGRADE)
    assert "RAISE EXCEPTION" in refuse
    assert "'submitting', 'submission_unknown'" in refuse
    downgrade = _source().split("def downgrade")[1]
    assert downgrade.index("_REFUSE_DOWNGRADE") < downgrade.index("DROP")


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


def _case(cur) -> tuple[str, str]:
    entity_id, case_id = str(uuid.uuid4()), str(uuid.uuid4())
    cur.execute(
        "INSERT INTO entities (id, company_name, br_number) VALUES (%s, %s, %s)",
        (entity_id, "UNKNOWN OUTCOME FIXTURE LIMITED", f"UO-{entity_id[:8]}"))
    cur.execute(
        "INSERT INTO nar1_cases (id, entity_id, nar1_type, case_no, "
        "verification_sent_at, client_approved) "
        "VALUES (%s, %s, 'annual_return', %s, now(), true)",
        (case_id, entity_id, f"UO-{case_id[:8]}"))
    return entity_id, case_id


def _filing(cur, entity_id, case_id, stage, **cols) -> str:
    names = ["entity_id", "nar1_case_id", "form_code", "stage", *cols]
    values = [entity_id, case_id, "Nar1", stage, *cols.values()]
    cur.execute(
        f"INSERT INTO tpsi_filings ({', '.join(names)}) "
        f"VALUES ({', '.join(['%s'] * len(values))}) RETURNING id", values)
    return cur.fetchone()[0]


@db
@pytest.mark.parametrize("stage", ["submitting", "submission_unknown"])
def test_the_check_accepts_the_new_stages(conn, stage):
    with conn.cursor() as cur:
        entity_id, case_id = _case(cur)
        _filing(cur, entity_id, case_id, stage)


@db
def test_the_check_still_refuses_a_stage_nobody_writes(conn):
    import psycopg2

    with conn.cursor() as cur:
        entity_id, case_id = _case(cur)
        with pytest.raises(psycopg2.errors.CheckViolation):
            _filing(cur, entity_id, case_id, "failed")


@db
@pytest.mark.parametrize("first,second", [
    ("submitting", "submitted"),
    ("submission_unknown", "submitting"),
    ("submitted", "submission_unknown"),
    ("registered", "submitted"),
])
def test_the_index_refuses_a_second_filing_cr_may_hold_on_one_case(conn, first,
                                                                    second):
    """AC5's database half: a direct write, past every application check."""
    import psycopg2

    with conn.cursor() as cur:
        entity_id, case_id = _case(cur)
        _filing(cur, entity_id, case_id, first)
        with pytest.raises(psycopg2.errors.UniqueViolation) as exc:
            _filing(cur, entity_id, case_id, second)
    assert filings.CASE_LOCK_INDEX in str(exc.value)


@db
def test_the_index_leaves_ordinary_attempts_alone(conn):
    with conn.cursor() as cur:
        entity_id, case_id = _case(cur)
        _filing(cur, entity_id, case_id, "submitted")
        for stage in ("superseded", "draft", "submission_failed", "edrive"):
            _filing(cur, entity_id, case_id, stage)


@db
def test_the_new_codes_are_seeded_as_g_flowdesk(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT code, origin, category FROM audit_event_types "
            "WHERE code IN ('TPSI_SUBMISSION_UNKNOWN', 'TPSI_SUBMISSION_RESOLVED') "
            "ORDER BY code")
        rows = cur.fetchall()
    assert [r[0] for r in rows] == ["TPSI_SUBMISSION_RESOLVED",
                                    "TPSI_SUBMISSION_UNKNOWN"]
    assert {r[1] for r in rows} == {"g_flowdesk"}
    assert all(r[2] for r in rows)


@db
def test_the_repair_moves_a_timeout_and_leaves_a_crs_refusal_alone(conn):
    import json

    with conn.cursor() as cur:
        entity_id, timeout_case = _case(cur)
        timed_out = _filing(cur, entity_id, timeout_case, "submission_failed",
                            cr_error=json.dumps({
                                "faults": [],
                                "message": "cannot reach TPSI: The read "
                                           "operation timed out"}))
        _, refusal_case = _case(cur)
        refused = _filing(cur, entity_id, refusal_case, "submission_failed",
                          cr_error=json.dumps({
                              "faults": [["ERR_X", "Deposit suspended"]],
                              "message": "ERR_X: Deposit suspended"}))
        _, held_case = _case(cur)
        _filing(cur, entity_id, held_case, "submitted")
        beside_a_filed_one = _filing(
            cur, entity_id, held_case, "submission_failed",
            cr_error=json.dumps({"faults": [],
                                 "message": "cannot reach TPSI: timed out"}))

        cur.execute(_migration()._REPAIR)
        cur.execute("SELECT id::text, stage FROM tpsi_filings WHERE id IN "
                    "(%s, %s, %s)", (timed_out, refused, beside_a_filed_one))
        stages = dict(cur.fetchall())

    assert stages[str(timed_out)] == "submission_unknown"
    assert stages[str(refused)] == "submission_failed"
    # Left alone so the index can be built; the application's case lock still
    # refuses it, because its sibling holds the lock.
    assert stages[str(beside_a_filed_one)] == "submission_failed"


@db
def test_the_view_puts_both_new_stages_at_submission(conn):
    with conn.cursor() as cur:
        entity_id, live_case = _case(cur)
        _filing(cur, entity_id, live_case, "submitting",
                submit_started_at="now")
        _, unknown_case = _case(cur)
        _filing(cur, entity_id, unknown_case, "submission_unknown")
        _, stale_case = _case(cur)
        _filing(cur, entity_id, stale_case, "submitting",
                submit_started_at="2020-01-01T00:00:00Z")
        cur.execute(
            "SELECT id::text, workflow_status, filing_stage "
            "FROM nar1_case_registry WHERE id IN (%s, %s, %s)",
            (live_case, unknown_case, stale_case))
        rows = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    assert rows[live_case] == ("submission", "submitting")
    assert rows[unknown_case] == ("submission", "submission_unknown")
    assert rows[stale_case] == ("submission", "submission_unknown")
