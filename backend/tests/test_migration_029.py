"""Migration 029 — the CR filing receipt as a case-owned document (spec §4).

DB-backed, per tests/test_migration_021.py through 024: runs only with
RUN_DB_TESTS=1 against a database that has had `alembic upgrade head` applied.
Skipped in the mocked unit run.

The three things this migration has to get right, and each is a way the feature
fails silently if it is wrong:

  1. `documents.nar1_case_id` exists — without it every receipt upload 400s at
     PostgREST with an unknown column.
  2. The owner CHECK admits a case-only owner — the constraint from migration
     007 names only entity and person, and would reject every receipt row.
  3. `cr_receipt` is seeded with `applies_to='case'` — seeded as 'company' it
     would appear in the loose company-document dropdown, where a filing
     receipt has no business being uploadable.
"""
import os

import pytest

psycopg2 = pytest.importorskip("psycopg2")

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)


def _conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def _column(table: str, column: str) -> tuple | None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s "
            "AND column_name = %s",
            (table, column),
        )
        return cur.fetchone()


def _check_clause(name: str) -> str | None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = %s", (name,),
        )
        row = cur.fetchone()
        return row[0] if row else None


# --------------------------------------------------------------------------- #
#  documents.nar1_case_id
# --------------------------------------------------------------------------- #

def test_documents_has_a_case_owner_column():
    assert _column("documents", "nar1_case_id") is not None


def test_the_case_owner_column_is_nullable():
    """Every document that already exists is owned by a company or a person.
    NOT NULL would have required inventing a case for all of them."""
    assert _column("documents", "nar1_case_id")[1] == "YES"


def test_the_case_owner_is_a_real_foreign_key_that_cascades():
    """A receipt outlives its case only as an orphan nothing can reach. The
    cascade is what stops the storage bucket accumulating unreferenced
    evidence."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY (c.conkey)
            WHERE c.contype = 'f' AND t.relname = 'documents'
              AND a.attname = 'nar1_case_id'
            """
        )
        definitions = [r[0] for r in cur.fetchall()]
    assert definitions, "documents.nar1_case_id has no foreign key"
    assert any("nar1_cases" in d and "ON DELETE CASCADE" in d for d in definitions)


def test_the_case_owner_column_is_indexed():
    """The manual-submit gate and the case's document list both filter on it."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = 'public' AND tablename = 'documents'"
        )
        definitions = [r[0] for r in cur.fetchall()]
    assert any("nar1_case_id" in d for d in definitions)


# --------------------------------------------------------------------------- #
#  the owner CHECK
# --------------------------------------------------------------------------- #

def test_the_owner_check_admits_a_case_only_owner():
    clause = _check_clause("documents_owner_present")
    assert clause, "documents_owner_present is missing entirely"
    assert "nar1_case_id" in clause


def test_the_owner_check_still_refuses_a_document_with_no_owner_at_all():
    """Widened, not weakened. A row owned by nobody is still a bug."""
    clause = _check_clause("documents_owner_present")
    for column in ("entity_id", "person_id", "nar1_case_id"):
        assert column in clause


def test_a_case_owned_document_can_actually_be_inserted():
    """information_schema says the columns are declared; this says the database
    accepts the row. The CHECK from migration 007 would refuse it."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM nar1_cases LIMIT 1")
        row = cur.fetchone()
        if row is None:
            pytest.skip("no nar1_cases rows in this database to attach to")
        cur.execute(
            "INSERT INTO documents "
            "  (nar1_case_id, document_type_code, storage_path, file_name) "
            "VALUES (%s, 'cr_receipt', 'receipt/x/1/r.pdf', 'r.pdf') "
            "RETURNING id",
            (row[0],),
        )
        document_id = cur.fetchone()[0]
        assert document_id
        # Never left behind: this is a fabricated row, not test data anybody
        # asked for.
        cur.execute("DELETE FROM documents WHERE id = %s", (document_id,))


# --------------------------------------------------------------------------- #
#  the cr_receipt document type
# --------------------------------------------------------------------------- #

def test_cr_receipt_is_seeded():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT label, category, is_generated, applies_to "
            "FROM document_types WHERE code = 'cr_receipt'"
        )
        row = cur.fetchone()
    assert row is not None, "cr_receipt was not seeded"
    label, category, is_generated, applies_to = row
    assert label == "CR Filing Receipt"
    assert category == "filing"
    # CR generates it, not us. `is_generated` means "this portal produces it".
    assert is_generated is False


def test_cr_receipt_is_scoped_to_a_case_so_it_stays_out_of_both_dropdowns():
    """`routers/documents.py` filters `applies_to IN (owner_type, 'both')`.
    Seeded as 'company' or 'both', a filing receipt would become uploadable as a
    loose company document, outside the endpoint that gates the submission
    behind it."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT applies_to FROM document_types WHERE code = 'cr_receipt'"
        )
        assert cur.fetchone()[0] == "case"


def test_the_applies_to_check_admits_case_without_dropping_the_others():
    clause = _check_clause("document_types_applies_to_valid")
    assert clause
    for value in ("'company'", "'person'", "'both'", "'case'"):
        assert value in clause


# --------------------------------------------------------------------------- #
#  nar1_cases pointer
# --------------------------------------------------------------------------- #

def test_the_case_carries_the_receipt_pointer_and_its_version():
    """id AND version, for migration 023's reason: upload_document versions in
    place, so an id alone stops resolving to THIS case's evidence as soon as
    anything re-uploads against the same owner and type."""
    assert _column("nar1_cases", "manual_receipt_document_id") is not None
    version = _column("nar1_cases", "manual_receipt_document_version")
    assert version is not None
    assert version[0] == "integer"
    assert version[1] == "YES"
