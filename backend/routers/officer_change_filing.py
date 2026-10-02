"""ND2A / ND2B: the steps that involve the Companies Registry (spec §5).

  e-Sign route   validate (free, no PIN) -> sign (consents + overall, one call)
                 -> submit (free, irreversible)
  manual route   mark as checked -> upload the form signed on CR's portal ->
                 record the CR-portal filing with CR's receipt details
                 — and NO call to CR at any point.

`tpsi:write` validates and signs; `tpsi:submit` files, records a filing and
undoes a profile update, exactly as on NAR1. Marking as checked and uploading
the signed form are case work (`officer_changes:write`).

A filing is irreversible. Everything after CR's receipt — writing the change to
the profiles, saving the supporting documents to each officer's profile — is
reported in the response and NEVER turns it into an error (Review Focus 4): CR
holds the form, and an error would say otherwise.
"""
from __future__ import annotations

import re
import sys
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from middleware.auth import require_permission
from routers import tpsi as tpsi_router
from routers.officer_changes import MODULE, audit, load_case, refuse_if_closed, respond
from services import audit_events as ev, document_service, nar1_cases
from services.officer_changes import apply, cases as svc, documents, eservice, prepare, signing
from services.tpsi import credentials, doc_status, filings

router = APIRouter()

_PDF = ("application/pdf",)
_RECEIPT_TYPES = ("application/pdf", "image/png", "image/jpeg")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_approved(case: dict) -> None:
    if case.get("client_approved") is not True:
        raise HTTPException(409, {"message": "The client has not confirmed this form yet.",
                                  "reason": "not_approved"})


def _refuse_if_filed(case: dict) -> None:
    filing = nar1_cases.current_filing(case["id"])
    if case.get("manual_receipt") or (filing and filing.get("stage") in
                                      nar1_cases.CR_FILED_STAGES):
        raise HTTPException(409, {"message": "This form has already been filed.",
                                  "reason": "already_filed"})


def _refuse_if_dates_missing(case: dict) -> None:
    """Nothing is signed or filed with a blank effective date (Jacqueline A1:
    the client may be sent the draft undated; Signing asks for the dates)."""
    missing = svc.dates_missing_for(case["id"])
    if missing:
        raise HTTPException(409, {"message": "Enter the effective date of: "
                                             + "; ".join(missing) + ".",
                                  "reason": "dates_missing", "missing": missing})


#: CR's own refusals of an ND2A/ND2B, MEASURED on CR TEST (2026-10-02), with
#: what each means for the operator. CR's sentence is kept verbatim beside it.
_CR_HINTS = (
    ("signer does not match with officer",
     "A new director's particulars on this form must match their e-Registry account "
     "exactly: English and Chinese names, HKID or passport. A Chinese name the account "
     "holds but the profile does not is enough for CR to refuse. Correct the profile, "
     "or file this form on the manual route."),
    ("no matched individual offic",   # CR spells it "officier"
     "CR cannot find the officer on its register under the name and partial identity "
     "number on this form. A ceasing or changing officer is identified as CR holds "
     "them — if their name or identity number changed, file the ND2B for that first."),
    ("please check selectpersonid",
     "CR does not accept the signing account for this company. Check the e-Service "
     "account under CR Credentials, and that whoever signs is a current officer — or "
     "a director of the body-corporate secretary signing for it."),
)


def _explain(exc: HTTPException) -> HTTPException:
    """NAR1's 422, in an officer change's words, with a hint per known refusal."""
    detail = exc.detail if isinstance(exc.detail, dict) else None
    if exc.status_code != 422 or detail is None:
        return exc
    text = " ".join(str(p) for p in detail.get("problems") or []).lower()
    hints = [hint for needle, hint in _CR_HINTS if needle in text]
    message = (detail.get("message") or "").replace("this return", "this form")
    return HTTPException(422, {**detail, "message": message,
                               **({"hints": hints} if hints else {})})


def _refuse_manual_conflict(case_id: str, *, step: str) -> None:
    """`nar1_cases.manual_conflict` against the filing that decides it."""
    reason = nar1_cases.manual_conflict(nar1_cases.blocking_filing(case_id), step=step)
    if reason:
        raise HTTPException(409, {"message": reason[0].upper() + reason[1:] + ".",
                                  "reason": "efiling_conflict"})


