"""NAR1 case-workflow endpoints (BE-4).

Permission module is `nar1` (OQ-B, Levi 2026-08-16) — deliberately not
`companies`. Editing a company record and driving a statutory filing are
different authorities: the second sends mail to clients and spends money.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from middleware.auth import require_permission
from services import (
    audit_events as ev, document_service, nar1_case_status, nar1_cases,
)
from services.audit_service import log_event

router = APIRouter()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CaseIn(BaseModel):
    entity_id: str
    form_code: str = "Nar1"


class CasePatch(BaseModel):
    """Only the fields a PATCH is allowed to own.

    client_approved is absent on purpose: that fact belongs to
    POST /cases/{id}/verification/response, which audits it as a client
    decision. Letting a generic PATCH set it would put a client approval in the
    trail with no record of the client.
    """
    aml_cleared: bool | None = None
    accounts_ready: bool | None = None
    signing_method: str | None = None
    assigned_to: str | None = None
    restart_verification: bool = False


@router.post("", status_code=201)
async def create_case(
    body: CaseIn, user=Depends(require_permission("nar1", "write"))
):
    try:
        row = nar1_cases.create_case(
            entity_id=body.entity_id, form_code=body.form_code, user_id=user["id"]
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    await log_event(
        user_id=user["id"], user_display_name=user["display_name"],
        action_type=ev.CASE_STATUS_CHANGED, event_code=ev.CASE_STATUS_CHANGED,
        entity_type="nar1_case", entity_id=row["id"], case_id=row["id"],
        new_value="Data Verification",
        metadata={"case_no": row.get("case_no"), "entity_id": body.entity_id},
    )
    return row


@router.get("")
async def list_cases(
    scope: str | None = Query(None, description="dashboard"),
    search: str | None = Query(None),
    workflow_status: str | None = Query(None, description="one of the seven badges"),
    anniv_op: str | None = Query(None, description="lte | gte | eq"),
    anniv_days: int | None = Query(None, description="signed day count"),
    sort: str | None = Query(None),
    dir: str = Query("asc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(nar1_cases._DEFAULT_PAGE_SIZE, ge=1,
                           le=nar1_cases._MAX_PAGE_SIZE),
    user=Depends(require_permission("nar1", "read")),
):
    """The case dashboard — one row per case (BE-7).

    Deliberately NOT the company listing: a company with two open cases is two
    rows here, and a row click opens that case's workflow rather than the
    company profile. The company-level anniversary filter is untouched and still
    lives on GET /companies — this reuses the same `days_to_anniversary` column
    (migration 019) through `nar1_case_registry`, it does not restate it.

    Read-only, so nothing is audited: CLAUDE.md puts reads outside audit scope,
    and a dashboard load per page view would drown the trail it shares with the
    statutory events.
    """
    # Rejected, not silently ignored. A filter the server drops looks like a
    # filter that matched everything, and on a paginated listing the user has no
    # way to tell the difference.
    #
    # `scope` gets the same treatment as every other parameter here. It has one
    # legal value today, so accepting anything else and returning the dashboard
    # anyway would be the exact defect this block exists to prevent: a caller
    # asking for something we do not serve, and receiving something else with
    # no indication. Omitting it stays legal -- the dashboard is this route's
    # only listing -- so a caller that never learned about `scope` is not broken.
    if scope is not None and scope != "dashboard":
        raise HTTPException(422, f"Unknown scope '{scope}'")
    if anniv_op is not None and anniv_op not in nar1_cases._ANNIV_OPS:
        raise HTTPException(422, f"Unknown comparison '{anniv_op}'")
    if (anniv_op is None) != (anniv_days is None):
        raise HTTPException(422, "anniv_op and anniv_days must be supplied together")
    if workflow_status and workflow_status not in nar1_case_status.WORKFLOW_STATUSES:
        raise HTTPException(422, f"Unknown workflow status '{workflow_status}'")
    if sort and sort not in nar1_cases._SORTABLE:
        raise HTTPException(422, f"Cannot sort by '{sort}'")

    return await nar1_cases.list_dashboard(
        search=search,
        workflow_status=workflow_status,
        anniv_op=anniv_op,
        anniv_days=anniv_days,
        sort=sort,
        direction=dir,
        page=page,
        page_size=page_size,
    )


@router.get("/{case_id}")
async def get_case(case_id: str, user=Depends(require_permission("nar1", "read"))):
    """The case with BOTH badges — workflow status and CR-form status, reported
    side by side and never merged (D-6)."""
    try:
        return nar1_cases.composite(case_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc))


@router.patch("/{case_id}")
async def patch_case(
    case_id: str, body: CasePatch, user=Depends(require_permission("nar1", "write"))
):
    try:
        before = nar1_cases.get_case(case_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc))

    patch: dict = {}
    events: list[tuple[str, str, str | None, str | None]] = []

    if body.aml_cleared is not None and body.aml_cleared != before.get("aml_cleared"):
        patch["aml_cleared"] = body.aml_cleared
        # A tick without a time cannot answer "when was AML cleared?", which is
        # the only question anyone asks of it later.
        patch["aml_cleared_at"] = _now() if body.aml_cleared else None
        events.append((ev.AML_STATUS_CHANGED, "aml_cleared",
                       str(before.get("aml_cleared")), str(body.aml_cleared)))

    if body.accounts_ready is not None and body.accounts_ready != before.get("accounts_ready"):
        patch["accounts_ready"] = body.accounts_ready
        patch["accounts_ready_at"] = _now() if body.accounts_ready else None
        events.append((ev.CASE_FIELD_UPDATED, "accounts_ready",
                       str(before.get("accounts_ready")), str(body.accounts_ready)))

    if body.signing_method is not None:
        # Validation runs whether or not the value is a no-op: an invalid
        # value must still 400, never be silently swallowed by the "unchanged"
        # check below.
        if body.signing_method not in ("esign", "manual"):
            raise HTTPException(400, "signing_method must be 'esign' or 'manual'")
        if body.signing_method != before.get("signing_method"):
            patch["signing_method"] = body.signing_method
            events.append((ev.CASE_FIELD_UPDATED, "signing_method",
                           before.get("signing_method"), body.signing_method))

    if body.assigned_to is not None and body.assigned_to != before.get("assigned_to"):
        patch["assigned_to"] = body.assigned_to
        events.append((ev.CASE_FIELD_UPDATED, "assigned_to",
                       before.get("assigned_to"), body.assigned_to))

    if body.restart_verification:
        # All three together, or the case reads as still-approved on the next
        # GET and jumps straight back to Signing.
        patch["verification_sent_at"] = None
        patch["client_approved"] = None
        patch["client_response_at"] = None
        events.append((ev.CASE_STATUS_CHANGED, "verification",
                       "sent", "restarted"))

    if not patch:
        return nar1_cases.composite(case_id)

    nar1_cases.update_case(case_id, patch)
    for action, field, old, new in events:
        await log_event(
            user_id=user["id"], user_display_name=user["display_name"],
            action_type=action, event_code=action,
            entity_type="nar1_case", entity_id=case_id, case_id=case_id,
            old_value=old, new_value=new, metadata={"field": field},
        )
    return nar1_cases.composite(case_id)


# --------------------------------------------------------------------------- #
#  The manual (wet-signature, off-portal) path — BE-6
#
#  NOTHING below calls CR. The filing happens on paper, outside the portal, and
#  the portal's job is only to hold the evidence and say so. Both routes read
#  the filing ledger to refuse a case CR already holds, but neither writes to
#  it: tpsi_filings owns CR-side facts (D-6), and a receipt CR never issued is
#  not one of them.
# --------------------------------------------------------------------------- #


class ManualSubmitIn(BaseModel):
    receipt: dict


@router.post("/{case_id}/manual-sign", status_code=201)
async def manual_sign(
    case_id: str,
    file: UploadFile = File(...),
    user=Depends(require_permission("documents", "write")),
):
    """Upload the wet-signed NAR1 (BE-6). No CR call.

    `documents:write`, not `tpsi:*`: this is a document going into storage. The
    privileged act is recording the SUBMISSION, which is the next endpoint.
    """
    try:
        case = nar1_cases.get_case(case_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc))

    if case.get("manual_receipt"):
        raise HTTPException(
            409,
            "this case's off-portal submission is already recorded — the signed "
            "form behind it is fixed. Upload a corrected scan through the "
            "company's documents, which versions it.",
        )

    conflict = nar1_cases.manual_conflict(
        nar1_cases.blocking_filing(case_id), step="sign"
    )
    if conflict:
        raise HTTPException(409, conflict)

    content = await file.read()
    if not content:
        # A zero-byte upload proves nothing and would still satisfy the
        # manual-submit gate below.
        raise HTTPException(400, "the uploaded file is empty")

    # `nar1` is the document_type_code migration 003 already seeds
    # ("NAR1 — Annual Return"). No new document type is needed. Owner is the
    # ENTITY, not the case: documents are owned by companies, and a re-upload
    # versions the same row rather than overwriting it.
    document = await document_service.upload_document(
        owner_kind="entity",
        owner_id=case["entity_id"],
        document_type_code="nar1",
        file_name=file.filename or "signed-nar1.pdf",
        content=content,
        mime_type=file.content_type,
        title=f"Signed NAR1 — {case.get('case_no') or case_id}",
        user=user,
    )

    # Only after the upload succeeded: document_service raises on a storage
    # failure, and marking the case manually signed off the back of a failed
    # upload would open the manual-submit gate with no evidence behind it.
    # The VERSION as well as the id. upload_document versions in place: the
    # documents row for (entity, 'nar1') is reused and rewritten every year, so
    # this company's 2027 scan comes back under the same id already stored on the
    # 2026 case and mutates the row that id points at. (id, version) is the pair
    # document_versions is keyed on, and is the only pointer that still resolves
    # to THIS case's evidence at the next annual return.
    patch = {
        "manual_signed_document_id": document["id"],
        "manual_signed_document_version": document.get("current_version") or 1,
        # The upload IS the choice of route; leaving this unset would keep the
        # case reading as an e-Sign case in every listing.
        "signing_method": "manual",
    }
    nar1_cases.update_case(case_id, patch)

    # signing_method is a case FIELD, and PATCH /cases/{id} audits every change
    # to it with old and new. Writing it here and logging only the document
    # event would leave the field-change view of the trail with a hole the PATCH
    # route does not have — CLAUDE.md's PBI-11 table asks for one
    # CASE_FIELD_UPDATED per changed field. Only on a real change: a re-upload on
    # an already-manual case changed nothing, and a no-op must not write a false
    # audit row (Task 6).
    previous_method = case.get("signing_method")
    if previous_method != "manual":
        await log_event(
            user_id=user["id"], user_display_name=user["display_name"],
            action_type=ev.CASE_FIELD_UPDATED, event_code=ev.CASE_FIELD_UPDATED,
            entity_type="nar1_case", entity_id=case_id, case_id=case_id,
            old_value=previous_method, new_value="manual",
            metadata={"field": "signing_method"},
        )

    await log_event(
        user_id=user["id"], user_display_name=user["display_name"],
        action_type=ev.NAR1_MANUAL_SIGN_UPLOADED,
        event_code=ev.NAR1_MANUAL_SIGN_UPLOADED,
        entity_type="nar1_case", entity_id=case_id, case_id=case_id,
        new_value=file.filename,
        metadata={"document_id": document["id"], "filename": file.filename,
                  "bytes": len(content),
                  "version": patch["manual_signed_document_version"]},
    )
    return {"document_id": document["id"],
            "document_version": patch["manual_signed_document_version"]}


@router.post("/{case_id}/manual-submit")
async def manual_submit(
    case_id: str,
    body: ManualSubmitIn,
    user=Depends(require_permission("tpsi", "submit")),
):
    """Record an off-portal submission (BE-6). NO CR CALL, NO CHARGE.

    Gated on `tpsi:submit` even though no money moves through us: this is the
    act that declares the annual return filed, and it is exactly as consequential
    in the register as the e-Signed one.

    The guards run before the receipt is even looked at, most specific first, so
    the answer names the real obstacle rather than the first field that happens
    to be blank.
    """
    try:
        case = nar1_cases.get_case(case_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc))

    if case.get("manual_receipt"):
        raise HTTPException(
            409, "this case already has a recorded off-portal submission"
        )

    conflict = nar1_cases.manual_conflict(
        nar1_cases.blocking_filing(case_id), step="submit"
    )
    if conflict:
        raise HTTPException(409, conflict)

    if not case.get("manual_signed_document_id"):
        raise HTTPException(
            409,
            "upload the wet-signed NAR1 before recording the submission — a "
            "completion with no signed form is a false record",
        )

    problems = nar1_cases.validate_receipt(body.receipt)
    if problems:
        raise HTTPException(400, {"message": "receipt is incomplete",
                                  "problems": problems})

    # One clock reading for both columns: two calls to _now() would stamp two
    # different instants on a single event.
    now = _now()
    # A CONDITIONAL write, not update_case(). The manual_receipt check at the top
    # of this handler is a read, and two concurrent requests both pass it; the
    # condition has to travel with the UPDATE for Postgres to settle it. Nothing
    # below this line runs unless this request is the one that claimed the row —
    # audit_log is insert-only, so a second NAR1_MANUAL_SUBMISSION_RECORDED for
    # one return could never be taken back.
    claimed = nar1_cases.claim_manual_submission(case_id, {
        "manual_receipt": body.receipt,
        "manual_submitted_at": now,
        "signing_method": "manual",
        "submitted_at": now,
        "submitted_by": user["id"],
    })
    if claimed is None:
        raise HTTPException(
            409, "this case already has a recorded off-portal submission"
        )

    # The receipt is the only evidence the return was filed, so the trail
    # carries it whole. Safe in after_state (which audit_service does NOT scrub)
    # only because validate_receipt has just refused every key outside CR's own
    # receipt vocabulary.
    await log_event(
        user_id=user["id"], user_display_name=user["display_name"],
        action_type=ev.NAR1_MANUAL_RECEIPT_ENTERED,
        event_code=ev.NAR1_MANUAL_RECEIPT_ENTERED,
        entity_type="nar1_case", entity_id=case_id, case_id=case_id,
        after_state={"manual_receipt": body.receipt},
        metadata={"caseNo": body.receipt.get("caseNo"),
                  "totalAmount": body.receipt.get("totalAmount")},
    )
    await log_event(
        user_id=user["id"], user_display_name=user["display_name"],
        action_type=ev.NAR1_MANUAL_SUBMISSION_RECORDED,
        event_code=ev.NAR1_MANUAL_SUBMISSION_RECORDED,
        entity_type="nar1_case", entity_id=case_id, case_id=case_id,
        new_value="Completed",
        metadata={"channel": "off_portal", "cr_called": False,
                  "submitted_at": now},
    )
    return nar1_cases.composite(case_id)
