"""ND2A / ND2B officer-change cases: the case, its change list, supporting
documents, client verification and closing (spec §5; plan contract C-3).

Permission module `officer_changes` (migration 050), seeded for every role that
holds the matching `nar1` level: preparing a change of officers is the same
kind of work as preparing an annual return, but it is a different authority —
a role may be trusted with one and not the other. The CR steps (validate, sign,
file) live in `routers/officer_change_filing.py` behind `tpsi:*`.

Audit rows use NAR1's convention (`routers/cases._audit_target`): the CASE id
in `entity_id`, the COMPANY id in `case_id`, so an officer change appears on
the company's trail beside its annual returns.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel

from middleware.auth import require_permission
from routers import cases as nar1_router
from services import (
    audit_events as ev, email_service, nar1_approvals, nar1_cases,
)
from services.audit_service import log_event
from services.officer_change_form import FormFillError, render as render_form
from services.officer_changes import (
    cases as svc, documents, emails, eservice, prepare,
    recipients as recipients_svc, resolution,
)
from services.tpsi import filings as tpsi_filings
from services.tpsi.forms.cr_vocabularies import CAPACITY_BODY_CORPORATE, CAPACITY_INDIVIDUAL

router = APIRouter()
MODULE = "officer_changes"
MAX_RECIPIENTS = nar1_router.MAX_RECIPIENTS


# -- shared helpers (Task 8's router imports these) ------------------------------------

def load_case(case_id: str) -> dict:
    """The officer-change case, or 404 — a NAR1 case id included."""
    try:
        return svc.get_case(case_id)
    except LookupError:
        raise HTTPException(404, "Officer-change case not found")


def refuse_if_closed(case: dict, action: str) -> None:
    if case.get("closed_at"):
        raise HTTPException(409, {
            "message": (f"case {case.get('case_no')} was closed and cannot be changed "
                        f"— {action} would write to a case that was permanently ended."),
            "reason": "case_closed"})


def refused(exc: svc.CaseRefused) -> HTTPException:
    return HTTPException(409, {"message": exc.message, "reason": exc.reason})


async def audit(case: dict, user: dict, action_type: str, **fields) -> None:
    """One audit row; a failure is logged and never fails the request (PBI-11)."""
    try:
        await log_event(user_id=user["id"], user_display_name=user["display_name"],
                        action_type=action_type, event_code=action_type,
                        **nar1_router._audit_target(case), **fields)
    except Exception as exc:  # noqa: BLE001
        print(f"[officer_changes] audit {action_type} failed: {exc!r}", file=sys.stderr)


async def respond(case_id: str, user: dict) -> dict:
    return await svc.composite(case_id, user=user)


def filed(case: dict) -> bool:
    if case.get("manual_receipt") or case.get("changes_applied_at"):
        return True
    filing = nar1_cases.current_filing(case["id"])
    return bool(filing and filing.get("stage") in nar1_cases.CR_FILED_STAGES)


# -- the case ----------------------------------------------------------------------------

class CaseCreateIn(BaseModel):
    class Config:
        extra = "forbid"

    entity_id: str
    form_code: str
    entry: dict | None = None


@router.post("", status_code=201)
async def create_case(body: CaseCreateIn,
                      user=Depends(require_permission(MODULE, "write"))):
    try:
        case, reused = svc.create_case(entity_id=body.entity_id, form_code=body.form_code,
                                       user_id=user["id"])
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not reused:
        await audit(case, user, ev.CASE_STATUS_CHANGED, old_value=None,
                    new_value="client_verification",
                    metadata={"case_no": case.get("case_no"), "form_code": body.form_code,
                              "reason": "officer-change case opened"})
    if body.entry:
        try:
            entry = svc.add_entry(case, body.entry, user_id=user["id"])
        except svc.CaseRefused as exc:
            raise refused(exc)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        await _audit_entry(case, user, ev.OFFICER_CHANGE_ADDED, entry)
    return {"case": await respond(case["id"], user), "reused": reused}


@router.get("/pending")
async def pending(entity_id: str | None = Query(None), person_id: str | None = Query(None),
                  user=Depends(require_permission(MODULE, "read"))):
    if not (entity_id or person_id):
        raise HTTPException(400, "Name a company (entity_id) or a person (person_id)")
    return {"cases": svc.open_cases_for(entity_id=entity_id, person_id=person_id)}


@router.get("/{case_id}")
async def get_case(case_id: str, user=Depends(require_permission(MODULE, "read"))):
    case = load_case(case_id)
    if case.get("form_code") == "Nd2b" and svc.editable(case):
        # The profile may have moved since the page last looked (answer 14):
        # edited back, a line disappears; edited again, it appears.
        svc.refresh_items(case, svc.list_entries(case_id))
    return await respond(case_id, user)


class CasePatchIn(BaseModel):
    class Config:
        extra = "forbid"

    signing_method: str | None = None
    signatory_capacity: str | None = None
    restart_verification: bool | None = None


@router.patch("/{case_id}")
async def patch_case(case_id: str, body: CasePatchIn,
                     user=Depends(require_permission(MODULE, "write"))):
    case = load_case(case_id)
    refuse_if_closed(case, "changing it")
    if filed(case):
        raise HTTPException(409, {"message": "This form has been filed.",
                                  "reason": "already_filed"})
    patch: dict = {}
    if body.signing_method is not None:
        if body.signing_method not in ("esign", "manual"):
            raise HTTPException(400, "signing_method is 'esign' or 'manual'")
        if body.signing_method == "esign":
            plan = await prepare.consent_plan(case, svc.list_entries(case_id))
            missing = [c["reason"] for c in plan if not c.get("ready")]
            if missing:
                raise HTTPException(409, {"message": "e-Sign is not available: "
                                                     + "; ".join(missing),
                                          "reason": "esign_unavailable"})
        if body.signing_method != case.get("signing_method"):
            patch["signing_method"] = body.signing_method
            # The two routes check different things (the manual route needs
            # each new director's consent document), so a data check made for
            # one does not carry to the other (review finding 1).
            if case.get("data_checked_at"):
                patch["data_checked_at"] = None
                patch["data_checked_by"] = None
    if body.signatory_capacity is not None:
        capacity = body.signatory_capacity.strip()
        # The vocabulary of THIS signer: CR takes any string here and refuses a
        # capacity of the wrong kind only after the form is submitted.
        _, is_corporate = svc._signatory_party(case["entity_id"])
        valid = CAPACITY_BODY_CORPORATE if is_corporate else CAPACITY_INDIVIDUAL
        if capacity and capacity not in valid:
            kind = "a body corporate" if is_corporate else "a natural person"
            raise HTTPException(400, f"signatory_capacity {capacity!r} is not one of CR's "
                                     f"capacities for {kind} signing")
        if capacity != (case.get("signatory_capacity") or ""):
            patch["signatory_capacity"] = capacity or None
    for field, new in patch.items():
        await audit(case, user, ev.CASE_FIELD_UPDATED, old_value=case.get(field),
                    new_value=new, metadata={"field": field, "case_no": case.get("case_no")})
    if body.restart_verification:
        await _restart(case, user, patch)
    elif patch:
        nar1_cases.update_case(case_id, patch)
    return await respond(case_id, user)


async def _restart(case: dict, user: dict, patch: dict) -> None:
    """Back to an editable change list: outstanding links stop working, any
    live filing is superseded (what the client approved is no longer what will
    be filed), the client's answer and every signing artefact are cleared."""
    links = nar1_approvals.supersede_outstanding(case["id"])
    superseded = tpsi_filings.supersede_all_for_case(case["id"])
    nar1_cases.update_case(case["id"], {
        **patch, "verification_sent_at": None, "verification_xml": None,
        "client_approved": None, "client_response_at": None,
        "client_approval_source": None, "client_approval_person_id": None,
        "client_approval_name": None, "data_checked_at": None, "data_checked_by": None,
        "manual_signed_document_id": None, "manual_signed_document_version": None,
    })
    for entry in svc.list_entries(case["id"]):
        if entry.get("consent_signed_at"):
            svc.get_supabase().table("officer_change_entries").update(
                {"consent_signed_at": None}).eq("id", entry["id"]).execute()
    await audit(case, user, ev.CASE_STATUS_CHANGED, old_value=None,
                new_value="client_verification",
                metadata={"reason": "verification restarted", "case_no": case.get("case_no"),
                          "approval_links_revoked": links, "filings_superseded": superseded})


