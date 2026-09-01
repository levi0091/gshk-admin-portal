"""Migration 028 — the columns NAR1 and NNC1 need on the profiles.

DB-backed, per tests/tpsi/test_migration_016.py: runs only with RUN_DB_TESTS=1
against a database that has had `alembic upgrade head` applied. Skipped in the
mocked unit run, so CI's migrations job (upgrade head + downgrade base) is what
proves reversibility.

Read-only throughout — this runs against DEV on a developer machine.
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


def _column(cur, table, column):
    cur.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = %s",
        (table, column),
    )
    return cur.fetchone()


@pytest.mark.parametrize("table, column", [
    ("entities", "business_nature_code"),
    ("entities", "business_nature_desc"),
    ("entities", "mortgages_total"),
    ("share_classes", "issued_amount"),
    ("persons", "former_name_zh"),
    ("persons", "alias_en"),
    ("persons", "alias_zh"),
    ("entity_officers", "correspondence_address_id"),
])
def test_the_cr_columns_exist(table, column):
    with _conn() as conn, conn.cursor() as cur:
        assert _column(cur, table, column) is not None


def test_issued_amount_is_numeric_not_an_integer_count():
    """The whole point of the column. `total_issued` counts shares;
    `issued_amount` is what they are worth, and a share can be worth a
    fraction of a dollar."""
    with _conn() as conn, conn.cursor() as cur:
        assert _column(cur, "share_classes", "issued_amount")[0] == "numeric"


def test_mortgages_total_is_text_because_cr_accepts_nil():
    with _conn() as conn, conn.cursor() as cur:
        assert _column(cur, "entities", "mortgages_total")[0] == "text"


def test_record_locations_table_exists_with_one_row_per_register():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.entity_record_locations')")
        assert cur.fetchone()[0] is not None

        cur.execute(
            "SELECT 1 FROM pg_constraint "
            "WHERE conname = 'entity_record_locations_unique'"
        )
        assert cur.fetchone() is not None, (
            "a company must not be able to hold two locations for the same "
            "register; re-pointing has to update in place"
        )


def test_correspondence_address_points_at_addresses():
    """It must be a real address row, not free text — the whole reason it is
    a separate column is that CR reads it as five discrete lines."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM pg_constraint "
            "WHERE conname = 'entity_officers_correspondence_address_fkey' "
            "AND contype = 'f'"
        )
        assert cur.fetchone() is not None


@pytest.mark.parametrize("field", [
    "business_nature_code", "mortgages_total", "issued_amount",
    "alias_en", "alias_zh", "former_name_zh", "correspondence_address_id",
])
def test_every_new_field_is_labelled_for_the_audit_trail(field):
    """There is no FK from audit rows to this table, so an unlabelled field
    does not fail — it renders as a raw column name. Migration 022 exists
    because exactly that happened before."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT label FROM audit_field_labels WHERE field = %s",
                    (field,))
        row = cur.fetchone()
        assert row is not None and row[0].strip()
