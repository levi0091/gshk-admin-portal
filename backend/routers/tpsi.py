"""TPSI endpoints.

Permission rule (spec §6): the level reflects the effect on CR and on money,
not on our own ledger.
    read   -> no CR-side effect, no charge (balance, status, validate)
    write  -> changes something at CR or stores a credential (sign, e-Drive)
    submit -> chargeable and irreversible
"""
import sys
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from middleware.auth import require_permission
from services import audit_events as ev
from services.audit_service import log_event
from services.tpsi import credentials, filings, reads
from services.tpsi.client import TpsiClient
from services.tpsi.errors import (
    TpsiAuthError,
    TpsiError,
    TpsiPasswordExpiredError,
    TpsiUnavailableError,
)

router = APIRouter()


class CredentialIn(BaseModel):
    presentor_account_id: str
    tpsi_password: str
    eservice_user_id: str | None = None
    eservice_password: str | None = None


class PasswordChangeIn(BaseModel):
    new_password: str


def client_for(user: dict) -> TpsiClient:
    """Build a client bound to the logged-in user's own CR account (spec D5)."""
    credential = credentials.load_for_use(user["id"])
    return TpsiClient(credential.account_id, credential.tpsi_password)


async def audit_auth(user: dict, client: TpsiClient) -> None:
    """Record TPSI_AUTH when a CR session was actually opened.

    `client.last_auth` is set only on a real login, never on cache reuse, so the
    audit trail shows when a session opened rather than once per API call. Also
    persists `password_expires_in` — the 180-day expiry has to surface before it
    blocks a filing, not when someone is mid-submission.

    The CR call that got us here already succeeded — record_password_expiry is
    bookkeeping on top of that success, not part of it. Same never-raise
    discipline as `log_event`: a Supabase hiccup here must not turn a
    successful balance/status read into a 500.
    """
    if client.last_auth is None:
        return
    try:
        credentials.record_password_expiry(user["id"], client.last_auth.password_expires_in)
    except Exception as exc:
        print(f"[routers.tpsi] ERROR: failed to persist password_expires_in: {exc}", file=sys.stderr)
    await log_event(
        user_id=user["id"],
        user_display_name=user["display_name"],
        action_type=ev.TPSI_AUTH,
        event_code=ev.TPSI_AUTH,
        entity_type="tpsi",
        entity_id=client.account_id,
        metadata={"password_expires_in": client.last_auth.password_expires_in},
    )


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, (LookupError, ValueError)):
        return HTTPException(400, str(exc))
    if isinstance(exc, TpsiPasswordExpiredError):
        return HTTPException(409, str(exc))
    if isinstance(exc, TpsiAuthError):
        return HTTPException(502, str(exc))
    if isinstance(exc, TpsiUnavailableError):
        return HTTPException(503, str(exc))
    if isinstance(exc, (TpsiError, RuntimeError)):
        return HTTPException(502, str(exc))
    raise exc


@router.get("/credentials")
async def get_credentials(user=Depends(require_permission("tpsi", "read"))):
    """Metadata only — this path cannot return a secret."""
    return credentials.get_metadata(user["id"]) or {}


@router.post("/credentials")
async def set_credentials(
    body: CredentialIn, user=Depends(require_permission("tpsi", "write"))
):
    meta = credentials.set_credential(
        user_id=user["id"],
        presentor_account_id=body.presentor_account_id,
        tpsi_password=body.tpsi_password,
        eservice_user_id=body.eservice_user_id,
        eservice_password=body.eservice_password,
    )
    await log_event(
        user_id=user["id"],
        user_display_name=user["display_name"],
        action_type=ev.TPSI_CRED_SET,
        event_code=ev.TPSI_CRED_SET,
        entity_type="tpsi_credential",
        entity_id=user["id"],
        metadata={"presentor_account_id": body.presentor_account_id},
    )
    return meta


@router.put("/credentials")
async def rotate_credentials(
    body: CredentialIn, user=Depends(require_permission("tpsi", "write"))
):
    meta = credentials.rotate_credential(
        user_id=user["id"],
        presentor_account_id=body.presentor_account_id,
        tpsi_password=body.tpsi_password,
        eservice_user_id=body.eservice_user_id,
        eservice_password=body.eservice_password,
    )
    await log_event(
        user_id=user["id"],
        user_display_name=user["display_name"],
        action_type=ev.TPSI_CRED_ROTATE,
        event_code=ev.TPSI_CRED_ROTATE,
        entity_type="tpsi_credential",
        entity_id=user["id"],
        metadata={"presentor_account_id": body.presentor_account_id},
    )
    return meta


