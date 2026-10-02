"""The page where a new director signs their consent to act (Jacqueline A2).

Reached from a button in that director's own verification email. Every rule of
the Confirm page (`routers/public_approval.py`) holds here, and the helpers are
that module's, not copies:

  * GET WRITES NOTHING. A mail-security scanner that fetches every link must
    leave the case, the token and the audit trail exactly as they were.
  * NO SCRIPT. An unauthenticated page from a link in an email has the smallest
    attack surface when it has none; the form posts to the path it is on, so
    the token never appears in the HTML.
  * ONE ANSWER FOR EVERY MISS — unknown, malformed, superseded, expired,
    rate-limited, closed case — so the route cannot be used to learn which
    links exist.
  * NO CREDENTIAL IS ASKED FOR. The director types their name and ticks CR's
    statement; nothing on the page is worth phishing for.

The POST takes exactly two fields, the typed name and the tick. A name that is
not the one on the form is refused on the page with the case unchanged.
"""
from __future__ import annotations

import html
import sys

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from db.supabase import get_supabase
from routers.public_approval import (
    _client_ip, _hkt, _rate_limited, _render, _unavailable,
)
from services import audit_events as ev, audit_subject, nar1_cases
from services.audit_service import log_event
from services.email_service import RENEWAL_MAILBOX
from services.officer_changes import econsent
from services.officer_changes.deadlines import _as_date

router = APIRouter()
_MISS = "this form"


def _resolve(token: str, request: Request):
    """`(row, case, entry, person)` or None — every failure identically."""
    if _rate_limited(f"c:{token}", f"ip:{_client_ip(request) or 'unknown'}"):
        return None
    try:
        row = econsent.find(token)
    except Exception as exc:  # noqa: BLE001 — never a stack trace at a client
        print(f"[public_consent] token lookup failed: {exc}", file=sys.stderr)
        return None
    if row is None:
        return None
    try:
        case = nar1_cases.get_case(row["case_id"])
    except Exception:  # noqa: BLE001
        return None
    if case.get("form_code") != "Nd2a" or case.get("closed_at"):
        return None
    sb = get_supabase()
    entries = (sb.table("officer_change_entries").select("*").eq("id", row["entry_id"])
               .execute().data) or []
    entry = entries[0] if entries else None
    if not entry or entry.get("kind") != "appointment" or not entry.get("person_id"):
        return None
    people = (sb.table("persons").select("*").eq("id", entry["person_id"])
              .execute().data) or []
    return row, case, entry, (people[0] if people else {})


def _entity(case: dict) -> dict:
    try:
        return nar1_cases.entity_for(case["entity_id"]) or {}
    except Exception:  # noqa: BLE001
        return {}


def _ask(case: dict, entry: dict, person: dict, *, error: str = "",
         typed: str = "") -> HTMLResponse:
    entity = _entity(case)
    when = _as_date(entry.get("effective_date"))
    rows = [("Company", entity.get("company_name")),
            ("Business Registration No.", entity.get("br_number")),
            ("Name on the form", person.get("full_name")),
            ("Capacity", "Director"),
            ("Effective date", f"{when.day} {when:%B %Y}" if when else "To be confirmed"),
            ("Our reference", case.get("case_no"))]
    ledger = "".join(f"<dt>{html.escape(label)}</dt><dd>{html.escape(str(value))}</dd>"
                     for label, value in rows if value)
    problem = (f'<p class="stop" role="alert">{html.escape(error)}</p>' if error else "")
    field = ("display:block;width:100%;box-sizing:border-box;margin:6px 0 14px;"
             "padding:11px 12px;border:1px solid #E2E4ED;border-radius:8px;"
             "font-size:16px;color:#1A2050")
    body = (
        f"<dl>{ledger}</dl>{problem}"
        '<form method="post"><div class="warn">'
        '<div class="warn-top"><div>'
        '<p class="warn-h">Consent to act as director</p>'
        f'<p class="warn-t">{html.escape(econsent.STATEMENT)}</p>'
        '</div></div>'
        '<div style="padding:4px 22px 18px">'
        '<label for="full_name" style="font-size:13px;font-weight:600;color:#1A2050">'
        "Type your full name to sign</label>"
        f'<input id="full_name" name="full_name" autocomplete="name" required '
        f'value="{html.escape(typed, quote=True)}" style="{field}">'
        '<label style="display:flex;gap:10px;align-items:flex-start;font-size:14px">'
        '<input type="checkbox" name="agree" value="on" required style="margin-top:3px">'
        "<span>I confirm the statement above.</span></label></div>"
        '<div class="warn-foot"><button type="submit">Sign consent</button></div>'
        "</div></form>"
        '<p class="note">This signature is recorded electronically in G-FlowDesk with the '
        "date, time and your IP address. If anything is wrong, do not sign — email "
        f"{html.escape(RENEWAL_MAILBOX)}.</p>")
    return _render(title="Consent to act as director",
                   heading="Consent to act as director",
                   sub="Please check the details below, then sign.", body=body)


