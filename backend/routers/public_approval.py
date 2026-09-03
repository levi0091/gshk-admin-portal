"""The client's approval page — the only unauthenticated route that WRITES.

(`GET /auth/super-admins` is the other unauthenticated route: a read of two or
three staff addresses for the login screen, with no token, no parameter and
nothing it can change. Everything below is about this one, which does change
something.)


Spec §5. A director opens the link in their verification email, sees the return
they were asked about, and presses one button.

WHY `GET` MUTATES NOTHING. This is the load-bearing decision on this file, not
a nicety. Outlook SafeLinks, Gmail, Proofpoint and essentially every mail
security gateway FETCH every link in a message before a human sees it. A
one-click GET that approved would be fired by the scanner — recording the
scanner's IP as the approving director, minutes after the email was sent and
before anybody read it. Only the POST from this page approves.

WHY IT CARRIES NO `require_permission`. It has no user. That is precisely why
its capability is bounded to one row: the token authorises exactly one action
(approve) on exactly one case, and nothing else in the API is reachable with it.
There is no session, no cookie, no credential, and pressing the button twice
changes nothing.

THE HARDENING, POINT BY POINT (Levi: "limit the type of response received so
that there is no vulnerability to exploit"):

  * The response set is FIXED — approval page, already-approved, expired,
    not-found — and all four are the same shape and size class, so the route
    cannot be used to discover which tokens or cases exist.
  * NOTHING FROM THE REQUEST IS ECHOED. The page renders from the case record
    alone. The token never appears in the HTML, not even in the form action,
    which is why the form posts to the same path the browser is already on.
  * The only accepted POST body is empty. There is no field to supply, so there
    is nothing to inject. FastAPI parses no body here at all.
  * The token is read from the PATH and validated as an opaque URL-safe string
    before it reaches the database layer.
  * Rate-limited per token and per source IP.
  * No reject. See services/nar1_approvals — a rejection needs to carry what is
    wrong, and free client text on an unauthenticated route is exactly what this
    design avoids.
"""
from __future__ import annotations

import html
import ipaddress
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from services import audit_events as ev, nar1_approvals, nar1_cases
from services.audit_service import log_event

router = APIRouter()

#: `secrets.token_urlsafe` produces exactly this alphabet. Anything else is
#: rejected before a query is made — not as security in itself (the hash lookup
#: is), but so the database is never asked about obvious junk.
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,128}$")

#: Requests allowed per key per window, for both keys. Generous enough that a
#: director refreshing the page is never blocked, tight enough that the route is
#: not a useful oracle.
_RATE_LIMIT = 20
_RATE_WINDOW_SECONDS = 300

#: In-process, per worker. Deliberately not Redis: this is a rate limiter, not a
#: lock, and the thing it must stop — a script hammering one token — is stopped
#: well enough per worker. The real defence against guessing is a 256-bit token.
_HITS: dict[str, list] = defaultdict(list)

#: How many keys the limiter will hold before it sheds the idle ones.
#:
#: WITHOUT THIS IT IS ITSELF A DENIAL OF SERVICE. Every distinct token that
#: arrives becomes a dict key, so a script sending random 40-character strings
#: grows this map without bound on an UNAUTHENTICATED route — the map would run
#: the worker out of memory long before the tokens ran out. The sweep below
#: drops every key whose window has fully elapsed, which is all of them for an
#: attacker walking the keyspace.
_HITS_MAX_KEYS = 10_000

_HKT = timezone(timedelta(hours=8))


def _sweep(now: float) -> None:
    """Drop every key whose window has fully elapsed. See `_HITS_MAX_KEYS`."""
    stale = [k for k, hits in _HITS.items()
             if not hits or now - hits[-1] >= _RATE_WINDOW_SECONDS]
    for key in stale:
        del _HITS[key]
    if len(_HITS) > _HITS_MAX_KEYS:
        # Everything is inside its window and there are still too many. Keep the
        # most recently seen, because those are the ones a limit can still act
        # on; an attacker's spent keys are the oldest by construction.
        keep = sorted(_HITS.items(), key=lambda kv: kv[1][-1],
                      reverse=True)[:_HITS_MAX_KEYS]
        _HITS.clear()
        _HITS.update(keep)


def _rate_limited(*keys: str) -> bool:
    now = time.monotonic()
    if len(_HITS) >= _HITS_MAX_KEYS:
        _sweep(now)
    limited = False
    for key in keys:
        if not key:
            continue
        recent = [t for t in _HITS[key] if now - t < _RATE_WINDOW_SECONDS]
        recent.append(now)
        _HITS[key] = recent
        if len(recent) > _RATE_LIMIT:
            limited = True
    return limited


