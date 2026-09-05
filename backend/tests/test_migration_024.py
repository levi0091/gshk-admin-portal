"""Migration 024 — the `nar1_case_registry` case-level dashboard relation.

DB-backed and RUN_DB_TESTS-gated, per tests/test_migration_021/022/023.py.

NAMED `test_migration_024.py` ON PURPOSE, not the brief's
`test_nar1_case_registry.py`. `.github/workflows/backend-ci.yml` runs DB-backed
tests as `pytest tests/test_migration_*.py` under RUN_DB_TESTS=1; a file outside
that glob is skipped by the `unit` job and never collected by the `migrations`
job, so it would not run ANYWHERE. That is the exact trap the branch already hit
twice (61655e8's migration_016, and the docs/ glob that silently collected zero
cases). The parity test below is the entire licence for the view duplicating
`services/nar1_case_status.py`; a parity test that never executes is not one.

The parity test drives REAL rows through the REAL view and compares against the
REAL Python function. A hand-written Python mirror of the SQL would only ever
test the mirror.

Every test rolls its fixtures back. This runs against DEV on a developer
machine and must leave nothing behind.
"""
import itertools
import os
import uuid

import pytest

from services import nar1_case_status as st
from services import nar1_cases
from services.tpsi import filings as tpsi_filings

psycopg2 = pytest.importorskip("psycopg2")
from psycopg2.extras import execute_values  # noqa: E402

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)

VIEW = "nar1_case_registry"

#: Every stage the CHECK constraint (migration 018) permits, plus "no filing at
#: all" as None. `superseded` is excluded here and exercised on its own — the
#: view is supposed to ignore it, so feeding it into the parity table would be
#: comparing against a filing the view deliberately did not pick.
STAGES = [
    None,
    tpsi_filings.STAGE_DRAFT,
    tpsi_filings.STAGE_VALIDATED,
    tpsi_filings.STAGE_VALIDATION_FAILED,
    tpsi_filings.STAGE_SIGNED,
    tpsi_filings.STAGE_SIGNING_FAILED,
    tpsi_filings.STAGE_SUBMITTED,
    tpsi_filings.STAGE_SUBMISSION_FAILED,
    tpsi_filings.STAGE_REGISTERED,
    tpsi_filings.STAGE_EDRIVE,
]
SENT = [None, "2026-08-16T00:00:00Z"]
APPROVED = [None, True, False]

#: The receipt column is jsonb and Python tests it for TRUTH, not for NULL.
#: `{}` and JSON `null` are the two values a naive `manual_receipt IS NOT NULL`
#: mirror gets wrong — SQL would call the case Completed while derive() would
#: not. Neither is reachable through validate_receipt() today, which is exactly
#: why they belong in the table: nothing else would ever catch the divergence.
MANUAL = [None, '{"caseNo": "1"}', "{}", "null"]

#: Migration 039. A FIFTH axis rather than a handful of extra cases, because
#: `closed` is the FIRST branch of both implementations: it has to beat every
#: other combination, and "beats everything" is a claim about the whole table.
#: 240 rows become 480, still one batched insert and one read.
CLOSED = [None, "2026-09-05T02:00:00Z"]

COMBINATIONS = list(itertools.product(STAGES, SENT, APPROVED, MANUAL, CLOSED))


def _conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def _badge(row: dict) -> dict:
    """What the view says, in derive()'s own shape."""
    return st.badge_from_row(row)


def _expected(row: dict) -> dict:
    """What the Python function says, from the DB's own stored values."""
    case = {
        "verification_sent_at": row["verification_sent_at"],
        "client_approved": row["client_approved"],
        "manual_receipt": row["manual_receipt"],
        "days_to_anniversary": row["days_to_anniversary"],
        "closed_at": row["closed_at"],
    }
    filing = {"stage": row["filing_stage"]} if row["filing_stage"] else None
    return st.derive(case, filing)


