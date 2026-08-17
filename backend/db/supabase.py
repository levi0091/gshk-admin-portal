import os
import threading

from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

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
                # Published only once it is complete, so a reader that skipped
                # the lock never sees a partially initialised client.
                _client = client
    return _client