def _client_ip(request: Request) -> str | None:
    """The caller's address, trusting the proxy Railway actually puts in front.

    The LEFTMOST entry in X-Forwarded-For is the client; everything after it is
    a proxy chain. It is client-controllable, which is why it is only ever
    RECORDED and displayed to staff — never used to authorise anything.

    IT IS ALSO PARSED BEFORE IT IS RETURNED, and that is not tidiness.
    `nar1_client_approvals.ip_address` is an `inet` column: a header of
    `<script>` or `not-an-ip` would make the INSERT fail, the whole `claim`
    fail, and the route answer 500 — a client-controlled string turning a
    director's confirmation into an error page. Anything unparseable yields
    None, which the column accepts and which honestly records that we do not
    know where the press came from.
    """
    forwarded = request.headers.get("x-forwarded-for") or ""
    candidate = forwarded.split(",")[0].strip()
    if not candidate:
        candidate = request.client.host if request.client else ""
    try:
        # Normalised through ipaddress rather than regex-matched: it accepts
        # every form Postgres's `inet` does, and rejects everything else.
        return str(ipaddress.ip_address(candidate.strip("[]")))
    except ValueError:
        return None


def _hkt(value) -> str:
    """A timestamp as a Hong Kong reader would write it. HK is UTC+8 with no
    DST, so this is a fixed offset and never a locale lookup."""
    if not value:
        return ""
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    # `%d` and not `%-d`: the no-pad flag is glibc-only and raises on
    # Windows, where this suite also runs. A leading zero on the day is not
    # worth a platform branch in a client-facing page.
    return moment.astimezone(_HKT).strftime("%d %B %Y at %H:%M HKT")


# --------------------------------------------------------------------------- #
#  The four pages. One shape, one stylesheet, no branching in the caller.
# --------------------------------------------------------------------------- #

