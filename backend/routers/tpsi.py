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

from middleware.auth import require_permission, require_super_admin
from services import audit_events as ev
from services.audit_service import log_event
from services.tpsi import credentials, filings, reads, shared_credentials
# Moved to services/tpsi/filings.py (BE-4): it reads only filings.* vocabulary,
# and services/nar1_cases.py needed it too — a service importing a router is
# an inverted dependency. Imported here so `routers.tpsi.form_status` still
# resolves for existing call sites in this router and existing tests.
from services.tpsi.filings import form_status
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
    deposit_account_no: str | None = None


def _opt(body: CredentialIn, name: str):
    """Tell "client omitted this field" apart from "client sent null".

    Pydantic fills an omitted optional with None, and credentials._payload reads
    None as an explicit "clear this column". Passing it straight through means
    the ROUTINE case — CR forces a TPSI password change every 180 days, so a
    password-only rotation is the common one — silently wipes the stored
    e-Service signing password and the deposit account number.

    model_fields_set contains only what was actually in the request body, so it
    is what carries the distinction across the HTTP boundary to the _UNSET
    sentinel the service layer already implements.
    """
    return getattr(body, name) if name in body.model_fields_set else credentials.UNSET


class PasswordChangeIn(BaseModel):
    new_password: str


def client_for(
    user: dict, credential: "shared_credentials.SharedPresenter | None" = None
) -> TpsiClient:
    """Build a client bound to the SHARED GSHK presenter account (BE-5, W-6).

    Was per-user (PBI-44 AC5/AC8). Everything GSHK files, it files under one CR
    identity, so a staff change never means a new CR account and a filing is
    never attributed to whoever happened to click the button. The `user`
    argument stays in the signature: the caller is still who the AUDIT records,
    and who must supply the e-Service signature.

    `credential`: when a caller (submit_filing/preview_filing, via
    `_deposit_account`) already loaded the shared record to resolve the
    deposit account, it is passed straight through here instead of being
    decrypted and round-tripped from Supabase a second time in the same
    request.
    """
    credential = credential or shared_credentials.load_for_use()
    return TpsiClient(credential.account_id, credential.tpsi_password)


def _deposit_account(
    explicit: str | None,
    shared: "shared_credentials.SharedPresenter | None" = None,
) -> str:
    """The deposit account a charge is drawn from.

    An explicit value still wins — a second GSHK deposit account would be named
    per call — but the frontend no longer knows or sends one, so the shared
    presenter record is the source. Refuses rather than defaulting to empty: a
    submit is chargeable and irreversible, and an unknown account is not a
    condition to discover at CR.

    `shared`: when the caller already loaded the shared presenter record (to
    also pass into `client_for`), it is reused here rather than loaded again —
    see the callers in preview_filing/submit_filing.
    """
    if explicit:
        return explicit
    shared = shared or shared_credentials.load_for_use()
    account = shared.deposit_account_no
    if not account:
        raise HTTPException(
            400,
            "no deposit account is configured on the shared presenter "
            "credential — a Super Admin must set one before submitting",
        )
    return account


async def audit_auth(user: dict, client: TpsiClient) -> None:
    """Record TPSI_AUTH when a CR session was actually opened.

    `client.last_auth` is set only on a real login, never on cache reuse, so the
    audit trail shows when a session opened rather than once per API call. Also
    persists `password_expires_in` — the 180-day expiry has to surface before it
    blocks a filing, not when someone is mid-submission.

    Persisted against the SHARED presenter record (BE-5): the CR login is now
    shared, so its 180-day expiry is a property of the shared credential, not
    of whichever user happened to trigger the session.

    The CR call that got us here already succeeded — record_password_expiry is
    bookkeeping on top of that success, not part of it. Same never-raise
    discipline as `log_event`: a Supabase hiccup here must not turn a
    successful balance/status read into a 500.
    """
    if client.last_auth is None:
        return
    try:
        shared_credentials.record_password_expiry(client.last_auth.password_expires_in)
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
        eservice_user_id=_opt(body, "eservice_user_id"),
        eservice_password=_opt(body, "eservice_password"),
        deposit_account_no=_opt(body, "deposit_account_no"),
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
        eservice_user_id=_opt(body, "eservice_user_id"),
        eservice_password=_opt(body, "eservice_password"),
        deposit_account_no=_opt(body, "deposit_account_no"),
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


class SharedCredentialIn(BaseModel):
    presentor_account_id: str
    tpsi_password: str
    deposit_account_no: str | None = None
    rotated: bool = False


@router.get("/shared-credential")
async def get_shared_credential(user=Depends(require_super_admin())):
    """Metadata only — this path cannot return a secret.

    Super Admin only (OQ-C): this record IS the GSHK filing identity, and the
    deposit account it names is real money. `tpsi:write` lets a user file; it
    does not let them change who GSHK files as.
    """
    return shared_credentials.get_metadata() or {}


