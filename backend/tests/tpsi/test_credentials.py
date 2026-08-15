from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from services.tpsi import config as cfg
from services.tpsi import credentials as creds
from services.tpsi.secrets import decrypt, encrypt


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
    # Assert what the name promises — the stored value is ciphertext that
    # decrypts back to the password — not that a 2-character substring is
    # absent. Fernet output is ~100 base64 chars, so "pw" turns up in it by
    # chance in 2.25% of runs (measured over 2,000 keys); that assertion was
    # reddening CI at random while proving nothing about encryption.
    assert captured["tpsi_password_enc"] != "pw"
    assert decrypt(captured["tpsi_password_enc"]) == "pw"
    assert captured["eservice_password_enc"] != "epw"
    assert decrypt(captured["eservice_password_enc"]) == "epw"
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


# ── Last-four password hint (Levi 2026-08-02) ───────────────────────────────


def test_hint_masks_all_but_the_last_four(monkeypatch):
    monkeypatch.setattr(creds, "decrypt", lambda _e: "Abcd1234567")
    assert creds._hint("enc") == "•••••••4567"


def test_hint_reveals_nothing_for_a_very_short_password(monkeypatch):
    # "the last four" of a 4-char password is the whole secret.
    monkeypatch.setattr(creds, "decrypt", lambda _e: "abcd")
    assert creds._hint("enc") == "••••"
    monkeypatch.setattr(creds, "decrypt", lambda _e: "ab")
    assert creds._hint("enc") == "••"


def test_hint_is_none_when_nothing_is_stored():
    assert creds._hint(None) is None


def test_metadata_never_returns_a_password_or_ciphertext(monkeypatch):
    monkeypatch.setattr(creds, "decrypt", lambda _e: "Abcd1234567")
    meta = creds._to_metadata({
        "presentor_account_id": "T1",
        "tpsi_password_enc": "CIPHERTEXT-TPSI",
        "eservice_password_enc": "CIPHERTEXT-ESVC",
        "eservice_user_id": "E1",
        "deposit_account_no": "N001",
        "is_test": True,
    })
    blob = repr(meta)
    assert "CIPHERTEXT" not in blob          # no ciphertext escapes
    assert "Abcd1234567" not in blob         # no plaintext escapes
    assert meta["tpsi_password_hint"] == "•••••••4567"
    assert meta["deposit_account_no"] == "N001"


# ── The routine rotation must not wipe untouched fields ─────────────────────


def test_password_only_rotation_preserves_signing_password_and_deposit_account():
    """CR forces a TPSI password change every 180 days, so this IS the common
    path. Omitted fields must be absent from the payload entirely — present-and-
    None means "clear it" to PostgREST."""
    payload = creds._payload(
        "u1", "T1", "newpw",
        creds.UNSET, creds.UNSET, creds.UNSET,
        rotated=True,
    )
    assert "eservice_password_enc" not in payload
    assert "eservice_user_id" not in payload
    assert "deposit_account_no" not in payload
    assert payload["last_rotated_at"]


def test_explicit_null_still_clears():
    payload = creds._payload(
        "u1", "T1", "pw", None, None, None, rotated=False,
    )
    assert payload["eservice_password_enc"] is None
    assert payload["deposit_account_no"] is None