async def _write_back(case_id: str, user: dict, case: dict | None = None
                      ) -> tuple[dict, list[dict]]:
    """Profiles, then supporting documents. Never raises (module docstring) —
    including the re-read of the case, which falls back to the row the caller
    already holds."""
    try:
        case = svc.get_case(case_id)
    except Exception as exc:  # noqa: BLE001
        print(f"[officer_change_filing] re-read failed for {case_id}: {exc!r}", file=sys.stderr)
        case = case or {"id": case_id}
    try:
        data = await svc.composite(case_id, user=user)
        result = await apply.apply_changes(case, data["entries"], user=user)
    except Exception as exc:  # noqa: BLE001
        print(f"[officer_change_filing] apply failed for {case_id}: {exc!r}", file=sys.stderr)
        result, data = {"applied": [], "errors": [f"The profiles were not updated: {exc}"]}, None
    try:
        filed_docs = await documents.file_to_profiles(
            case, data["entries"] if data else svc.list_entries(case_id), user=user)
    except Exception as exc:  # noqa: BLE001
        filed_docs = [{"error": f"The supporting documents were not saved: {exc}"}]
    await audit(case, user, ev.OFFICER_CHANGES_APPLIED,
                new_value=f"{len(result['applied'])} change(s)",
                metadata={"applied": result["applied"], "errors": result["errors"],
                          "documents": [{"document_id": d.get("id"),
                                         "filed_document_id": d.get("filed_document_id"),
                                         "destination": d.get("destination"),
                                         "error": d.get("error")} for d in filed_docs]})
    return result, filed_docs


# -- e-Sign route ----------------------------------------------------------------------

@router.post("/{case_id}/validate")
async def validate(case_id: str, user=Depends(require_permission("tpsi", "write"))):
    case = load_case(case_id)
    refuse_if_closed(case, "validating it with CR")
    _require_approved(case)
    _refuse_if_filed(case)
    _refuse_if_dates_missing(case)
    entries = svc.list_entries(case_id)
    plan = await prepare.consent_plan(case, entries)
    missing = [c["reason"] for c in plan if not c.get("ready")]
    if missing:
        raise HTTPException(409, {"message": "e-Sign is not available: " + "; ".join(missing),
                                  "reason": "esign_unavailable"})
    try:
        xml = await prepare.build_form_xml(
            case, entries, signing_identity=credentials.load_signatory_identity(user["id"]),
            for_esign=True)
    except prepare.MappingError as exc:
        raise HTTPException(422, {"message": "The form cannot be validated yet",
                                  "problems": list(exc.problems)})
    filing = nar1_cases.current_filing(case_id)
    created = False
    if filing is not None and filing.get("stage") in filings.REBUILDABLE_STAGES:
        filing = filings.rebuild_draft(filing["id"], xml) or filing
    elif filing is not None and filing.get("stage") == filings.STAGE_VALIDATED:
        # Re-validating after a change: CR's previous answer described a
        # different form, so it is superseded rather than reused.
        filings.supersede(filing["id"])
        filing = None
    if filing is None or filing.get("stage") not in filings.REBUILDABLE_STAGES:
        filing = filings.create_filing(entity_id=case["entity_id"], form_code=case["form_code"],
                                       form_xml=xml, user_id=user["id"], nar1_case_id=case_id)
        created = True
    try:
        filings.validate(tpsi_router.client_for(user), filing["id"])
    except Exception as exc:
        await audit(case, user, ev.TPSI_VALIDATE, new_value="refused",
                    metadata={"filing_id": filing["id"], "form_code": case["form_code"],
                              "faults": getattr(exc, "faults", None)})
        raise _explain(tpsi_router._handle(exc))
    nar1_cases.update_case(case_id, {"signing_method": "esign"})
    if created:
        await audit(case, user, ev.TPSI_FILING_CREATED, new_value=filing["id"],
                    metadata={"form_code": case["form_code"]})
    await audit(case, user, ev.TPSI_VALIDATE, new_value="validated",
                metadata={"filing_id": filing["id"], "form_code": case["form_code"]})
    return await respond(case_id, user)