# -- the change list -------------------------------------------------------------------

def _entry_metadata(entry: dict) -> dict:
    """What an entry is, for the trail: the officer and the act, never an
    identity number or an address."""
    meta = {"entry_id": entry.get("id"), "kind": entry.get("kind"),
            "capacity": entry.get("capacity"), "party_type": entry.get("party_type"),
            "person_id": entry.get("person_id"),
            "corporate_entity_id": entry.get("corporate_entity_id"),
            "effective_date": entry.get("effective_date"),
            "items": [i.get("key") for i in entry.get("items") or []]}
    if entry.get("promoted_from_register"):
        # Ceasing a register-only secretary wrote an officer row mirroring it
        # (cases._promote_register_secretary). A profile write, so it is named.
        meta["promoted_from_register"] = entry["promoted_from_register"]
    return meta


async def _audit_entry(case, user, action, entry, before=None, after=None):
    await audit(case, user, action, new_value=entry.get("kind"),
                before_state=before, after_state=after, metadata=_entry_metadata(entry))


@router.post("/{case_id}/entries")
async def add_entry(case_id: str, body: dict,
                    user=Depends(require_permission(MODULE, "write"))):
    case = load_case(case_id)
    refuse_if_closed(case, "adding to its change list")
    try:
        entry = svc.add_entry(case, body, user_id=user["id"])
    except svc.CaseRefused as exc:
        raise refused(exc)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await _audit_entry(case, user, ev.OFFICER_CHANGE_ADDED, entry)
    return await respond(case_id, user)


