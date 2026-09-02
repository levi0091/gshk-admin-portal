"""NAR1 case-workflow endpoints (BE-4).

Permission module is `nar1` (OQ-B, Levi 2026-08-16) — deliberately not
`companies`. Editing a company record and driving a statutory filing are
different authorities: the second sends mail to clients and spends money.
"""
import asyncio
import os
import re
import sys
from datetime import datetime, timezone

from fastapi import (APIRouter, Depends, File, HTTPException, Query, Request,
                     UploadFile)
from pydantic import BaseModel

from middleware.auth import require_permission
from services import (
    audit_events as ev, document_service, email_service, nar1_approvals,
    nar1_case_status, nar1_cases, nar1_return_data, table_filters as tf,
)
from services.nar1_form import fill as nar1_form_fill
from services.nar1_form.appearance import AppearanceError
from services.audit_service import log_event
from services.tpsi import filings as tpsi_filings
from services.tpsi.forms import nar1_source
from services.tpsi.forms.cr_vocabularies import (
    CAPACITY_BODY_CORPORATE, CAPACITY_INDIVIDUAL,
)

router = APIRouter()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit_target(case: dict) -> dict:
    """Where a NAR1 audit row points.

    `audit_log.case_id` HOLDS THE ENTITY ID, not the case id. That is the
    convention the rest of the repo already writes and reads:
    `routers/companies.py` puts `company["id"]` there, and `routers/audit.py`
    filters the company trail with `.eq("case_id", company_id)`.

    Writing `nar1_cases.id` into it instead — which every log_event in this
    file used to do — made the whole NAR1 workflow **invisible** on a company's
    audit trail: status changes, client verification, manual signing and the
    off-portal submission all wrote rows that no company query could ever
    return, and that rendered with a blank company name. That trail is the
    record PBI-11 exists to keep, so the id space has to match.

    The case's own id keeps its place in `entity_id`, where
    `entity_type="nar1_case"` says how to read it.
    """
    target = {
        "entity_type": "nar1_case",
        "entity_id": case["id"],
        "case_id": case.get("entity_id"),
    }
    try:
        entity = nar1_cases.entity_for(case["entity_id"])
    except Exception:  # noqa: BLE001
        # Audit must never block or fail the operation it is recording, and a
        # missing company name is a worse trail, not a broken one.
        return target
    target["company_name"] = (entity or {}).get("company_name")
    return target


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
    #: CR's selectCapacityDesc for whoever signs this return. Empty string
    #: clears it back to "not yet chosen"; None (absent) leaves it alone. That
    #: distinction matters — a picker reset to its blank option must be able to
    #: say so, and `None` already means "field not in this PATCH".
    signatory_capacity: str | None = None


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
        **_audit_target(row),
        new_value="Data Verification",
        metadata={"case_no": row.get("case_no"), "entity_id": body.entity_id},
    )
    return row


