import base64

import httpx
import pytest
from cryptography.fernet import Fernet

from services.tpsi import client as cl
from services.tpsi import config as cfg
from services.tpsi import errors

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


def _client(handler, account="T260727100116D", password="pw"):
    transport = httpx.MockTransport(handler)
    c = cl.TpsiClient(account, password)
    c._transport = transport
    return c


def test_auth_header_is_base64_of_account_colon_sha256_password():
    """Verified against the spec's own example: the Basic value decodes to
    CAMILLE:5fef526bd3b7b26001f826f469250cb954299a0169a46d11ac37a263a9ab6ab5"""
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["Authorization"]
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"access_token": "T", "expires_in": 1800})

    _client(handler, account="CAMILLE", password="pw").authenticate()

    scheme, value = seen["auth"].split(" ", 1)
    assert scheme == "Basic"
    decoded = base64.b64decode(value).decode()
    user, digest = decoded.split(":", 1)
    assert user == "CAMILLE"
    assert len(digest) == 64 and digest == digest.lower()
    assert "scope=tpsi" in seen["url"]
    assert "/oauth/token.do" in seen["url"]


def test_authenticate_returns_expiry_metadata():
    def handler(request):
        return httpx.Response(200, json={
            "access_token": "TOK", "expires_in": 1800,
            "password_expires_in": "2026-12-31 23:59:59",
        })

    result = _client(handler).authenticate()
    assert result.access_token == "TOK"
    assert result.expires_in == 1800
    assert result.password_expires_in == "2026-12-31 23:59:59"


def test_401_raises_auth_error_and_is_never_retried():
    """CR locks accounts after repeated failures. Exactly one attempt."""
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401, text="bad credentials")

    with pytest.raises(errors.TpsiAuthError):
        _client(handler).authenticate()
    assert len(calls) == 1


def test_expired_password_raises_its_own_error():
    def handler(request):
        return httpx.Response(401, text="TPSI password expired")

    with pytest.raises(errors.TpsiPasswordExpiredError):
        _client(handler).authenticate()


def test_post_soap_sends_bearer_token_and_returns_body():
    seen = {}

    def handler(request):
        if "token.do" in str(request.url):
            return httpx.Response(200, json={"access_token": "TOK", "expires_in": 1800})
        seen["auth"] = request.headers["Authorization"]
        seen["ctype"] = request.headers["Content-Type"]
        return httpx.Response(200, content=b"<ok/>")

    c = _client(handler)
    c._token_cache = "TOK"
    body = c.post_soap("/tpsi/enquireDepositAccount", "<x/>")
    assert body == b"<ok/>"
    assert seen["auth"] == "Bearer TOK"
    assert "xml" in seen["ctype"]


def test_post_soap_reauthenticates_once_on_401_then_gives_up():
    """The ONE permitted retry: a cached token rejected as expired. It must not
    recurse — two 401s in a row is a failure, not a loop."""
    calls = {"auth": 0, "post": 0}

    def handler(request):
        if "token.do" in str(request.url):
            calls["auth"] += 1
            return httpx.Response(200, json={"access_token": "T2", "expires_in": 1800})
        calls["post"] += 1
        return httpx.Response(401, text="token expired")

    c = _client(handler)
    c._token_cache = "STALE"
    with pytest.raises(errors.TpsiAuthError):
        c.post_soap("/tpsi/enquireDepositAccount", "<x/>")
    assert calls["post"] == 2   # original + exactly one retry
    assert calls["auth"] == 1


def test_network_failure_raises_unavailable():
    def handler(request):
        raise httpx.ConnectError("no route to host")

    c = _client(handler)
    c._token_cache = "TOK"
    with pytest.raises(errors.TpsiUnavailableError):
        c.post_soap("/tpsi/enquireDepositAccount", "<x/>")


def test_tls_verify_follows_config(monkeypatch):
    assert cfg.get_config().tls_verify is False
    monkeypatch.setenv("TPSI_ENV", "prod")
    monkeypatch.setenv("TPSI_BASE_URL", "https://www.e-services.cr.gov.hk/ICRIS3EF")
    cfg.get_config.cache_clear()
    assert cfg.get_config().tls_verify is True
