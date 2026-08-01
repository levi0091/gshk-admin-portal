"""One live TPSI token per CR account, shared across workers and replicas.

TPSI issues ONE token per account at a time. An in-process cache is correct only
while the API runs as a single worker on a single replica, and it fails silently
when that stops being true: worker B logs in, worker A's token is invalidated,
and A gets a 401 — possibly mid-submit on a chargeable call. So the token lives
in Postgres behind an advisory lock.
"""
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import psycopg2

from db.supabase import get_supabase
from services.tpsi.secrets import decrypt, encrypt

# Never hand out a token that could expire mid-request.
REFRESH_MARGIN_SECONDS = 60


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
        # No direct connection configured (e.g. a unit-test environment).
        # Correctness under concurrency needs the lock, so this is a
        # single-process fallback only. In production DATABASE_URL is
        # mandatory (set alongside SUPABASE_URL) — this branch should never
        # be reached there, so a loud warning beats a silent skip if it is.
        print(
            "tpsi.tokens: DATABASE_URL not set — acquiring token WITHOUT the "
            "advisory lock. Safe for single-process tests only; unsafe with "
            "more than one worker/replica.",
            file=sys.stderr,
        )
        return fn()
    conn = psycopg2.connect(dsn)
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