_EMPTY_BODY_ONLY = ("Send an empty body: the form is signed with your own e-Service "
                    "account, and each new director's consent with their own stored "
                    "e-Registry account.")


@router.post("/{case_id}/sign")
async def sign(case_id: str, request: Request,
               user=Depends(require_permission("tpsi", "write"))):
    """Empty body. The overall signature is the signed-in user's own e-Service
    account; each new director's consent is THEIR stored e-Registry account
    (answer 8).

    The body is read raw, not declared: a declared `dict` answered a JSON list
    or string with FastAPI's 422, which echoes the input — a password sent
    here by mistake would have come straight back. Anything but nothing, or
    `{}`, gets one fixed sentence."""
    raw = (await request.body()).strip()
    if raw and raw not in (b"{}", b"null"):
        raise HTTPException(400, _EMPTY_BODY_ONLY)
    case = load_case(case_id)
    refuse_if_closed(case, "signing it")
    _require_approved(case)
    filing = nar1_cases.current_filing(case_id)
    if not filing or filing.get("stage") != filings.STAGE_VALIDATED:
        raise HTTPException(409, {"message": "Validate the form with CR before signing.",
                                  "reason": "not_validated"})
    _refuse_if_dates_missing(case)
    pair = credentials.load_eservice(user["id"])
    if pair is None:
        raise HTTPException(409, {"message": "You have no e-Service signing password stored. "
                                             "Add one under CR Credentials.",
                                  "reason": "no_signing_credential"})
    plan = await prepare.consent_plan(case, svc.list_entries(case_id))
    consents = []
    for row in plan:
        stored = eservice.load_for_signing(row["signer_person_id"]) \
            if row.get("signer_person_id") else None
        if stored is None:
            raise HTTPException(409, {"message": f"{row['signer_name']} has no complete "
                                                 "e-Registry account stored, so their "
                                                 "consent cannot be signed.",
                                      "reason": "esign_unavailable"})
        consents.append({"bean_id": row["bean_id"], "user_id": stored[0],
                         "password": stored[2], "entry_id": row["entry_id"],
                         "person_id": row["signer_person_id"]})
    try:
        signing.sign(tpsi_router.client_for(user), filing["id"], signatory_user_id=pair[0],
                     eservice_password=pair[1],
                     consents=[{k: c[k] for k in ("bean_id", "user_id", "password")}
                               for c in consents])
    except filings.SignatoryMismatch as exc:
        raise HTTPException(409, str(exc))
    except filings.SubmitGateError as exc:
        raise HTTPException(409, {"message": str(exc), "reason": "case_finished"})
    except signing.ConsentCredentialMissing as exc:
        raise HTTPException(409, {"message": str(exc), "reason": "esign_unavailable"})
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise _explain(tpsi_router._handle(exc))
    now = _now()
    for consent in consents:
        svc.get_supabase().table("officer_change_entries").update(
            {"consent_signed_at": now}).eq("id", consent["entry_id"]).execute()
        await audit(case, user, ev.OFFICER_CONSENT_SIGNED, new_value=consent["bean_id"],
                    metadata={"entry_id": consent["entry_id"], "person_id": consent["person_id"],
                              "eservice_user_id": consent["user_id"]})
    await audit(case, user, ev.TPSI_SIGN, new_value="signed",
                metadata={"filing_id": filing["id"], "form_code": case["form_code"],
                          "consents": len(consents)})
    return await respond(case_id, user)


class ConfirmIn(BaseModel):
    confirm: bool = False


