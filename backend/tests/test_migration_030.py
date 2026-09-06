"""Migration 030 — nar1_client_approvals, provenance columns, audit codes.

DB-backed, per tests/test_migration_021.py onwards: runs only with
RUN_DB_TESTS=1 against a database that has had `alembic upgrade head` applied.
Skipped in the mocked unit run.

The failures this file is written to catch, all of which are silent:

  * a `token_hash` that is not UNIQUE — a duplicate would make "which case did
    this token approve" ambiguous on the one route with no user behind it;
  * an `outcome` CHECK that admits anything — 'rejected' written here would be
    a client rejection nothing in the code can produce and nothing renders;
  * the three audit codes unseeded — there is NO FK from audit_log to
    audit_event_types, so an unseeded code writes fine and then renders
    UNLABELLED in the trail. That is what migration 022 exists to repair, and
    this is the test that stops it happening a second time.
"""
import os

import pytest

psycopg2 = pytest.importorskip("psycopg2")

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)

AUDIT_CODES = {
    "CLIENT_APPROVAL_LINK_SENT",
    "CLIENT_APPROVAL_SELF_SERVICE",
    "CLIENT_APPROVAL_AUTO_APPROVED",
}


def _conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def _columns(table: str) -> dict:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s",
            (table,),
        )
        return {r[0]: (r[1], r[2]) for r in cur.fetchall()}


# --------------------------------------------------------------------------- #
#  The table
# --------------------------------------------------------------------------- #

def test_the_approvals_table_exists_with_every_column_the_service_writes():
    columns = _columns("nar1_client_approvals")
    assert columns, "nar1_client_approvals was not created"
    for name in ("id", "nar1_case_id", "person_id", "recipient_email",
                 "recipient_name", "token_hash", "sent_at", "expires_at",
                 "responded_at", "outcome", "ip_address", "user_agent",
                 "created_at"):
        assert name in columns, f"nar1_client_approvals.{name} is missing"


def test_the_token_hash_is_unique():
    """A duplicate would make "which case did this token approve" ambiguous on
    the one route in this API that has no authenticated user behind it."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = 'public' "
            "AND tablename = 'nar1_client_approvals'"
        )
        definitions = [r[0] for r in cur.fetchall()]
    assert any("UNIQUE" in d and "token_hash" in d for d in definitions)


def test_the_ip_address_is_stored_as_an_inet_not_as_text():
    """Levi asked for the IP to be logged. `inet` refuses a value that is not
    an address, which is the whole point of recording one."""
    assert _columns("nar1_client_approvals")["ip_address"][0] == "inet"


def test_the_outcome_vocabulary_is_constrained():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'nar1_client_approvals_outcome_valid'"
        )
        row = cur.fetchone()
    assert row, "the outcome CHECK is missing"
    clause = row[0]
    assert "'approved'" in clause
    # 'superseded' is the load-bearing third state: without it, a restart could
    # not invalidate an outstanding link and a director holding the previous
    # email could approve a document that has since been discarded.
    assert "'superseded'" in clause


def test_an_unanswered_token_has_a_null_outcome():
    """NULL means issued and unanswered. It has to be permitted, or every
    insert would need to invent a state the client has not reached."""
    assert _columns("nar1_client_approvals")["outcome"][1] == "YES"


def test_deleting_a_person_does_not_erase_the_approval_record():
    """ON DELETE SET NULL, never CASCADE: removing a contact record must not
    take with it the evidence that somebody approved a statutory filing."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY (c.conkey)
            WHERE c.contype = 'f' AND t.relname = 'nar1_client_approvals'
              AND a.attname = 'person_id'
            """
        )
        definitions = [r[0] for r in cur.fetchall()]
    assert definitions
    assert any("SET NULL" in d for d in definitions)


def test_the_expiry_index_only_covers_what_the_job_actually_scans():
    """The 14-day job asks for unanswered tokens past their expiry. A full index
    would grow with every token ever issued; this one grows with what is due."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' "
            "AND tablename = 'nar1_client_approvals'"
        )
        definitions = [r[0] for r in cur.fetchall()]
    assert any("expires_at" in d and "outcome IS NULL" in d for d in definitions)


# --------------------------------------------------------------------------- #
#  Provenance on the case
# --------------------------------------------------------------------------- #

def test_the_case_carries_how_it_was_approved():
    columns = _columns("nar1_cases")
    for name in ("client_approval_source", "client_approval_person_id",
                 "client_approval_name"):
        assert name in columns, f"nar1_cases.{name} is missing"
        assert columns[name][1] == "YES", f"{name} must be nullable"


def test_the_source_is_not_constrained_in_the_database():
    """Migration 026's reason: the vocabulary lives in
    services/nar1_approvals.py, and a constraint that disagreed with the code
    would refuse a value the application considers valid."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'public.nar1_cases'::regclass AND contype = 'c'"
        )
        clauses = [r[0] for r in cur.fetchall()]
    assert not any("client_approval_source" in c for c in clauses)


# --------------------------------------------------------------------------- #
#  Audit codes — the failure that is silent
# --------------------------------------------------------------------------- #

def test_the_three_audit_codes_are_seeded():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT code FROM audit_event_types WHERE code = ANY(%s)",
            (list(AUDIT_CODES),),
        )
        found = {r[0] for r in cur.fetchall()}
    assert found == AUDIT_CODES


def test_the_codes_are_labelled_as_G_FlowDesk_and_not_as_Viewpoint():
    """The column default is origin='viewpoint', which would file these as
    imported history from a system that never produced them."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT code, name, category, origin FROM audit_event_types "
            "WHERE code = ANY(%s)", (list(AUDIT_CODES),),
        )
        rows = cur.fetchall()
    assert rows
    for code, name, category, origin in rows:
        assert origin == "g_flowdesk", f"{code} is filed as {origin}"
        assert category == "nar1", f"{code} is categorised as {category}"
        assert name and name != code, f"{code} has no human label"


def test_the_staff_relay_code_is_untouched():
    """CLIENT_APPROVAL_RECEIVED still fires for a reply a human relayed. Three
    codes for three routes: the evidence behind each is different."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM audit_event_types "
            "WHERE code = 'CLIENT_APPROVAL_RECEIVED'"
        )
        assert cur.fetchone()[0] == 1
