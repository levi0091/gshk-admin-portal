"""db/supabase.py — the one shared Supabase client, built exactly once.

Written for a real, observed failure. `nar1_source.load_entity_graph` issues
five independent reads through `asyncio.gather(asyncio.to_thread(...))`, and in
a standalone script that call is the FIRST use of the client. supabase-py
initialises `Client.postgrest` lazily and WITHOUT a lock:

    @property
    def postgrest(self):
        if self._postgrest is None:
            self._postgrest = self._init_postgrest_client(...)
        return self._postgrest

Five threads hitting that cold means five `SyncPostgrestClient` objects, five
`httpx.Client` connection pools, and four of them dropped on the floor with
their sockets open. That is the shape of the errors the controller saw:
`httpx.RemoteProtocolError: Server disconnected` and a Cloudflare 400.

In the API path the auth middleware always warms the client on the request
thread before a handler runs, which is why this never showed up there.

These tests do not construct a real client — `create_client` is patched.
"""
import threading
from unittest.mock import MagicMock, patch

import pytest

import db.supabase as dbs


@pytest.fixture(autouse=True)
def _fresh_client_singleton(monkeypatch):
    monkeypatch.setattr(dbs, "_client", None)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "a.b.c")
    yield
    dbs._client = None


def test_concurrent_first_use_builds_exactly_one_client():
    made = []

    def slow_create(url, key):
        # Widen the window the real race lives in: construction is not
        # instantaneous, and every thread must still end up with one object.
        threading.Event().wait(0.01)
        client = MagicMock(name=f"client-{len(made)}")
        made.append(client)
        return client

    seen = []
    with patch.object(dbs, "create_client", side_effect=slow_create):
        threads = [threading.Thread(target=lambda: seen.append(dbs.get_supabase()))
                   for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert len(made) == 1, "supabase client was constructed more than once"
    assert all(c is made[0] for c in seen)


def test_the_lazy_sub_clients_are_warmed_before_the_client_is_published():
    """The race is not in `create_client`, it is in the properties it leaves
    unset. Touching them under the same lock means no thread can ever observe a
    client with `_postgrest is None`."""
    warmed = {}
    client = MagicMock()
    type(client).postgrest = property(
        lambda self: warmed.setdefault("postgrest", True))
    type(client).storage = property(
        lambda self: warmed.setdefault("storage", True))
    type(client).functions = property(
        lambda self: warmed.setdefault("functions", True))

    with patch.object(dbs, "create_client", return_value=client):
        dbs.get_supabase()

    assert warmed == {"postgrest": True, "storage": True, "functions": True}


def test_missing_credentials_still_raise_and_do_not_cache_a_broken_client(
    monkeypatch,
):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    with pytest.raises(RuntimeError):
        dbs.get_supabase()
    assert dbs._client is None