@router.patch("/{case_id}/entries/{entry_id}")
async def update_entry(case_id: str, entry_id: str, body: dict,
                       user=Depends(require_permission(MODULE, "write"))):
    case = load_case(case_id)
    refuse_if_closed(case, "editing its change list")
    try:
        before, after = svc.update_entry(case, entry_id, body, user_id=user["id"])
    except svc.CaseRefused as exc:
        raise refused(exc)
    except LookupError:
        raise HTTPException(404, "Entry not found on this case")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    changed = sorted(k for k in after if after.get(k) != before.get(k)
                     and k not in ("updated_at",))
    await _audit_entry(case, user, ev.OFFICER_CHANGE_UPDATED, after,
                       before={k: before.get(k) for k in changed},
                       after={k: after.get(k) for k in changed})
    return await respond(case_id, user)


@router.delete("/{case_id}/entries/{entry_id}")
async def remove_entry(case_id: str, entry_id: str,
                       user=Depends(require_permission(MODULE, "write"))):
    case = load_case(case_id)
    refuse_if_closed(case, "removing from its change list")
    try:
        gone = svc.remove_entry(case, entry_id)
    except svc.CaseRefused as exc:
        raise refused(exc)
    except LookupError:
        raise HTTPException(404, "Entry not found on this case")
    await _audit_entry(case, user, ev.OFFICER_CHANGE_REMOVED, gone)
    return await respond(case_id, user)


class KycIn(BaseModel):
    cleared: bool


@router.post("/{case_id}/entries/{entry_id}/kyc")
async def set_kyc(case_id: str, entry_id: str, body: KycIn,
                  user=Depends(require_permission(MODULE, "write"))):
    case = load_case(case_id)
    refuse_if_closed(case, "recording KYC on it")
    try:
        entry = svc.set_kyc(case, entry_id, body.cleared, user_id=user["id"])
    except svc.CaseRefused as exc:
        raise refused(exc)
    except LookupError:
        raise HTTPException(404, "Entry not found on this case")
    await audit(case, user, ev.CASE_FIELD_UPDATED, new_value=str(body.cleared).lower(),
                metadata={"field": "kyc_cleared", **_entry_metadata(entry)})
    return await respond(case_id, user)


class EffectiveDateIn(BaseModel):
    class Config:
        extra = "forbid"

    effective_date: str
    #: An ND2B line's key; absent for a cessation or an appointment.
    item_key: str | None = None


@router.put("/{case_id}/entries/{entry_id}/effective-date")
async def set_effective_date(case_id: str, entry_id: str, body: EffectiveDateIn,
                             user=Depends(require_permission(MODULE, "write"))):
    """Fill in a date that was blank when the client was sent the form
    (Jacqueline A1) — at Signing, before anything is signed or filed."""
    case = load_case(case_id)
    refuse_if_closed(case, "dating a change on it")
    try:
        before, after = svc.set_effective_date(case, entry_id, body.effective_date,
                                               item_key=body.item_key, user_id=user["id"])
    except svc.CaseRefused as exc:
        raise refused(exc)
    except LookupError:
        raise HTTPException(404, "Entry not found on this case")
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    def date_of(row):
        if body.item_key:
            return next((i.get("effective_date") for i in row.get("items") or []
                         if i.get("key") == body.item_key), None)
        return row.get("effective_date")

    await audit(case, user, ev.CASE_FIELD_UPDATED, old_value=date_of(before),
                new_value=date_of(after),
                metadata={"field": "effective_date", "item_key": body.item_key,
                          "deferred": True, **_entry_metadata(after)})
    return await respond(case_id, user)


# -- supporting documents (answers 7, 11, 13) ---------------------------------------------

@router.post("/{case_id}/entries/{entry_id}/documents")
async def upload_document(case_id: str, entry_id: str, file: UploadFile = File(...),
                          document_type_code: str = Form(...),
                          user=Depends(require_permission(MODULE, "write"))):
    case = load_case(case_id)
    refuse_if_closed(case, "uploading to it")
    entry = next((e for e in svc.list_entries(case_id) if e["id"] == entry_id), None)
    if entry is None:
        raise HTTPException(404, "Entry not found on this case")
    content = await file.read()
    try:
        row = await documents.upload(case, entry, document_type_code=document_type_code,
                                     file_name=file.filename or "file", content=content,
                                     mime_type=file.content_type, user=user)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await audit(case, user, ev.OFFICER_SUPPORT_DOC_UPLOADED, new_value=row["file_name"],
                metadata={"document_id": row["id"], "document_type_code": document_type_code,
                          **_entry_metadata(entry)})
    return await respond(case_id, user)


