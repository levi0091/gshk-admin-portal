"""Migration 038 — a person's TCSP licence, and a beneficial owner's nature of control.

DB-backed and RUN_DB_TESTS-gated, per tests/test_migration_021..037.py.

NAMED `test_migration_038.py` ON PURPOSE. `.github/workflows/backend-ci.yml`
runs DB-backed tests as `pytest tests/test_migration_*.py` under RUN_DB_TESTS=1;
a file outside that glob is skipped by the `unit` job and never collected by the
`migrations` job, so it would run nowhere at all.

What each assertion is here for, rather than in the unit suite:

  * the three columns exist and are `text`. Every unit test mocks PostgREST, so
    a column that was never added passes them all and then 500s the profile.
  * `percent_interest` and `percent_vote` SURVIVE. They are off the screen, and
    the temptation on the next tidy-up is to drop them — they hold ETL'd
    Viewpoint values on real rows, and neither CR form has ever read either
    (nothing in `cr_forms/contract.py` maps to `beneficial_owners.*`). Dropping
    data to tidy a form is the one part of this change that is not reversible.
  * the audit labels are seeded. There is no FK from `audit_log` to
    `audit_field_labels`, so an unlabelled field does not fail — it renders as a
    raw column name in the trail, which is the silent failure migration 022
    exists to close.

Every fixture is rolled back. This runs against DEV on a developer machine and
must leave nothing behind.
"""
import os

import pytest

from services.cr_forms import control_nature

psycopg2 = pytest.importorskip("psycopg2")

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)


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


def _columns(cur, table):
    cur.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table,),
    )
    return dict(cur.fetchall())


def test_a_person_can_hold_a_tcsp_licence(conn):
    with conn.cursor() as cur:
        cols = _columns(cur, "persons")
    assert cols.get("tcsp_licence_no") == "text"
    assert cols.get("tcsp_exemption_reason") == "text"


def test_the_person_columns_are_named_as_they_are_on_entities(conn):
    """One name for one fact. The Company Secretary tile falls back from the
    corporate party to the person without translating between two spellings."""
    with conn.cursor() as cur:
        entities = _columns(cur, "entities")
        persons = _columns(cur, "persons")
    for name in ("tcsp_licence_no", "tcsp_exemption_reason"):
        assert entities.get(name) == persons.get(name) == "text"


def test_nature_of_control_exists_and_is_not_constrained(conn):
    """No CHECK on purpose: the vocabulary is served from
    `services/cr_forms/control_nature.py` and enforced on write, so a wording
    revision is a code change rather than a migration — and 34 legacy rows
    already carry free text a constraint would refuse on an unrelated edit."""
    with conn.cursor() as cur:
        assert _columns(cur, "beneficial_owners").get("nature_of_control") == "text"
        cur.execute(
            """
            SELECT conname FROM pg_constraint
            WHERE conrelid = 'public.beneficial_owners'::regclass
              AND contype = 'c'
              AND pg_get_constraintdef(oid) ILIKE '%nature_of_control%'
            """
        )
        assert cur.fetchall() == []


def test_the_two_percentage_columns_were_not_dropped(conn):
    """They are off the screen, not out of the database — see the docstring."""
    with conn.cursor() as cur:
        cols = _columns(cur, "beneficial_owners")
    assert "percent_interest" in cols
    assert "percent_vote" in cols


def test_a_row_accepts_every_code_the_dropdown_offers(conn):
    """The list the screen draws from and the column that stores it have to
    agree — rolled back, so nothing is left behind."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM entities LIMIT 1")
        row = cur.fetchone()
        if not row:
            pytest.skip("no entities in this database")
        for code, _ in control_nature.NATURE_OF_CONTROL:
            cur.execute(
                "INSERT INTO beneficial_owners (entity_id, owner_type, "
                "nature_of_control) VALUES (%s, %s, %s) RETURNING id",
                (row[0], "ubo", code),
            )
            assert cur.fetchone()[0]
    conn.rollback()


def test_the_new_fields_are_labelled_in_the_audit_trail(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT field, label FROM audit_field_labels WHERE field = ANY(%s)",
            (["tcsp_licence_no", "tcsp_exemption_reason", "nature_of_control"],),
        )
        labels = dict(cur.fetchall())
    assert labels.get("tcsp_licence_no") == "TCSP Licence No."
    assert labels.get("tcsp_exemption_reason") == "TCSP Exemption Reason"
    assert labels.get("nature_of_control") == "Nature of Control"
