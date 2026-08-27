"""db/supabase.py — the read-only retry transport.

Supabase sits behind Cloudflare, which closes connections when it likes. When
that lands mid-request httpx raises `RemoteProtocolError: Server disconnected`
and the portal shows "Failed to fetch" on a page that would have loaded a
moment later. Measured on DEV during the 2026-08-27 browser run.

The restriction to GET/HEAD is the part that matters and is asserted hardest: a
disconnect gives NO evidence about whether the server processed the request, so
retrying a POST can file a second NAR1 or send a client a second email.
"""
from unittest.mock import patch

import httpx
import pytest

from db.supabase import _RetryReadsTransport


def _request(method: str) -> httpx.Request:
    return httpx.Request(method, "https://example.supabase.co/rest/v1/entities")


def _ok() -> httpx.Response:
    return httpx.Response(200, content=b"[]")


def test_a_get_is_retried_after_a_dropped_connection():
    calls = []

    def flaky(self, request):
        calls.append(request.method)
        if len(calls) == 1:
            raise httpx.RemoteProtocolError("Server disconnected")
        return _ok()

    with patch.object(httpx.HTTPTransport, "handle_request", flaky):
        with patch("time.sleep"):
            response = _RetryReadsTransport().handle_request(_request("GET"))

    assert response.status_code == 200
    assert calls == ["GET", "GET"]


@pytest.mark.parametrize("method", ["POST", "PATCH", "PUT", "DELETE"])
def test_a_write_is_never_retried(method):
    """A retried write can file a second statutory return. This is the single
    most important assertion in this file."""
    calls = []

    def always_drops(self, request):
        calls.append(request.method)
        raise httpx.RemoteProtocolError("Server disconnected")

    with patch.object(httpx.HTTPTransport, "handle_request", always_drops):
        with patch("time.sleep"):
            with pytest.raises(httpx.RemoteProtocolError):
                _RetryReadsTransport().handle_request(_request(method))

    assert calls == [method], "a write must be attempted exactly once"


def test_a_read_gives_up_and_raises_rather_than_retrying_forever():
    calls = []

    def always_drops(self, request):
        calls.append(1)
        raise httpx.RemoteProtocolError("Server disconnected")

    with patch.object(httpx.HTTPTransport, "handle_request", always_drops):
        with patch("time.sleep"):
            with pytest.raises(httpx.RemoteProtocolError):
                _RetryReadsTransport().handle_request(_request("GET"))

    assert len(calls) == _RetryReadsTransport._ATTEMPTS


def test_an_http_error_status_is_not_a_retry():
    """A 500 from PostgREST is an answer, not a dropped connection. Retrying it
    turns one bad query into three."""
    calls = []

    def five_hundred(self, request):
        calls.append(1)
        return httpx.Response(500, content=b"{}")

    with patch.object(httpx.HTTPTransport, "handle_request", five_hundred):
        response = _RetryReadsTransport().handle_request(_request("GET"))

    assert response.status_code == 500
    assert len(calls) == 1


def test_the_retry_transport_is_installed_on_the_shared_client():
    from db import supabase as mod

    class _Session:
        def __init__(self):
            self._transport = httpx.HTTPTransport()

    class _Client:
        def __init__(self):
            self.postgrest = type("S", (), {"session": _Session()})()
            self.storage = type("S", (), {"session": _Session()})()
            self.functions = type("S", (), {"session": _Session()})()

    client = _Client()
    mod._install_read_retries(client)

    for sub in ("postgrest", "storage", "functions"):
        transport = getattr(client, sub).session._transport
        assert isinstance(transport, _RetryReadsTransport), sub


def test_installing_twice_does_not_nest_transports():
    from db import supabase as mod

    class _Session:
        def __init__(self):
            self._transport = httpx.HTTPTransport()

    client = type("C", (), {})()
    client.postgrest = type("S", (), {"session": _Session()})()
    client.storage = None
    client.functions = None

    mod._install_read_retries(client)
    first = client.postgrest.session._transport
    mod._install_read_retries(client)

    assert client.postgrest.session._transport is first