@router.get("")
async def list_cases(
    scope: str | None = Query(None, description="dashboard"),
    search: str | None = Query(None),
    workflow_status: str | None = Query(
        None, description="one badge, or several comma-separated"),
    anniv_op: str | None = Query(None, description="lte | gte | eq"),
    anniv_days: int | None = Query(None, description="signed day count"),
    filter_: list[str] = Query(
        default_factory=list, alias="filter",
        description="repeatable column:op:value — see services/table_filters",
    ),
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
    # One badge or several. The two dashboard tiles each stand for a SET —
    # "Action Required" is the five badges whose next move is ours — so the
    # parameter that the tile writes has to be able to say all five.
    picked = [s for s in (workflow_status or "").split(",") if s]
    unknown = [s for s in picked if s not in nar1_case_status.WORKFLOW_STATUSES]
    if unknown:
        raise HTTPException(422, f"Unknown workflow status '{unknown[0]}'")
    if sort and sort not in nar1_cases._SORTABLE:
        raise HTTPException(422, f"Cannot sort by '{sort}'")
    try:
        col_filters = tf.parse(filter_, nar1_cases._FILTERABLE)
    except tf.FilterError as exc:
        raise HTTPException(422, str(exc))

    return await nar1_cases.list_dashboard(
        search=search,
        workflow_statuses=picked,
        anniv_op=anniv_op,
        anniv_days=anniv_days,
        filters=col_filters,
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


@router.get("/{case_id}/return-data")
async def get_return_data(
    case_id: str, user=Depends(require_permission("nar1", "read"))
):
    """What CR is about to be shown, read off the live company profile.

    `nar1:read`, not `tpsi:write`: this opens no filing and contacts no one. It
    is the Data Verification card, and an operator who may look at the case may
    look at the return it is about.
    """
    try:
        case = nar1_cases.get_case(case_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc))

    try:
        graph = await nar1_source.load_entity_graph(case["entity_id"])
    except LookupError as exc:
        raise HTTPException(404, str(exc))

    return nar1_return_data.summarise(
        graph, signatory_capacity=case.get("signatory_capacity")
    )


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

    if body.signatory_capacity is not None:
        capacity = body.signatory_capacity.strip()
        # Validated against cr_vocabularies — the same table the mapper checks,
        # so there is one vocabulary and not two that can drift. Both lists are
        # accepted here rather than only the body-corporate one: this endpoint
        # does not know whether the resolved signatory is a person or a company,
        # and the mapper checks the value against the RIGHT list for the actual
        # signatory anyway. Rejecting a valid Individual value here would block
        # a natural-person signer for no reason.
        if capacity and capacity not in (
            CAPACITY_BODY_CORPORATE | CAPACITY_INDIVIDUAL
        ):
            raise HTTPException(
                400,
                f"signatory_capacity {capacity!r} is not in CR's capacity "
                f"vocabulary. CR accepts any string here and rejects it "
                f"server-side, after the fee has been taken.",
            )
        if capacity != (before.get("signatory_capacity") or ""):
            patch["signatory_capacity"] = capacity or None
            events.append((ev.CASE_FIELD_UPDATED, "signatory_capacity",
                           before.get("signatory_capacity"), capacity or None))

    if body.assigned_to is not None and body.assigned_to != before.get("assigned_to"):
        patch["assigned_to"] = body.assigned_to
        events.append((ev.CASE_FIELD_UPDATED, "assigned_to",
                       before.get("assigned_to"), body.assigned_to))

    if body.restart_verification:
        # REFUSED ONCE THE RETURN IS FILED (Levi 2026-08-31).
        #
        # `supersede()` already declined to retire a filed filing, so the FILING
        # was never in danger — but the handler went on to clear
        # verification_sent_at, client_approved and client_response_at anyway.
        # A completed case lost the client's recorded approval and dropped back
        # to Client Verification while CR held the registered return: a case
        # reporting it was waiting on a client whose answer had been acted on
        # days before, and an approval erased from the record that the filing
        # in the register was built on.
        #
        # Both roads to the register count. `manual_submitted_at` and
        # `manual_receipt` mean the return was filed off-portal, which is the
        # same fact arrived at differently — the manual gate in
        # `blocking_filing` makes exactly this distinction.
        filed = nar1_cases.current_filing(case_id)
        if (before.get("manual_submitted_at") or before.get("manual_receipt")
                or (filed and filed.get("stage") in nar1_cases.CR_FILED_STAGES)):
            raise HTTPException(
                409,
                "the Companies Registry already holds this return, so the "
                "verification behind it cannot be restarted; a filed return is "
                "corrected by filing again, not by re-asking the client",
            )

        # THE SNAPSHOT GOES TOO. The confirmation the operator clicks through
        # says "The case goes back to Data Verification. The CR-signed snapshot
        # is discarded" — and until this line existed, only the client-side
        # fields were cleared. The filing stayed at 'validated', so the case
        # landed back on CLIENT Verification holding CR's OLD signed XML, and
        # the next send mailed the client a return whose particulars had just
        # been corrected. That is precisely the "show one document, file
        # another" failure the verification gate exists to prevent.
        #
        # `supersede()` is still the second line of defence, not a formality:
        # it filters on the stage inside the UPDATE, so a submit that lands
        # between the guard above and this line cannot be un-filed here.
        filing = filed
        if filing and tpsi_filings.supersede(filing["id"]):
            events.append((ev.CASE_STATUS_CHANGED, "filing",
                           filing.get("stage"), "superseded"))

        # EVERY OUTSTANDING APPROVAL LINK STOPS WORKING (spec §5).
        #
        # Unconditional, and before the guard below: a director holding the
        # PREVIOUS email would otherwise be able to approve a snapshot that has
        # just been discarded and rebuilt, and the portal would record consent
        # to a document CR is no longer being asked to file. Same class of
        # defect as the stale snapshot `supersede()` above exists for, arriving
        # through a different door — which is why `outcome` carries a
        # 'superseded' value rather than being a boolean.
        #
        # Never blocks the restart: a token store that will not write is a
        # reason to shout on stderr, not a reason to leave the case holding a
        # snapshot the operator has already decided is wrong.
        try:
            nar1_approvals.supersede_outstanding(case_id)
        except Exception as exc:  # noqa: BLE001
            print(f"[cases] WARN: outstanding approval links could not be "
                  f"superseded for case {case_id}: {exc}", file=sys.stderr)

        if any(before.get(field) is not None
               for field in ("verification_sent_at", "client_approved",
                             "client_response_at")):
            # Guarded, because audit_log is insert-only: restarting a case that
            # was never sent for verification changes nothing, and writing
            # CASE_STATUS_CHANGED anyway puts a status transition in a permanent
            # trail that did not happen.
            #
            # All three cleared together, or the case reads as still-approved on
            # the next GET and jumps straight back to Signing.
            patch["verification_sent_at"] = None
            patch["client_approved"] = None
            patch["client_response_at"] = None
            # The provenance of an approval that no longer stands. Left behind,
            # the case would report "System-approved — the client did not
            # respond" over a case that is back at Data Verification and has no
            # client decision at all.
            patch["client_approval_source"] = None
            patch["client_approval_person_id"] = None
            patch["client_approval_name"] = None
            events.append((ev.CASE_STATUS_CHANGED, "verification",
                           "sent", "restarted"))

    if not patch and not events:
        return nar1_cases.composite(case_id)

    if patch:
        nar1_cases.update_case(case_id, patch)
    for action, field, old, new in events:
        await log_event(
            user_id=user["id"], user_display_name=user["display_name"],
            action_type=action, event_code=action,
            **_audit_target(before),
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
    user=Depends(require_permission("nar1", "write")),
):
    """Upload the wet-signed NAR1 (BE-6). No CR call.

    `nar1:write` (Levi 2026-08-22), NOT `documents:write`. It was the latter on
    the reasoning that this is "a document going into storage" — but the
    handler also writes `signing_method` and the signed-document pointer onto
    `nar1_cases`, and `signing_method` is a field `PATCH /cases/{id}` requires
    `nar1:write` to change. Two routes changing one column under two different
    permissions is the gap: a `documents:write`-only role could flip a case
    onto the manual path and open the `tpsi:submit` manual-submit gate behind
    it.

    Still not `tpsi:*`: the privileged act is recording the SUBMISSION, which
    is the next endpoint and does require `tpsi:submit`.
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
            **_audit_target(case),
            old_value=previous_method, new_value="manual",
            metadata={"field": "signing_method"},
        )

    await log_event(
        user_id=user["id"], user_display_name=user["display_name"],
        action_type=ev.NAR1_MANUAL_SIGN_UPLOADED,
        event_code=ev.NAR1_MANUAL_SIGN_UPLOADED,
        **_audit_target(case),
        new_value=file.filename,
        metadata={"document_id": document["id"], "filename": file.filename,
                  "bytes": len(content),
                  "version": patch["manual_signed_document_version"]},
    )
    return {"document_id": document["id"],
            "document_version": patch["manual_signed_document_version"]}


#: What CR's own portal hands back as a filing receipt. Nothing else: a receipt
#: is a scan or a download, and accepting arbitrary types would make the proof
#: behind an irreversible statutory record whatever the uploader chose to send.
RECEIPT_MIME_TYPES = frozenset({
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/tiff",
    "image/heic",
})


@router.post("/{case_id}/manual-receipt", status_code=201)
async def manual_receipt(
    case_id: str,
    file: UploadFile = File(...),
    user=Depends(require_permission("tpsi", "submit")),
):
    """Upload the CR filing receipt for an off-portal submission (spec §4).

    `tpsi:submit`, matching `manual-submit` rather than `manual-sign`. This file
    is the evidence a filing happened, and it is the second half of the gate
    that lets a case be declared filed; a role that could not record the
    submission must not be able to satisfy its precondition either.

    MANUAL PATH ONLY. An e-Signed filing gets its receipt from CR in the submit
    response (`filings.parse_receipt`), which is CR's own word rather than a
    scan somebody attached, so there is nothing to upload and nothing here
    touches it.

    NO CR CALL. Like the rest of this section, the filing happened outside the
    portal and the portal's job is to hold the evidence.
    """
    try:
        case = nar1_cases.get_case(case_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc))

    if case.get("manual_receipt"):
        raise HTTPException(
            409,
            "this case's off-portal submission is already recorded — the "
            "receipt behind it is fixed. Upload a corrected scan through the "
            "company's documents, which versions it.",
        )

    conflict = nar1_cases.manual_conflict(
        nar1_cases.blocking_filing(case_id), step="submit"
    )
    if conflict:
        raise HTTPException(409, conflict)

    content = await file.read()
    if not content:
        # A zero-byte upload proves nothing and would still satisfy the
        # manual-submit gate below — the same hole manual-sign closes.
        raise HTTPException(400, "the uploaded file is empty")

    # Checked against the DECLARED type, which is all an upload carries. It
    # keeps an honest mistake (a .docx, a .zip) out of the evidence slot; it is
    # not a content check and does not pretend to be one.
    mime = (file.content_type or "").split(";")[0].strip().lower()
    if mime not in RECEIPT_MIME_TYPES:
        raise HTTPException(
            400,
            f"a CR receipt must be a PDF or an image; this file declares "
            f"'{file.content_type or 'no type'}'",
        )

    document = await document_service.upload_document(
        # The CASE owns it, not the company (migration 029). upload_document
        # versions in place on (owner, type), so an entity-owned receipt would
        # have next year's return overwrite the row this year's case points at.
        owner_kind="receipt",
        owner_id=case_id,
        document_type_code="cr_receipt",
        file_name=file.filename or "cr-receipt.pdf",
        content=content,
        mime_type=mime,
        title=f"CR filing receipt — {case.get('case_no') or case_id}",
        user=user,
    )

    # Only after the upload succeeded: document_service raises on a storage
    # failure, and pointing the case at a document that was never stored would
    # open the manual-submit gate with no evidence behind it.
    patch = {
        "manual_receipt_document_id": document["id"],
        "manual_receipt_document_version": document.get("current_version") or 1,
    }
    nar1_cases.update_case(case_id, patch)

    await log_event(
        user_id=user["id"], user_display_name=user["display_name"],
        action_type=ev.NAR1_MANUAL_RECEIPT_ENTERED,
        event_code=ev.NAR1_MANUAL_RECEIPT_ENTERED,
        **_audit_target(case),
        new_value=file.filename,
        # `source` is what separates this row from the one manual-submit writes
        # under the same code. Both are "the receipt was entered"; one is the
        # scan, the other the figures typed off it, and a trail that could not
        # tell them apart would show two identical events for two different acts.
        metadata={"source": "upload", "document_id": document["id"],
                  "filename": file.filename, "bytes": len(content),
                  "mime_type": mime,
                  "version": patch["manual_receipt_document_version"]},
    )
    return {"document_id": document["id"],
            "document_version": patch["manual_receipt_document_version"],
            "file_name": document.get("file_name")}


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

    # BOTH halves of the receipt, spec §4. The typed figures are what the audit
    # trail and fee reconciliation read; the file is what proves CR ever issued
    # them. Nothing parses values out of the scan — one is not derived from the
    # other, so neither substitutes for the other.
    if not case.get("manual_receipt_document_id"):
        raise HTTPException(
            409,
            "upload the CR filing receipt before recording the submission — "
            "the typed figures are not evidence on their own",
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
        **_audit_target(case),
        after_state={"manual_receipt": body.receipt},
        metadata={"caseNo": body.receipt.get("caseNo"),
                  "totalAmount": body.receipt.get("totalAmount")},
    )
    await log_event(
        user_id=user["id"], user_display_name=user["display_name"],
        action_type=ev.NAR1_MANUAL_SUBMISSION_RECORDED,
        event_code=ev.NAR1_MANUAL_SUBMISSION_RECORDED,
        **_audit_target(case),
        new_value="Completed",
        metadata={"channel": "off_portal", "cr_called": False,
                  "submitted_at": now},
    )
    return nar1_cases.composite(case_id)


# ---------------------------------------------------------------------------
# Client verification (BE-3)
#
# R1 has NO inbound mail handling and no client-facing endpoint. The client
# replies to a human, and an admin records the answer here. Both routes are
# staff-only (`nar1:write`): there is no token, no magic link, and nothing an
# unauthenticated caller can reach -- which is precisely why this flow has no
# security surface to get wrong. Do not add one without revisiting that.
# ---------------------------------------------------------------------------

#: Deliberately weak, and only ever applied to an address a human typed into the
#: override box. It exists to catch "please send it to Mary" -- free text that
#: would otherwise be handed to Resend as a recipient. The address on record
#: comes out of the ETL and is filtered in nar1_cases.recipient_email.
_ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

#: Stages whose validated_xml IS the document CR is holding. `validation_failed`
#: is deliberately excluded and handled separately -- see _verification_gate.
_SENDABLE_STAGES = ("validated", "signed", "signing_failed", "submission_failed")


def _verification_gate(case: dict, filing: dict | None) -> str | None:
    """Why this case may not be sent for verification, or None."""
    if case.get("manual_receipt"):
        return ("this case was completed off-portal; there is nothing left for "
                "the client to approve")
    if filing is None:
        return "no filing has been prepared for this case yet"
    if (filing.get("form_code") or "").strip().lower() != "nar1":
        return (f"this filing is a {filing.get('form_code')} form; only NAR1 "
                "can be sent for client verification")
    if filing.get("stage") in nar1_cases.CR_FILED_STAGES:
        return ("CR already holds this return; asking the client to approve it "
                "now is a request their answer cannot change")
    # THE STALE-SNAPSHOT HOLE. filings.validate() sets the stage on failure but
    # LEAVES THE PREVIOUS validated_xml in place. So a filing CR has just
    # rejected still satisfies "has validated_xml", and a gate that checked only
    # that would mail the client a form CR is no longer holding.
    if filing.get("stage") == "validation_failed":
        return ("the most recent validation of this filing failed; re-validate "
                "before sending it to the client")
    if filing.get("stage") not in _SENDABLE_STAGES or not filing.get("validated_xml"):
        return ("this filing has not been validated by CR yet; the client would "
                "be approving a form that may be rejected minutes later")
    return None


#: One message, this many recipients at most. Resend's own ceiling is 50; the
#: lower bound here is about the return rather than the transport -- a NAR1
#: carries directors' residential addresses and identity numbers, and a
#: twenty-address send is a mistake long before it is a limit.
MAX_RECIPIENTS = 20


class VerificationSendIn(BaseModel):
    """Who this send goes to.

    A list, because a board of three directors is three recipients on ONE
    message. A bare string is still accepted: it is what the route shipped with,
    and a caller that sends one is not wrong.

    Absent (None) means "whoever the company's directors are" -- resolved at
    send time, not by the client. An empty LIST is not the same thing and is
    refused: it says the operator cleared every chip, and mailing the directors
    anyway would send a statutory return to people they had just removed.
    """
    to: list[str] | str | None = None


@router.get("/{case_id}/verification/recipients")
async def verification_recipients(
    case_id: str, user=Depends(require_permission("nar1", "read")),
):
    """Who this case's verification email goes to unless the operator says
    otherwise: every current director, and the company address behind them.

    Directors with NO address are returned too, each carrying the reason. The
    send screen shows them greyed rather than omitting them — a three-director
    board that renders two chips must not look like a two-director board.

    `nar1:read`, not `write`: this only says who would be mailed. Read-only, so
    nothing is audited.
    """
    try:
        case = nar1_cases.get_case(case_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc))

    recipients = nar1_cases.default_recipients(case["entity_id"])
    company_email = nar1_cases.recipient_email(case["entity_id"])
    default_to = [r["email"] for r in recipients if r["email"]]
    # Same fallback the send route applies, computed in one place so the screen
    # cannot promise one set of addresses and the send use another.
    if not default_to and company_email:
        default_to = [company_email]

    return {
        "recipients": recipients,
        "company_email": company_email,
        "default_to": default_to,
        "max_recipients": MAX_RECIPIENTS,
    }


def _approval_link_base(request: Request) -> str | None:
    """Where the client's approval link points (spec §5).

    `PUBLIC_API_BASE_URL` first — an explicit setting is the only thing that
    survives a proxy that rewrites Host, and Railway sits behind one. The
    incoming request's own base URL is the fallback, because the admin frontend
    reaches this API at the address the client should reach it at too.

    Returns None when neither yields an https/http origin, and the caller then
    sends the email WITHOUT a link. That is a real degradation, not a failure:
    the message already asks the client to reply, which is the path that existed
    before this feature and which staff still record by hand. Refusing to send
    at all would block every verification on one unset variable.
    """
    configured = (os.environ.get("PUBLIC_API_BASE_URL") or "").strip()
    base = configured or str(request.base_url or "").strip()
    if not base.lower().startswith(("http://", "https://")):
        return None
    return base.rstrip("/")


@router.post("/{case_id}/verification/send")
async def send_verification(
    case_id: str, body: VerificationSendIn, request: Request,
    user=Depends(require_permission("nar1", "write")),
):
    """Mail the client the PDF of the return CR validated, for approval.

    The attachment is rendered from `validated_xml` -- the document CR is
    holding -- not from the company profile as it reads today. Those two diverge
    the moment anyone edits the company, and the client must approve the thing
    that will actually be filed.
    """
    try:
        case = nar1_cases.get_case(case_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc))

    filing = nar1_cases.current_filing(case_id)
    refusal = _verification_gate(case, filing)
    if refusal:
        raise HTTPException(409, refusal)

    if body.to is not None:
        given = [body.to] if isinstance(body.to, str) else list(body.to)
        # Refused, not quietly turned back into "the directors" — see
        # VerificationSendIn. An operator who removed every chip did so on
        # purpose, and the alternative is mailing the people they just took off.
        if not given:
            raise HTTPException(
                422, "no recipient was given; add at least one address, or omit "
                     "'to' to use the directors on record")
        if len(given) > MAX_RECIPIENTS:
            raise HTTPException(
                422, f"{len(given)} recipients is more than one verification "
                     f"email should carry (limit {MAX_RECIPIENTS})")
        recipients = []
        seen = set()
        for address in given:
            address = (address or "").strip()
            # These direct a document carrying directors' residential addresses
            # and identity numbers. Free text is not an address.
            if not _ADDRESS.match(address):
                raise HTTPException(422, f"not an email address: {address!r}")
            # Case-insensitively deduped: two chips differing only in case are
            # one mailbox, and Resend would deliver the return to it twice.
            if address.lower() in seen:
                continue
            seen.add(address.lower())
            recipients.append(address)
    else:
        # Every current director with an address — the people whose particulars
        # this return declares. The company contact is the fallback for a
        # company whose directors carry no address at all, which is most of the
        # ETL'd book.
        recipients = [r["email"] for r in
                      nar1_cases.default_recipients(case["entity_id"]) if r["email"]]
        if not recipients:
            fallback = nar1_cases.recipient_email(case["entity_id"])
            recipients = [fallback] if fallback else []
        if not recipients:
            raise HTTPException(
                409, "no email address is on record for this company or its "
                     "directors; supply one explicitly to send the verification")

    entity = nar1_cases.entity_for(case["entity_id"])

    try:
        # CR's OWN FORM, not a summary of it (Levi 2026-08-30). This PDF is
        # attached to an email asking a director to approve their company's
        # statutory return. A director knows what Form NAR1 looks like; they
        # cannot check our field table against anything.
        #
        # Off the event loop: filling and compressing a 15-page AcroForm is
        # CPU-bound and this handler is `async def`, so rendering inline would
        # block every other request this worker is serving.
        pdf = await asyncio.to_thread(
            nar1_form_fill.render,
            filing["validated_xml"],
            company_type=nar1_form_fill.company_type_from_profile(
                entity.get("company_type")
            ),
        )
    except (ValueError, nar1_form_fill.FormFillError, AppearanceError) as exc:
        raise HTTPException(
            422, f"the validated snapshot could not be rendered: {exc}")

    attachment_name = f"NAR1-{case.get('case_no') or case_id}.pdf"

    # --- who each address belongs to, and their own approval link ---------- #
    #
    # ONE MESSAGE PER RECIPIENT, reversing this endpoint's original "a board of
    # three directors is one message with three recipients". Spec §5 needs to
    # record WHICH director approved, and the only honest evidence of that is a
    # token delivered to that director's mailbox alone. A shared link in a
    # shared message would let any recipient approve in any other's name, which
    # is a misattribution in a statutory record.
    #
    # The cost is partial failure, which the original shape avoided: a Resend
    # error on the second of three now leaves one director informed and two
    # not. That is handled below by reporting exactly which addresses failed
    # rather than by pretending the send was atomic.
    board = nar1_cases.default_recipients(case["entity_id"])
    by_email = {(r["email"] or "").lower(): r
                for r in board if r.get("email")}
    targets = [{
        "email": address,
        # For the greeting. See the `recipient_name=` argument below.
        "given_names": (by_email.get(address.lower()) or {}).get("given_names"),
        # None when an operator typed an address that belongs to no director on
        # record. The token is still real; the trail simply cannot name a
        # person, and says so rather than guessing.
        "person_id": (by_email.get(address.lower()) or {}).get("person_id"),
        "name": (by_email.get(address.lower()) or {}).get("name"),
    } for address in recipients]

    link_base = _approval_link_base(request)
    if link_base:
        try:
            targets = nar1_approvals.issue(case_id=case_id, recipients=targets)
        except Exception as exc:  # noqa: BLE001
            # A token store that will not write must not stop the return going
            # out. Without links the message is exactly the one that shipped
            # before spec §5, and staff record the reply by hand as they always
            # have.
            print(f"[cases] WARN: approval tokens could not be issued for case "
                  f"{case_id}: {exc}", file=sys.stderr)
            link_base = None

    operator = (user.get("email") or "").strip() or None

    sends, failures = [], []
    for index, target in enumerate(targets):
        approval_url = (
            f"{link_base}/public/nar1-approval/{target['token']}"
            if link_base and target.get("token") else None
        )
        subject, html = email_service.verification_email(
            case, entity, attachment_name=attachment_name,
            approval_url=approval_url,
            deadline=target.get("expires_at"),
            # The GIVEN name where the record has one. The letter greets the
            # reader by name, and this book is mostly Hong Kong directors
            # recorded surname-first — splitting a full name on whitespace
            # would greet CHAN TAI MAN as "Hi CHAN", which is their surname.
            recipient_name=target.get("given_names") or target.get("name"),
            # The case worker signs it, as they do when they send it by hand.
            sender_name=user.get("display_name"),
        )

        try:
            # Off the event loop: email_service.send is a synchronous
            # httpx.post with a 15-second timeout, so a hung Resend would stall
            # the whole worker rather than this one request.
            #
            # The COPY goes on the first message only. The case worker asked to
            # be copied on the request (Levi 2026-08-30), not on each director's
            # copy of it -- three directors must not mean three identical mails
            # in their inbox. `reply_to` is on EVERY message, because it is the
            # load-bearing half: the mail is sent from no-reply@getstarted.hk
            # and asks the client to reply, so without it the one action the
            # message requests reaches nobody.
            sent = await asyncio.to_thread(
                email_service.send,
                to=[target["email"]],
                cc=[operator] if (operator and index == 0) else None,
                reply_to=operator,
                subject=subject, html=html,
                attachments=[(attachment_name, pdf)],
            )
        except email_service.EmailError as exc:
            failures.append({"email": target["email"], "reason": str(exc)})
            continue
        except RuntimeError as exc:
            # Unset RESEND_API_KEY, or an EMAIL_TRANSPORT left over from before
            # the console stub was removed. A deployment fault, not a crash --
            # and it will fail identically for every remaining recipient, so
            # there is nothing to be gained by trying them.
            raise HTTPException(503, str(exc))
        sends.append({"target": target, "sent": sent})

    if not sends:
        # NOTHING is written: a case marked sent on mail that never left sits in
        # Awaiting Client forever, waiting on a reply to nothing.
        reasons = "; ".join(f["reason"] for f in failures) or "no recipients"
        raise HTTPException(502, f"the verification email was not sent: {reasons}")

    sent_at = datetime.now(timezone.utc).isoformat()
    patch = {"verification_sent_at": sent_at}

    # A previous answer answered the PREVIOUS request. Left in place it pins the
    # badge at Client Rejected forever while the client is looking at a fresh
    # PDF -- so it is cleared, and because that is a workflow change it has to
    # be visible as one rather than silently ceasing to count.
    superseded = case.get("client_approved")
    if superseded is not None or case.get("client_response_at") is not None:
        patch["client_approved"] = None
        patch["client_response_at"] = None
        # And how it was approved. See the restart branch: a stale provenance
        # would have the screen describe a decision the case no longer holds.
        patch["client_approval_source"] = None
        patch["client_approval_person_id"] = None
        patch["client_approval_name"] = None

    nar1_cases.update_case(case_id, patch)

    # Flattened across the per-recipient sends, so the audit row and the
    # response keep the same shape they had when this was one message. `to`
    # is who ACTUALLY received something; `intended_to` is who it was addressed
    # to. Outside production those differ, and a trail that recorded only the
    # intention would claim a client was told when they were not.
    def _across(key: str) -> list:
        out, seen = [], set()
        for record in sends:
            for address in (record["sent"].get(key) or []):
                if address not in seen:
                    seen.add(address)
                    out.append(address)
        return out

    delivered = _across("to") or [s["target"]["email"] for s in sends]
    intended = _across("intended_to") or [s["target"]["email"] for s in sends]
    copied = _across("cc")
    intended_cc = _across("intended_cc")
    message_ids = [s["sent"].get("id") for s in sends if s["sent"].get("id")]

    await log_event(
        user_id=user["id"], user_display_name=user["display_name"],
        action_type=ev.EMAIL_SENT, event_code=ev.EMAIL_SENT,
        **_audit_target(case),
        # Joined, because the trail renders `new_value` as text. EVERY address
        # is named: "who was told" is the fact this row exists to keep, and a
        # trail that recorded only the first of three directors would be worse
        # than one that recorded none -- it would look complete.
        new_value=", ".join(delivered),
        # Identifiers only. The PDF is the whole statutory return; its bytes
        # belong on the filing row, not in an insert-only trail -- and
        # after_state is NOT scrubbed by audit_service.
        metadata={# The first, kept so existing readers of this key still
                  # resolve to a real message; `message_ids` is the whole set,
                  # because there is now one message per director.
                  "message_id": message_ids[0] if message_ids else None,
                  "message_ids": message_ids,
                  "intended_to": intended,
                  "recipient_count": len(intended),
                  # Named, not counted. An operator who sees "2 of 3 sent" and
                  # not WHICH one failed cannot resend to the right person.
                  "failed_to": [f["email"] for f in failures],
                  # Both, for the same reason `to` and `intended_to` are both
                  # here: on a test deployment the copy is dropped rather than
                  # delivered, and a trail that recorded only the intention
                  # would claim the case worker was copied when they were not.
                  "cc": copied,
                  "intended_cc": intended_cc,
                  "redirected": bool(sent.get("redirected")),
                  # Always 'resend' now that the console stub is gone, and kept
                  # so the trail stays self-describing: existing rows say
                  # 'console', meaning NOTHING WAS DELIVERED, and a reader must
                  # be able to tell those apart from a real send without
                  # knowing the date the stub was removed.
                  "transport": sends[0]["sent"].get("transport", "resend"),
                  "case_no": case.get("case_no")},
    )

    # One row per director whose link went out. Spec §5's
    # CLIENT_APPROVAL_LINK_SENT: the trail has to be able to answer "who was
    # given the power to approve this, and when did their 14 days start" —
    # which the single EMAIL_SENT row above cannot, because it names addresses
    # and not the people or the deadlines behind them.
    for record in sends:
        target = record["target"]
        if not target.get("token"):
            continue
        await log_event(
            user_id=user["id"], user_display_name=user["display_name"],
            action_type=ev.CLIENT_APPROVAL_LINK_SENT,
            event_code=ev.CLIENT_APPROVAL_LINK_SENT,
            **_audit_target(case),
            new_value=target.get("name") or target["email"],
            # NO TOKEN. The trail is readable by every staff member with
            # audit_trail:read, and a token in it would let any of them approve
            # a client's statutory return in that client's name.
            metadata={"recipient_email": target["email"],
                      "person_id": target.get("person_id"),
                      "expires_at": (target["expires_at"].isoformat()
                                     if hasattr(target.get("expires_at"), "isoformat")
                                     else target.get("expires_at")),
                      "case_no": case.get("case_no")},
        )

    if "client_approved" in patch:
        await log_event(
            user_id=user["id"], user_display_name=user["display_name"],
            action_type=ev.CASE_STATUS_CHANGED,
            event_code=ev.CASE_STATUS_CHANGED,
            **_audit_target(case),
            old_value=("approved" if superseded
                       else "rejected" if superseded is False else None),
            new_value="awaiting_client",
            metadata={"reason": "a fresh verification request superseded the "
                                "previous client answer"},
        )

    return {"sent_at": sent_at, "to": delivered, "intended_to": intended,
            "cc": copied, "intended_cc": intended_cc,
            "redirected": any(bool(s["sent"].get("redirected")) for s in sends),
            "transport": sends[0]["sent"].get("transport", "resend"),
            "message_id": message_ids[0] if message_ids else None,
            "message_ids": message_ids,
            # Named so the operator can resend to exactly the people who were
            # missed, rather than re-mailing a board that mostly already has it.
            "failed_to": [f["email"] for f in failures],
            # False when PUBLIC_API_BASE_URL is unset and the request's own
            # base URL is unusable. The screen says so, because the difference
            # decides whether the client can confirm with a button or must
            # reply to the email.
            "approval_links": bool(link_base)}


class VerificationResponseIn(BaseModel):
    #: Required, with no default: an absent answer is not a "no".
    approved: bool
    #: WHO said so, when the staff member knows. Optional, because they may be
    #: relaying a reply from a shared company mailbox that names nobody — but
    #: recorded when it is known, because spec §5 forbids a bare "Approved" and
    #: "recorded by staff" alone does not say whose decision was relayed.
    approved_by: str | None = None


@router.post("/{case_id}/verification/response")
async def record_verification_response(
    case_id: str, body: VerificationResponseIn,
    user=Depends(require_permission("nar1", "write")),
):
    """Record the client's Yes/No, as relayed to an admin.

    R1 has no inbound mail handling: a human reads the reply and records it
    here. That is why this route is staff-only, and why it refuses to record an
    answer to a request that was never sent.
    """
    try:
        case = nar1_cases.get_case(case_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc))

    if not case.get("verification_sent_at"):
        raise HTTPException(
            409, "no verification request has been sent for this case; "
                 "recording a reply now would put an approval in the trail "
                 "with no request behind it")

    previous = case.get("client_approved")
    if previous is body.approved:
        # A no-op must not put a second client decision into an insert-only
        # trail -- the same rule PATCH /cases and manual-sign already follow.
        return nar1_cases.composite(case_id)

    nar1_cases.update_case(case_id, {
        "client_approved": body.approved,
        "client_response_at": datetime.now(timezone.utc).isoformat(),
        # Provenance, spec §5. A relayed reply must be distinguishable from a
        # client who pressed the button themselves and from one the 14-day job
        # approved on their silence — the three have different evidence behind
        # them and a reader has to be able to tell which they are looking at.
        "client_approval_source": (nar1_approvals.SOURCE_STAFF_RELAY
                                   if body.approved else None),
        "client_approval_name": ((body.approved_by or "").strip() or None
                                 if body.approved else None),
        "client_approval_person_id": None,
    })

    await log_event(
        user_id=user["id"], user_display_name=user["display_name"],
        action_type=ev.CLIENT_APPROVAL_RECEIVED,
        event_code=ev.CLIENT_APPROVAL_RECEIVED,
        **_audit_target(case),
        old_value=(None if previous is None
                   else "approved" if previous else "rejected"),
        new_value="approved" if body.approved else "rejected",
        metadata={"case_no": case.get("case_no"), "recorded_by_staff": True,
                  "channel": "staff_relay",
                  "approved_by": (body.approved_by or "").strip() or None},
    )
    return nar1_cases.composite(case_id)
