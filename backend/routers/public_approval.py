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
    ONE EXCEPTION (e-signature-nd2, Levi 2026-10-29): on the ND2A / ND2B page, a
    DIRECTOR's POST carries one field, `signature`, a drawn PNG. It is read from
    the raw stream under a 300 KB cap (never the framework's form parser),
    validated by `signatures.decode` BEFORE the claim, and kept only after the
    claim wins. Every other POST on every page is still bodyless.
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
from urllib.parse import parse_qs
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse

from services import audit_events as ev, nar1_approvals, nar1_cases
from services.officer_changes import signatures, signers
from services.audit_service import log_event
# ONE OWNER FOR THE ADDRESS. The verification email tells the client that
# replies are not monitored and to write to this mailbox instead; a page that
# named a different one — or that still said "reply to the email" — would send
# a client somewhere nobody is reading.
from services.email_service import RENEWAL_MAILBOX
# The same "Rev. N" the email printed, from the same function, so the page and
# the inbox cannot spell a revision differently.
from services.email_service import revision_label
from services import audit_subject
# The receipt mailed after a press that claimed the approval (Levi 2026-10-17).
# Bound by name so the suite can stub THIS binding (conftest) and still test
# the service itself.
from services.approval_receipt import confirmed_documents
from services.approval_receipt import ACTOR
from services.approval_receipt import send as send_receipt

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
  button {{ padding:13px 24px; border:0; border-radius:8px;
           background:#F36C32; color:#fff; font-size:16px; font-weight:600;
           cursor:pointer; }}
  .conf-h {{ margin:0 0 8px; font-size:11px; letter-spacing:.07em;
            text-transform:uppercase; color:#7C80A3; }}
  .conf {{ margin:0 0 24px; padding:0; list-style:none; }}
  .conf li {{ padding:10px 14px; margin-bottom:8px; border:1px solid #E2E4ED;
             border-radius:8px; background:#FAFBFD; color:#1A2050;
             font-weight:600; }}
  .conf-file {{ display:block; margin-top:2px; font-size:13px; font-weight:400;
               color:#7C80A3; word-break:break-all; }}
  .warn {{ border:1px solid #E2E4ED; border-radius:10px; overflow:hidden; }}
  .warn-top {{ display:flex; gap:14px; padding:20px 22px 18px; }}
  .warn-ico {{ flex:0 0 auto; line-height:0; padding-top:2px; }}
  .warn-h {{ margin:0 0 8px; font-size:19px; font-weight:700; color:#1A2050; }}
  .warn-t {{ margin:0; font-size:15px; color:#3A4060; }}
  .warn-foot {{ display:flex; justify-content:flex-end; padding:14px 22px;
               border-top:1px solid #E2E4ED; background:#FAFBFD; }}
  button:disabled {{ opacity:.45; cursor:not-allowed; }}
  button.ghost {{ background:#fff; color:#3A4060; border:1px solid #E2E4ED;
                 padding:8px 16px; font-size:14px; }}
  .sig {{ margin:0 0 20px; }}
  .sig-pad {{ display:block; width:100%; height:auto; aspect-ratio:3/1;
             background:#fff; border:1px solid #E2E4ED; border-radius:8px;
             touch-action:none; cursor:crosshair; }}
  .sig-bar {{ display:flex; justify-content:space-between; align-items:center;
             gap:12px; margin-top:8px; }}
  .sig-bar p {{ margin:0; font-size:13px; color:#7C80A3; }}
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


def _unavailable(subject: str = "this Annual Return") -> HTMLResponse:
    """The ONE answer for every miss: unknown token, malformed token, expired
    token, rate-limited, deleted case.

    Identical in shape, size class and status for all of them, so the route
    cannot be used to learn which tokens or cases exist. 200, not 404: a status
    that differed per reason would leak exactly what the identical body hides.

    `subject` is chosen by the ROUTE, never by the token: the officer-change
    page says "this form" for every miss, so its wording cannot tell an ND2A
    token from an ND2B one or from none at all.
    """
    return _render(
        title="Link unavailable",
        heading="This link is no longer available",
        sub="It may have expired, or a newer request may have replaced it.",
        body='<p class="stop">Nothing has been changed.</p>'
             f'<p class="note">If you still need to confirm {html.escape(subject)}, '
             f'please email {html.escape(RENEWAL_MAILBOX)} and we will '
             'help.</p>',
    )


def _subject(case: dict) -> tuple[str, str]:
    """`(heading noun, one-word noun)` for the form this case files — so a
    director asked to confirm an ND2A is never told an Annual Return is done."""
    form = case.get("form_code") or "Nar1"
    if form in _OFFICER_CHANGE_FORMS:
        return f"Form {form.upper()}", "form"
    return "This Annual Return", "return"


def _already(name: str, when: str, case: dict | None = None) -> HTMLResponse:
    who = name or "another director"
    heading, noun = _subject(case or {})
    return _render(
        title="Already confirmed",
        heading=f"{heading} has already been confirmed",
        sub=f"Confirmed by {who}{f' on {when}' if when else ''}.",
        body='<p class="done">No further action is needed.</p>'
             f'<p class="note">Only one confirmation is required for a {noun}. '
             'If something in it looks wrong, please email '
             f'{html.escape(RENEWAL_MAILBOX)}.</p>',
    )


def _confirmed(company: str) -> HTMLResponse:
    return _render(
        title="Confirmed",
        heading="Thank you — your confirmation is recorded",
        sub=f"We will file the Annual Return for {company}." if company
            else "We will file the Annual Return.",
        body='<p class="done">Confirmation recorded.</p>'
             '<p class="note">You do not need to do anything else. If you '
             'later notice something wrong, email '
             f'{html.escape(RENEWAL_MAILBOX)} as soon as you can.</p>',
    )


#: The warning triangle from the approved mock, drawn rather than fetched. An
#: <img> would be a second request from a client's mail-restricted browser, and
#: the one that fails silently leaves the panel looking unfinished.
_WARNING_MARK = (
    '<svg width="30" height="30" viewBox="0 0 24 24" aria-hidden="true" '
    'focusable="false">'
    '<path fill="#F36C32" stroke="#F36C32" stroke-width="2.4" '
    'stroke-linejoin="round" d="M12 3.4 2.7 20h18.6z"/>'
    '<path fill="#fff" d="M11 9.2h2v5.4h-2zm0 6.7h2v2.1h-2z"/>'
    "</svg>"
)


def _confirming(documents) -> str:
    """The "You are confirming" list: each document by title, with the file name
    it carries in the verification email.

    Plain `<ul>` and escaped text, no script (the page runs none). Titles and
    file names are built from the case, which holds free text, so every value
    goes through `html.escape`. Empty when there is nothing to name, so a
    caller that has no list still renders the page it always did.
    """
    items = "".join(
        f'<li>{html.escape(str(d.get("title") or ""))}'
        f'<span class="conf-file">{html.escape(str(d.get("file_name") or ""))}</span></li>'
        for d in documents or () if d.get("title"))
    if not items:
        return ""
    return f'<p class="conf-h">You are confirming</p><ul class="conf">{items}</ul>'


def _ask(*, company: str, br_number: str, period: str, case_no: str,
         deadline: str, revision: str = "", documents=()) -> HTMLResponse:
    """The confirmation page, carrying the approved warning panel.

    THE WARNING IS SHOWN ON ARRIVAL, not behind a first press. The mock draws
    it as a modal over the page (Levi 2026-09-08), but a modal needs script to
    open and this route runs none — see `test_the_page_runs_no_script_at_all`:
    it is an unauthenticated page reached from a link in a client's email, and
    the smallest attack surface is no attack surface. Rendered inline it says
    the same words at the same moment, before anything can be pressed, which is
    the whole job of the warning.

    There is CONSEQUENTLY no Cancel. In the mock it dismisses a dialog; here
    there is no dialog to dismiss, and a button that did nothing would be a
    worse answer to "something is wrong" than the note below, which names the
    mailbox that reads it.
    """
    # "Revision" only from Rev. 2 (`revision` is "" before that, and the row
    # is skipped like any other empty one): with two emails in the inbox, it
    # says which one this page is confirming.
    rows = [("Company", company), ("Business Registration No.", br_number),
            ("Return period", period), ("Our reference", case_no),
            ("Revision", revision)]
    ledger = "".join(
        f"<dt>{html.escape(label)}</dt><dd>{html.escape(str(value))}</dd>"
        for label, value in rows if value
    )
    # The form posts to the SAME path the browser is already on, so the token
    # never appears in the HTML — not in a hidden field, not in an action
    # attribute, not anywhere a "view source" or a copied page would carry it.
    body = (
        f"<dl>{ledger}</dl>"
        f"{_confirming(documents)}"
        '<form method="post"><div class="warn">'
        f'<div class="warn-top"><div class="warn-ico">{_WARNING_MARK}</div>'
        '<div><p class="warn-h">Warning</p>'
        '<p class="warn-t">By clicking <strong>Confirm &amp; File</strong>, '
        'you confirm that you have reviewed the draft and that the information '
        'is correct. The NAR1 will then be arranged for submission without '
        'further confirmation.</p></div></div>'
        '<div class="warn-foot">'
        '<button type="submit">Confirm &amp; File</button>'
        "</div></div></form>"
        '<p class="note">If anything is wrong, do not press Confirm &amp; File '
        f"— email {html.escape(RENEWAL_MAILBOX)} instead and tell us what "
        "needs changing."
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

#: Which forms each page confirms. The approval tokens share one table, so a
#: token is only good on the page for its own form: an ND2A link opened on the
#: NAR1 page would show a director annual-return wording about an officer
#: change, and confirm it in those words.
_NAR1_FORMS = ("Nar1",)
_OFFICER_CHANGE_FORMS = ("Nd2a", "Nd2b")


def _resolve(token: str, request: Request, forms=_NAR1_FORMS):
    """(approval_row, case) or None. Every failure returns None identically,
    a token for another form's page included."""
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
    if (case.get("form_code") or "Nar1") not in forms:
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
    # CLOSED FIRST, and as "unavailable" rather than anything more specific.
    # The reader is a company director on the public internet holding a link
    # from an email, and the page must not tell them the case was cancelled,
    # by whom, or why — that is GSHK's business with their client, and this
    # route authenticates nobody.
    #
    # Closing supersedes every outstanding token, so a link normally stops
    # working before it reaches this line. This is the second lock: a token
    # store that would not write is a reason to shout on stderr, not a reason
    # to let a director approve a return that will never be filed.
    miss = _miss_for(case)
    if case.get("closed_at"):
        return _unavailable(miss)

    decision = case.get("client_approved")
    if decision is True and case.get("client_approval_source") == \
            nar1_approvals.SOURCE_STAFF_WAIVER:
        # GSHK is proceeding without the client's confirmation (an ND2B,
        # Jacqueline BQ1). Nobody confirmed, so the page must not say anybody
        # did — and the client's own confirmation is still worth having.
        return None
    if decision is True:
        approved = nar1_approvals.approved_row_for(case["id"])
        return _already((approved or {}).get("recipient_name") or "",
                        _hkt((approved or {}).get("responded_at")), case)
    if decision is False:
        return _unavailable(miss)
    return None


def _miss_for(case_or_forms) -> str:
    """The `_unavailable` subject: "this form" on the officer-change page, for
    every miss alike; "this Annual Return" on NAR1's."""
    forms = case_or_forms if isinstance(case_or_forms, tuple) else \
        ((case_or_forms or {}).get("form_code") or "Nar1",)
    return "this form" if set(forms) & set(_OFFICER_CHANGE_FORMS) else "this Annual Return"


@router.get("/nar1-approval/{token}", response_class=HTMLResponse)
async def show_approval(token: str, request: Request):
    """Render the confirmation page. WRITES NOTHING — see the module docstring.

    A mail-security scanner fetching this link must leave the case exactly as it
    found it, including its audit trail.
    """
    return await _show(token, request, forms=_NAR1_FORMS, ask=lambda case, entity, row: _ask(
        company=entity.get("company_name") or "",
        br_number=entity.get("br_number") or "",
        period=str(case.get("ar_period_year") or ""),
        case_no=case.get("case_no") or "",
        deadline=_hkt(row.get("expires_at")),
        # The LINK's revision, from its own row — a stale one never gets here.
        revision=revision_label(row.get("revision")),
        documents=confirmed_documents(case, row)))


@router.post("/nar1-approval/{token}", response_class=HTMLResponse)
async def record_approval(token: str, request: Request, background: BackgroundTasks):
    """The only mutating half. Takes NO body — there is nothing to supply.

    (`BackgroundTasks` is injected by FastAPI, not read from the request: the
    route still parses no body.)"""
    return await _record(token, request, forms=_NAR1_FORMS, confirmed=_confirmed,
                         background=background)


# --------------------------------------------------------------------------- #
#  ND2A / ND2B — the same guarantees, an officer change's words (spec §5)
#
#  Same token table, same first-approval-wins claim, same no-script page and
#  the same GET-mutates-nothing rule. There is NO auto-approval behind these
#  links (spec §5), so the page never says silence will be taken as consent.
# --------------------------------------------------------------------------- #

_FORM_TITLES = {"Nd2a": ("ND2A", "the change of company secretary and directors"),
                "Nd2b": ("ND2B", "the change in particulars of your company officers")}


#: The drawing pad's script. INLINE, SELF-CONTAINED, NO NETWORK: it draws on a
#: <canvas> with Pointer Events and, on submit, writes the PNG data URL into the
#: hidden `signature` field of the form that is already there. It is the only
#: script this route has ever served, and it is served only to a director who has
#: a box to sign (`signatures.must_sign`); the NAR1 page and every other ND2 page
#: still run none. `test_a_directors_page_runs_the_pad_and_nothing_else` pins it.
#:
#: Nothing here may reach the network, and it touches only the five ids below.
_PAD_SCRIPT = """(function () {
  var panel = document.getElementById('sigpanel');
  var canvas = document.getElementById('sigpad');
  var field = document.getElementById('sigdata');
  var go = document.getElementById('sigok');
  var clear = document.getElementById('sigclear');
  if (!panel || !canvas || !field || !go || !clear) { return; }
  if (!canvas.getContext || !window.PointerEvent) {
    panel.textContent = 'Signing needs a newer browser. Please use a current ' +
      'version of Chrome, Safari, Edge or Firefox.';
    panel.hidden = false;
    return;
  }
  var ctx = canvas.getContext('2d');
  ctx.lineWidth = 3;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.strokeStyle = '#1A2050';
  var drawing = false;
  var inked = false;
  function at(e) {
    var r = canvas.getBoundingClientRect();
    return { x: (e.clientX - r.left) * canvas.width / r.width,
             y: (e.clientY - r.top) * canvas.height / r.height };
  }
  canvas.addEventListener('pointerdown', function (e) {
    drawing = true;
    canvas.setPointerCapture(e.pointerId);
    var p = at(e);
    ctx.beginPath();
    ctx.moveTo(p.x, p.y);
    ctx.lineTo(p.x + 0.1, p.y + 0.1);
    ctx.stroke();
    if (!inked) { inked = true; go.disabled = false; }
    e.preventDefault();
  });
  canvas.addEventListener('pointermove', function (e) {
    if (!drawing) { return; }
    var p = at(e);
    ctx.lineTo(p.x, p.y);
    ctx.stroke();
    e.preventDefault();
  });
  function lift() { drawing = false; }
  canvas.addEventListener('pointerup', lift);
  canvas.addEventListener('pointercancel', lift);
  clear.addEventListener('click', function () {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    inked = false;
    go.disabled = true;
    field.value = '';
  });
  // A <canvas> is not a form control and has no `.form`; the hidden input is.
  field.form.addEventListener('submit', function (e) {
    if (!inked) { e.preventDefault(); return; }
    field.value = canvas.toDataURL('image/png');
  });
  panel.hidden = false;
})();"""

#: Said on the ask page when the drawing could not be used, whatever the reason.
#: One fixed sentence: the page does not tell an unauthenticated caller which of
#: the checks it failed.
_SIGNATURE_RETRY = "We could not read your signature. Please draw it again."


def _signature_panel(form_code: str, error: str = "") -> str:
    """The "Your signature" panel, ABOVE the warning and the button.

    The pad is hidden until the script runs, so without script the director sees
    the <noscript> note instead and the button (rendered disabled) cannot be
    pressed. The canvas is a fixed 600 x 200 whatever the screen, far inside the
    server's 1600 x 600 limit, and it keeps a phone's pixel ratio from inflating
    the upload.
    """
    on = ("the form and the written resolution" if form_code == "Nd2a"
          else "the form")
    return (
        '<div class="sig"><p class="conf-h">Your signature</p>'
        + (f'<p class="stop">{html.escape(error)}</p>' if error else "")
        + '<noscript><p class="stop">Signing needs JavaScript. Turn it on, or '
          f"reply to {html.escape(RENEWAL_MAILBOX)}.</p></noscript>"
        '<div id="sigpanel" hidden>'
        '<canvas id="sigpad" class="sig-pad" width="600" height="200" '
        'role="img" aria-label="Signature drawing area"></canvas>'
        '<input type="hidden" name="signature" id="sigdata" value="">'
        '<div class="sig-bar"><p>Draw your signature. It will be printed on '
        f"{on} listed above where a director signs.</p>"
        '<button type="button" class="ghost" id="sigclear">Clear</button></div>'
        "</div></div>"
    )


def _ask_officer_change(*, company: str, br_number: str, form_code: str, case_no: str,
                        deadline: str, revision: str = "",
                        documents=(), sign: bool = False,
                        signature_error: str = "", note: str = "") -> HTMLResponse:
    code, what = _FORM_TITLES.get(form_code, _FORM_TITLES["Nd2a"])
    # "Revision" from Rev. 2 only, exactly as NAR1's page (`_ask`).
    rows = [("Company", company), ("Business Registration No.", br_number),
            ("Form", f"Form {code}"), ("Our reference", case_no),
            ("Revision", revision)]
    ledger = "".join(f"<dt>{html.escape(label)}</dt><dd>{html.escape(str(value))}</dd>"
                     for label, value in rows if value)
    body = (
        f"<dl>{ledger}</dl>"
        f"{_confirming(documents)}"
        # One extra line, only when the caller has something to add (the
        # multi-signer page says each director signs from their own email).
        + (f'<p class="note">{html.escape(note)}</p>' if note else "")
        + '<form method="post">'
        + (_signature_panel(form_code, signature_error) if sign else "")
        + '<div class="warn">'
        f'<div class="warn-top"><div class="warn-ico">{_WARNING_MARK}</div>'
        '<div><p class="warn-h">Warning</p>'
        '<p class="warn-t">By clicking <strong>Confirm &amp; File</strong>, you '
        f"confirm that you have reviewed the draft Form {code} and that the changes "
        "it reports are correct. It will then be arranged for submission to the "
        "Companies Registry without further confirmation.</p></div></div>"
        # Disabled until something is drawn; with no script it stays disabled,
        # which the <noscript> note above says.
        '<div class="warn-foot"><button type="submit"'
        + (' id="sigok" disabled' if sign else "")
        + ">Confirm &amp; File</button>"
        "</div></div></form>"
        '<p class="note">If anything is wrong, do not press Confirm &amp; File '
        f"— email {html.escape(RENEWAL_MAILBOX)} instead and tell us what needs "
        "changing."
        + (f" Please let us know by {html.escape(deadline)}." if deadline else "")
        + "</p>"
        + (f"<script>{_PAD_SCRIPT}</script>" if sign else "")
    )
    return _render(title=f"Confirm Form {code}",
                   heading=f"Please confirm {what}",
                   # An ND2A goes out with its written resolution: two documents.
                   sub=("Check the details below against the documents attached to our email."
                        if form_code == "Nd2a" else
                        "Check the details below against the form attached to our email."),
                   body=body)


def _confirmed_officer_change(case: dict):
    code, _what = _FORM_TITLES.get(case.get("form_code"), _FORM_TITLES["Nd2a"])

    def page(company: str) -> HTMLResponse:
        return _render(
            title="Confirmed", heading="Thank you — your confirmation is recorded",
            sub=(f"We will file Form {code} for {company}." if company
                 else f"We will file Form {code}."),
            body='<p class="done">Confirmation recorded.</p>'
                 '<p class="note">You do not need to do anything else. If you later '
                 f"notice something wrong, email {html.escape(RENEWAL_MAILBOX)} as "
                 "soon as you can.</p>")
    return page


def _officer_change_ask(case: dict, entity: dict, row: dict, error: str = "", *,
                        sign: bool | None = None, note: str = "") -> HTMLResponse:
    """The ND2A / ND2B page for this link: with the drawing pad when the person
    it was issued to is a director with a box to sign, today's page otherwise.

    Decided HERE, on the server, from the link's own `person_id` — never from
    anything the browser sent — and decided again on the POST.

    `sign=None` is that rule. The multi-signer page passes `sign=True`: there,
    membership of the round's frozen signer set is what puts a person on a box,
    and `must_sign` reads live data that the round deliberately does not follow.
    """
    return _ask_officer_change(
        company=entity.get("company_name") or "",
        br_number=entity.get("br_number") or "",
        form_code=case.get("form_code"), case_no=case.get("case_no") or "",
        deadline=_hkt(row.get("expires_at")),
        revision=revision_label(row.get("revision")),
        documents=confirmed_documents(case, row),
        sign=(signatures.must_sign(case, row.get("person_id")) if sign is None else sign),
        signature_error=error, note=note)


@router.get("/officer-change-approval/{token}", response_class=HTMLResponse)
async def show_officer_change_approval(token: str, request: Request):
    """WRITES NOTHING, exactly as the NAR1 page."""
    resolved = _resolve(token, request, _OFFICER_CHANGE_FORMS)
    if resolved is not None and resolved[1].get("multi_signer"):
        return await _show_signer(resolved)
    return await _show(token, request, forms=_OFFICER_CHANGE_FORMS,
                       ask=_officer_change_ask, resolved=resolved)


#: A POST carrying more than this is refused before it is parsed. The decoded
#: signature is capped at 200 KB (about 267 KB as base64); the rest of the form
#: is one short field. Starlette puts no limit of its own on an urlencoded body.
_MAX_POST_BYTES = 300 * 1024


class _Signature:
    """What the signature policy decided about one POST."""

    def __init__(self, required: bool, png: bytes | None = None):
        self.required = required
        self.png = png

    @property
    def refused(self) -> bool:
        return self.required and self.png is None


async def _read_signature_field(request: Request) -> str | None:
    """The `signature` form field, reading at most `_MAX_POST_BYTES`.

    Reads the raw stream under a cap instead of calling the framework's form
    parser, which would buffer whatever an unauthenticated caller sends. None
    when the body is over the cap, malformed or has no such field.
    """
    declared = request.headers.get("content-length")
    try:
        if declared is not None and int(declared) > _MAX_POST_BYTES:
            return None
    except ValueError:
        return None
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > _MAX_POST_BYTES:
            return None
    try:
        fields = parse_qs(bytes(body).decode("ascii"), keep_blank_values=True,
                          max_num_fields=10)
    except (UnicodeDecodeError, ValueError):
        return None
    values = fields.get("signature") or []
    return values[0] if values else None


async def _officer_change_signature(request: Request, row: dict, case: dict) -> _Signature:
    """Validate the drawn signature BEFORE the claim (spec section 3).

    Not required of anybody `must_sign` says has no box. For a director it must
    be a readable drawing with ink on it: the claim cannot be undone, so a
    confirmation that arrives without one is answered with the page again and
    nothing is recorded.
    """
    if not signatures.must_sign(case, row.get("person_id")):
        return _Signature(required=False)
    field = await _read_signature_field(request)
    try:
        return _Signature(required=True, png=signatures.decode(field))
    except signatures.SignatureError as exc:
        print(f"[public_approval] signature refused on case {case.get('id')}: {exc}",
              file=sys.stderr)
        return _Signature(required=True)


@router.post("/officer-change-approval/{token}", response_class=HTMLResponse)
async def record_officer_change_approval(token: str, request: Request,
                                         background: BackgroundTasks):
    # Resolved ONCE (one rate-limiter hit), then dispatched on the case's mode.
    resolved = _resolve(token, request, _OFFICER_CHANGE_FORMS)
    if resolved is not None and resolved[1].get("multi_signer"):
        return await _record_signer(resolved, request, background)
    return await _record(token, request, forms=_OFFICER_CHANGE_FORMS,
                         confirmed=None, background=background,
                         ask=_officer_change_ask,
                         signature_policy=_officer_change_signature,
                         resolved=resolved)


def _earlier_revision(row: dict, case: dict, forms) -> HTMLResponse | None:
    """The page for a link from a revision the client has since been re-sent,
    or None when this link is the current one (Levi 2026-10-02; migration 051).

    ASKED FIRST, ahead of the link's own outcome, because that outcome describes
    a form that has been replaced. A director who approved Rev. 1 and opens
    that email again after Rev. 2 went out used to be told it had already been
    confirmed — true of a document nobody is filing any more, and false of the
    one awaiting them in the newer email.

    Otherwise the same answers as a superseded link: if the CASE has since been
    settled, say so; if not, the one "no longer available" page, whose sub-line
    already says a newer request may have replaced it. No more specific than
    that, by the rule at the top of this file — the page does not describe a
    client's case to whoever holds a link. One function for NAR1, ND2A and
    ND2B, because `_show` and `_record` serve all three.
    """
    if not nar1_approvals.is_stale(row, case):
        return None
    return _decided(case) or _unavailable(_miss_for(forms))


#: "Resolve the token yourself". `None` is a real answer to `_resolve` (a miss),
#: so it cannot stand for "not supplied".
_UNRESOLVED = object()


async def _show(token: str, request: Request, *, forms, ask,
                resolved=_UNRESOLVED) -> HTMLResponse:
    if resolved is _UNRESOLVED:
        resolved = _resolve(token, request, forms)
    if resolved is None:
        return _unavailable(_miss_for(forms))
    row, case = resolved

    stale = _earlier_revision(row, case, forms)
    if stale is not None:
        return stale
    if row.get("outcome") == nar1_approvals.OUTCOME_APPROVED:
        return _already(row.get("recipient_name") or "",
                        _hkt(row.get("responded_at")), case)
    # A superseded token and an expired one are the same thing to the reader:
    # this link no longer works, and nothing they do here matters. Except when
    # the CASE was settled by somebody else — then the honest answer is that it
    # is already done, not that the link is broken.
    if row.get("outcome") or nar1_approvals.is_expired(row):
        return _decided(case) or _unavailable(_miss_for(forms))

    settled = _decided(case)
    if settled is not None:
        return settled

    return ask(case, _entity_or_empty(case), row)


async def _record(token: str, request: Request, *, forms, confirmed,
                  background: BackgroundTasks | None = None,
                  ask=None, signature_policy=None,
                  resolved=_UNRESOLVED) -> HTMLResponse:
    """The only mutating half. Takes NO body — there is nothing to supply —
    except on the officer-change route for a director, whose `signature_policy`
    reads the one drawn-signature field (capped) and whose `ask` re-draws the
    page when it cannot be used."""
    if resolved is _UNRESOLVED:
        resolved = _resolve(token, request, forms)
    if resolved is None:
        return _unavailable(_miss_for(forms))
    row, case = resolved

    # Before the claim, and before the idempotent replay below: a link from an
    # earlier revision must not record an approval of a form the client has
    # since been sent a corrected version of.
    stale = _earlier_revision(row, case, forms)
    if stale is not None:
        return stale
    if row.get("outcome") == nar1_approvals.OUTCOME_APPROVED:
        # Idempotent: the same director pressing twice, or a browser replaying
        # the POST, sees what they saw the first time rather than an error.
        return _already(row.get("recipient_name") or "",
                        _hkt(row.get("responded_at")), case)
    if row.get("outcome") or nar1_approvals.is_expired(row):
        return _decided(case) or _unavailable(_miss_for(forms))

    # THE CASE MAY BE DECIDED WITHOUT ANY TOKEN BEING USED — see `_decided`.
    # Without this the link would overwrite a decision somebody else already
    # recorded, and the provenance on the case would change from what actually
    # happened to a self-service approval that arrived second.
    settled = _decided(case)
    if settled is not None:
        return settled

    # THE SIGNATURE IS CHECKED BEFORE THE CLAIM, because the claim cannot be
    # undone. A director who pressed Confirm & File without a usable drawing is
    # shown the page again with one sentence, and nothing is recorded.
    drawn = signature_policy and await signature_policy(request, row, case)
    if drawn and drawn.refused:
        return ask(case, _entity_or_empty(case), row, _SIGNATURE_RETRY)

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
                        _hkt((approved or {}).get("responded_at")), case)

    name = claimed.get("recipient_name") or row.get("recipient_name")
    responded = claimed.get("responded_at")

    # Kept only now, past the claim: a lost race, a stale link or a replay never
    # leaves a signature behind. The image is never put in the audit row below —
    # only whether one was captured, and its id.
    signature = (_keep_signature(drawn, case, row, claimed)
                 if drawn and drawn.required else None)

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
        **audit_subject.for_case(case),
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
            # Which emailed revision the director confirmed. NULL for a link
            # issued before migration 051.
            "revision": claimed.get("revision", row.get("revision")),
            # Only on a link that was asked for a signature.
            **({"signature": signature} if signature is not None else {}),
        },
    )

    # THE RECEIPT, mailed after this page is returned (Levi 2026-10-17): the
    # director gets the moment and the documents they confirmed, renewal@
    # copied. Only here — past the claim — so a GET, a replay, a stale link and
    # the director who lost the race never send one. It never raises.
    if background is not None:
        background.add_task(send_receipt, case["id"], {**row, **claimed})

    page = confirmed or _confirmed_officer_change(case)
    return page(entity.get("company_name") or "")


def _keep_signature(drawn, case: dict, row: dict, claimed: dict) -> dict:
    """Store the drawing for the approval that just won; `{"captured": ...}`.

    One retry: the claim cannot be undone, so a transient fault here must not
    cost the director their signature when a second attempt would have kept it.
    If both fail the confirmation still stands (the director did confirm), the
    audit row says `captured: false`, and nothing is printed for that person.
    """
    revision = claimed.get("revision", row.get("revision"))
    if revision is None:
        revision = nar1_approvals.current_revision(case)
    for attempt in (1, 2):
        try:
            saved = signatures.store(
                case_id=case["id"], approval_id=claimed["id"],
                person_id=claimed.get("person_id") or row.get("person_id"),
                revision=int(revision), png=drawn.png)
            return {"captured": True, "signature_id": saved.get("id")}
        except Exception as exc:  # noqa: BLE001
            print(f"[public_approval] signature store failed (attempt {attempt}) on "
                  f"case {case.get('id')}: {exc}", file=sys.stderr)
    return {"captured": False}


def _entity_or_empty(case: dict) -> dict:
    """The company, or {} — a client-facing page must not 500 because a lookup
    failed. The ledger simply omits the rows it has no value for."""
    try:
        return nar1_cases.entity_for(case["entity_id"]) or {}
    except Exception:  # noqa: BLE001
        return {}


# --------------------------------------------------------------------------- #
#  ND2A / ND2B when SEVERAL DIRECTORS MUST SIGN (nd2-multi-signer, spec 2.5)
#
#  Dispatched to from the two officer-change routes above, only when the case
#  carries `multi_signer`. The NAR1 routes never come here, and `_show` /
#  `_record` above are the same code they always were: single-mode ND2 and NAR1
#  keep "the first confirmation wins".
#
#  Here a link is one DIRECTOR's, it stays live until that director signs, and
#  the case counts as client-approved only when every director in the round's
#  frozen set holds a signed row (`signers.record_signing`). The pages obey the
#  rules of the rest of this file: a GET writes nothing, the answers for a
#  link that cannot be used are the same few sentences, and the route
#  authenticates nobody -- so the waiting page shows a COUNT and never names
#  another director.
# --------------------------------------------------------------------------- #

_EACH_DIRECTOR_SIGNS = ("Each director signs from their own email. The form is "
                        "filed once every director has signed.")


def _converged(case: dict) -> bool:
    """Every director has signed and the case says so. A staff waiver is not it."""
    return (case.get("client_approved") is True
            and case.get("client_approval_source") != nar1_approvals.SOURCE_STAFF_WAIVER)


def _decided_signer(case: dict) -> HTMLResponse | None:
    """The page to show when the CASE is settled, or None to carry on.

    Closed or declined -> "unavailable", with no reason, by the rule at the top
    of this file. Converged -> everyone has signed. An ND2B filed without
    confirmation is NOT settled: nobody confirmed, and the signatures still count.
    """
    if case.get("closed_at") or case.get("client_approved") is False:
        return _unavailable(_miss_for(case))
    if _converged(case):
        return _signer_all_signed(case)
    return None


def _signer_counts(case: dict) -> dict | None:
    """`{"signed", "required"}` for the round, or None when it cannot be read.

    A count that could not be read is left off the page; a wrong "1 of 2" would
    tell a director something false about a statutory filing.
    """
    try:
        frozen, _ = signers.signer_set(case)
        ids = {s["person_id"] for s in frozen}
        signed = {r.get("person_id") for r in signers.round_approvals(case)
                  if r.get("outcome") == nar1_approvals.OUTCOME_APPROVED}
        return {"signed": len(signed & ids), "required": len(ids)}
    except Exception as exc:  # noqa: BLE001 — a page must not 500 over a count
        print(f"[public_approval] could not count the signatures on case "
              f"{case.get('id')}: {exc}", file=sys.stderr)
        return None


def _signer_waiting(case: dict, counts: dict | None) -> HTMLResponse:
    """This director has signed; others have not. A count, never a name."""
    code, _what = _FORM_TITLES.get(case.get("form_code"), _FORM_TITLES["Nd2a"])
    company = _entity_or_empty(case).get("company_name") or ""
    counted = (f"{counts['signed']} of {counts['required']} directors have signed. "
               if counts else "")
    return _render(
        title="Signature recorded",
        heading="Thank you — your signature is recorded",
        sub=(f"Form {code} for {company} will be filed once the other directors "
             "have signed." if company else
             f"Form {code} will be filed once the other directors have signed."),
        body='<p class="done">Signature recorded.</p>'
             f'<p class="note">{counted}You will receive the signed form by email '
             "once everyone has signed.</p>")


def _signer_all_signed(case: dict) -> HTMLResponse:
    code, _what = _FORM_TITLES.get(case.get("form_code"), _FORM_TITLES["Nd2a"])
    company = _entity_or_empty(case).get("company_name") or ""
    return _render(
        title="Signed",
        heading="Thank you — every director has now signed",
        sub=f"We will file Form {code} for {company}." if company
            else f"We will file Form {code}.",
        body='<p class="done">All signatures recorded.</p>'
             '<p class="note">The signed form is on its way to you by email. If you '
             f"later notice something wrong, email {html.escape(RENEWAL_MAILBOX)} "
             "as soon as you can.</p>")


def _in_round(case: dict, row: dict) -> bool:
    frozen, _ = signers.signer_set(case)
    return row.get("person_id") in {s["person_id"] for s in frozen}


def _signer_ask(case: dict, row: dict, error: str = "") -> HTMLResponse:
    return _officer_change_ask(case, _entity_or_empty(case), row, error,
                               sign=True, note=_EACH_DIRECTOR_SIGNS)


async def _show_signer(resolved) -> HTMLResponse:
    """The GET. WRITES NOTHING -- a mail scanner fetching a director's link must
    neither sign for them nor retry a convergence."""
    row, case = resolved
    stale = _earlier_revision(row, case, _OFFICER_CHANGE_FORMS)
    if stale is not None:
        return stale
    if row.get("outcome") == nar1_approvals.OUTCOME_APPROVED:
        return _decided_signer(case) or _signer_waiting(case, _signer_counts(case))
    if row.get("outcome") or nar1_approvals.is_expired(row):
        return _decided_signer(case) or _unavailable(_miss_for(case))
    settled = _decided_signer(case)
    if settled is not None:
        return settled
    if not _in_round(case, row):
        return _unavailable(_miss_for(case))
    return _signer_ask(case, row)


async def _converge(case: dict, outcome: dict, background: BackgroundTasks | None) -> None:
    """What only the request that WON the convergence may do (spec 2.3, 2.6).

    Called with `record_signing`'s result when `won` is true: the leftover links,
    the status row, and ONE combined receipt per signer. Receipts go out here and
    not at each signature because `images_for` prints nothing until the case is
    approved -- a receipt at signing time would carry an unsigned copy.
    """
    revoked = None
    try:
        revoked = nar1_approvals.supersede_outstanding(case["id"])
    except Exception as exc:  # noqa: BLE001 — the case is approved; this is housekeeping
        print(f"[public_approval] could not supersede the leftover links on case "
              f"{case.get('id')}: {exc}", file=sys.stderr)
    entity = _entity_or_empty(case)
    approvals = outcome["approvals"]
    names = {s["person_id"]: s.get("name") for s in signers.signer_set(case)[0]}
    await log_event(
        user_id=None, user_display_name=ACTOR,
        action_type=ev.CASE_STATUS_CHANGED, event_code=ev.CASE_STATUS_CHANGED,
        case_id=case.get("entity_id"), entity_type="nar1_case", entity_id=case["id"],
        company_name=entity.get("company_name"), **audit_subject.for_case(case),
        old_value="awaiting_client", new_value="approved",
        metadata={
            "reason": "every required director has signed",
            "revision": case.get("verification_revision"),
            "signers": [{"person_id": a.get("person_id"),
                         "name": a.get("recipient_name") or names.get(a.get("person_id")),
                         "responded_at": a.get("responded_at")} for a in approvals],
            "approval_links_revoked": revoked,
        })
    if background is not None:
        for approval in approvals:
            background.add_task(send_receipt, case["id"], approval)


async def _after_signing(case: dict, outcome: dict,
                         background: BackgroundTasks | None) -> HTMLResponse:
    """Act on a counted round and choose the page: the convergence side effects
    for the one request that won, then everyone-signed or the waiting page."""
    if outcome["won"]:
        await _converge(case, outcome, background)
    if outcome["converged"]:
        return _signer_all_signed(case)
    counts = ({"signed": outcome["signed"], "required": outcome["required"]}
              if outcome["required"] else _signer_counts(case))
    return _signer_waiting(case, counts)


async def _record_signer(resolved, request: Request,
                         background: BackgroundTasks) -> HTMLResponse:
    """The POST: one director signs. Spec 2.5, steps 1 to 11."""
    row, case = resolved

    # 1. A link from an earlier revision records nothing.
    stale = _earlier_revision(row, case, _OFFICER_CHANGE_FORMS)
    if stale is not None:
        return stale

    # 2. This director already signed: a replay, or a second tab. Idempotent --
    # and the place a convergence that FAILED is retried (S6). The last signer's
    # UPDATE can fail after every claim has landed; nothing else would ever run
    # it again, and a fully signed case must never be stuck. `record_signing`
    # is conditional, so calling it for a case that already converged does
    # nothing and `won` is false.
    if row.get("outcome") == nar1_approvals.OUTCOME_APPROVED:
        settled = _decided_signer(case)
        if settled is not None:
            return settled
        return await _after_signing(case, signers.record_signing(case, row), background)

    # 3. Superseded or expired.
    if row.get("outcome") or nar1_approvals.is_expired(row):
        return _decided_signer(case) or _unavailable(_miss_for(case))

    # 4. Closed, declined or converged. A waiver carries on.
    settled = _decided_signer(case)
    if settled is not None:
        return settled

    # 5. Defence in depth: multi-signer links are only ever issued to signers.
    if not _in_round(case, row):
        return _unavailable(_miss_for(case))

    # 6. The drawing is ALWAYS required: membership of the set is what puts a
    # person on a box. Validated before the claim, which cannot be undone.
    field = await _read_signature_field(request)
    try:
        drawn = _Signature(required=True, png=signatures.decode(field))
    except signatures.SignatureError as exc:
        print(f"[public_approval] signature refused on case {case.get('id')}: {exc}",
              file=sys.stderr)
        return _signer_ask(case, row, _SIGNATURE_RETRY)

    # 7. This director's claim, settled by Postgres. If it was lost, this
    # director's other tab answered the row between our read and now.
    claimed = nar1_approvals.claim(
        row["id"], ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"))
    if claimed is None:
        now = next((r for r in signers.round_approvals(case)
                    if r.get("id") == row["id"]), None)
        if now and now.get("outcome") == nar1_approvals.OUTCOME_APPROVED:
            return _decided_signer(case) or _signer_waiting(case, _signer_counts(case))
        return _unavailable(_miss_for(case))

    # 8. Kept only past the claim, then counted.
    signature = _keep_signature(drawn, case, row, claimed)
    outcome = signers.record_signing(case, claimed)

    # 9. The director's act, in the same words as a single-mode approval.
    name = claimed.get("recipient_name") or row.get("recipient_name")
    entity = _entity_or_empty(case)
    await log_event(
        user_id=None,
        user_display_name=name or claimed.get("recipient_email") or "Client",
        action_type=ev.CLIENT_APPROVAL_SELF_SERVICE,
        event_code=ev.CLIENT_APPROVAL_SELF_SERVICE,
        case_id=case.get("entity_id"), entity_type="nar1_case", entity_id=case["id"],
        company_name=entity.get("company_name"), **audit_subject.for_case(case),
        new_value="approved",
        metadata={
            "case_no": case.get("case_no"),
            "person_id": claimed.get("person_id"),
            "recipient_email": claimed.get("recipient_email"),
            "ip_address": claimed.get("ip_address"),
            "user_agent": claimed.get("user_agent"),
            "responded_at": claimed.get("responded_at"),
            "channel": "self_service",
            "revision": claimed.get("revision", row.get("revision")),
            "signature": signature,
            "multi_signer": {"signed": outcome["signed"],
                             "required": outcome["required"],
                             "converged": outcome["converged"]},
        })

    # 10 and 11.
    return await _after_signing(case, outcome, background)
