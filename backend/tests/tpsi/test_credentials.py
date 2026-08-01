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

    # `_read` is also patched here: set_credential's return value flows through
    # get_metadata -> _read, and an unmocked _read would hit the real Supabase
    # client (db/supabase.py loads live creds from .env) — tests must not
    # touch the network. Only `_upsert`'s captured payload is under test.
    with patch.object(creds, "_upsert", side_effect=fake_upsert), \
         patch.object(creds, "_read", return_value=None):
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
    with patch.object(creds, "_upsert", side_effect=lambda p: captured.update(p)), \
         patch.object(creds, "_read", return_value=None):
        creds.set_credential(
            user_id="user-1", presentor_account_id="ACCT",
            tpsi_password="pw", eservice_user_id=None, eservice_password=None,
        )
    assert captured["eservice_password_enc"] is None