_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{title}</title>
<style>
  body {{ margin:0; background:#F5F6FB; color:#3A4060;
         font:16px/1.55 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }}
  .wrap {{ max-width:560px; margin:0 auto; padding:40px 20px; }}
  .card {{ background:#fff; border:1px solid #E2E4ED; border-radius:12px;
          padding:28px; }}
  h1 {{ margin:0 0 6px; font-size:20px; color:#1A2050; }}
  .sub {{ margin:0 0 22px; color:#7C80A3; font-size:14px; }}
  dl {{ margin:0 0 24px; }}
  dt {{ font-size:11px; letter-spacing:.07em; text-transform:uppercase;
       color:#7C80A3; margin-top:14px; }}
  dd {{ margin:2px 0 0; color:#1A2050; font-weight:600; }}
  button {{ width:100%; padding:14px 18px; border:0; border-radius:8px;
           background:#F36C32; color:#fff; font-size:16px; font-weight:600;
           cursor:pointer; }}
  .note {{ margin-top:18px; font-size:13px; color:#7C80A3; }}
  .done {{ padding:14px 16px; border-radius:8px; background:#E6F1ED;
          color:#027248; font-weight:600; }}
  .stop {{ padding:14px 16px; border-radius:8px; background:#FEF0EB;
          color:#8A3410; font-weight:600; }}
</style></head><body><div class="wrap"><div class="card">
<h1>{heading}</h1>
<p class="sub">{sub}</p>
{body}
</div></div></body></html>"""


def _render(*, title: str, heading: str, sub: str, body: str,
            status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        _PAGE.format(title=html.escape(title), heading=html.escape(heading),
                     sub=html.escape(sub), body=body),
        status_code=status,
        # A page reached by a one-time link, showing a company's filing details.
        # It must not sit in a shared cache or in the back-button history of a
        # borrowed machine.
        headers={"Cache-Control": "no-store, max-age=0",
                 "Referrer-Policy": "no-referrer",
                 "X-Robots-Tag": "noindex, nofollow"},
    )


def _unavailable() -> HTMLResponse:
    """The ONE answer for every miss: unknown token, malformed token, expired
    token, rate-limited, deleted case.

    Identical in shape, size class and status for all of them, so the route
    cannot be used to learn which tokens or cases exist. 200, not 404: a status
    that differed per reason would leak exactly what the identical body hides.
    """
    return _render(
        title="Link unavailable",
        heading="This link is no longer available",
        sub="It may have expired, or a newer request may have replaced it.",
        body='<p class="stop">Nothing has been changed.</p>'
             '<p class="note">If you still need to confirm this Annual Return, '
             'please reply to the email you received and we will help.</p>',
    )


def _already(name: str, when: str) -> HTMLResponse:
    who = name or "another director"
    return _render(
        title="Already confirmed",
        heading="This Annual Return has already been confirmed",
        sub=f"Confirmed by {who}{f' on {when}' if when else ''}.",
        body='<p class="done">No further action is needed.</p>'
             '<p class="note">Only one confirmation is required for a return. '
             'If something in it looks wrong, please reply to the email you '
             'received.</p>',
    )


def _confirmed(company: str) -> HTMLResponse:
    return _render(
        title="Confirmed",
        heading="Thank you — your confirmation is recorded",
        sub=f"We will file the Annual Return for {company}." if company
            else "We will file the Annual Return.",
        body='<p class="done">Confirmation recorded.</p>'
             '<p class="note">You do not need to do anything else. If you '
             'later notice something wrong, reply to the email you received '
             'as soon as you can.</p>',
    )


def _ask(*, company: str, br_number: str, period: str, case_no: str,
         deadline: str) -> HTMLResponse:
    rows = [("Company", company), ("Business Registration No.", br_number),
            ("Return period", period), ("Our reference", case_no)]
    ledger = "".join(
        f"<dt>{html.escape(label)}</dt><dd>{html.escape(str(value))}</dd>"
        for label, value in rows if value
    )
    # The form posts to the SAME path the browser is already on, so the token
    # never appears in the HTML — not in a hidden field, not in an action
    # attribute, not anywhere a "view source" or a copied page would carry it.
    body = (
        f"<dl>{ledger}</dl>"
        '<form method="post"><button type="submit">'
        'Confirm this Annual Return is correct</button></form>'
        '<p class="note">Pressing Confirm tells us to file this return with '
        'the Companies Registry. If anything is wrong, do not press it — '
        'reply to the email instead and tell us what needs changing.'
        + (f' If we do not hear from you by {html.escape(deadline)}, we will '
           'proceed with filing.' if deadline else '')
        + '</p>'
    )
    return _render(
        title="Confirm your Annual Return",
        heading="Please confirm your Annual Return",
        sub="Check the details below against the form attached to our email.",
        body=body,
    )


# --------------------------------------------------------------------------- #
#  Routes
# --------------------------------------------------------------------------- #

def _resolve(token: str, request: Request):
    """(approval_row, case) or None. Every failure returns None identically."""
    if not _TOKEN.match(token or ""):
        return None
    if _rate_limited(f"t:{token}", f"ip:{_client_ip(request) or 'unknown'}"):
        return None
    try:
        row = nar1_approvals.find_by_token(token)
    except Exception as exc:  # noqa: BLE001 — a database fault must not render a stack trace at a client
        print(f"[public_approval] token lookup failed: {exc}", file=sys.stderr)
        return None
    if row is None:
        return None
    try:
        case = nar1_cases.get_case(row["nar1_case_id"])
    except Exception:  # noqa: BLE001 — LookupError, or a database fault
        return None
    return row, case


def _decided(case: dict) -> HTMLResponse | None:
    """The page to show when the CASE is already settled, or None.

    A case can be decided without any token being used: a staff member records
    a relayed reply, or the 14-day job approves on the client's silence. Neither
    touches a token, so an outstanding link's own `outcome` is still NULL and
    every check on the row passes.

    Approved -> say so, and by whom. REJECTED -> "unavailable", not "already
    confirmed": the client said no, staff are correcting the return, and telling
    a director their return is confirmed would be false. Both halves of this
    route ask this one function, so they cannot answer the same case
    differently.
    """
    decision = case.get("client_approved")
    if decision is True:
        approved = nar1_approvals.approved_row_for(case["id"])
        return _already((approved or {}).get("recipient_name") or "",
                        _hkt((approved or {}).get("responded_at")))
    if decision is False:
        return _unavailable()
    return None


@router.get("/nar1-approval/{token}", response_class=HTMLResponse)
async def show_approval(token: str, request: Request):
    """Render the confirmation page. WRITES NOTHING — see the module docstring.

    A mail-security scanner fetching this link must leave the case exactly as it
    found it, including its audit trail.
    """
    resolved = _resolve(token, request)
    if resolved is None:
        return _unavailable()
    row, case = resolved

    if row.get("outcome") == nar1_approvals.OUTCOME_APPROVED:
        return _already(row.get("recipient_name") or "",
                        _hkt(row.get("responded_at")))
    # A superseded token and an expired one are the same thing to the reader:
    # this link no longer works, and nothing they do here matters. Except when
    # the CASE was settled by somebody else — then the honest answer is that it
    # is already done, not that the link is broken.
    if row.get("outcome") or nar1_approvals.is_expired(row):
        return _decided(case) or _unavailable()

    settled = _decided(case)
    if settled is not None:
        return settled

    entity = _entity_or_empty(case)
    return _ask(
        company=entity.get("company_name") or "",
        br_number=entity.get("br_number") or "",
        period=str(case.get("ar_period_year") or ""),
        case_no=case.get("case_no") or "",
        deadline=_hkt(row.get("expires_at")),
    )


@router.post("/nar1-approval/{token}", response_class=HTMLResponse)
async def record_approval(token: str, request: Request):
    """The only mutating half. Takes NO body — there is nothing to supply."""
    resolved = _resolve(token, request)
    if resolved is None:
        return _unavailable()
    row, case = resolved

    if row.get("outcome") == nar1_approvals.OUTCOME_APPROVED:
        # Idempotent: the same director pressing twice, or a browser replaying
        # the POST, sees what they saw the first time rather than an error.
        return _already(row.get("recipient_name") or "",
                        _hkt(row.get("responded_at")))
    if row.get("outcome") or nar1_approvals.is_expired(row):
        return _decided(case) or _unavailable()

    # THE CASE MAY BE DECIDED WITHOUT ANY TOKEN BEING USED — see `_decided`.
    # Without this the link would overwrite a decision somebody else already
    # recorded, and the provenance on the case would change from what actually
    # happened to a self-service approval that arrived second.
    settled = _decided(case)
    if settled is not None:
        return settled

    # FIRST APPROVAL WINS, settled by Postgres. The condition travels with the
    # UPDATE, so two directors pressing in the same second cannot both record a
    # decision on one return — and audit_log is insert-only, so a second row
    # could never be taken back.
    claimed = nar1_approvals.claim(
        row["id"], ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    if claimed is None:
        approved = nar1_approvals.approved_row_for(case["id"])
        return _already((approved or {}).get("recipient_name") or "",
                        _hkt((approved or {}).get("responded_at")))

    name = claimed.get("recipient_name") or row.get("recipient_name")
    responded = claimed.get("responded_at")

    try:
        nar1_cases.update_case(case["id"], {
            "client_approved": True,
            "client_response_at": responded,
            "client_approval_source": nar1_approvals.SOURCE_SELF_SERVICE,
            "client_approval_person_id": claimed.get("person_id"),
            # Denormalised on purpose (migration 030): the trail must keep
            # saying who approved even if the person row is later renamed,
            # merged or removed.
            "client_approval_name": name,
        })
        # Every other outstanding link for this case stops working. One return,
        # one approval.
        nar1_approvals.supersede_outstanding(case["id"], exclude_id=claimed["id"])
    except Exception as exc:  # noqa: BLE001
        # The token row is already claimed and cannot be un-claimed, so the
        # client HAS approved; what failed is the case write. Say so on stderr
        # and still tell the client their answer was recorded — because on the
        # record that matters, it was.
        print(f"[public_approval] case update failed after a recorded client "
              f"approval on case {case.get('id')}: {exc}", file=sys.stderr)

    entity = _entity_or_empty(case)
    await log_event(
        # No user_id: there is no portal user behind this. The director is
        # named instead, which is the whole point of the row.
        user_id=None,
        user_display_name=name or claimed.get("recipient_email") or "Client",
        action_type=ev.CLIENT_APPROVAL_SELF_SERVICE,
        event_code=ev.CLIENT_APPROVAL_SELF_SERVICE,
        case_id=case.get("entity_id"),
        entity_type="nar1_case",
        entity_id=case["id"],
        company_name=entity.get("company_name"),
        new_value="approved",
        metadata={
            "case_no": case.get("case_no"),
            "person_id": claimed.get("person_id"),
            "recipient_email": claimed.get("recipient_email"),
            # Levi asked for the IP, the date and the time to be logged. They
            # are on the approval row as well; they are repeated here because
            # the audit trail is what an auditor reads, and it should not need
            # a join to answer "who approved this and from where".
            "ip_address": claimed.get("ip_address"),
            "user_agent": claimed.get("user_agent"),
            "responded_at": responded,
            "channel": "self_service",
        },
    )

    return _confirmed(entity.get("company_name") or "")


def _entity_or_empty(case: dict) -> dict:
    """The company, or {} — a client-facing page must not 500 because a lookup
    failed. The ledger simply omits the rows it has no value for."""
    try:
        return nar1_cases.entity_for(case["entity_id"]) or {}
    except Exception:  # noqa: BLE001
        return {}
