"""Migration 050 — ND2A and ND2B cases share `nar1_cases` and its badge.

TWO HALVES, like 047's. The pure half pins the SQL text: 050 restates 047's
view, and a restatement is exactly where an unrelated line drifts — nothing
about a drifted view fails loudly, it just disagrees with the Python that
badges the same case. The DB half (RUN_DB_TESTS) proves what only Postgres
can: that the view and `nar1_case_status.derive()` agree for an officer-change
case on every reachable state, that an annual return is untouched by any of
it, and that the table holding other people's e-Registry passwords cannot be
read through PostgREST.

NAMED `test_migration_050.py` ON PURPOSE: `.github/workflows/backend-ci.yml`
collects the DB-backed assertions by that glob.
"""
import importlib.util
import itertools
import os
import re
import uuid

import pytest

from services import audit_events as ev
from services import document_sections
from services import nar1_case_status as st
from services import nar1_cases
from services.tpsi import filings as tpsi_filings

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

M047 = "047_nar1_case_return_year.py"
M050 = "050_officer_changes_nd2a_nd2b.py"

VIEW = "nar1_case_registry"


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

def test_without_the_officer_change_columns_the_view_is_047s_exactly():
    """The downgrade target, and the proof the restatement changed nothing it
    did not mean to: comments and whitespace out, byte for byte."""
    assert _normalise(_migration(M050)._case_view_sql(officer_changes=False)) == \
        _normalise(_migration(M047)._case_view_sql(with_year=True))


def test_the_new_branch_is_gated_on_the_form_so_a_nar1_cannot_take_it():
    """The manual branch reads `data_checked_at`, which an annual return never
    sets. Ungated, every approved NAR1 on the manual path would be re-badged
    Data Verification."""
    sql = _normalise(_migration(M050)._case_view_sql(officer_changes=True))
    assert ("WHEN base.form_code <> 'Nar1' AND base.signing_method = 'manual' "
            "THEN CASE") in sql


def test_the_manual_branch_sits_after_the_client_and_before_the_filing_stage():
    """Same place in the order as `nar1_case_status._code`. Above the client
    branches it would let an unapproved form reach Signing; below the stage
    branches it would never be reached at all."""
    sql = _normalise(_migration(M050)._case_view_sql(officer_changes=True))
    awaiting = sql.index("THEN 'awaiting_client'")
    manual = sql.index("base.form_code <> 'Nar1'")
    stage = sql.index("WHEN base.filing_stage IS NULL")
    assert awaiting < manual < stage


def test_the_anniversary_is_null_on_an_officer_change():
    """It belongs to the annual return. Left in, an ND2A would sort by — and be
    flagged overdue on — a date that has nothing to do with it."""
    sql = _normalise(_migration(M050)._case_view_sql(officer_changes=True))
    assert ("CASE WHEN c.form_code = 'Nar1' THEN e.days_to_anniversary END "
            "AS days_to_anniversary") in sql


def test_case_type_comes_from_the_form_code():
    sql = _normalise(_migration(M050)._case_view_sql(officer_changes=True))
    assert "WHEN 'Nd2a' THEN 'ND2A'" in sql
    assert "WHEN 'Nd2b' THEN 'ND2B'" in sql
    assert "ELSE 'NAR1' END AS case_type" in sql
    assert "'NAR1'::text AS case_type" not in sql


def test_the_recreate_restates_the_grants():
    m50 = _migration(M050)
    assert "REVOKE ALL ON public.nar1_case_registry FROM anon" in m50._CASE_GRANTS
    assert ("REVOKE ALL ON public.nar1_case_registry FROM authenticated"
            in m50._CASE_GRANTS)
    assert ("GRANT SELECT ON public.nar1_case_registry TO service_role"
            in m50._CASE_GRANTS)


def test_the_stage_lists_match_the_services():
    m50 = _migration(M050)
    assert set(m50.CR_FILED_STAGES) == set(nar1_cases.CR_FILED_STAGES)
    assert m50.FILING_WINDOW_DAYS == st.FILING_WINDOW_DAYS
    assert tuple(m50.CR_STATUS_CODES) == tuple(st.CR_STATUS_CODES)
    assert m50.CR_NOT_CHECKED == st.CR_NOT_CHECKED
    assert set(m50.FORM_CODES) == {"Nar1"} | set(st.OFFICER_CHANGE_FORMS)