@router.post("/{case_id}/documents")
async def upload_case_document(case_id: str, file: UploadFile = File(...),
                               document_type_code: str = Form(...),
                               send_with_email: str = Form("false"),
                               user=Depends(require_permission(MODULE, "write"))):
    """A document for the whole form — the written resolution, or anything else
    GSHK sends with the client email (Jacqueline A3). Held on the case; filed to
    the company's profile when the form is filed."""
    case = load_case(case_id)
    refuse_if_closed(case, "uploading to it")
    send = str(send_with_email).strip().lower() in ("true", "1", "yes", "on")
    content = await file.read()
    try:
        row = await documents.upload(case, None, document_type_code=document_type_code,
                                     file_name=file.filename or "file", content=content,
                                     mime_type=file.content_type, user=user,
                                     send_with_email=send)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await audit(case, user, ev.OFFICER_SUPPORT_DOC_UPLOADED, new_value=row["file_name"],
                metadata={"document_id": row["id"], "document_type_code": document_type_code,
                          "entry_id": None, "send_with_email": send,
                          "case_no": case.get("case_no")})
    return await respond(case_id, user)


class DocumentPatchIn(BaseModel):
    class Config:
        extra = "forbid"

    send_with_email: bool


@router.patch("/{case_id}/documents/{doc_id}")
async def patch_document(case_id: str, doc_id: str, body: DocumentPatchIn,
                         user=Depends(require_permission(MODULE, "write"))):
    """Tick or untick a document to go with the client email."""
    case = load_case(case_id)
    refuse_if_closed(case, "changing its attachments")
    try:
        row = documents.set_send_with_email(case, doc_id, body.send_with_email)
    except LookupError:
        raise HTTPException(404, "Document not found on this case")
    await audit(case, user, ev.CASE_FIELD_UPDATED, new_value=body.send_with_email,
                metadata={"field": "send_with_email", "document_id": doc_id,
                          "file_name": row.get("file_name"), "case_no": case.get("case_no")})
    return await respond(case_id, user)


@router.get("/{case_id}/resolution")
async def resolution_preview(case_id: str,
                             user=Depends(require_permission(MODULE, "read"))):
    """The generated written resolution (ND2A), as it would be attached."""
    case = load_case(case_id)
    if case.get("form_code") != "Nd2a":
        raise HTTPException(409, {"message": "A written resolution goes with an ND2A.",
                                  "reason": "nd2a_only"})
    data = await svc.composite(case_id, user=user)
    entity = nar1_cases.entity_for(case["entity_id"]) or {}
    pdf = await asyncio.to_thread(resolution.render, case, entity, data.get("entries") or [],
                                  data.get("officers") or [])
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="{resolution.file_name(case)}"'})


@router.delete("/{case_id}/documents/{doc_id}")
async def remove_document(case_id: str, doc_id: str,
                          user=Depends(require_permission(MODULE, "write"))):
    case = load_case(case_id)
    refuse_if_closed(case, "removing a document from it")
    try:
        gone = documents.remove(case, doc_id)
    except LookupError:
        raise HTTPException(404, "Document not found on this case")
    except ValueError as exc:
        raise HTTPException(409, {"message": str(exc), "reason": "already_filed"})
    await audit(case, user, ev.OFFICER_SUPPORT_DOC_REMOVED, old_value=gone["file_name"],
                metadata={"document_id": doc_id, "entry_id": gone.get("entry_id"),
                          "document_type_code": gone.get("document_type_code")})
    return await respond(case_id, user)


@router.get("/{case_id}/documents/{doc_id}/download")
async def download_document(case_id: str, doc_id: str,
                            user=Depends(require_permission(MODULE, "read"))):
    load_case(case_id)
    doc = documents.get(case_id, doc_id)
    if doc is None:
        raise HTTPException(404, "Document not found on this case")
    try:
        return {"url": documents.signed_url(doc), "file_name": doc.get("file_name")}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Could not sign a download link: {exc}")


# -- the form, as the client and staff see it -------------------------------------------

def _problems(exc: prepare.MappingError) -> HTTPException:
    return HTTPException(422, {"message": "The form cannot be prepared yet",
                               "problems": list(exc.problems)})


async def _form_xml(case: dict, filing: dict | None) -> str:
    """CR's own copy once it has one; otherwise the form built from the record."""
    if filing and filing.get("validated_xml"):
        return filing["validated_xml"]
    return await prepare.build_form_xml(case, svc.list_entries(case["id"]))


async def _render(case: dict, xml: str, filing: dict | None, *, public_only: bool) -> bytes:
    entity = nar1_cases.entity_for(case["entity_id"]) or {}
    name = "  ".join(p for p in (entity.get("company_name"), entity.get("company_name_zh")) if p)
    return await asyncio.to_thread(
        render_form, case["form_code"], xml, company_name=name, public_only=public_only,
        submitted_on=nar1_cases.filed_on(filing, case))


