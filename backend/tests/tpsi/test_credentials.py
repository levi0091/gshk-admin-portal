from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from services.tpsi import config as cfg
from services.tpsi import credentials as creds
from services.tpsi.secrets import encrypt


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path, make_pem):
    key = tmp_path / "k.pem"
    key.write_text(make_pem())
    monkeypatch.setenv("TPSI_ENV", "test")
    monkeypatch.setenv("TPSI_BASE_URL", "https://apitest.cr.gov.hk/ICRIS3EF")
    monkeypatch.setenv("TPSI_TLS_VERIFY", "false")
    monkeypatch.setenv("TPSI_CRED_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("TPSI_CR_PUBLIC_KEY_PATH", str(key))
    cfg.get_config.cache_clear()
    yield
    cfg.get_config.cache_clear()


def test_metadata_never_exposes_a_password():
    row = {
        "presentor_account_id": "T260727100116D",
        "tpsi_password_enc": encrypt("pw"),
        "eservice_password_enc": encrypt("epw"),
        "eservice_user_id": "T260727100116D",
        "tpsi_password_expires_at": "2026-12-31T00:00:00+00:00",
        "is_test": True,
        "last_rotated_at": None,
    }
    with patch.object(creds, "_read", return_value=row):
        meta = creds.get_metadata("user-1")

    flat = str(meta)
    assert "pw" not in flat.replace("presentor", "")  # no plaintext
    assert "_enc" not in flat
    assert meta["presentor_account_id"] == "T260727100116D"
    assert meta["has_eservice_password"] is True


def test_metadata_reports_absent_signing_password():
    row = {
        "presentor_account_id": "A", "tpsi_password_enc": encrypt("pw"),
        "eservice_password_enc": None, "eservice_user_id": None,
        "tpsi_password_expires_at": None, "is_test": True, "last_rotated_at": None,
    }
    with patch.object(creds, "_read", return_value=row):
        assert creds.get_metadata("user-1")["has_eservice_password"] is False


def test_load_for_use_decrypts_both_passwords():
    row = {
        "presentor_account_id": "ACCT", "tpsi_password_enc": encrypt("pw"),
        "eservice_password_enc": encrypt("epw"), "eservice_user_id": "EID",
        "tpsi_password_expires_at": None, "is_test": True, "last_rotated_at": None,
    }
    with patch.object(creds, "_read", return_value=row):
        c = creds.load_for_use("user-1")
    assert c.tpsi_password == "pw"
    assert c.eservice_password == "epw"
    assert c.eservice_user_id == "EID"


def test_is_test_mismatch_refuses_before_any_call_reaches_cr():
    """A restored dump pointed at the wrong environment must fail loudly, not
    file a real form against production with test credentials."""
    row = {
        "presentor_account_id": "ACCT", "tpsi_password_enc": encrypt("pw"),
        "eservice_password_enc": None, "eservice_user_id": None,
        "tpsi_password_expires_at": None, "is_test": False, "last_rotated_at": None,
    }
    with patch.object(creds, "_read", return_value=row):
        with pytest.raises(RuntimeError, match="is_test"):
            creds.load_for_use("user-1")


def test_missing_credential_raises():
    with patch.object(creds, "_read", return_value=None):
        with pytest.raises(LookupError):
            creds.load_for_use("user-1")


def test_set_credential_stores_ciphertext_not_plaintext():
    captured = {}

    def fake_upsert(payload):
        captured.update(payload)
        return payload

    # No `_read` patch needed: set_credential now builds its return value
    # from the row `_upsert` already returned (_to_metadata), not a second
    # SELECT — so the only Supabase-facing call to mock is `_upsert` itself.
    with patch.object(creds, "_upsert", side_effect=fake_upsert):
        creds.set_credential(
            user_id="user-1", presentor_account_id="ACCT",
            tpsi_password="pw", eservice_user_id="EID", eservice_password="epw",
        )
    assert "pw" not in str(captured.get("tpsi_password_enc"))
    assert "epw" not in str(captured.get("eservice_password_enc"))
    assert captured["is_test"] is True


def test_set_credential_without_eservice_password_stores_null():
    """Storing the signing password is optional — a director signs live."""
    captured = {}

    def fake_upsert(payload):
        captured.update(payload)
        return payload

    with patch.object(creds, "_upsert", side_effect=fake_upsert):
        creds.set_credential(
            user_id="user-1", presentor_account_id="ACCT",
            tpsi_password="pw", eservice_user_id=None, eservice_password=None,
        )
    assert captured["eservice_password_enc"] is None
    assert captured["eservice_user_id"] is None


def test_set_credential_omitting_eservice_args_also_stores_null():
    """A fresh set (first-time — nothing stored yet) with the eservice
    arguments left at their default omits those keys from the payload
    entirely. On INSERT that's equivalent to NULL (the columns have no other
    default), so a brand-new credential with no signing password supplied
    still ends up with has_eservice_password=False — matching the explicit-
    None case above, just reached by not mentioning the fields at all."""
    captured = {}

    def fake_upsert(payload):
        captured.update(payload)
        return payload

    with patch.object(creds, "_upsert", side_effect=fake_upsert):
        creds.set_credential(
            user_id="user-1", presentor_account_id="ACCT", tpsi_password="pw",
        )
    assert "eservice_password_enc" not in captured
    assert "eservice_user_id" not in captured


def test_rotate_omitting_eservice_args_preserves_stored_signing_password():
    """The bug this guards against: CR forces a TPSI password change every
    180 days, so `rotate_credential(user_id=..., presentor_account_id=...,
    tpsi_password=new_pw)` — omitting the signing password — is the routine
    case, not an edge case. It must NOT wipe a previously stored
    eservice_password_enc. Omitting the keys from the payload (rather than
    sending them as None) is what makes PostgREST leave the stored value
    untouched, the same mechanism tpsi_password_expires_at already relies on
    to survive a rotation."""
    captured = {}

    def fake_upsert(payload):
        captured.update(payload)
        return payload

    with patch.object(creds, "_upsert", side_effect=fake_upsert):
        creds.rotate_credential(
            user_id="user-1", presentor_account_id="ACCT", tpsi_password="new-pw",
        )
    assert "eservice_password_enc" not in captured
    assert "eservice_user_id" not in captured
    assert "tpsi_password_enc" in captured
    assert "last_rotated_at" in captured


def test_rotate_with_explicit_none_clears_the_signing_password():
    """Distinct from the omission case above: passing None explicitly is a
    deliberate clear, and must still reach the payload as NULL."""
    captured = {}

    def fake_upsert(payload):
        captured.update(payload)
        return payload

    with patch.object(creds, "_upsert", side_effect=fake_upsert):
        creds.rotate_credential(
            user_id="user-1", presentor_account_id="ACCT", tpsi_password="new-pw",
            eservice_user_id=None, eservice_password=None,
        )
    assert captured["eservice_password_enc"] is None
    assert captured["eservice_user_id"] is None