def test_every_audit_code_the_services_name_is_seeded_and_no_others():
    """There is no FK from audit_log to audit_event_types, so a code that is
    written but not seeded renders with a blank Action (migrations 022, 034).
    And a seeded code nothing writes is a filter option that finds nothing."""
    seeded = {code for code, _name in _migration(M050).AUDIT_CODES}
    assert seeded == set(ev.OFFICER_CHANGE_CODES)


def test_every_supporting_document_type_lands_in_a_section_that_exists():
    """A category matching no section falls to "Other Documents"; these are the
    evidence behind a statutory filing and have a section of their own."""
    for _code, _label, category, applies_to, _order in _migration(M050).DOCUMENT_TYPES:
        owners = (["person", "company"] if applies_to == "both" else [applies_to])
        for owner in owners:
            keys = {s["key"] for s in document_sections.sections_for(owner)}
            assert category in keys, (category, owner)


def test_the_credential_table_is_locked_down_like_the_rest():
    m50 = _migration(M050)
    assert "person_eservice_credentials" in m50._NEW_TABLES
    sql = _normalise(m50._lock_down("person_eservice_credentials"))
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "REVOKE ALL ON public.person_eservice_credentials FROM anon" in sql
    assert ("REVOKE ALL ON public.person_eservice_credentials "
            "FROM authenticated") in sql
    # No policy anywhere in the migration for it: RLS-on-with-no-policy is the
    # default-deny, and a policy would be the thing that opened it.
    source = open(os.path.join(_HERE, "alembic", "versions", M050),
                  encoding="utf-8").read()
    assert "CREATE POLICY" not in source


# --------------------------------------------------------------------------- #
#  Needs Postgres
# --------------------------------------------------------------------------- #

psycopg2 = pytest.importorskip("psycopg2")
from psycopg2.extras import execute_values  # noqa: E402

needs_db = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)

STAGES = [None, tpsi_filings.STAGE_DRAFT, tpsi_filings.STAGE_VALIDATED,
          tpsi_filings.STAGE_SIGNED, tpsi_filings.STAGE_SUBMITTED]
SENT = [None, "2026-08-16T00:00:00Z"]
APPROVED = [None, True, False]
MANUAL_RECEIPT = [None, '{"caseNo": "1"}']
CLOSED = [None, "2026-09-05T02:00:00Z"]
METHOD = [None, "esign", "manual"]
CHECKED = [None, "2026-09-20T02:00:00Z"]
#: Whether the wet-signed form has been uploaded. A real `documents` row, since
#: the column is a foreign key.
SIGNED_FORM = [False, True]
#: Days from today (Hong Kong) to the filing deadline. -1 is the first overdue
#: day and 0 the last day in time — the off-by-one the predicate turns on.
DEADLINE = [None, -1, 0, 9]

COMBINATIONS = list(itertools.product(
    STAGES, SENT, APPROVED, MANUAL_RECEIPT, CLOSED, METHOD, CHECKED,
    SIGNED_FORM, DEADLINE))


def _conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