@router.get("/{case_id}/preview")
async def preview(case_id: str, audience: str = Query("client"),
                  user=Depends(require_permission(MODULE, "read"))):
    """The PDF. `client` (default) and `staff` are CR's full form, PI sheets
    included — since Jacqueline's A8/B2 the client is sent the PI pages to check
    too; `public` is the public pages only."""
    if audience not in ("client", "staff", "public"):
        raise HTTPException(400, "audience is 'client', 'staff' or 'public'")
    case = load_case(case_id)
    filing = nar1_cases.current_filing(case_id)
    try:
        xml = await _form_xml(case, filing)
        pdf = await _render(case, xml, filing, public_only=audience == "public")
    except prepare.MappingError as exc:
        raise _problems(exc)
    except FormFillError as exc:
        raise HTTPException(422, {"message": f"The form could not be rendered: {exc}"})
    name = f"{case['form_code'].upper()}-{case.get('case_no') or case_id}.pdf"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}"'})


# -- client verification (stage 1) ------------------------------------------------------

@router.get("/{case_id}/verification/recipients")
async def verification_recipients(case_id: str,
                                  user=Depends(require_permission(MODULE, "read"))):
    case = load_case(case_id)
    entries = svc.list_entries(case_id)
    rows = recipients_svc.default_recipients(case, entries)
    from services.officer_changes import deadlines
    due = deadlines.filing_deadline(entries)
    return {"recipients": rows,
            "default_to": [r["email"] for r in rows if r.get("email")],
            "max_recipients": MAX_RECIPIENTS,
            "deadline": due.isoformat() if due else None,
            "reply_by_default": (lambda d: d.isoformat() if d else None)(
                deadlines.reply_by_default(due, deadlines.hk_today()))}


class SendIn(BaseModel):
    emails: list[str] | None = None
    #: Accepted as well, because NAR1's chip component posts `to`.
    to: list[str] | str | None = None
    respond_by: str | None = None


def _addresses(body: SendIn, case: dict, entries: list[dict]) -> tuple[list[str], list[dict]]:
    failures: list[dict] = []
    given = body.emails if body.emails is not None else body.to
    if given is None:
        chosen = [r["email"] for r in recipients_svc.default_recipients(case, entries)
                  if r.get("email")]
        if not chosen:
            raise HTTPException(409, "No officer on this form has an email address on "
                                     "record; add one to send the verification")
        return chosen, failures
    given = [given] if isinstance(given, str) else list(given)
    if not given:
        raise HTTPException(422, "No recipient was given")
    if len(given) > MAX_RECIPIENTS:
        raise HTTPException(422, f"{len(given)} recipients is more than the limit of "
                                 f"{MAX_RECIPIENTS}")
    out, seen = [], set()
    for address in given:
        address = (address or "").strip()
        if not nar1_router._ADDRESS.match(address):
            failures.append({"email": address or "(blank)",
                             "reason": "not a valid email address"})
            continue
        if address.lower() not in seen:
            seen.add(address.lower())
            out.append(address)
    if not out:
        raise HTTPException(422, "Nothing was sent: no valid email address was given ("
                                 + ", ".join(f["email"] for f in failures) + ")")
    return out, failures


