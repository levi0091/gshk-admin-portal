"""Migration 020 — the shared presenter table and the per-user relaxation.

Static assertions on the migration source, as test_migration_016.py does: CI has
no Supabase, and the facts that matter here are structural.
"""
from pathlib import Path

import pytest

SRC = (
    Path(__file__).resolve().parents[2]
    / "alembic" / "versions" / "020_shared_presenter_credential.py"
).read_text(encoding="utf8")


def test_creates_the_shared_presenter_table():
    assert "CREATE TABLE tpsi_shared_presenter" in SRC


def test_shared_table_is_a_singleton():
    """One GSHK presenter identity, enforced by the schema rather than by hope.

    A boolean primary key that must be true admits exactly one row, so a second
    PUT can only ever be an update of the first."""
    assert "id boolean PRIMARY KEY DEFAULT true" in SRC
    assert "CHECK (id)" in SRC


def test_per_user_credential_becomes_signing_only():
    """A user who only SIGNS must not be forced to hold a CR login password."""
    assert "ALTER COLUMN presentor_account_id DROP NOT NULL" in SRC
    assert "ALTER COLUMN tpsi_password_enc DROP NOT NULL" in SRC


def test_seeds_the_shared_config_audit_code():
    assert "TPSI_CRED_CONFIG" in SRC


def test_downgrade_removes_everything_it_added():
    down = SRC.split("def downgrade()")[1]
    assert "DROP TABLE IF EXISTS tpsi_shared_presenter" in down
    assert "TPSI_CRED_CONFIG" in down


@pytest.mark.parametrize("column", [
    "presentor_account_id", "tpsi_password_enc", "deposit_account_no",
    "tpsi_password_expires_at", "is_test", "last_rotated_at", "updated_by",
])
def test_shared_table_carries_the_presenter_identity(column):
    body = SRC.split("CREATE TABLE tpsi_shared_presenter")[1].split(");")[0]
    assert column in body
