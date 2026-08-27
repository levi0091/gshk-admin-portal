import os
import threading
import time

import httpx
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()


class _RetryReadsTransport(httpx.HTTPTransport):
    """Retry a dropped connection, but only for reads.

    Supabase sits behind Cloudflare, which closes a connection whenever it
    likes. When that lands mid-request httpx raises `RemoteProtocolError:
    Server disconnected`, and because it happens between the request going out
    and any response coming back, there is nothing for the caller to do with it
    — the portal simply shows "Failed to fetch" on a page that would have
    loaded a second later. Measured on DEV during the 2026-08-27 UI run: a
    company profile that had loaded minutes earlier.

    GET and HEAD ONLY, and that restriction is the whole point. A disconnect
    gives no evidence about whether the server processed the request, so
    retrying a POST can file a second NAR1 or send a client a second email.
    `httpx.HTTPTransport(retries=...)` is not enough on its own: it covers
    connect failures, not a disconnect after the request was written.
    """

    _RETRY_ON = (httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError)
    _ATTEMPTS = 3
    _BACKOFF = 0.25

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.method not in ("GET", "HEAD"):
            return super().handle_request(request)
        last: Exception | None = None
        for attempt in range(self._ATTEMPTS):
            try:
                return super().handle_request(request)
            except self._RETRY_ON as exc:
                last = exc
                if attempt < self._ATTEMPTS - 1:
                    time.sleep(self._BACKOFF * (2 ** attempt))
        raise last  # type: ignore[misc]


def _install_read_retries(client: Client) -> None:
    """Swap the transport under the sub-clients that talk to PostgREST.

    Done here rather than by passing options to create_client() because
    supabase-py builds those httpx clients itself and exposes no hook for the
    transport.
    """
    for sub in ("postgrest", "storage", "functions"):
        session = getattr(getattr(client, sub, None), "session", None)
        transport = getattr(session, "_transport", None)
        if isinstance(transport, httpx.HTTPTransport) and not isinstance(
            transport, _RetryReadsTransport
        ):
            session._transport = _RetryReadsTransport()

_client: Client | None = None
# Guards BOTH the construction of the singleton and the first touch of the
# lazily-built sub-clients hanging off it. See get_supabase().
_lock = threading.Lock()


def get_supabase() -> Client:
    """The one shared Supabase client, constructed exactly once.

    The lock is not decoration. supabase-py builds `postgrest`, `storage` and
    `functions` lazily on first property access and does it WITHOUT any
    synchronisation:

        @property
        def postgrest(self):
            if self._postgrest is None:
                self._postgrest = self._init_postgrest_client(...)
            return self._postgrest

    `nar1_source.load_entity_graph` issues five independent reads through
    `asyncio.gather(asyncio.to_thread(...))`. When that is the first use of the
    client -- which it is in any standalone script, and was in the BE-1 smoke
    runs -- five threads read `self._postgrest is None` at once, five
    `SyncPostgrestClient` objects are built, each with its own `httpx.Client`
    connection pool, and four are dropped unreferenced with their sockets open.
    That is the shape of the instability recorded against this loader:
    `httpx.RemoteProtocolError: Server disconnected` and a Cloudflare 400 from
    Supabase's edge.

    Touching the three properties here, inside the lock, means no caller can
    ever observe a half-built client. After that the object is read-only shared
    state and `httpx.Client`'s own pool (httpcore guards it with a ThreadLock)
    is safe across threads, so the client stays a singleton rather than
    becoming per-thread -- one connection pool, not one per worker thread.
    """
    global _client
    if _client is None:
        with _lock:
            # Re-checked inside the lock: two threads can both pass the
            # unlocked test above.
            if _client is None:
                url = os.environ.get("SUPABASE_URL")
                key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
                if not url or not key:
                    raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")
                client = create_client(url, key)
                # Force the lazy sub-clients while we still hold the lock.
                # None of these performs I/O; they only construct the httpx
                # clients that the properties would otherwise race to build.
                client.postgrest
                client.storage
                client.functions
                # Still inside the lock: the transport swap must be finished
                # before any other thread can reach the sub-clients.
                _install_read_retries(client)
                # Published only once it is complete, so a reader that skipped
                # the lock never sees a partially initialised client.
                _client = client
    return _client
