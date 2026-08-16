"""NAR1 case-workflow endpoints (BE-4).

Permission module is `nar1` (OQ-B, Levi 2026-08-16) — deliberately not
`companies`. Editing a company record and driving a statutory filing are
different authorities: the second sends mail to clients and spends money.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from middleware.auth import require_permission
from services import audit_events as ev, nar1_cases
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
        if body.signing_method not in ("esign", "manual"):
            raise HTTPException(400, "signing_method must be 'esign' or 'manual'")
        patch["signing_method"] = body.signing_method
        events.append((ev.CASE_FIELD_UPDATED, "signing_method",
                       before.get("signing_method"), body.signing_method))

    if body.assigned_to is not None:
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