@router.post("/{case_id}/verification/send")
async def send_verification(case_id: str, body: SendIn, request: Request,
                            user=Depends(require_permission(MODULE, "write"))):
    """Mail the client the public pages of the form, with a Confirm link each.

    NAR1's send, step for step (routers/cases.send_verification): one message
    per recipient carrying their own link; `renewal@` copied and replying; the
    non-production recipient lock inside `email_service.send`; DNS-dead domains
    reported beside malformed addresses; the delivery map written to the audit
    row so the splash and the delivery route can ask Resend later. What differs:
    the company rules must pass, and nobody is ever approved on silence.
    """
    case = load_case(case_id)
    refuse_if_closed(case, "mailing the client")
    if filed(case):
        raise HTTPException(409, {"message": "This form has been filed.",
                                  "reason": "already_filed"})
    data = await svc.composite(case_id, user=user)
    if data["rules"]["blocking"]:
        failing = [c["text"] for c in data["rules"]["checks"]
                   if not c["ok"] and c.get("level") == "rule"]
        raise HTTPException(409, {"message": "Nothing was sent: " + " ".join(failing),
                                  "reason": "rules_blocking"})
    entries = svc.list_entries(case_id)
    try:
        xml = await prepare.build_form_xml(case, entries)
    except prepare.MappingError as exc:
        raise _problems(exc)

    filing = nar1_cases.current_filing(case_id)
    superseded = 0
    if filing is not None and filing.get("stage") not in tpsi_filings.REBUILDABLE_STAGES:
        # A re-send after CR validated (or signed) the form. That filing froze
        # the XML CR checked; mailing a freshly built form and leaving it live
        # would have the client approve one document while the old one is
        # signed and filed. The re-send starts the CR steps again instead.
        superseded = tpsi_filings.supersede_all_for_case(case_id)
        filing = None
    if filing is None:
        filing = tpsi_filings.create_filing(entity_id=case["entity_id"],
                                            form_code=case["form_code"], form_xml=xml,
                                            user_id=user["id"], nar1_case_id=case_id)
    else:
        filing = tpsi_filings.rebuild_draft(filing["id"], xml) or filing

    deadline_at = nar1_router._deadline_from(body.respond_by)
    addresses, failures = _addresses(body, case, entries)
    dead = await nar1_router._undeliverable(addresses)
    if dead:
        failures.extend({"email": a, "reason": r} for a, r in dead.items())
        addresses = [a for a in addresses if a not in dead]
    if not addresses:
        raise HTTPException(422, "Nothing was sent: no address can receive mail ("
                                 + "; ".join(f"{f['email']} ({f['reason']})"
                                             for f in failures) + ")")
    try:
        # The FULL form (Jacqueline A8/B2): the client checks the PI sheets too.
        pdf = await _render(case, xml, filing, public_only=False)
    except FormFillError as exc:
        raise HTTPException(422, {"message": f"The form could not be rendered: {exc}"})
    # Which verification email this is (Levi 2026-10-02, migration 051): the
    # client sees "[Rev. 2]" and up from the second send, exactly as on NAR1.
    # Stored only once something has gone out (the patch below), so a send
    # that reached nobody does not use a number up.
    revision = nar1_approvals.next_revision(case)
    attachment = (f"{case['form_code'].upper()}-{case.get('case_no') or case_id}"
                  f"{f'-Rev{revision}' if revision >= 2 else ''}.pdf")
    # Everything that goes with the letter, gathered BEFORE any link is issued
    # (Jacqueline A3: one email, not two). A file that cannot be read stops the
    # send: a letter must not promise an attachment it does not carry.
    files = [(attachment, pdf)]
    # An ND2A always goes with its written resolution (Levi 2026-10-05: "When
    # they click send to client button then both are sent to client").
    if case["form_code"] == "Nd2a":
        entity_row = nar1_cases.entity_for(case["entity_id"]) or {}
        files.append((resolution.file_name(case), await asyncio.to_thread(
            resolution.render, case, entity_row, data.get("entries") or [],
            data.get("officers") or [])))
    try:
        files += documents.email_attachments(case_id)
    except documents.AttachmentError as exc:
        # 409, not 502 (review finding 5): behind Cloudflare a 502's body never
        # reaches the page, and naming the file is the point of the refusal.
        raise HTTPException(409, {"message": f"The email was not sent: {exc.file_name} "
                                             "could not be read from storage. Upload it "
                                             "again or untick it.",
                                  "reason": "attachment_unreadable"})
    names = [name for name, _ in files]
    consents = await _consent_wording(case, entries)

    board = {(r.get("email") or "").lower(): r
             for r in recipients_svc.default_recipients(case, entries) if r.get("email")}
    targets = [{"email": a, "person_id": (board.get(a.lower()) or {}).get("person_id"),
                "name": (board.get(a.lower()) or {}).get("name")} for a in addresses]
    link_base = nar1_router._approval_link_base(request)
    if link_base:
        try:
            # Supersedes every outstanding link first — the earlier revision's
            # Confirm button dies here — and stamps this revision on the new
            # ones, the second lock (nar1_approvals.is_stale).
            targets = nar1_approvals.issue(case_id=case_id, recipients=targets,
                                           expires_at=deadline_at, revision=revision)
        except Exception as exc:  # noqa: BLE001 — links are a convenience; the reply path remains
            print(f"[officer_changes] approval tokens not issued for {case_id}: {exc}",
                  file=sys.stderr)
            link_base = None

    entity = nar1_cases.entity_for(case["entity_id"]) or {}
    respond_day = deadline_at.astimezone(nar1_router._HK).date()
    sends = []
    for target in targets:
        url = (f"{link_base}/public/officer-change-approval/{target['token']}"
               if link_base and target.get("token") else None)
        subject, html = emails.officer_change_email(
            case, entity, data["entries"], approval_url=url, respond_by=respond_day,
            revision=revision, attachments=names,
            consent=consents.get(target.get("person_id")))
        try:
            sent = await asyncio.to_thread(
                email_service.send, to=[target["email"]], cc=[email_service.CLIENT_CC],
                reply_to=email_service.CLIENT_CC, subject=subject, html=html,
                attachments=files)
        except email_service.EmailError as exc:
            failures.append({"email": target["email"], "reason": str(exc)})
            continue
        except RuntimeError as exc:
            raise HTTPException(503, str(exc))
        sends.append({"target": target, "sent": sent})
    if not sends:
        raise HTTPException(502, "The verification email was not sent: "
                                 + ("; ".join(f["reason"] for f in failures) or "no recipients"))

    sent_at = datetime.now(timezone.utc).isoformat()
    previous = case.get("client_approved")
    # The revision the client now holds; from this write on an earlier one's
    # link is refused even if superseding it failed.
    patch = {"verification_sent_at": sent_at, "verification_xml": xml,
             "verification_revision": revision}
    if previous is not None or case.get("client_response_at"):
        patch.update(client_approved=None, client_response_at=None,
                     client_approval_source=None, client_approval_person_id=None,
                     client_approval_name=None)
    nar1_cases.update_case(case_id, patch)
    # Every undated change is now DEFERRED to Signing; every dated one is a
    # date the client has seen (Jacqueline A1).
    try:
        svc.mark_deferred(case_id)
    except Exception as exc:  # noqa: BLE001 — the mail is out; say so on stderr
        print(f"[officer_changes] mark_deferred failed for {case_id}: {exc!r}",
              file=sys.stderr)

    def across(key):
        out = []
        for record in sends:
            for address in record["sent"].get(key) or []:
                if address not in out:
                    out.append(address)
        return out

    delivered = across("to") or [s["target"]["email"] for s in sends]
    intended = across("intended_to") or [s["target"]["email"] for s in sends]
    message_ids = [s["sent"].get("id") for s in sends if s["sent"].get("id")]
    deliveries = [{"email": s["target"]["email"], "name": s["target"].get("name"),
                   "message_id": s["sent"].get("id"),
                   "delivered_to": s["sent"].get("to") or [],
                   "redirected": bool(s["sent"].get("redirected"))} for s in sends]
    await audit(case, user, ev.EMAIL_SENT, new_value=", ".join(delivered), metadata={
        "form_code": case["form_code"], "message_id": message_ids[0] if message_ids else None,
        "message_ids": message_ids, "deliveries": deliveries, "intended_to": intended,
        "recipient_count": len(intended), "failed_to": [f["email"] for f in failures],
        "failed": failures, "respond_by": deadline_at.isoformat(),
        "cc": across("cc"), "intended_cc": across("intended_cc"),
        "reply_to": across("reply_to"), "intended_reply_to": across("intended_reply_to"),
        "redirected": any(d["redirected"] for d in deliveries),
        "transport": sends[0]["sent"].get("transport", "resend"),
        # A re-send after validation superseded the CR filing that froze the
        # previous form (the CR steps start again).
        "filings_superseded": superseded,
        # Which email about this form — the "[Rev. N]" the client saw.
        "revision": revision,
        # What went with it (Jacqueline A3).
        "attachments": names,
        "case_no": case.get("case_no")})
    for record in sends:
        target = record["target"]
        if target.get("token"):
            expires = target.get("expires_at")
            await audit(case, user, ev.CLIENT_APPROVAL_LINK_SENT,
                        new_value=target.get("name") or target["email"],
                        metadata={"recipient_email": target["email"],
                                  "person_id": target.get("person_id"),
                                  "expires_at": expires.isoformat()
                                  if hasattr(expires, "isoformat") else expires,
                                  "revision": revision,
                                  "case_no": case.get("case_no")})
    if "client_approved" in patch:
        await audit(case, user, ev.CASE_STATUS_CHANGED,
                    old_value="approved" if previous else "rejected",
                    new_value="awaiting_client",
                    metadata={"reason": "a fresh verification superseded the previous answer"})
    return {"sent_at": sent_at, "to": delivered, "intended_to": intended,
            "revision": revision,
            "redirected": any(d["redirected"] for d in deliveries),
            "message_ids": message_ids, "deliveries": deliveries,
            "failed_to": [f["email"] for f in failures], "failed": failures,
            "respond_by": deadline_at.isoformat(), "approval_links": bool(link_base)}


