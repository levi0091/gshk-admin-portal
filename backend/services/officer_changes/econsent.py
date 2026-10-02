"""A new director's consent to act, signed in G-FlowDesk (Jacqueline A2).

"The proposed director must pen/e-sign page 2 of the ND2A form ... we must
collect the signed page 2 before submitting the form to CR ... Is there any
chance they can sign directly from the system?"

WHO GETS A LINK. A new natural-person DIRECTOR with an email address and no
complete e-Registry account stored. Where GSHK holds the account, GSHK applies
CR's own consent signature from it at Signing and the client signs nothing
(A5: "this part will not require the client to complete the e-signature").

WHY A LINK OF ITS OWN. The first director to press Confirm supersedes every
other Confirm link on the case — one form, one approval. The incoming director
must still be able to sign their consent after that, so the consent link is a
separate token in a separate table, superseded only by the next send, a
restart, or closing the case.

WHAT SIGNING PRODUCES. The ND2A the client was sent, cut to the page carrying
that director's consent box (page 2 for the first natural-person appointment,
a Continuation Sheet B for each one after), with their typed name and a
"signed electronically" line drawn into the box, plus a one-page signature
record (name typed, time, IP address, browser, case, revision). It is filed as
the entry's *Consent to act* document, which is what Data Verification's
consent check reads. Rendering is best-effort: a failure still records the
signature, and staff can produce the PDF again.

Only the token's SHA-256 is stored, as for the Confirm links.
"""
from __future__ import annotations

import hmac
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone

import pymupdf

from db.supabase import get_supabase
from services import nar1_approvals
from services.officer_changes import documents

_TABLE = "officer_change_consents"
_TOKEN_BYTES = 32
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,128}$")
_HKT = timezone(timedelta(hours=8))

#: CR's own words, from the consent box on page 2 of Form ND2A.
STATEMENT = ("I consent to act as director of this company and confirm that I have "
             "attained the age of 18 years.")


class NameMismatch(ValueError):
    """The typed name is not the name on the form."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# -- who, and the tokens ------------------------------------------------------------

def _complete(account: dict | None) -> bool:
    account = account or {}
    return bool(account.get("eservice_user_id") and account.get("eservice_person_name")
                and account.get("has_password"))


def eligible(entries: list[dict], eservice_meta: dict[str, dict],
             emails: dict[str, str], *, esign_case: bool = True) -> list[dict]:
    """New natural-person directors with an email and no complete account —
    or, when the CASE cannot go e-Sign at all (another director has no
    account, an overseas corporate director), every one of them: a stored
    account is then never used, and the manual route needs their consent
    (review finding 4)."""
    return [e for e in entries
            if e.get("kind") == "appointment" and e.get("capacity") == "director"
            and e.get("person_id") and emails.get(e["person_id"])
            and (not esign_case or not _complete(eservice_meta.get(e["person_id"])))]


def supersede(case_id: str) -> int:
    """Every unsigned, live link for the case stops working. A SIGNED consent
    is never touched: it is a signature, not an invitation."""
    rows = (get_supabase().table(_TABLE).update({"superseded_at": _now().isoformat()})
            .eq("case_id", case_id).is_("signed_at", "null").is_("superseded_at", "null")
            .execute().data) or []
    return len(rows)


def issue(case_id: str, entries: list[dict], *, revision: int | None,
          expires_at: datetime | None) -> dict[str, str]:
    """`{entry_id: plaintext token}`, after superseding the case's live links."""
    supersede(case_id)
    out = {}
    for entry in entries:
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        get_supabase().table(_TABLE).insert({
            "case_id": case_id, "entry_id": entry["id"], "person_id": entry.get("person_id"),
            "token_hash": nar1_approvals.hash_token(token), "revision": revision,
            "issued_at": _now().isoformat(),
            "expires_at": expires_at.isoformat() if expires_at else None,
        }).execute()
        out[entry["id"]] = token
    return out


def find(token: str) -> dict | None:
    if not _TOKEN.match(token or ""):
        return None
    digest = nar1_approvals.hash_token(token)
    rows = (get_supabase().table(_TABLE).select("*").eq("token_hash", digest)
            .execute().data) or []
    row = rows[0] if rows else None
    if row is None or not hmac.compare_digest(row.get("token_hash") or "", digest):
        return None
    return row


def _expired(row: dict) -> bool:
    value = row.get("expires_at")
    if not value:
        return False
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return True
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment < _now()


