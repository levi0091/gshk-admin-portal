"""DB-backed migration assertions (PBI-38 greenfield documents).

Runs only when RUN_DB_TESTS=1 and DATABASE_URL point at a Postgres that has had
`alembic upgrade head` applied (the CI `migrations` job). Skipped in the mocked
unit run.
"""
import os

import pytest

psycopg2 = pytest.importorskip("psycopg2")

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (set RUN_DB_TESTS=1 + DATABASE_URL)",
)

EXPECTED_TYPES = {
    "nar1", "nnc1", "aoa", "fwr", "coi", "incumbency",
    "share_certificate", "id_scan", "address_proof", "other",
}


def _conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def test_document_types_seeded_ten_rows():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT code FROM document_types")
        codes = {r[0] for r in cur.fetchall()}
    assert codes == EXPECTED_TYPES


def test_documents_empty_at_go_live():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM documents")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM document_versions")
        assert cur.fetchone()[0] == 0


def test_greenfield_drops_applied():
    with _conn() as conn, conn.cursor() as cur:
        # document_sequences table dropped
        cur.execute("SELECT to_regclass('public.document_sequences')")
        assert cur.fetchone()[0] is None
        # document_kind enum dropped
        cur.execute("SELECT 1 FROM pg_type WHERE typname = 'document_kind'")
        assert cur.fetchone() is None
        # documents has the Storage-native columns and none of the old ones
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'documents'"
        )
        cols = {r[0] for r in cur.fetchall()}
        assert {"storage_bucket", "storage_path", "checksum_sha256", "document_type_code"} <= cols
        assert not ({"kind", "ocr_text", "vp_doc_file_id", "source", "revision"} & cols)


def test_document_type_fk_rejects_unknown_code():
    with _conn() as conn, conn.cursor() as cur:
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute(
                "INSERT INTO documents (document_type_code, storage_path) "
                "VALUES ('does_not_exist', 'p/q.pdf')"
            )
        conn.rollback()
