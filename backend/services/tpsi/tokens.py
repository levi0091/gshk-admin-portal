"""One live TPSI token per CR account, shared across workers and replicas.

TPSI issues ONE token per account at a time. An in-process cache is correct only
while the API runs as a single worker on a single replica, and it fails silently
when that stops being true: worker B logs in, worker A's token is invalidated,
and A gets a 401 — possibly mid-submit on a chargeable call. So the token lives
in Postgres behind an advisory lock.
"""
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import urlsplit

import psycopg2

from db.supabase import get_supabase
from services.tpsi.config import get_config
from services.tpsi.secrets import decrypt, encrypt

# Never hand out a token that could expire mid-request.
REFRESH_MARGIN_SECONDS = 60

#: Supabase's per-project DIRECT host. It publishes AAAA records and no A
#: record, so a deployment with no IPv6 route cannot open a socket to it at all.
#: The session-mode pooler is the reachable alternative, and the one every other
#: psycopg2 caller in this repo (alembic, the ETL) is already pointed at by hand.
_DIRECT_HOST = re.compile(r"^db\.[a-z0-9]+\.supabase\.co$", re.IGNORECASE)


def _host_of(dsn: str) -> str:
    """The host in a DSN, and never anything else in it.

    Parsing can fail on an awkward password; the caller is already reporting a
    failure and must not be turned into a second, different one.
    """
    try:
        return urlsplit(dsn).hostname or "the configured database host"
    except ValueError:
        return "the configured database host"


def _connect_for_lock(dsn: str):
    """Open the lock's connection, or refuse in a sentence an operator can act on.

    PROD, 2026-09-16, on the first live filing against the real CR portal:
    DATABASE_URL held the direct Supabase host, Railway has no IPv6 route, and
    psycopg2's OperationalError travelled all the way out. `routers.tpsi._handle`
    classifies TpsiError and RuntimeError and re-raises anything else, so this
    surfaced as a bare 500 whose body was the generic "The server could not
    complete this request. Nothing was saved." -- which reads as a problem with
    the return being filed. It was not: CR was never contacted, and the return
    was fine. The operator had no way to tell those two apart.

    A RuntimeError instead, because _handle already maps that to a 502 CARRYING
    ITS MESSAGE. The driver's own text is kept as the __cause__, so the Railway
    log still has every detail; it is deliberately NOT interpolated into the
    message, which is rendered in a browser and must never carry a DSN.
    """
    try:
        return psycopg2.connect(dsn)
    except psycopg2.OperationalError as exc:
        host = _host_of(dsn)
        detail = (
            "The Postgres advisory lock that serialises TPSI token acquisition "
            f"could not be taken: opening a connection to {host} failed. No "
            "token was acquired, and nothing was sent to the Companies Registry."
        )
        if _DIRECT_HOST.match(host):
            detail += (
                f" {host} is Supabase's direct host, which publishes IPv6"
                " addresses only -- a Railway deployment has no route to it."
                " Point DATABASE_URL at the session-mode pooler instead:"
                " postgres.<project-ref>@aws-<n>-<region>.pooler.supabase.com:5432."
            )
        raise RuntimeError(detail) from exc


@dataclass(frozen=True)
class AuthResult:
    access_token: str
    expires_in: int
    password_expires_in: str | None


def _read_row(account_id: str):
    rows = (
        get_supabase()
        .table("tpsi_tokens")
        .select("access_token_enc, expires_at")
        .eq("presentor_account_id", account_id)
        .execute()
        .data
    )
    if not rows:
        return None
    row = rows[0]
    return row["access_token_enc"], datetime.fromisoformat(row["expires_at"])


def _write_row(account_id: str, token_enc: str, expires_at: datetime) -> None:
    get_supabase().table("tpsi_tokens").upsert(
        {
            "presentor_account_id": account_id,
            "access_token_enc": token_enc,
            "expires_at": expires_at.isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="presentor_account_id",
    ).execute()


def _delete_row(account_id: str) -> None:
    get_supabase().table("tpsi_tokens").delete().eq(
        "presentor_account_id", account_id
    ).execute()


def _with_lock(account_id: str, fn: Callable):
    """Serialise acquisition for one account across every worker.

    pg_advisory_xact_lock is released when the transaction ends, so a crashed
    worker cannot leave the lock held.
    """
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        # No direct connection configured. Without the lock, two workers can
        # both log in and stomp each other's token — surfacing as a 401
        # part-way through a chargeable, irreversible submission. In
        # production that risk is never acceptable, so fail fast instead of
        # proceeding unlocked.
        #
        # get_config() needs TPSI_ENV etc. to already be configured; a bare
        # unit-test process that hasn't set up TPSI config at all must not
        # explode here just from asking "are we in prod?" — treat a raising
        # get_config() as "not prod" and fall through to the warned,
        # unlocked path below, same as before.
        try:
            is_prod = get_config().env == "prod"
        except Exception:
            is_prod = False

        if is_prod:
            raise RuntimeError(
                "DATABASE_URL is not set: the Postgres advisory lock is "
                "unavailable, so TPSI token acquisition cannot be "
                "serialised across workers/replicas. Refusing to acquire a "
                "token unlocked in production."
            )

        # Non-prod (or config not even loaded, e.g. plain unit tests):
        # single-process fallback only, loudly flagged so it's never mistaken
        # for the locked path if seen in a real deployment's logs.
        print(
            "tpsi.tokens: DATABASE_URL not set — acquiring token WITHOUT the "
            "advisory lock. Safe for single-process tests only; unsafe with "
            "more than one worker/replica.",
            file=sys.stderr,
        )
        return fn()
    conn = _connect_for_lock(dsn)
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (account_id,))
            return fn()
    finally:
        conn.close()


def acquire_token(account_id: str, authenticate: Callable[[], AuthResult]) -> str:
    """Return a valid access token, reusing the stored one when it has life left.

    `authenticate` performs exactly one login attempt (see the auth-failure rule
    in the plan's Global Constraints) and is only called when no usable token is
    stored.
    """

    def _acquire() -> str:
        row = _read_row(account_id)
        if row:
            token_enc, expires_at = row
            margin = datetime.now(timezone.utc) + timedelta(
                seconds=REFRESH_MARGIN_SECONDS
            )
            if expires_at > margin:
                return decrypt(token_enc)

        result = authenticate()
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=result.expires_in)
        _write_row(account_id, encrypt(result.access_token), expires_at)
        return result.access_token

    return _with_lock(account_id, _acquire)


def invalidate(account_id: str) -> None:
    """Drop the stored token — called after a 401 or an explicit logout."""
    _delete_row(account_id)
