from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from services.tpsi import config as cfg
from services.tpsi import tokens

# make_pem is a shared fixture from tests/tpsi/conftest.py.


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


def _auth(token="TOK", expires_in=1800):
    return lambda: tokens.AuthResult(
        access_token=token, expires_in=expires_in, password_expires_in=None
    )


def test_fresh_acquisition_calls_authenticate_and_stores(monkeypatch):
    rows = {}
    monkeypatch.setattr(tokens, "_read_row", lambda a: rows.get(a))
    monkeypatch.setattr(tokens, "_write_row", lambda a, t, e: rows.update({a: (t, e)}))
    monkeypatch.setattr(tokens, "_with_lock", lambda a, fn: fn())

    calls = []

    def auth():
        calls.append(1)
        return tokens.AuthResult("TOK", 1800, None)

    assert tokens.acquire_token("ACCT", auth) == "TOK"
    assert len(calls) == 1
    assert "ACCT" in rows


def test_valid_cached_token_is_reused_without_authenticating(monkeypatch):
    from services.tpsi.secrets import encrypt

    future = datetime.now(timezone.utc) + timedelta(minutes=20)
    monkeypatch.setattr(tokens, "_read_row", lambda a: (encrypt("CACHED"), future))
    monkeypatch.setattr(tokens, "_write_row", lambda a, t, e: None)
    monkeypatch.setattr(tokens, "_with_lock", lambda a, fn: fn())

    calls = []

    def auth():
        calls.append(1)
        return tokens.AuthResult("NEW", 1800, None)

    assert tokens.acquire_token("ACCT", auth) == "CACHED"
    assert calls == []


def test_token_expiring_within_the_margin_is_not_handed_out(monkeypatch):
    """A token with 30s left would expire mid-request. Re-acquire instead."""
    from services.tpsi.secrets import encrypt

    nearly = datetime.now(timezone.utc) + timedelta(seconds=30)
    monkeypatch.setattr(tokens, "_read_row", lambda a: (encrypt("OLD"), nearly))
    monkeypatch.setattr(tokens, "_write_row", lambda a, t, e: None)
    monkeypatch.setattr(tokens, "_with_lock", lambda a, fn: fn())

    assert tokens.acquire_token("ACCT", _auth("NEW")) == "NEW"


def test_acquisition_happens_inside_the_advisory_lock(monkeypatch):
    """One token per account: two workers must not both log in."""
    order = []
    monkeypatch.setattr(tokens, "_read_row", lambda a: None)
    monkeypatch.setattr(tokens, "_write_row", lambda a, t, e: order.append("write"))

    def fake_lock(account, fn):
        order.append("lock")
        result = fn()
        order.append("unlock")
        return result

    monkeypatch.setattr(tokens, "_with_lock", fake_lock)

    def auth():
        order.append("auth")
        return tokens.AuthResult("TOK", 1800, None)

    tokens.acquire_token("ACCT", auth)
    assert order == ["lock", "auth", "write", "unlock"]


def test_invalidate_deletes_the_row(monkeypatch):
    deleted = []
    monkeypatch.setattr(tokens, "_delete_row", lambda a: deleted.append(a))
    tokens.invalidate("ACCT")
    assert deleted == ["ACCT"]


def test_stored_token_is_encrypted_not_plaintext(monkeypatch):
    captured = {}
    monkeypatch.setattr(tokens, "_read_row", lambda a: None)
    monkeypatch.setattr(
        tokens, "_write_row", lambda a, t, e: captured.update({"enc": t})
    )
    monkeypatch.setattr(tokens, "_with_lock", lambda a, fn: fn())
    tokens.acquire_token("ACCT", _auth("SECRET-JWT"))
    assert "SECRET-JWT" not in captured["enc"]