async def _consent_wording(case: dict, entries: list[dict]) -> dict[str, dict]:
    """person_id -> wording: an incoming director is told "no signature is
    needed" when GSHK will PIN-sign their consent from their stored e-Registry
    account (Jacqueline A5) — and only when the whole CASE can go e-Sign (review
    finding 4). Otherwise nothing: the case is filed on CR's portal, outside
    G-FlowDesk (Levi 2026-10-05). Never fails the send."""
    try:
        plan = await prepare.consent_plan(case, entries)
    except Exception as exc:  # noqa: BLE001 — wording only
        print(f"[officer_changes] consent plan for the letter failed: {exc!r}",
              file=sys.stderr)
        return {}
    if not all(row.get("ready") for row in plan):
        return {}
    natural = {e["id"]: e for e in entries
               if e.get("kind") == "appointment" and e.get("person_id")}
    out = {}
    for row in plan:
        entry = natural.get(row.get("entry_id"))
        if entry:
            out[entry["person_id"]] = {"mode": "esign", "url": None,
                                       "name": row.get("signer_name")}
    return out


@router.get("/{case_id}/verification/delivery")
async def verification_delivery(case_id: str,
                                user=Depends(require_permission(MODULE, "read"))):
    """Whether each letter arrived — NAR1's own reader, which keys on the case
    id and the audit row's `deliveries`, both of which an officer change shares."""
    load_case(case_id)
    return await nar1_router.verification_delivery(case_id, user=user)