@pytest.fixture(scope="module")
def officer_change_rows():
    """One ND2A case per combination, read through the view once, rolled back."""
    entity_id = str(uuid.uuid4())
    document_id = str(uuid.uuid4())
    ids = {}
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO entities (id, company_name, br_number, incorporation_date) "
                "VALUES (%s, %s, %s, DATE '2020-03-01')",
                (entity_id, "OFFICER CHANGE FIXTURE LIMITED", "OC-BR-0050"),
            )
            cur.execute(
                "INSERT INTO documents (id, entity_id, document_type_code, "
                "file_name, storage_bucket, storage_path, status) "
                "VALUES (%s, %s, 'nd2a', 'signed.pdf', 'b', 'p', 'active')",
                (document_id, entity_id),
            )
            cur.execute("SELECT public.hk_today()")
            today = cur.fetchone()[0]

            cases, filings = [], []
            for index, combination in enumerate(COMBINATIONS):
                (stage, sent, approved, receipt, closed, method, checked,
                 signed_form, deadline) = combination
                case_id = str(uuid.uuid4())
                cases.append((
                    case_id, entity_id, f"OC-{index:05d}", sent, approved,
                    receipt, closed, method, checked,
                    document_id if signed_form else None,
                    deadline,
                ))
                if stage:
                    filings.append((entity_id, case_id, "Nd2a", stage))
                ids[combination] = case_id

            execute_values(
                cur,
                "INSERT INTO nar1_cases (id, entity_id, nar1_type, form_code, "
                "case_no, verification_sent_at, client_approved, manual_receipt, "
                "closed_at, signing_method, data_checked_at, "
                "manual_signed_document_id, filing_deadline) VALUES %s",
                cases,
                template="(%s, %s, 'appointment_and_resignation', 'Nd2a', %s, "
                         "%s, %s, %s::jsonb, %s, %s, %s, %s, "
                         f"DATE '{today.isoformat()}' + %s::integer)",
            )
            execute_values(
                cur,
                "INSERT INTO tpsi_filings (entity_id, nar1_case_id, form_code, "
                "stage) VALUES %s",
                filings,
            )
            cur.execute(
                f"SELECT r.id, r.workflow_status, r.workflow_off_portal, "
                f"       r.workflow_overdue, r.days_to_anniversary, "
                f"       r.days_to_deadline, r.filing_deadline, r.filing_stage, "
                f"       r.case_type, r.form_code, r.cr_doc_status, "
                f"       c.verification_sent_at, c.client_approved, "
                f"       c.manual_receipt, c.closed_at, c.signing_method, "
                f"       c.data_checked_at, c.manual_signed_document_id, "
                f"       c.cr_doc_status_code "
                f"FROM {VIEW} r JOIN nar1_cases c ON c.id = r.id "
                f"WHERE r.entity_id = %s",
                (entity_id,),
            )
            columns = [d.name for d in cur.description]
            view = {r[0]: dict(zip(columns, r)) for r in cur.fetchall()}
        yield {key: view[case_id] for key, case_id in ids.items()}
    finally:
        conn.rollback()
        conn.close()


def _expected(row: dict) -> dict:
    """What `derive()` says, from the DB's own stored values."""
    case = {key: row[key] for key in (
        "form_code", "verification_sent_at", "client_approved",
        "manual_receipt", "closed_at", "signing_method", "data_checked_at",
        "manual_signed_document_id", "cr_doc_status_code", "cr_doc_status",
        "days_to_anniversary", "days_to_deadline")}
    filing = {"stage": row["filing_stage"]} if row["filing_stage"] else None
    return st.derive(case, filing)


@needs_db
def test_the_view_and_derive_agree_on_every_officer_change_state(officer_change_rows):
    """The same parity `test_migration_024` holds the annual return to, over
    the two things that differ: the manual route and the 15-day deadline."""
    disagreements = [
        (combination, st.badge_from_row(row), _expected(row))
        for combination, row in officer_change_rows.items()
        if st.badge_from_row(row) != _expected(row)
    ]
    assert not disagreements, (
        f"{len(disagreements)} of {len(officer_change_rows)} states disagree "
        "(stage, sent, approved, receipt, closed, method, checked, signed form, "
        "deadline) -> view != derive():\n"
        + "\n".join(f"  {c}: {got} != {want}" for c, got, want in disagreements[:20])
    )


@needs_db
def test_the_manual_route_reaches_every_stage_it_should(officer_change_rows):
    """A branch that is never taken is a branch nobody has tested."""
    manual = {row["workflow_status"] for combination, row in
              officer_change_rows.items() if combination[5] == "manual"}
    assert {"data_verification", "signing", "submission"} <= manual


@needs_db
def test_an_officer_change_is_overdue_the_day_after_its_deadline(officer_change_rows):
    open_rows = [(combination, row) for combination, row in
                 officer_change_rows.items()
                 if row["workflow_status"] in st.GSHK_STATUSES]
    assert open_rows
    for combination, row in open_rows:
        deadline = combination[8]
        assert row["workflow_overdue"] is (deadline is not None and deadline < 0), \
            (combination, row["days_to_deadline"])


@needs_db
def test_days_to_deadline_is_the_signed_distance_from_today(officer_change_rows):
    for combination, row in officer_change_rows.items():
        assert row["days_to_deadline"] == combination[8]


@needs_db
def test_the_anniversary_column_is_null_and_the_type_is_nd2a(officer_change_rows):
    assert {row["days_to_anniversary"] for row in
            officer_change_rows.values()} == {None}
    assert {row["case_type"] for row in officer_change_rows.values()} == {"ND2A"}