def usable(row: dict) -> bool:
    """Not superseded and not expired. (A signed row is answered separately.)"""
    return not row.get("superseded_at") and not _expired(row)


def status_for(case_id: str) -> dict[str, dict]:
    """`{entry_id: {sent, signed_at, signed_name, document_id}}` — a signed row
    wins over any later unsigned one."""
    rows = (get_supabase().table(_TABLE).select("*").eq("case_id", case_id)
            .execute().data) or []
    out: dict[str, dict] = {}
    for row in sorted(rows, key=lambda r: r.get("issued_at") or ""):
        current = out.get(row["entry_id"])
        if current and current.get("signed_at"):
            continue
        out[row["entry_id"]] = {"sent": True, "signed_at": row.get("signed_at"),
                                "signed_name": row.get("signed_name"),
                                "document_id": row.get("document_id"),
                                "consent_id": row.get("id")}
    return out


# -- signing ------------------------------------------------------------------------

def _norm(value) -> str:
    return " ".join(str(value or "").split()).casefold()


def names_match(typed: str, person: dict) -> bool:
    """The name on the form, case and spacing ignored — full name, or surname
    followed by given names."""
    wanted = _norm(typed)
    if not wanted:
        return False
    names = {_norm(person.get("full_name")),
             _norm(f"{person.get('surname') or ''} {person.get('given_names') or ''}")}
    return wanted in {n for n in names if n}


def claim(consent_id: str, *, typed_name: str, ip: str | None,
          user_agent: str | None) -> dict | None:
    """First signature wins, settled by the conditional UPDATE."""
    rows = (get_supabase().table(_TABLE).update({
        "signed_at": _now().isoformat(), "signed_name": " ".join(typed_name.split()),
        "ip_address": ip, "user_agent": (user_agent or "")[:500] or None,
    }).eq("id", consent_id).is_("signed_at", "null").execute().data) or []
    return rows[0] if rows else None


async def sign(row: dict, case: dict, entry: dict, person: dict, *, typed_name: str,
               ip: str | None, user_agent: str | None) -> dict:
    """Record the signature, then file the stamped consent. `NameMismatch`
    before anything is written; `{"already": True}` when it was signed."""
    if not names_match(typed_name, person):
        raise NameMismatch("The name must match the name on the form")
    claimed = claim(row["id"], typed_name=typed_name, ip=ip, user_agent=user_agent)
    if claimed is None:
        return {"already": True, "document_id": None, "error": None}
    result = {"already": False, "signed_at": claimed.get("signed_at"),
              "document_id": None, "error": None}
    try:
        pdf = await consent_pdf(case, entry, claimed)
        doc = await documents.upload(
            case, entry, document_type_code="consent_to_act",
            file_name=f"Consent-to-act-{_file_safe(typed_name)}.pdf", content=pdf,
            mime_type="application/pdf", user=None, source="econsent",
            uploaded_by_name=typed_name)
        get_supabase().table(_TABLE).update({"document_id": doc["id"]}) \
            .eq("id", claimed["id"]).execute()
        result["document_id"] = doc["id"]
    except Exception as exc:  # noqa: BLE001 — the signature stands; see docstring
        print(f"[econsent] consent PDF for {claimed.get('id')} not produced: {exc!r}",
              file=sys.stderr)
        result["error"] = str(exc)
    return result


async def regenerate(case: dict, entry: dict) -> str:
    """Produce and file the PDF for a consent signed when rendering failed.
    `LookupError` when the entry has no signed consent."""
    rows = (get_supabase().table(_TABLE).select("*").eq("case_id", case["id"])
            .eq("entry_id", entry["id"]).execute().data) or []
    signed = next((r for r in rows if r.get("signed_at")), None)
    if signed is None:
        raise LookupError("This director has not signed a consent in G-FlowDesk")
    pdf = await consent_pdf(case, entry, signed)
    name = signed.get("signed_name") or "director"
    doc = await documents.upload(
        case, entry, document_type_code="consent_to_act",
        file_name=f"Consent-to-act-{_file_safe(name)}.pdf", content=pdf,
        mime_type="application/pdf", user=None, source="econsent", uploaded_by_name=name)
    get_supabase().table(_TABLE).update({"document_id": doc["id"]}) \
        .eq("id", signed["id"]).execute()
    return doc["id"]


def _file_safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-") or "director"


# -- the stamped page ---------------------------------------------------------------

