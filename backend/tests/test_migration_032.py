"""Migration 032 — Viewpoint's sub-national country codes rewritten.

DB-backed, per tests/test_migration_021.py onwards: runs only with
RUN_DB_TESTS=1 against a database that has had `alembic upgrade head` applied.
Skipped in the mocked unit run.

The failure this catches is the one the migration exists for: a country column
still holding a code CR has no entry for. That state is invisible on the
profile — the address renders, the save succeeds, every check passes — and
surfaces only when a NAR1 reaches Data Verification and refuses to be built.
"""
import os

import pytest

psycopg2 = pytest.importorskip("psycopg2")

from services.tpsi.forms.cr_vocabularies import (  # noqa: E402
    VIEWPOINT_SUBDIVISIONS,
    resolve_country,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_DB_TESTS"),
    reason="requires Postgres with migrations applied (RUN_DB_TESTS=1 + DATABASE_URL)",
)

COUNTRY_COLUMNS = (
    ("entities", "incorporation_place"),
    ("person_identity_documents", "issuing_country"),
    ("addresses", "country"),
)


def _conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def _distinct(table: str, column: str) -> list[str]:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT DISTINCT {column} FROM {table} "
            f"WHERE coalesce(btrim({column}), '') <> ''"
        )
        return [row[0] for row in cur.fetchall()]


@pytest.mark.parametrize("table,column", COUNTRY_COLUMNS)
def test_no_row_holds_a_code_cr_cannot_file(table, column):
    """The whole point. Named per value so a failure says WHICH code came
    back, not merely that one did."""
    offenders = sorted(
        v for v in _distinct(table, column)
        if v.strip().upper() in VIEWPOINT_SUBDIVISIONS
    )
    assert not offenders, (
        f"{table}.{column} still holds {offenders} — a NAR1 built from any of "
        f"these rows dies at Data Verification"
    )


@pytest.mark.parametrize("table,column", COUNTRY_COLUMNS)
def test_every_stored_country_resolves_to_a_cr_code(table, column):
    """Stronger than the check above and the one that actually matters: a value
    outside the subdivision table is just as unfilable. If this fails with a
    code that is NOT in VIEWPOINT_SUBDIVISIONS, someone found a new one — add
    it there with its justification, do not widen this test."""
    unresolvable = sorted(
        v for v in _distinct(table, column) if resolve_country(v) is None
    )
    assert not unresolvable, (
        f"{table}.{column} holds countries CR has no code for: {unresolvable}"
    )


def test_the_poisoned_options_can_no_longer_be_offered():
    """Deactivated rather than deleted — see the migration docstring. An active
    row in `lookup_values` is a row something can put in a dropdown, and that
    is how 'HK-CH' was stored in the first place."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT code FROM lookup_values "
            "WHERE category = 'country' AND is_active "
            "AND upper(btrim(code)) = ANY(%s)",
            (list(VIEWPOINT_SUBDIVISIONS),),
        )
        still_active = sorted(row[0] for row in cur.fetchall())
    assert not still_active, f"still offerable: {still_active}"


def test_the_parents_are_all_still_offerable():
    """Deactivating 香港 must not take 'Hong Kong' with it — the replacement has
    to be pickable, or an operator correcting an address has nothing to
    choose."""
    parents = sorted(set(VIEWPOINT_SUBDIVISIONS.values()))
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT upper(btrim(code)) FROM lookup_values "
            "WHERE category = 'country' AND is_active "
            "AND upper(btrim(code)) = ANY(%s)",
            (parents,),
        )
        active = {row[0] for row in cur.fetchall()}
    assert set(parents) <= active, f"missing parents: {sorted(set(parents) - active)}"