@pytest.fixture(scope="module")
def registry_rows():
    """Insert one case per truth-table combination, read the view once, roll back.

    Module-scoped and batched: 240 combinations as 240 separate transactions
    would be 240 round trips to DEV for one assertion each.
    """
    entity_id = str(uuid.uuid4())
    ids = {}
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO entities (id, company_name, br_number, incorporation_date) "
                "VALUES (%s, %s, %s, DATE '2020-03-01')",
                (entity_id, "PARITY FIXTURE LIMITED", "PARITY-BR-0001"),
            )

            cases, filings = [], []
            for index, (stage, sent, approved, manual, closed) in enumerate(
                    COMBINATIONS):
                case_id = str(uuid.uuid4())
                cases.append((case_id, entity_id, f"PARITY-{index:04d}",
                              sent, approved, manual, closed))
                if stage:
                    filings.append((entity_id, case_id, "Nar1", stage))
                ids[(stage, sent, approved, manual, closed)] = case_id

            execute_values(
                cur,
                "INSERT INTO nar1_cases (id, entity_id, nar1_type, case_no, "
                "verification_sent_at, client_approved, manual_receipt, "
                "closed_at) VALUES %s",
                cases,
                template="(%s, %s, 'annual_return', %s, %s, %s, %s::jsonb, %s)",
            )
            execute_values(
                cur,
                "INSERT INTO tpsi_filings (entity_id, nar1_case_id, form_code, "
                "stage) VALUES %s",
                filings,
            )

            cur.execute(
                f"SELECT r.id, r.workflow_status, r.workflow_off_portal, "
                f"       r.workflow_overdue, r.days_to_anniversary, r.filing_stage, "
                f"       r.filing_id, r.manual_receipt_present, r.case_no, "
                f"       r.company_name, r.br_number, r.case_type, r.entity_id, "
                f"       r.closed_by_name, r.closed_reason, "
                f"       c.verification_sent_at, c.client_approved, "
                f"       c.manual_receipt, c.closed_at "
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


# --------------------------------------------------------------------------- #
#  Parity — the whole reason the view is allowed to restate derive()
# --------------------------------------------------------------------------- #

def test_the_view_and_the_python_function_agree_on_every_reachable_state(registry_rows):
    """The view's badge must equal derive()'s badge for every reachable state.

    Not just the code: off_portal and overdue too, because the dashboard filters
    on all three. One test rather than 240 parametrised ones so a failure names
    EVERY disagreement at once — one flipped branch of the CASE breaks dozens of
    combinations, and a list of them is what tells you which branch moved.

    If this ever fails, one of the two implementations moved and the dashboard is
    sorting and filtering on a different rule than the case detail displays.
    """
    disagreements = [
        (combination, _badge(row), _expected(row))
        for combination, row in registry_rows.items()
        if _badge(row) != _expected(row)
    ]
    assert not disagreements, (
        f"{len(disagreements)} of {len(registry_rows)} states disagree "
        f"(stage, sent, approved, manual) -> view != derive():\n"
        + "\n".join(f"  {c}: {got} != {want}" for c, got, want in disagreements[:20])
    )


def test_every_python_status_is_emitted_by_the_view(registry_rows):
    """A status Python can produce but the view never emits would be unsortable
    and unfilterable — visible on the case detail, invisible on the dashboard."""
    assert {row["workflow_status"] for row in registry_rows.values()} == set(
        st.WORKFLOW_STATUSES
    )


def test_manual_receipt_present_mirrors_pythons_truthiness_not_null_ness(registry_rows):
    """`{}` and JSON `null` are NOT a recorded off-portal submission.

    Python asks `if case.get("manual_receipt")`. A SQL mirror written as
    `manual_receipt IS NOT NULL` calls both of those Completed, and a case with
    an empty receipt would show as filed on the dashboard while the case detail
    still showed it in Data Verification.
    """
    for (stage, sent, approved, manual, _closed), row in registry_rows.items():
        assert row["manual_receipt_present"] is bool(row["manual_receipt"]), (
            f"manual_receipt {manual!r} -> present={row['manual_receipt_present']}"
        )


# --------------------------------------------------------------------------- #
#  Closure (migration 039) — the branch that has to come first
# --------------------------------------------------------------------------- #

def test_every_closed_row_reads_closed_whatever_else_is_true_of_it(registry_rows):
    """The parity test already compares the two implementations. This says what
    the ANSWER is, so a change that moved the branch in BOTH at once — leaving
    them in agreement and both wrong — still fails."""
    for key, row in registry_rows.items():
        closed = key[4]
        assert (row["workflow_status"] == "closed") is bool(closed), key


def test_a_closed_row_is_never_flagged_overdue(registry_rows):
    """`workflow_overdue` gained 'closed' alongside 'completed' in 039. These
    fixtures have an anniversary inside the window so nothing is overdue anyway;
    what this pins is that the closed rows are not the exception."""
    assert not [k for k, r in registry_rows.items()
                if r["workflow_status"] == "closed" and r["workflow_overdue"]]


def test_the_view_carries_the_closer_and_the_reason(registry_rows):
    """The workflow screen names who closed a case and why. `nar1_cases` holds
    only the uuid, so `closed_by_name` has to be joined here — a banner that
    names a uuid is one nobody can read."""
    row = next(iter(registry_rows.values()))
    assert "closed_by_name" in row
    assert "closed_reason" in row


# --------------------------------------------------------------------------- #
#  Which filing the row is about
# --------------------------------------------------------------------------- #

def test_one_row_per_case_not_per_company(registry_rows):
    """A company with many open cases is many rows. If the LATERAL join ever
    became a plain JOIN against all filings, one case would fan out into one row
    per filing and the dashboard would double-count."""
    assert len(registry_rows) == len(COMBINATIONS)


def test_superseded_filings_are_ignored():
    """A Restart marks the old attempt superseded and opens a new one. Joining
    the old one reports the case at the stage it used to be at."""
    entity_id, case_id = str(uuid.uuid4()), str(uuid.uuid4())
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO entities (id, company_name) VALUES (%s, 'SUPERSEDED FIXTURE')",
                (entity_id,),
            )
            cur.execute(
                "INSERT INTO nar1_cases (id, entity_id, nar1_type) "
                "VALUES (%s, %s, 'annual_return')", (case_id, entity_id),
            )
            cur.execute(
                "INSERT INTO tpsi_filings (entity_id, nar1_case_id, form_code, stage) "
                "VALUES (%s, %s, 'Nar1', %s)",
                (entity_id, case_id, tpsi_filings.STAGE_SUPERSEDED),
            )
            cur.execute(
                f"SELECT filing_stage, workflow_status FROM {VIEW} WHERE id = %s",
                (case_id,),
            )
            stage, status = cur.fetchone()
        assert stage is None
        assert status == st.DATA_VERIFICATION
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.parametrize("filed_stage", nar1_cases.CR_FILED_STAGES)
def test_a_filing_cr_already_holds_wins_over_a_newer_draft(filed_stage):
    """THE HAZARD THIS VIEW REFUSES TO INHERIT.

    `services/nar1_cases.current_filing()` takes the NEWEST non-superseded
    filing — and nothing in the codebase ever writes `superseded`. So a second
    POST /tpsi/filings/prepare against an already-submitted case opens a fresh
    `draft` that sorts first, and `composite()` then reports the case as Data
    Verification when CR has already registered the return.

    That is a live Task 5/6 defect, logged for the whole-branch review and NOT
    fixed here. But the dashboard must not repeat it: a case CR is holding shows
    as Completed. The rule is `nar1_cases.blocking_filing()`'s, not a third one
    invented for this view — CR-filed stages first, newest non-superseded
    otherwise. Parametrised over CR_FILED_STAGES so widening that constant
    without widening the view fails here.
    """
    entity_id, case_id = str(uuid.uuid4()), str(uuid.uuid4())
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO entities (id, company_name) VALUES (%s, 'TWO FILING FIXTURE')",
                (entity_id,),
            )
            cur.execute(
                "INSERT INTO nar1_cases (id, entity_id, nar1_type) "
                "VALUES (%s, %s, 'annual_return')", (case_id, entity_id),
            )
            cur.execute(
                "INSERT INTO tpsi_filings (entity_id, nar1_case_id, form_code, "
                "stage, created_at) VALUES (%s, %s, 'Nar1', %s, now() - interval '1 day')",
                (entity_id, case_id, filed_stage),
            )
            cur.execute(
                "INSERT INTO tpsi_filings (entity_id, nar1_case_id, form_code, "
                "stage, created_at) VALUES (%s, %s, 'Nar1', 'draft', now())",
                (entity_id, case_id),
            )
            cur.execute(
                f"SELECT filing_stage, workflow_status FROM {VIEW} WHERE id = %s",
                (case_id,),
            )
            stage, status = cur.fetchone()
        assert stage == filed_stage
        assert status == st.COMPLETED
    finally:
        conn.rollback()
        conn.close()