class ResponseIn(BaseModel):
    approved: bool
    approved_by: str | None = None
    note: str | None = None


@router.post("/{case_id}/verification/response")
async def record_response(case_id: str, body: ResponseIn,
                          user=Depends(require_permission(MODULE, "write"))):
    """The client's answer, relayed by staff (a reply to renewal@, a call)."""
    case = load_case(case_id)
    refuse_if_closed(case, "recording a client decision on it")
    if not case.get("verification_sent_at"):
        raise HTTPException(409, "No verification has been sent for this case")
    previous = case.get("client_approved")
    if previous is body.approved:
        return await respond(case_id, user)
    nar1_cases.update_case(case_id, {
        "client_approved": body.approved,
        "client_response_at": datetime.now(timezone.utc).isoformat(),
        "client_approval_source": nar1_approvals.SOURCE_STAFF_RELAY if body.approved else None,
        "client_approval_name": ((body.approved_by or "").strip() or None)
        if body.approved else None,
        "client_approval_person_id": None,
    })
    await audit(case, user, ev.CLIENT_APPROVAL_RECEIVED,
                old_value=None if previous is None else ("approved" if previous else "rejected"),
                new_value="approved" if body.approved else "rejected",
                metadata={"case_no": case.get("case_no"), "channel": "staff_relay",
                          "approved_by": (body.approved_by or "").strip() or None,
                          "note": (body.note or "").strip() or None})
    return await respond(case_id, user)


class ProceedIn(BaseModel):
    reason: str


@router.post("/{case_id}/verification/proceed")
async def proceed_without_confirmation(case_id: str, body: ProceedIn,
                                       user=Depends(require_permission(MODULE, "write"))):
    """An ND2B filed without the client's confirmation (Jacqueline BQ1: "we
    usually submit the ND2B even if the client has not confirmed the form"),
    with the reason on record. The client's link stays live: a confirmation
    that arrives later replaces this one. An ND2A is never filed this way."""
    case = load_case(case_id)
    refuse_if_closed(case, "proceeding with it")
    if case.get("form_code") != "Nd2b":
        raise HTTPException(409, {"message": "Only an ND2B may proceed without the "
                                             "client's confirmation.",
                                  "reason": "nd2b_only"})
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(400, "Say why the ND2B is going ahead without the client")
    if len(reason) > nar1_router._MAX_CLOSE_REASON:
        raise HTTPException(400, f"Keep the reason to {nar1_router._MAX_CLOSE_REASON} "
                                 "characters")
    if not case.get("verification_sent_at"):
        raise HTTPException(409, {"message": "Send the form to the client first.",
                                  "reason": "not_sent"})
    if case.get("client_approved") is not None:
        raise HTTPException(409, {"message": "The client's answer is already recorded.",
                                  "reason": "answered"})
    nar1_cases.update_case(case_id, {
        "client_approved": True,
        "client_response_at": datetime.now(timezone.utc).isoformat(),
        "client_approval_source": nar1_approvals.SOURCE_STAFF_WAIVER,
        "client_approval_name": reason, "client_approval_person_id": None,
    })
    await audit(case, user, ev.OFFICER_CONFIRMATION_WAIVED, old_value=None,
                new_value="proceeding without confirmation",
                metadata={"case_no": case.get("case_no"), "reason": reason})
    return await respond(case_id, user)


# -- closing -------------------------------------------------------------------------------

class CloseIn(BaseModel):
    reason: str


@router.post("/{case_id}/close")
async def close_case(case_id: str, body: CloseIn,
                     user=Depends(require_permission(MODULE, "write"))):
    """Permanent, as NAR1's: there is no reopen. A change that is going ahead
    after all is a new case, which keeps both decisions in the trail."""
    case = load_case(case_id)
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(400, "Say why this case is being closed")
    if len(reason) > nar1_router._MAX_CLOSE_REASON:
        raise HTTPException(400, f"Keep the reason to {nar1_router._MAX_CLOSE_REASON} "
                                 "characters")
    if filed(case):
        raise HTTPException(409, {"message": "The Companies Registry already holds this "
                                             "form; it cannot be closed as abandoned.",
                                  "reason": "already_filed"})
    closed = nar1_cases.close_case(case_id, user_id=user["id"], reason=reason)
    if closed is None:
        raise HTTPException(409, {"message": "This case is already closed.",
                                  "reason": "case_closed"})
    try:
        superseded = tpsi_filings.supersede_all_for_case(case_id)
    except Exception:  # noqa: BLE001 — closed is closed; report, do not fail
        superseded = None
    try:
        revoked = nar1_approvals.supersede_outstanding(case_id)
    except Exception:  # noqa: BLE001
        revoked = None
    await audit(case, user, ev.NAR1_CASE_CLOSED, new_value="Closed",
                metadata={"case_no": case.get("case_no"), "reason": reason,
                          "form_code": case["form_code"], "filings_superseded": superseded,
                          "approval_links_revoked": revoked})
    return await respond(case_id, user)
