"""services/tpsi/shared_credentials.py — the ONE GSHK CR filing identity."""
from unittest.mock import MagicMock, patch

import pytest

from services.tpsi import shared_credentials as sc


def _row(**over):
    row = {
        "id": True,
        "presentor_account_id": "T260727100116D",
        "tpsi_password_enc": "enc-pw",
        "deposit_account_no": "N00061980009",
        "tpsi_password_expires_at": None,
        "is_test": True,
        "last_rotated_at": None,
    }
    row.update(over)
    return row


def test_metadata_never_returns_a_password_or_ciphertext():
    with patch.object(sc, "_read", return_value=_row()), \
         patch.object(sc, "decrypt", return_value="s3cret"):
        meta = sc.get_metadata()
    assert meta["presentor_account_id"] == "T260727100116D"
    assert "s3cret" not in str(meta)
    assert "enc-pw" not in str(meta)


def test_metadata_hint_reveals_only_the_last_four():
    with patch.object(sc, "_read", return_value=_row()), \
         patch.object(sc, "decrypt", return_value="abcdefgh"):
        meta = sc.get_metadata()
    assert meta["tpsi_password_hint"] == "••••efgh"


def test_metadata_is_none_when_nothing_is_configured():
    with patch.object(sc, "_read", return_value=None):
        assert sc.get_metadata() is None


def test_load_for_use_raises_a_lookup_error_when_unset():
    """LookupError, not a bare Exception: routers/tpsi.py::_handle maps it to a
    clean 400 ("configure the shared credential"), not a 502 blamed on CR."""
    with patch.object(sc, "_read", return_value=None):
        with pytest.raises(LookupError):
            sc.load_for_use()


def test_load_for_use_refuses_a_test_credential_in_prod():
    """The guard that stops a TEST account being used to file for real."""
    cfg = MagicMock(env="prod")
    with patch.object(sc, "_read", return_value=_row(is_test=True)), \
         patch.object(sc, "get_config", return_value=cfg):
        with pytest.raises(RuntimeError, match="TPSI_ENV"):
            sc.load_for_use()


def test_load_for_use_decrypts_the_password():
    cfg = MagicMock(env="test")
    with patch.object(sc, "_read", return_value=_row()), \
         patch.object(sc, "get_config", return_value=cfg), \
         patch.object(sc, "decrypt", return_value="s3cret"):
        cred = sc.load_for_use()
    assert cred.account_id == "T260727100116D"
    assert cred.tpsi_password == "s3cret"
    assert cred.deposit_account_no == "N00061980009"


def test_set_shared_writes_the_singleton_row_and_encrypts():
    cfg = MagicMock(env="test")
    captured = {}

    def fake_upsert(payload):
        captured.update(payload)
        return _row()

    with patch.object(sc, "_upsert", side_effect=fake_upsert), \
         patch.object(sc, "get_config", return_value=cfg), \
         patch.object(sc, "encrypt", return_value="enc!"), \
         patch.object(sc, "decrypt", return_value="s3cret"):
        sc.set_shared(
            presentor_account_id="ACCT",
            tpsi_password="s3cret",
            deposit_account_no="N001",
            updated_by="u1",
        )
    assert captured["id"] is True
    assert captured["tpsi_password_enc"] == "enc!"
    assert "tpsi_password" not in captured
    assert captured["updated_by"] == "u1"


def test_a_password_only_rotation_leaves_the_deposit_account_untouched():
    """CR forces a password change every 180 days, so rotating the password
    alone is the ROUTINE case. PostgREST only touches columns present in the
    payload, so omitting the key is what preserves the stored value."""
    captured = {}

    def fake_upsert(payload):
        captured.update(payload)
        return _row()

    with patch.object(sc, "_upsert", side_effect=fake_upsert), \
         patch.object(sc, "get_config", return_value=MagicMock(env="test")), \
         patch.object(sc, "encrypt", return_value="enc!"), \
         patch.object(sc, "decrypt", return_value="s3cret"):
        sc.set_shared(
            presentor_account_id="ACCT",
            tpsi_password="new-pw",
            updated_by="u1",
            rotated=True,
        )
    assert "deposit_account_no" not in captured
    assert captured["last_rotated_at"] is not None