def test_the_newest_attempt_wins_when_none_is_filed_at_cr():
    """With nothing filed, the rule falls back to current_filing()'s — newest
    first — so an in-flight retry is what the badge follows."""
    entity_id, case_id = str(uuid.uuid4()), str(uuid.uuid4())
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO entities (id, company_name) VALUES (%s, 'RETRY FIXTURE')",
                (entity_id,),
            )
            cur.execute(
                "INSERT INTO nar1_cases (id, entity_id, nar1_type, "
                "verification_sent_at, client_approved) "
                "VALUES (%s, %s, 'annual_return', now(), true)", (case_id, entity_id),
            )
            cur.execute(
                "INSERT INTO tpsi_filings (entity_id, nar1_case_id, form_code, "
                "stage, created_at) VALUES (%s, %s, 'Nar1', 'validation_failed', "
                "now() - interval '1 day')", (entity_id, case_id),
            )
            cur.execute(
                "INSERT INTO tpsi_filings (entity_id, nar1_case_id, form_code, "
                "stage, created_at) VALUES (%s, %s, 'Nar1', 'signed', now())",
                (entity_id, case_id),
            )
            cur.execute(
                f"SELECT filing_stage, workflow_status FROM {VIEW} WHERE id = %s",
                (case_id,),
            )
            stage, status = cur.fetchone()
        assert stage == tpsi_filings.STAGE_SIGNED
        assert status == st.SUBMISSION
    finally:
        conn.rollback()
        conn.close()