@router.post("/credentials/password")
async def change_password(
    body: PasswordChangeIn, user=Depends(require_permission("tpsi", "write"))
):
    try:
        result = client_for(user).change_password(body.new_password)
    except Exception as exc:
        raise _handle(exc)

    await log_event(
        user_id=user["id"],
        user_display_name=user["display_name"],
        action_type=ev.TPSI_PW_CHANGE,
        event_code=ev.TPSI_PW_CHANGE,
        entity_type="tpsi_credential",
        entity_id=user["id"],
        metadata={"result": result},
    )
    return {"result": result}


@router.get("/balance")
async def balance(account_no: str, user=Depends(require_permission("tpsi", "read"))):
    try:
        client = client_for(user)
        amount: Decimal = reads.check_balance(client, account_no)
    except Exception as exc:
        raise _handle(exc)

    await audit_auth(user, client)
    await log_event(
        user_id=user["id"],
        user_display_name=user["display_name"],
        action_type=ev.TPSI_BALANCE_CHECK,
        event_code=ev.TPSI_BALANCE_CHECK,
        entity_type="tpsi",
        entity_id=account_no,
        metadata={"account_no": account_no},
    )
    return {"account_no": account_no, "balance": str(amount)}


@router.get("/doc-status")
async def doc_status(
    br_no: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    case_no: str | None = None,
    document_ref_no: str | None = None,
    user=Depends(require_permission("tpsi", "read")),
):
    try:
        client = client_for(user)
        rows = reads.case_status(
            client,
            br_no=br_no,
            date_start=date_start,
            date_end=date_end,
            case_no=case_no,
            document_ref_no=document_ref_no,
        )
    except Exception as exc:
        raise _handle(exc)

    await audit_auth(user, client)
    await log_event(
        user_id=user["id"],
        user_display_name=user["display_name"],
        action_type=ev.TPSI_STATUS,
        event_code=ev.TPSI_STATUS,
        entity_type="tpsi",
        entity_id=case_no or document_ref_no or br_no or "",
        metadata={"results": len(rows)},
    )
    return rows


class FilingIn(BaseModel):
    entity_id: str
    form_code: str
    form_xml: str
    nar1_case_id: str | None = None
    form_filing_id: str | None = None


@router.post("/filings")
async def create_filing(
    body: FilingIn, user=Depends(require_permission("tpsi", "write"))
):
    try:
        row = filings.create_filing(
            entity_id=body.entity_id,
            form_code=body.form_code,
            form_xml=body.form_xml,
            user_id=user["id"],
            nar1_case_id=body.nar1_case_id,
            form_filing_id=body.form_filing_id,
        )
    except KeyError:
        raise HTTPException(400, f"unknown form code {body.form_code}")

    await log_event(
        user_id=user["id"], user_display_name=user["display_name"],
        action_type=ev.TPSI_FILING_CREATED, event_code=ev.TPSI_FILING_CREATED,
        entity_type="tpsi_filing", entity_id=row["id"],
        metadata={"form_code": body.form_code, "entity_id": body.entity_id},
    )
    return row


@router.post("/filings/{filing_id}/validate")
async def validate_filing(
    filing_id: str, user=Depends(require_permission("tpsi", "read"))
):
    """`read`: no CR-side effect and no charge (spec §6)."""
    try:
        row = filings.validate(client_for(user), filing_id)
    except Exception as exc:
        raise _handle(exc)

    await log_event(
        user_id=user["id"], user_display_name=user["display_name"],
        action_type=ev.TPSI_VALIDATE, event_code=ev.TPSI_VALIDATE,
        entity_type="tpsi_filing", entity_id=filing_id,
        metadata={"stage": row["stage"]},
    )
    return {"filing_id": filing_id, "stage": row["stage"]}


@router.post("/filings/{filing_id}/edrive")
async def edrive_filing(
    filing_id: str, user=Depends(require_permission("tpsi", "write"))
):
    try:
        result = filings.upload_edrive(client_for(user), filing_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise _handle(exc)

    await log_event(
        user_id=user["id"], user_display_name=user["display_name"],
        action_type=ev.TPSI_EDRIVE, event_code=ev.TPSI_EDRIVE,
        entity_type="tpsi_filing", entity_id=filing_id,
        metadata={"result": result["result"]},
    )
    return result
