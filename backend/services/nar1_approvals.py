"""Client self-approval tokens (spec §5, migration 030).

One token per director, per verification request. The token is 256 bits from
`secrets.token_urlsafe`; the DATABASE HOLDS ONLY ITS SHA-256. A read of this
table — a backup, a support query, an ETL dump — is therefore not enough to
approve anybody's annual return.

Comparison is constant-time (`hmac.compare_digest`) even though the lookup is by
unique index. The index means the query itself is O(1) and does not leak by
timing; the explicit compare is the belt for the day someone replaces the
lookup with a scan.

FIRST APPROVAL WINS. GSHK receives ONE approval for a return, not one per
director. The first valid press records it and every other token for that case
becomes `superseded`, which is also what a verification restart does to the
whole outstanding set — see `supersede_outstanding` and its docstring.

WHAT THIS MODULE DELIBERATELY CANNOT DO. There is no reject. A director who
disagrees is told to reply to the email, which is the action the message itself
asks for and which staff already record through
`POST /cases/{id}/verification/response`. A rejection has to carry WHAT is
wrong, and a free-text box on an unauthenticated public route is the one thing
§5's hardening exists to avoid.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from db.supabase import get_supabase

_TABLE = "nar1_client_approvals"

#: The window the client has, and the deadline the email prints. Re-sending
#: verification issues fresh tokens and restarts this clock, so the date in the
#: newest email is always the one the auto-approval job reads.
APPROVAL_WINDOW_DAYS = 14

#: 32 bytes -> 43 URL-safe characters. Long enough that guessing is not a
#: threat model, short enough to survive a mail client's line wrapping.
_TOKEN_BYTES = 32

OUTCOME_APPROVED = "approved"
OUTCOME_SUPERSEDED = "superseded"

#: How a case came to be approved. Written to `nar1_cases.client_approval_source`
#: and rendered verbatim-ish by the workflow screen and the audit trail — a bare
#: "Approved" is never shown, because a director who never answered must not
#: appear to have agreed to anything.
SOURCE_SELF_SERVICE = "self_service"
SOURCE_STAFF_RELAY = "staff_relay"
SOURCE_SYSTEM_TIMEOUT = "system_timeout"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(token: str) -> str:
    """SHA-256 hex of the token, which is the only form ever stored."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def issue(*, case_id: str, recipients: list[dict],
          sent_at: datetime | None = None) -> list[dict]:
    """One fresh token per recipient. Returns the PLAINTEXT tokens.

    The plaintext is returned to the caller once, to put in that person's email,
    and is never persisted. `recipients` is
    `[{"email": str, "person_id": str|None, "name": str|None}, ...]`.

    Any token still outstanding for this case is superseded first: re-sending
    verification means the previous message's document is no longer the one
    being asked about, and a director holding the older mail must not be able to
    approve it.
    """
    sent = sent_at or _now()
    expires = sent + timedelta(days=APPROVAL_WINDOW_DAYS)

    supersede_outstanding(case_id)

    issued = []
    rows = []
    for recipient in recipients:
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        rows.append({
            "nar1_case_id": case_id,
            "person_id": recipient.get("person_id"),
            "recipient_email": recipient["email"],
            "recipient_name": recipient.get("name"),
            "token_hash": hash_token(token),
            "sent_at": sent.isoformat(),
            "expires_at": expires.isoformat(),
        })
        issued.append({**recipient, "token": token, "expires_at": expires})

    if rows:
        get_supabase().table(_TABLE).insert(rows).execute()
    return issued


def supersede_outstanding(case_id: str, *, exclude_id: str | None = None) -> int:
    """Invalidate every unanswered token for a case. Returns how many.

    Called from two places, for two reasons that need the same effect:

      * a verification restart — the document the outstanding links approve has
        been discarded and rebuilt, so approving it would record consent to
        something CR is not being asked to file;
      * the first successful approval — GSHK receives one approval per return,
        and the other directors' links must stop working rather than record a
        second, contradictory decision on the same case.
    """
    query = (
        get_supabase().table(_TABLE)
        .update({"outcome": OUTCOME_SUPERSEDED,
                 "responded_at": _now().isoformat()})
        .eq("nar1_case_id", case_id)
        .is_("outcome", None)
    )
    if exclude_id:
        query = query.neq("id", exclude_id)
    rows = query.execute().data or []
    return len(rows)