def _consent_index(case_id: str, entry: dict) -> int:
    """The entry's position among the case's natural-person appointments — the
    order the ND2A prints them in (page 2, then one Sheet B each)."""
    rows = (get_supabase().table("officer_change_entries").select("*")
            .eq("case_id", case_id).execute().data) or []
    rows.sort(key=lambda r: (r.get("sort_order") or 0, r.get("created_at") or ""))
    natural = [r["id"] for r in rows if r.get("kind") == "appointment" and r.get("person_id")]
    return natural.index(entry["id"]) + 1 if entry["id"] in natural else 1


async def consent_pdf(case: dict, entry: dict, signed: dict) -> bytes:
    """The stamped consent page of the ND2A the client was sent."""
    import asyncio

    from services import nar1_cases
    from services.officer_change_form import page_plan, render
    from services.officer_changes import cases as svc, prepare

    xml = case.get("verification_xml") or await prepare.build_form_xml(
        case, svc.list_entries(case["id"]))
    entity = nar1_cases.entity_for(case["entity_id"]) or {}
    name = "  ".join(p for p in (entity.get("company_name"), entity.get("company_name_zh")) if p)
    pdf = await asyncio.to_thread(render, "Nd2a", xml, company_name=name, public_only=True)
    sheets = [p["sheet"] for p in page_plan("Nd2a", xml, public_only=True)]
    when = datetime.fromisoformat(str(signed.get("signed_at")).replace("Z", "+00:00")) \
        if signed.get("signed_at") else None
    return stamp(pdf, sheets, consent_index=_consent_index(case["id"], entry),
                 name=signed.get("signed_name") or "", when=when,
                 ip=signed.get("ip_address"), user_agent=signed.get("user_agent"),
                 case_no=case.get("case_no") or "", revision=signed.get("revision"))


def _page_for(sheets: list[str], consent_index: int) -> int:
    if consent_index <= 1:
        return sheets.index("2")
    b_pages = [i for i, s in enumerate(sheets) if s == "B"]
    return b_pages[consent_index - 2]


def stamp(pdf: bytes, sheets: list[str], *, consent_index: int, name: str, when,
          ip: str | None, user_agent: str | None, case_no: str, revision) -> bytes:
    """Two pages: the director's consent page with the signature drawn into the
    "Signed" box, and the signature record."""
    source = pymupdf.open(stream=pdf, filetype="pdf")
    out = pymupdf.open()
    out.insert_pdf(source, from_page=_page_for(sheets, consent_index),
                   to_page=_page_for(sheets, consent_index))
    page = out[0]
    hits = page.search_for("Signed")
    stamp_time = (when.astimezone(_HKT).strftime("%d %b %Y %H:%M HKT") if when
                  else "date not recorded")
    if hits:
        box = hits[-1]
        page.insert_text((box.x1 + 14, box.y1 - 3), name, fontname="tiit", fontsize=13,
                         color=(0.10, 0.13, 0.31))
        # Inside the box, just above the name: below it is the box's border.
        page.insert_text((box.x1 + 14, box.y0 - 6),
                         f"Signed electronically via G-FlowDesk · {stamp_time}",
                         fontname="helv", fontsize=6.5, color=(0.30, 0.32, 0.42))
    record = out.new_page(width=page.rect.width, height=page.rect.height)
    lines = [("Signature record", 16, "hebo"),
             ("Consent to act as director - Form ND2A", 11, "helv"), ("", 8, "helv"),
             (f"Statement: {STATEMENT}", 9.5, "helv"),
             (f"Name typed: {name}", 9.5, "helv"),
             (f"Signed at: {stamp_time}", 9.5, "helv"),
             (f"IP address: {ip or 'not recorded'}", 9.5, "helv"),
             (f"Browser: {(user_agent or 'not recorded')[:110]}", 9.5, "helv"),
             (f"Case: {case_no}" + (f" · Revision {revision}" if revision else ""), 9.5, "helv"),
             ("", 8, "helv"),
             ("Signed electronically in G-FlowDesk by typing the name above and ticking the "
              "statement.", 8.5, "helv")]
    y = 72
    for text, size, font in lines:
        if text:
            record.insert_textbox(pymupdf.Rect(60, y, record.rect.width - 60, y + 60), text,
                                  fontname=font, fontsize=size)
        y += size * 1.9 if len(text) < 95 else size * 3.4
    data = out.tobytes(garbage=3, deflate=True)
    source.close()
    out.close()
    return data