@router.post("/{case_id}/submit")
async def submit(case_id: str, body: ConfirmIn,
                 user=Depends(require_permission("tpsi", "submit"))):
    if body.confirm is not True:
        raise HTTPException(400, "Confirm the filing: it cannot be undone at CR")
    case = load_case(case_id)
    refuse_if_closed(case, "filing it")
    _require_approved(case)
    filing = nar1_cases.current_filing(case_id)
    if not filing or filing.get("stage") != filings.STAGE_SIGNED:
        raise HTTPException(409, {"message": "Sign the form before filing it.",
                                  "reason": "not_signed"})
    await audit(case, user, ev.TPSI_SUBMISSION_ATTEMPTED, new_value=case["form_code"],
                metadata={"filing_id": filing["id"], "endpoint": f"submitForm{case['form_code']}"})
    try:
        result = signing.submit(tpsi_router.client_for(user), filing["id"], confirm=True)
    except Exception as exc:
        await audit(case, user, ev.TPSI_SUBMISSION_FAILED, new_value=str(exc)[:200],
                    metadata={"filing_id": filing["id"],
                              "faults": getattr(exc, "faults", None)})
        if isinstance(exc, filings.SubmitGateError):
            raise HTTPException(409, {"message": str(exc), "reason": "case_finished"})
        if isinstance(exc, ValueError):
            raise HTTPException(400, str(exc))
        raise _explain(tpsi_router._handle(exc))
    receipt = result.get("receipt") or {}
    await audit(case, user, ev.TPSI_SUBMISSION_SUCCESS, new_value=receipt.get("caseNo"),
                metadata={"filing_id": filing["id"], "case_no_cr": receipt.get("caseNo"),
                          "ref_no": receipt.get("refNo")})
    write_back, filed_docs = await _write_back(case_id, user, case)
    return await _filed_response(case_id, user, case, write_back, filed_docs)


async def _filed_response(case_id: str, user: dict, case: dict, write_back: dict,
                          filed_docs: list[dict]) -> dict:
    """The answer to a form that IS filed. It must not become a 500: CR has the
    form whatever happens next, so a failure to re-read the case is reported
    beside the filing rather than in place of it."""
    extra = {"write_back": {"errors": write_back["errors"]}, "documents_filed": filed_docs}
    try:
        return {**await respond(case_id, user), **extra}
    except Exception as exc:  # noqa: BLE001
        print(f"[officer_change_filing] composite after filing failed for {case_id}: {exc!r}",
              file=sys.stderr)
        return {**case, **extra, "filed": True,
                "problems": ["The form is filed. The case could not be re-read just now; "
                             "reload the page."]}


@router.post("/{case_id}/apply")
async def retry_write_back(case_id: str, body: ConfirmIn,
                           user=Depends(require_permission("tpsi", "submit"))):
    """Re-run the profile update of a FILED form whose write-back did not finish.

    The write-back is per entry and idempotent (an entry already applied is
    skipped), so this completes exactly what is missing. Same permission as the
    filing that would have run it."""
    if body.confirm is not True:
        raise HTTPException(400, "Confirm the profile update")
    case = load_case(case_id)
    filing = nar1_cases.blocking_filing(case_id)
    filed = case.get("manual_receipt") or (
        filing and filing.get("stage") in nar1_cases.CR_FILED_STAGES)
    if not filed:
        raise HTTPException(409, {"message": "The form has not been filed yet.",
                                  "reason": "not_filed"})
    if case.get("changes_undone_at"):
        raise HTTPException(409, {"message": "The profile update was undone after CR "
                                             "rejected the form; it is not re-applied.",
                                  "reason": "undone"})
    if case.get("changes_applied_at"):
        raise HTTPException(409, {"message": "The profiles are already up to date.",
                                  "reason": "already_applied"})
    write_back, filed_docs = await _write_back(case_id, user, case)
    return await _filed_response(case_id, user, case, write_back, filed_docs)


# -- manual route (CR portal) -----------------------------------------------------------

class MarkCheckedIn(BaseModel):
    class Config:
        extra = "forbid"

    signing_method: str = "manual"