@router.put("/shared-credential")
async def put_shared_credential(
    body: SharedCredentialIn, user=Depends(require_super_admin())
):
    try:
        meta = shared_credentials.set_shared(
            presentor_account_id=body.presentor_account_id,
            tpsi_password=body.tpsi_password,
            deposit_account_no=_opt(body, "deposit_account_no"),
            updated_by=user["id"],
            rotated=body.rotated,
        )
    except Exception as exc:
        raise _handle(exc)

    await log_event(
        user_id=user["id"], user_display_name=user["display_name"],
        action_type=ev.TPSI_CRED_CONFIG, event_code=ev.TPSI_CRED_CONFIG,
        entity_type="tpsi_credential", entity_id="shared",
        metadata={"presentor_account_id": body.presentor_account_id,
                  "rotated": body.rotated},
    )
    return meta


@router.post("/credentials/password")
async def change_password(
    body: PasswordChangeIn, user=Depends(require_super_admin())
):
    """Rotates the SHARED GSHK presenter's CR login password (BE-5).

    Super Admin only (OQ-C) — the same rationale as PUT /tpsi/shared-
    credential: `client_for` authenticates every call as the shared
    presenter now, so this changes the ONE password every filing in the
    system depends on, not a caller's own.

    Persists the new password back to tpsi_shared_presenter on success. This
    step is NOT allowed to fail silently the way log_event/record_password_
    expiry do: if CR accepts the new password but the write-back fails, CR
    and our store disagree, and every subsequent client_for() call
    authenticates with a stale password against an API that locks accounts
    on repeated failure.
    """
    try:
        shared = shared_credentials.load_for_use()
        result = client_for(user, shared).change_password(body.new_password)
    except Exception as exc:
        raise _handle(exc)

    try:
        # deposit_account_no deliberately omitted (defaults to _UNSET) so the
        # stored value survives the rotation — CR forces this every 180 days,
        # so a password-only rotation is the routine case, not the exception.
        shared_credentials.set_shared(
            presentor_account_id=shared.account_id,
            tpsi_password=body.new_password,
            updated_by=user["id"],
            rotated=True,
        )
    except Exception as exc:
        raise HTTPException(
            500,
            "CR accepted the new password but it could not be saved. The "
            "stored credential is now stale and every subsequent request "
            "will fail authentication until this is corrected. Set the new "
            "password immediately via PUT /tpsi/shared-credential.",
        ) from exc

    await log_event(
        user_id=user["id"],
        user_display_name=user["display_name"],
        action_type=ev.TPSI_PW_CHANGE,
        event_code=ev.TPSI_PW_CHANGE,
        entity_type="tpsi_credential",
        entity_id="shared",
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
    except Exception as exc:
        raise _handle(exc)

    await log_event(
        user_id=user["id"], user_display_name=user["display_name"],
        action_type=ev.TPSI_FILING_CREATED, event_code=ev.TPSI_FILING_CREATED,
        entity_type="tpsi_filing", entity_id=row["id"],
        metadata={"form_code": body.form_code, "entity_id": body.entity_id},
    )
    return row


@router.get("/filings/{filing_id}")
async def get_filing(filing_id: str, user=Depends(require_permission("tpsi", "read"))):
    """Form status for one filing. Read-only, no CR call, no charge."""
    try:
        row = filings.get_filing(filing_id)
    except Exception as exc:
        raise _handle(exc)
    return {
        "filing_id": filing_id,
        "form_code": row["form_code"],
        "entity_id": row["entity_id"],
        "nar1_case_id": row.get("nar1_case_id"),
        "form_status": form_status(row),
        "validated_at": row.get("validated_at"),
        "signed_at": row.get("signed_at"),
        "submitted_at": row.get("submitted_at"),
        "receipt": row.get("receipt"),
    }


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
    return {"filing_id": filing_id, "stage": row["stage"], "form_status": form_status(row)}


class SignIn(BaseModel):
    """Either sign as the logged-in user (stored e-Service password), or name a
    director who supplies their own credentials live — never stored (spec D4)."""
    signatory_user_id: str | None = None
    eservice_password: str | None = None


@router.post("/filings/{filing_id}/sign")
async def sign_filing(
    filing_id: str, body: SignIn, user=Depends(require_permission("tpsi", "write"))
):
    # credentials.load_eservice lives INSIDE the try now, not before it: a
    # None it returns must map to a clean 400 via _handle like every other
    # TPSI endpoint (see /balance), not surface as an unhandled 500.
    try:
        if body.signatory_user_id and body.eservice_password:
            signatory, password = body.signatory_user_id, body.eservice_password
        else:
            pair = credentials.load_eservice(user["id"])
            if pair is None:
                raise HTTPException(
                    400,
                    "no stored e-Service password; supply signatory_user_id and "
                    "eservice_password for this signature",
                )
            signatory, password = pair

        result = filings.sign(client_for(user), filing_id, signatory, password)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise _handle(exc)

    await log_event(
        user_id=user["id"], user_display_name=user["display_name"],
        action_type=ev.TPSI_SIGN, event_code=ev.TPSI_SIGN,
        entity_type="tpsi_filing", entity_id=filing_id,
        # signatory id only — never the password (audit_service also scrubs it)
        metadata={"signatory": signatory, "result": result["result"]},
    )
    return result


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


class SubmitIn(BaseModel):
    deposit_account: str | None = None
    confirm: bool = False


@router.get("/filings/{filing_id}/preview")
async def preview_filing(
    filing_id: str,
    deposit_account: str | None = None,
    user=Depends(require_permission("tpsi", "read")),
):
    """Fee + live balance, nothing sent to CR. Audited separately from the
    confirm so the trail shows the preview and the decision to spend as two
    distinct events."""
    try:
        # Loaded once (when no explicit account was given) and handed to both
        # _deposit_account and client_for — one Supabase round trip and one
        # decrypt per request, not two. See _deposit_account.
        shared = None if deposit_account else shared_credentials.load_for_use()
        client = client_for(user, shared)
        account = _deposit_account(deposit_account, shared)
        result = filings.preview(client, filing_id, account)
    except Exception as exc:
        raise _handle(exc)

    await audit_auth(user, client)
    await log_event(
        user_id=user["id"], user_display_name=user["display_name"],
        action_type=ev.TPSI_PREVIEWED, event_code=ev.TPSI_PREVIEWED,
        entity_type="tpsi_filing", entity_id=filing_id,
        metadata={"fee": result["fee"], "sufficient": result["sufficient"]},
    )
    return result


@router.post("/filings/{filing_id}/submit")
async def submit_filing(
    filing_id: str, body: SubmitIn, user=Depends(require_permission("tpsi", "submit"))
):
    """CHARGEABLE AND IRREVERSIBLE.

    Gated on `tpsi:submit`, deliberately distinct from `tpsi:write`: a role may
    be allowed to prepare, validate and sign a NAR1 without being allowed to
    spend from the deposit account.
    """
    # Resolved BEFORE the attempt is logged and before any CR call: a submit
    # with an unresolvable deposit account is a clean 400, not something
    # discovered mid-CR-call after money could have moved. Loaded once (when
    # no explicit account was given) and handed to both _deposit_account and
    # client_for — see _deposit_account. Wrapped like every other TPSI
    # failure mode in this file: an unconfigured or env-mismatched shared
    # credential (LookupError/RuntimeError from load_for_use) must reach the
    # caller as a clean 400/502 via _handle, not an unhandled 500 — _deposit_
    # account's own HTTPException(400) passes through _handle unchanged.
    try:
        shared = None if body.deposit_account else shared_credentials.load_for_use()
        account = _deposit_account(body.deposit_account, shared)
    except Exception as exc:
        raise _handle(exc)

    await log_event(
        user_id=user["id"], user_display_name=user["display_name"],
        action_type=ev.TPSI_SUBMISSION_ATTEMPTED,
        event_code=ev.TPSI_SUBMISSION_ATTEMPTED,
        entity_type="tpsi_filing", entity_id=filing_id,
        metadata={"deposit_account": account, "confirm": body.confirm},
    )
    try:
        result = filings.submit(
            client_for(user, shared), filing_id, body.confirm, account
        )
    except filings.SubmitGateError as exc:
        await log_event(
            user_id=user["id"], user_display_name=user["display_name"],
            action_type=ev.TPSI_SUBMISSION_FAILED,
            event_code=ev.TPSI_SUBMISSION_FAILED,
            entity_type="tpsi_filing", entity_id=filing_id,
            metadata={"reason": str(exc), "gate": True},
        )
        raise HTTPException(409, str(exc))
    except Exception as exc:
        await log_event(
            user_id=user["id"], user_display_name=user["display_name"],
            action_type=ev.TPSI_SUBMISSION_FAILED,
            event_code=ev.TPSI_SUBMISSION_FAILED,
            entity_type="tpsi_filing", entity_id=filing_id,
            metadata={"reason": str(exc)},
        )
        raise _handle(exc)

    await log_event(
        user_id=user["id"], user_display_name=user["display_name"],
        action_type=ev.TPSI_SUBMISSION_SUCCESS,
        event_code=ev.TPSI_SUBMISSION_SUCCESS,
        entity_type="tpsi_filing", entity_id=filing_id,
        metadata={
            "caseNo": result["receipt"].get("caseNo"),
            "totalAmount": result["receipt"].get("totalAmount"),
        },
    )
    return result