@needs_db
def test_an_existing_annual_return_reads_as_nar1_with_no_deadline():
    """Every row written before 050 must come out of it exactly as it went in."""
    entity_id, case_id = str(uuid.uuid4()), str(uuid.uuid4())
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO entities (id, company_name, br_number, incorporation_date) "
            "VALUES (%s, %s, %s, DATE '2020-03-01')",
            (entity_id, "ANNUAL RETURN FIXTURE LIMITED", "AR-BR-0050"))
        # No form_code named: the column default is what existing code relies on.
        cur.execute(
            "INSERT INTO nar1_cases (id, entity_id, nar1_type, case_no) "
            "VALUES (%s, %s, 'annual_return', 'AR-0050')", (case_id, entity_id))
        cur.execute(
            f"SELECT case_type, form_code, filing_deadline, days_to_deadline, "
            f"days_to_anniversary FROM {VIEW} WHERE id = %s", (case_id,))
        case_type, form_code, deadline, to_deadline, to_anniversary = cur.fetchone()
        conn.rollback()
    assert (case_type, form_code, deadline, to_deadline) == \
        ("NAR1", "Nar1", None, None)
    assert to_anniversary is not None


@needs_db
def test_the_form_code_vocabulary_is_a_check_constraint():
    entity_id = str(uuid.uuid4())
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO entities (id, company_name) VALUES (%s, %s)",
            (entity_id, "CHECK FIXTURE LIMITED"))
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                "INSERT INTO nar1_cases (entity_id, nar1_type, form_code) "
                "VALUES (%s, 'annual_return', 'Nd4')", (entity_id,))
        conn.rollback()


@needs_db
def test_an_entry_names_exactly_one_party():
    """A person AND a company, or neither, is not an officer."""
    entity_id, case_id = str(uuid.uuid4()), str(uuid.uuid4())
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO entities (id, company_name) VALUES (%s, %s)",
            (entity_id, "PARTY FIXTURE LIMITED"))
        cur.execute(
            "INSERT INTO nar1_cases (id, entity_id, nar1_type, form_code) "
            "VALUES (%s, %s, 'appointment_and_resignation', 'Nd2a')",
            (case_id, entity_id))
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                "INSERT INTO officer_change_entries (case_id, kind, capacity) "
                "VALUES (%s, 'cessation', 'director')", (case_id,))
        conn.rollback()


@needs_db
@pytest.mark.parametrize("table", [
    "officer_change_entries", "officer_change_documents",
    "officer_cr_particulars", "person_eservice_credentials",
])
def test_the_new_tables_have_rls_on_and_no_policy(table):
    """RLS-on-with-no-policy is default-deny for every role but the service
    role. A policy is the thing that would open it."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT relrowsecurity FROM pg_class "
            "WHERE oid = %s::regclass", (f"public.{table}",))
        assert cur.fetchone()[0] is True
        cur.execute(
            "SELECT count(*) FROM pg_policies "
            "WHERE schemaname = 'public' AND tablename = %s", (table,))
        assert cur.fetchone()[0] == 0


@needs_db
@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_the_browser_facing_roles_cannot_read_a_stored_password(role):
    """`person_eservice_credentials` holds clients' CR e-Registry passwords.
    Supabase's default privileges GRANT ALL on every new public table to these
    two roles, so the migration has to take it back."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
        if cur.fetchone() is None:
            pytest.skip(f"role {role} does not exist in this database")
        cur.execute(
            "SELECT has_table_privilege(%s, 'public.person_eservice_credentials', "
            "'SELECT')", (role,))
        assert cur.fetchone()[0] is False


@needs_db
def test_every_officer_change_audit_code_is_labelled_as_g_flowdesks_own():
    """The column default is origin='viewpoint', which would file these as
    imported history."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT code, category, origin FROM audit_event_types "
            "WHERE code = ANY(%s)", (list(ev.OFFICER_CHANGE_CODES),))
        rows = cur.fetchall()
    assert {r[0] for r in rows} == set(ev.OFFICER_CHANGE_CODES)
    assert {(r[1], r[2]) for r in rows} == {("officer_changes", "g_flowdesk")}


@needs_db
def test_the_view_is_still_security_invoker_and_closed_to_the_browser():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT reloptions FROM pg_class WHERE relname = %s", (VIEW,))
        options = cur.fetchone()[0] or []
        assert "security_invoker=true" in [o.replace(" ", "") for o in options]
        for role in ("anon", "authenticated"):
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
            if cur.fetchone() is None:
                continue
            cur.execute("SELECT has_table_privilege(%s, %s, 'SELECT')", (role, VIEW))
            assert cur.fetchone()[0] is False
