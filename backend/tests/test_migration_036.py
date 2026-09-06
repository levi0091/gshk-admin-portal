"""Migration 036 — one document type per identity document, and sections.

DB-backed, per tests/test_migration_021.py onward: runs only with RUN_DB_TESTS=1
against a database that has had `alembic upgrade head` applied. Skipped in the
mocked unit run.

What has to be true, and how each fails silently if it is not:

  1. Every `id_document_type` enum value has a `document_types` row whose code
     `document_sections.CODE_BY_ID_TYPE` names. A missing one means an identity
     upload of that type hits the FK on `documents.document_type_code` and 400s
     at PostgREST — or, worse, is quietly filed under a type that versions over
     somebody else's document.
  2. `category` is 'identity' on all four. The profile draws its sections from
     `category`; a wrong one puts a passport under "Other Documents", where the
     identity fields do not appear.
  3. `applies_to` is 'person'. An identity document is not a company's.
  4. `id_scan` is RETIRED, not deleted. There is an FK from `documents`, and
     rows exist in DEV — deleting it would fail, and deactivating it is what
     stops it being offered while keeping old uploads labelled.
"""
import os

import pytest

from services import document_sections

psycopg2 = pytest.importorskip("psycopg2")

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)


def _conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def _types(codes):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT code, label, category, applies_to, is_active "
            "FROM public.document_types WHERE code = ANY(%s)",
            (list(codes),),
        )
        return {r[0]: r[1:] for r in cur.fetchall()}


def test_every_id_document_type_has_a_document_type_row():
    codes = list(document_sections.CODE_BY_ID_TYPE.values())
    rows = _types(codes)
    assert set(rows) == set(codes)


def test_the_identity_types_are_person_scoped_and_in_the_identity_section():
    rows = _types(document_sections.CODE_BY_ID_TYPE.values())
    for code, (_label, category, applies_to, is_active) in rows.items():
        assert category == document_sections.IDENTITY_CATEGORY, code
        assert applies_to == "person", code
        assert is_active is True, code


def test_the_enum_values_the_mapper_reads_are_all_offered():
    """`nar1_mapper` matches `id_type` on 'hkid' and 'passport'. Neither may be
    missing from the picker, or the filing cannot be prepared at all."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT unnest(enum_range(NULL::id_document_type))::text")
        enum_values = {r[0] for r in cur.fetchall()}
    assert enum_values == set(document_sections.CODE_BY_ID_TYPE)


def test_the_retired_catch_all_is_deactivated_and_still_present():
    rows = _types(["id_scan", "address_proof"])
    assert set(rows) == {"id_scan", "address_proof"}
    for code, (_label, category, _applies_to, is_active) in rows.items():
        assert is_active is False, code
    # Re-categorised so uploads made under them land in the right SECTION
    # rather than under a heading called "kyc".
    assert rows["id_scan"][1] == "identity"
    assert rows["address_proof"][1] == "address_proof"


def test_the_proof_of_address_types_share_the_proof_of_address_section():
    codes = ["addr_utility_bill", "addr_bank_statement",
             "addr_tenancy", "addr_govt_letter"]
    rows = _types(codes)
    assert set(rows) == set(codes)
    for code, (_label, category, applies_to, is_active) in rows.items():
        assert category == "address_proof", code
        assert applies_to == "both", code
        assert is_active is True, code


def test_every_active_type_lands_in_a_section_that_exists():
    """A category matching no section falls to "Other Documents". That is a
    safety net, not a plan — a document under the wrong heading is recoverable,
    one rendered nowhere is not, but neither should happen by accident."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT category FROM public.document_types "
            "WHERE is_active AND applies_to IN ('person', 'both')")
        categories = {r[0] for r in cur.fetchall()}
    person_sections = {s["key"] for s in document_sections.sections_for("person")}
    assert categories <= person_sections, categories - person_sections


def test_an_identity_document_can_reference_its_scan():
    """`person_identity_documents.scan_document_id` is the link the upload now
    writes. It existed and nothing ever set it, which is why a scan and the
    number it shows had no relationship at all."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "AND table_name = 'person_identity_documents' "
            "AND column_name = 'scan_document_id'")
        assert cur.fetchone() is not None


def test_the_renewal_reminder_column_survives_its_removal_from_the_screen():
    """Levi 2026-09-04 removed the field, not the data — the same treatment
    `place_of_issue` got, so no Viewpoint history is destroyed."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "AND table_name = 'person_identity_documents'")
        cols = {r[0] for r in cur.fetchall()}
    assert {"reminder_date", "place_of_issue"} <= cols