@router.post("/{case_id}/mark-checked")
async def mark_checked(case_id: str, body: MarkCheckedIn | None = None,
                       user=Depends(require_permission(MODULE, "write"))):
    """Data Verification done, without a CR call.

    The manual route's stand-in for CR's validation, as before. And, since
    Jacqueline's A1, the e-Sign route's way out of Data Verification when a
    date is still blank: CR's validation checks the dates, so on that route
    the dates are entered and CR validates at Signing (spec §2.1)."""
    method = (body.signing_method if body else "manual") or "manual"
    if method not in ("esign", "manual"):
        raise HTTPException(400, "signing_method is 'esign' or 'manual'")
    case = load_case(case_id)
    refuse_if_closed(case, "marking it as checked")
    _require_approved(case)
    _refuse_if_filed(case)
    if method == "esign":
        plan = await prepare.consent_plan(case, svc.list_entries(case_id))
        missing = [c["reason"] for c in plan if not c.get("ready")]
        if missing:
            raise HTTPException(409, {"message": "e-Sign is not available: "
                                                 + "; ".join(missing),
                                      "reason": "esign_unavailable"})
    nar1_cases.update_case(case_id, {"data_checked_at": _now(),
                                     "data_checked_by": user["id"],
                                     "signing_method": method})
    await audit(case, user, ev.CASE_STATUS_CHANGED, old_value="data_verification",
                new_value="signing", metadata={"reason": f"marked as checked ({method} route)",
                                               "case_no": case.get("case_no")})
    return await respond(case_id, user)


@router.post("/{case_id}/signed-form", status_code=201)
async def signed_form(case_id: str, file: UploadFile = File(...),
                      user=Depends(require_permission(MODULE, "write"))):
    """The form as signed on CR's portal. Stored on the COMPANY, as NAR1's is.
    It does not move the case on (answer 9): Continue is a separate, deliberate
    press on the page."""
    case = load_case(case_id)
    refuse_if_closed(case, "uploading a signed form")
    _refuse_if_filed(case)
    if not case.get("data_checked_at"):
        raise HTTPException(409, {"message": "Mark the form as checked first.",
                                  "reason": "not_checked"})
    _refuse_if_dates_missing(case)
    content = await file.read()
    if not content:
        raise HTTPException(400, "The file is empty")
    if (file.content_type or "") not in _PDF and not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Upload the signed form as a PDF")
    document = await document_service.upload_document(
        owner_kind="entity", owner_id=case["entity_id"],
        document_type_code=case["form_code"].lower(), file_name=file.filename or "signed.pdf",
        content=content, mime_type=file.content_type or "application/pdf",
        title=f"{case.get('case_no')} — signed {case['form_code'].upper()}", user=user)
    nar1_cases.update_case(case_id, {
        "manual_signed_document_id": document["id"],
        "manual_signed_document_version": document.get("current_version") or 1})
    await audit(case, user, ev.OFFICER_SIGNED_FORM_UPLOADED, new_value=file.filename,
                metadata={"document_id": document["id"],
                          "version": document.get("current_version") or 1})
    return await respond(case_id, user)


@router.post("/{case_id}/receipt", status_code=201)
async def upload_receipt(case_id: str, file: UploadFile = File(...),
                         user=Depends(require_permission("tpsi", "submit"))):
    """CR's receipt, kept on the CASE (NAR1's owner kind `receipt`)."""
    case = load_case(case_id)
    refuse_if_closed(case, "recording a CR receipt")
    # Once a filing is recorded its receipt is evidence, not a draft: replacing
    # the pointer would leave the recorded case number beside a different paper.
    if case.get("manual_receipt"):
        raise HTTPException(409, {"message": "A filing is already recorded for this case; "
                                             "its receipt cannot be replaced.",
                                  "reason": "already_filed"})
    _refuse_manual_conflict(case_id, step="sign")
    content = await file.read()
    if not content:
        raise HTTPException(400, "The file is empty")
    if (file.content_type or "") not in _RECEIPT_TYPES:
        raise HTTPException(400, "Upload CR's receipt as a PDF or an image")
    document = await document_service.upload_document(
        owner_kind="receipt", owner_id=case_id, document_type_code="cr_receipt",
        file_name=file.filename or "receipt.pdf", content=content,
        mime_type=file.content_type, title=f"{case.get('case_no')} — CR receipt", user=user)
    nar1_cases.update_case(case_id, {
        "manual_receipt_document_id": document["id"],
        "manual_receipt_document_version": document.get("current_version") or 1})
    await audit(case, user, ev.CASE_FIELD_UPDATED, new_value=file.filename,
                metadata={"field": "manual_receipt_document", "document_id": document["id"]})
    return await respond(case_id, user)


class ReceiptIn(BaseModel):
    class Config:
        extra = "forbid"

    caseNo: str
    transactionDate: str
    transactionTime: str | None = None
    refNo: str | None = None