def _already(row: dict) -> HTMLResponse:
    when = _hkt(row.get("signed_at"))
    return _render(title="Consent recorded", heading="Your consent is already recorded",
                   sub="Nothing more is needed from you.",
                   body=f'<p class="done">Signed{f" on {html.escape(when)}" if when else ""}'
                        "</p>")


def _thanks(name: str) -> HTMLResponse:
    return _render(title="Consent recorded", heading="Thank you — your consent is recorded",
                   sub="You do not need to do anything else.",
                   body=f'<p class="done">Signed by {html.escape(name)}.</p>'
                        '<p class="note">If you later notice something wrong, email '
                        f"{html.escape(RENEWAL_MAILBOX)} as soon as you can.</p>")


@router.get("/officer-consent/{token}", response_class=HTMLResponse)
async def show_consent(token: str, request: Request):
    """WRITES NOTHING — see the module docstring."""
    resolved = _resolve(token, request)
    if resolved is None:
        return _unavailable(_MISS)
    row, case, entry, person = resolved
    if row.get("signed_at"):
        return _already(row)
    if not econsent.usable(row):
        return _unavailable(_MISS)
    return _ask(case, entry, person)


@router.post("/officer-consent/{token}", response_class=HTMLResponse)
async def sign_consent(token: str, request: Request):
    resolved = _resolve(token, request)
    if resolved is None:
        return _unavailable(_MISS)
    row, case, entry, person = resolved
    if row.get("signed_at"):
        return _already(row)
    if not econsent.usable(row):
        return _unavailable(_MISS)
    try:
        form = await request.form()
    except Exception:  # noqa: BLE001 — an unreadable body is an empty one
        form = {}
    typed = str(form.get("full_name") or "")[:200]
    if str(form.get("agree") or "") != "on":
        return _ask(case, entry, person, typed=typed,
                    error="Tick the statement to sign.")
    ip, agent = _client_ip(request), request.headers.get("user-agent")
    try:
        result = await econsent.sign(row, case, entry, person, typed_name=typed, ip=ip,
                                     user_agent=agent)
    except econsent.NameMismatch:
        return _ask(case, entry, person, typed=typed,
                    error="The name must match the name on the form: "
                          f"{person.get('full_name') or ''}.")
    if result.get("already"):
        return _already(econsent.find(token) or row)
    entity = _entity(case)
    try:
        await log_event(
            user_id=None, user_display_name=" ".join(typed.split()),
            action_type=ev.OFFICER_ECONSENT_SIGNED, event_code=ev.OFFICER_ECONSENT_SIGNED,
            case_id=case.get("entity_id"), entity_type="nar1_case", entity_id=case["id"],
            company_name=entity.get("company_name"), **audit_subject.for_case(case),
            new_value="signed",
            metadata={"case_no": case.get("case_no"), "entry_id": entry["id"],
                      "person_id": entry.get("person_id"), "ip_address": ip,
                      "user_agent": agent, "signed_at": result.get("signed_at"),
                      "revision": row.get("revision"),
                      "document_id": result.get("document_id"),
                      "pdf_error": result.get("error"), "channel": "self_service"})
    except Exception as exc:  # noqa: BLE001 — the signature stands
        print(f"[public_consent] audit failed: {exc!r}", file=sys.stderr)
    return _thanks(" ".join(typed.split()))
