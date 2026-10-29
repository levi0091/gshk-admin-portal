"""Multi-director signing on an ND2A / ND2B: the state of a round (nd2-multi-signer,
Levi 2026-10-29).

Levi: "when multiple signatures are required from multiple directors ... we
should see 2 separate sending features and the signatures should converge once
all are collected." In that mode each required director gets a link of their own
and signs from their own mailbox; the case counts as client-approved only when
every one of them has. This module is the whole state machine behind that, so
the officer-change router (which sends), the signer routes (which report) and the
public page (which records a signature) share one answer and never read the
tables themselves. It is pure reads plus two writes, and it calls no router.

A ROUND is one verification revision in this mode. It OPENS with the first
per-signer send -- the moment `verification_sent_at` is set and the change list
locks -- and that send FREEZES the signer set into `nar1_cases.required_signers`.
The set is frozen because `signatures.required_signers` reads live company data:
a director marked ceased mid-round could shrink a live count to "everyone has
signed" with nobody left to press anything. Restart verification clears the
round and recomputes.

CONVERGENCE is decided by the CLAIMS, meaning the approval rows, not the stored
signature images. A director whose picture failed to store did confirm; their
box prints blank and `signature_captured` says so. The write that settles it is
one conditional UPDATE (`client_approved IS NULL`, else the ND2B waiver), so two
directors pressing in the same second cannot both converge the case: only the
request whose UPDATE returned a row is `won`, and only that request may audit,
supersede and mail.

`record_signing` and `latest_sends` never raise: the first is called after a
claim that cannot be undone, the second is an extra on a report. `state` lets a
database fault through, because a report that silently shows no signers would be
read as "nobody has signed".
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from db.supabase import get_supabase
from services import audit_events as ev
from services import nar1_approvals, nar1_cases
from services.officer_changes import signatures

_APPROVALS = "nar1_client_approvals"
_SIGNATURES = "officer_change_signatures"

#: `nar1_cases.client_approval_source` of an ND2B filed without confirmation.
#: A real convergence replaces it, exactly as a real answer does in single mode.
_WAIVER = nar1_approvals.SOURCE_STAFF_WAIVER

#: How many EMAIL_SENT rows `latest_sends` reads. A case is a handful of
#: directors sent a handful of times; 100 reaches past any real round.
_SENDS_LIMIT = 100


def _revision(case: dict) -> int:
    try:
        return int((case or {}).get("verification_revision") or 0)
    except (TypeError, ValueError):
        return 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# -- the round and its set ---------------------------------------------------------

def round_open(case: dict) -> bool:
    """Has the first per-signer send of this revision gone out?"""
    return bool((case or {}).get("verification_sent_at"))


def freeze(signers: list[dict]) -> list[dict]:
    """The JSON stored in `nar1_cases.required_signers`: plain, three keys, in
    the order given (which is the order the convergence names the signers in)."""
    return [{"person_id": s["person_id"], "name": s.get("name") or "",
             "roles": list(s.get("roles") or [])} for s in signers]


def signer_set(case: dict) -> tuple[list[dict], bool]:
    """`(signers, frozen)`: the set this round converges on.

    Once the round is open that is the frozen `required_signers`. Before it opens
    -- or on a case whose round is open but carries no frozen set -- it is the
    live rule, and `frozen` is False.
    """
    if round_open(case):
        frozen = (case or {}).get("required_signers")
        if isinstance(frozen, list):
            return frozen, True
    return signatures.required_signers(case), False


def round_approvals(case: dict) -> list[dict]:
    """Every `nar1_client_approvals` row of the case's current revision, any
    outcome. Links of an earlier revision never count."""
    revision = _revision(case)
    if not revision:
        return []
    return (get_supabase().table(_APPROVALS).select("*")
            .eq("nar1_case_id", case["id"]).eq("revision", revision)
            .execute().data) or []


def _approved(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("outcome") == nar1_approvals.OUTCOME_APPROVED]


# -- the report --------------------------------------------------------------------

def _sort_key(row: dict) -> tuple:
    return (row.get("sent_at") or "", row.get("created_at") or "")


def _status(rows: list[dict]) -> tuple[str, dict | None]:
    """`(status, the row it was read from)` for one director's rows.

    A signed row is terminal, so it wins over any later one (there cannot be a
    later one: a send to a signed director is refused). Otherwise the NEWEST row
    speaks. A link that is superseded and unsigned -- the case was closed or the
    answer withdrawn -- reads as `expired`: it no longer works and nobody signed.
    """
    if not rows:
        return "not_sent", None
    signed = _approved(rows)
    if signed:
        return "signed", max(signed, key=_sort_key)
    row = max(rows, key=_sort_key)
    if row.get("outcome") is None and not nar1_approvals.is_expired(row):
        return "sent", row
    return "expired", row


def state(case: dict) -> dict:
    """The GET contract (spec 3.1) WITHOUT `delivery`, which is layered on by the
    route that can ask Resend. Every signer carries `delivery: None` here.

    `status` is `not_sent`, `sent`, `signed` or `expired`; `not_delivered` and
    `redirected` are delivery verdicts the route overlays on a `sent` signer.
    """
    signers, frozen = signer_set(case)
    revision = _revision(case)
    ids = [s["person_id"] for s in signers]

    rows = round_approvals(case) if round_open(case) else []
    by_person: dict[str, list[dict]] = {}
    for row in rows:
        by_person.setdefault(row.get("person_id"), []).append(row)

    captured: set = set()
    if revision:
        captured = {r.get("person_id") for r in (
            get_supabase().table(_SIGNATURES).select("person_id")
            .eq("case_id", case["id"]).eq("revision", revision)
            .execute().data) or []}

    try:
        emails = nar1_cases._person_emails(ids)
    except Exception as exc:  # noqa: BLE001 — a missing suggestion is not a failed page
        print(f"[signers] could not read the directors' addresses: {exc}",
              file=sys.stderr)
        emails = {}

    out = []
    for signer in signers:
        status, row = _status(by_person.get(signer["person_id"], []))
        roles = list(signer.get("roles") or [])
        out.append({
            "person_id": signer["person_id"],
            "name": signer.get("name") or "",
            "roles": roles,
            "role_label": "incoming director" if "consent" in roles else "director",
            "suggested_email": emails.get(signer["person_id"]),
            "status": status,
            "email": (row or {}).get("recipient_email"),
            "sent_at": (row or {}).get("sent_at"),
            "expires_at": (row or {}).get("expires_at"),
            "signed_at": (row or {}).get("responded_at") if status == "signed" else None,
            "signature_captured": status == "signed" and signer["person_id"] in captured,
            "delivery": None,
        })

    signed = sum(1 for s in out if s["status"] == "signed")
    set_changed = False
    if frozen:
        # The STRICT read: `required_signers` answers [] to a fault, and "the
        # board has changed, restart" -- which discards every signature -- must
        # never be inferred from a passing read error. A fault reads as unknown,
        # which is reported as not changed.
        try:
            live = {s["person_id"] for s in signatures.required_signers_strict(case)}
            set_changed = live != set(ids)
        except Exception as exc:  # noqa: BLE001 — see the comment above
            print(f"[signers] could not compare the live board with the frozen "
                  f"one on case {(case or {}).get('id')}: {exc}", file=sys.stderr)
    return {
        "multi_signer": bool((case or {}).get("multi_signer")),
        "revision": revision,
        "frozen": frozen,
        "set_changed": set_changed,
        "required": len(out),
        "signed": signed,
        "converged": bool(out) and signed == len(out)
                     and (case or {}).get("client_approved") is True,
        "signers": out,
    }


def latest_sends(case: dict) -> dict[str, dict]:
    """`person_id -> the newest send's deliveries[0]` for the current revision.

    Each per-signer send writes its own untagged `EMAIL_SENT` row carrying
    `signer_person_id`, `multi_signer: true` and a one-entry `deliveries`. The
    filter is the one the NAR1 delivery check uses (the CASE in `entity_id`, never
    the company's `case_id`, which would return every year's trail) plus the
    multi-signer tag. Rows are newest first, so the first seen per person wins.
    A row from an earlier revision, or without a delivery entry, is skipped.
    Returns `{}` on a fault: a delivery verdict is an extra, never a reason to
    fail the report.
    """
    try:
        rows = (get_supabase().table("audit_log")
                .select("created_at, metadata")
                .eq("entity_id", case["id"])
                .eq("entity_type", "nar1_case")
                .eq("action_type", ev.EMAIL_SENT)
                .is_("metadata->>template", "null")
                .eq("metadata->>multi_signer", "true")
                .order("created_at", desc=True)
                .limit(_SENDS_LIMIT)
                .execute().data) or []
        revision = _revision(case)
        out: dict[str, dict] = {}
        for row in rows:
            meta = row.get("metadata") or {}
            person = meta.get("signer_person_id")
            deliveries = meta.get("deliveries") or []
            if not person or person in out or not deliveries:
                continue
            sent = meta.get("revision")
            if sent is not None and revision:
                try:
                    if int(sent) != revision:
                        continue
                except (TypeError, ValueError):
                    continue    # one unreadable row must not blank every verdict
            out[person] = deliveries[0]
        return out
    except Exception as exc:  # noqa: BLE001 — see the docstring
        print(f"[signers] latest_sends failed on case {(case or {}).get('id')}: {exc}",
              file=sys.stderr)
        return {}


# -- recording a signature ---------------------------------------------------------

def record_signing(case: dict, claimed: dict) -> dict:
    """Count this round's signatures after `claimed` was claimed, and converge.

    Returns `{"signed", "required", "converged", "won", "approvals"}`.
    `converged` is "every required director holds an approved row this revision";
    `won` is true only for the call whose conditional UPDATE of the case returned
    a row -- the one request allowed to audit, supersede and mail. `approvals` is
    one approved row per signer, in the frozen order, for the receipts.

    Never raises past a fault in the update: that reports `won: False` and logs.
    A fault reading the round reports nothing converged.
    """
    result = {"signed": 0, "required": 0, "converged": False, "won": False,
              "approvals": []}
    try:
        signers, frozen = signer_set(case)
        if not frozen:
            # Convergence counts against the set FROZEN at the first send and
            # nothing else. Counting an open round against the live rule would
            # let a board that shrank since converge the case on fewer
            # signatures than were asked for.
            print(f"[signers] no frozen signer set on case {(case or {}).get('id')}; "
                  f"nothing to converge on", file=sys.stderr)
            return result
        result["required"] = len(signers)
        rows = _approved(round_approvals(case))
        if (claimed and claimed.get("outcome") == nar1_approvals.OUTCOME_APPROVED
                and claimed.get("id") not in {r.get("id") for r in rows}):
            rows.append(claimed)
        newest = {}
        for row in sorted(rows, key=lambda r: r.get("responded_at") or ""):
            newest[row.get("person_id")] = row
        approvals = [newest[s["person_id"]] for s in signers if s["person_id"] in newest]
        result["signed"] = len(approvals)
        result["approvals"] = approvals
        result["converged"] = bool(signers) and len(approvals) == len(signers)
    except Exception as exc:  # noqa: BLE001 — see the docstring
        print(f"[signers] could not count the signatures on case "
              f"{(case or {}).get('id')}: {exc}", file=sys.stderr)
        return result

    if not result["converged"]:
        return result

    try:
        names = ", ".join(
            (r.get("recipient_name") or s.get("name") or "").strip()
            for s, r in zip(signers, approvals)
            if (r.get("recipient_name") or s.get("name")))
        payload = {
            "client_approved": True,
            # The LAST signature's time, whichever request got here first: two
            # directors pressing together can be counted by either handler.
            "client_response_at": max(
                (r.get("responded_at") or "" for r in approvals), default="") or _now(),
            "client_approval_source": nar1_approvals.SOURCE_SELF_SERVICE,
            "client_approval_name": names or None,
            # More than one person approved, so there is no single approver.
            "client_approval_person_id": None,
        }
        # `closed_at IS NULL` on both: a case closed while the last director was
        # drawing must not be marked approved by a press that raced the closure.
        #
        # Both are BOUND TO THE ROUND THAT WAS COUNTED. Restart verification
        # clears `verification_sent_at` and leaves the revision alone, so a
        # handler that read the case before the restart would otherwise still
        # match `client_approved IS NULL` and leave an approval sitting on a
        # change list the operator has just reopened for editing.
        def bound(query):
            return (query.eq("id", case["id"]).is_("closed_at", None)
                    .eq("verification_sent_at", case["verification_sent_at"])
                    .eq("verification_revision", _revision(case)))

        won = (bound(get_supabase().table("nar1_cases").update(payload))
               .is_("client_approved", None).execute().data)
        if not won:
            # An ND2B filed without confirmation is replaced by the real thing.
            won = (bound(get_supabase().table("nar1_cases").update(payload))
                   .eq("client_approval_source", _WAIVER).execute().data)
        result["won"] = bool(won)
    except Exception as exc:  # noqa: BLE001 — see the docstring
        print(f"[signers] convergence update failed on case {case.get('id')}: {exc}",
              file=sys.stderr)
        result["won"] = False
    return result