class RecordFilingIn(BaseModel):
    receipt: ReceiptIn
    confirm: bool = False


_DMY = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def _receipt_date(value: str) -> str:
    """DD/MM/YYYY, as CR prints it; YYYY-MM-DD accepted. Never in the future."""
    text = (value or "").strip()
    try:
        match = _DMY.match(text)
        day = (date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
               if match else date.fromisoformat(text[:10]))
    except (ValueError, AttributeError):
        raise HTTPException(400, f"{text!r} is not a date; enter it as DD/MM/YYYY")
    from services.officer_changes.deadlines import hk_today
    if day > hk_today():
        raise HTTPException(400, "The transaction date is in the future")
    return day.strftime("%d/%m/%Y")


@router.post("/{case_id}/record-filing")
async def record_filing(case_id: str, body: RecordFilingIn,
                        user=Depends(require_permission("tpsi", "submit"))):
    """A filing made on CR's portal, recorded from CR's receipt (answer 12)."""
    if body.confirm is not True:
        raise HTTPException(400, "Confirm the filing record")
    case = load_case(case_id)
    refuse_if_closed(case, "recording a filing")
    _require_approved(case)
    if not case.get("manual_signed_document_id"):
        raise HTTPException(409, {"message": "Upload the signed form first.",
                                  "reason": "not_signed"})
    if not case.get("manual_receipt_document_id"):
        raise HTTPException(409, {"message": "Attach CR's receipt first.",
                                  "reason": "no_receipt"})
    _refuse_if_dates_missing(case)
    # NAR1's gate, for the same reason: an e-filing CR already holds, or a
    # CR-signed one waiting to be submitted, would make this a second filing of
    # one form — and after a rejected e-filing was Undone, it would re-apply
    # the rejected changes to the profiles.
    _refuse_manual_conflict(case_id, step="submit")
    case_no = body.receipt.caseNo.strip()
    if not case_no:
        raise HTTPException(400, "Enter the CR case number from the receipt")
    receipt = {"caseNo": case_no,
               "transactionDate": _receipt_date(body.receipt.transactionDate),
               "transactionTime": (body.receipt.transactionTime or "").strip() or None,
               "refNo": (body.receipt.refNo or "").strip() or None,
               "totalAmount": "0.00"}
    claimed = nar1_cases.claim_manual_submission(case_id, {
        "manual_receipt": receipt, "manual_submitted_at": _now(), "signing_method": "manual"})
    if claimed is None:
        raise HTTPException(409, {"message": "A filing is already recorded for this case.",
                                  "reason": "already_filed"})
    await audit(case, user, ev.OFFICER_FILING_RECORDED, new_value=case_no,
                after_state={"manual_receipt": receipt})
    write_back, filed_docs = await _write_back(case_id, user, case)
    return await _filed_response(case_id, user, case, write_back, filed_docs)


@router.post("/{case_id}/undo")
async def undo(case_id: str, body: ConfirmIn,
               user=Depends(require_permission("tpsi", "submit"))):
    """After CR REJECTS a filed change: put the profiles back as they were."""
    if body.confirm is not True:
        raise HTTPException(400, "Confirm the undo")
    case = load_case(case_id)
    if case.get("cr_doc_status_code") != doc_status.REJECTED:
        raise HTTPException(409, {"message": "Undo is only for a change the Companies "
                                             "Registry has rejected.",
                                  "reason": "not_rejected"})
    data = await svc.composite(case_id, user=user)
    # Gated on what was actually applied, entry by entry — not on
    # `changes_applied_at`, which a write-back that stopped part-way never
    # sets, and which would then leave the applied half impossible to undo.
    if case.get("changes_undone_at") or not any(e.get("applied") for e in data["entries"]):
        raise HTTPException(409, {"message": "There is no applied change to undo.",
                                  "reason": "nothing_to_undo"})
    result = await apply.undo_changes(case, data["entries"], user=user)
    await audit(case, user, ev.OFFICER_CHANGES_UNDONE,
                new_value=f"{len(result['applied'])} change(s)",
                metadata={"undone": result["applied"], "errors": result["errors"]})
    return {**await respond(case_id, user), "undo": {"errors": result["errors"]}}