def find_by_token(token: str) -> dict | None:
    """The row this token addresses, or None.

    None covers every miss identically — unknown token, malformed token, empty
    token — because the public route's answers must not let a caller tell a real
    token from a fabricated one.
    """
    if not token or not isinstance(token, str):
        return None
    digest = hash_token(token)
    rows = (
        get_supabase().table(_TABLE)
        .select("*")
        .eq("token_hash", digest)
        .limit(1)
        .execute()
        .data
        or []
    )
    row = rows[0] if rows else None
    if row is None:
        return None
    # Constant-time even though the index already found exactly one row. See
    # the module docstring: this is the guard for a future refactor.
    if not hmac.compare_digest(row.get("token_hash") or "", digest):
        return None
    return row


def is_expired(row: dict, *, now: datetime | None = None) -> bool:
    """Past its 14 days. A malformed or absent expiry counts as EXPIRED.

    Failing closed is the safe direction here: the alternative is a token with
    an unreadable date working forever.
    """
    raw = row.get("expires_at")
    if not raw:
        return True
    try:
        expires = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return True
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return (now or _now()) >= expires


def claim(approval_id: str, *, ip: str | None, user_agent: str | None) -> dict | None:
    """Record THIS token as the approval, but only if it is still unanswered.

    Returns the updated row, or None when it was already answered — which is how
    "first approval wins" is settled: the condition travels with the UPDATE, so
    two directors pressing at the same moment is decided by Postgres and not by
    a read-then-write in the handler. The loser is told the return is already
    approved, which is true.

    `user_agent` is truncated: it is client-supplied text on an unauthenticated
    route, and nothing downstream needs more than enough to recognise a browser.
    """
    rows = (
        get_supabase().table(_TABLE)
        .update({
            "outcome": OUTCOME_APPROVED,
            "responded_at": _now().isoformat(),
            "ip_address": ip,
            "user_agent": (user_agent or "")[:400] or None,
        })
        .eq("id", approval_id)
        .is_("outcome", None)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def approved_row_for(case_id: str) -> dict | None:
    """The token that approved this case, if one did.

    Read by the "already approved" page so a later director is told WHO approved
    and WHEN, rather than a bare refusal that reads like a broken link.
    """
    rows = (
        get_supabase().table(_TABLE)
        .select("*")
        .eq("nar1_case_id", case_id)
        .eq("outcome", OUTCOME_APPROVED)
        .order("responded_at")
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def provenance(case: dict) -> dict | None:
    """How this case was approved, as the UI and the trail should say it.

    Returns None when the case carries no client decision. A case that IS
    approved always returns something with a `summary` — "Approved" on its own
    is never a valid answer, because a director who never replied must not
    appear to have agreed to anything.
    """
    if case.get("client_approved") is not True:
        return None

    source = case.get("client_approval_source")
    name = (case.get("client_approval_name") or "").strip() or None
    when = case.get("client_response_at")

    if source == SOURCE_SYSTEM_TIMEOUT:
        summary = ("System-approved — the client did not respond within "
                   f"{APPROVAL_WINDOW_DAYS} days")
    elif source == SOURCE_SELF_SERVICE:
        summary = (f"Approved by {name} using the link in the verification email"
                   if name else
                   "Approved by the client using the link in the verification email")
    elif source == SOURCE_STAFF_RELAY:
        summary = (f"Approved by {name}, recorded by a member of staff" if name
                   else "Recorded by a member of staff from the client's reply")
    else:
        # Approved before this column existed. Says what is actually known —
        # which is that somebody recorded it — rather than inventing a source.
        summary = "Approved — recorded before the source was tracked"

    return {
        "source": source,
        "name": name,
        "person_id": case.get("client_approval_person_id"),
        "responded_at": when,
        "summary": summary,
        "system": source == SOURCE_SYSTEM_TIMEOUT,
    }