# --------------------------------------------------------------------------- #
#  The anniversary column
# --------------------------------------------------------------------------- #

def test_days_to_anniversary_comes_from_the_company_registry_view(registry_rows):
    """Not recomputed here: migration 019 already pins it to Asia/Hong_Kong, and
    a second definition would disagree for the first eight hours of every HK
    working day. A NULL on every row means the join is wrong."""
    values = {row["days_to_anniversary"] for row in registry_rows.values()}
    assert values != {None}
    assert all(v is not None for v in values)


def test_the_overdue_flag_is_reachable():
    """THE INVERSE OF THE TEST THAT USED TO STAND HERE, which read: "A PIN ON A
    DEFECT, not an endorsement — DELETE THIS TEST WHEN IT IS FIXED."

    It pinned the fact that `derive()` sets overdue when days_to_anniversary <
    -42 while migration 019 floored that column at exactly -42, so the badge
    could never fire. Its own note said the fix was to change 019's floor rather
    than derive()'s threshold. Migration 033 did precisely that, at Levi's
    request on 2026-09-04 and for a different reason entirely — the registry
    filter's lower bound had nothing below -42 to find.

    So the assertion inverts: the column must now REACH the region the predicate
    tests. Asserting a count of overdue cases would instead be asserting a fact
    about today's DEV book, which is nobody's invariant.

    IT SEEDS ITS OWN ROW, and that is the point of this note. The first version
    read `min(days_to_anniversary)` off the ambient book — a fact about whichever
    companies happen to exist. On DEV that is 5,930 of them and the minimum sits
    near -182, so it passed; in CI the `migrations` job creates the database
    empty, `min()` over no rows is NULL, and the test failed on `assert floor is
    not None` for a reason with nothing to do with the view. It failed on two
    commits running, and because a red build is not deployed, that is why the
    uuid fix riding in the same commit never reached DEV. Assert the ARITHMETIC
    of the view, which holds on an empty database; never the contents of one.
    """
    with _conn() as conn, conn.cursor() as cur:
        # An anniversary 90 days past: beyond the 42-day window, and still on the
        # near side of the midpoint where the column counts down to the next one
        # instead. Built off hk_today() so it means the same thing during the
        # eight hours a day when UTC and Hong Kong disagree about the date.
        entity_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO public.entities (id, company_name, status, incorporation_date)
            VALUES (%s, %s, 'live',
                    (public.hk_today() - make_interval(days => 90))::date
                      - make_interval(years => 5))
            """,
            (entity_id, f"zz-024-{entity_id[:8]}"),
        )
        cur.execute(
            "SELECT days_to_anniversary FROM public.company_registry WHERE id = %s",
            (entity_id,),
        )
        days = cur.fetchone()[0]
        assert days is not None, "the view stopped computing the column at all"
        assert days < -st.FILING_WINDOW_DAYS, (
            f"an anniversary 90 days past reads {days}; the overdue predicate "
            f"tests < {-st.FILING_WINDOW_DAYS} and is unreachable again"
        )
        # The flag still has to COMPUTE, whatever it currently evaluates to.
        cur.execute(f"SELECT count(*) FROM {VIEW} WHERE workflow_overdue IS NULL")
        assert cur.fetchone()[0] == 0
        conn.rollback()


# --------------------------------------------------------------------------- #
#  Security posture
# --------------------------------------------------------------------------- #

def test_the_view_is_security_invoker():
    """A view that bypassed the caller's RLS would hand every case to every role
    that can reach PostgREST (same guard as 019's company_registry)."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT reloptions FROM pg_class WHERE relname = %s", (VIEW,))
        options = cur.fetchone()[0] or []
    assert "security_invoker=true" in [o.replace(" ", "") for o in options]


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_the_browser_facing_roles_cannot_read_the_view(role):
    """Supabase's default privileges GRANT ALL on every new public relation to
    anon and authenticated — measured on DEV: `anon=arwdDxtm/postgres` in
    pg_default_acl. So a view is exposed through PostgREST the moment it is
    created unless the migration takes it back.

    Nothing should reach this relation but the backend, which connects as
    service_role. CLAUDE.md: the frontend never talks to Supabase directly.
    Leaving the default grant would publish case numbers, company names, client
    approval state and the existence of a statutory receipt to anyone holding
    the publishable anon key.
    """
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
        if cur.fetchone() is None:
            pytest.skip(f"role {role} does not exist in this database")
        cur.execute("SELECT has_table_privilege(%s, %s, 'SELECT')", (role, VIEW))
        assert cur.fetchone()[0] is False


def test_the_backend_role_can_still_read_the_view():
    """The revoke above must not take the backend down with it."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'service_role'")
        if cur.fetchone() is None:
            pytest.skip("role service_role does not exist in this database")
        cur.execute("SELECT has_table_privilege('service_role', %s, 'SELECT')", (VIEW,))
        assert cur.fetchone()[0] is True


# --------------------------------------------------------------------------- #
#  Shape
# --------------------------------------------------------------------------- #

def test_the_view_carries_every_column_the_dashboard_lists_on(registry_rows):
    """The dashboard sorts, filters and searches IN THE DATABASE. A column it
    needs that is not in the relation cannot be paginated correctly — sorting
    the 50 rows a page happens to hold answers the wrong question."""
    required = {
        "id", "case_no", "entity_id", "company_name", "br_number", "case_type",
        "filing_stage", "filing_id", "verification_sent_at", "client_approved",
        "manual_receipt_present", "days_to_anniversary", "workflow_status",
        "workflow_off_portal", "workflow_overdue",
    }
    row = next(iter(registry_rows.values()))
    assert required <= set(row)


def test_case_type_says_nar1(registry_rows):
    """R1 is NAR1 only. The column exists so the dashboard's Type header has
    something to render before NNC1 cases arrive in R3."""
    assert {row["case_type"] for row in registry_rows.values()} == {"NAR1"}
