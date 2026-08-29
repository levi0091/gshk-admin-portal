"""TPSI endpoints.

Permission rule (spec §6): the level reflects the effect on CR and on money,
not on our own ledger.
    read   -> no CR-side effect, no charge (balance, status, validate)
    write  -> changes something at CR or stores a credential (sign, e-Drive)
    submit -> chargeable and irreversible
"""
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from middleware.auth import require_permission, require_super_admin
from services import audit_events as ev
from services import nar1_cases
from services.nar1_form import fill as nar1_form_fill
from services.audit_service import log_event
from services.tpsi import credentials, filings, reads, shared_credentials
from services.tpsi.forms import nar1, nar1_mapper, nar1_source, nar1_summary
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
    TpsiSignatureError,
    TpsiUnavailableError,
    TpsiValidationError,
    account_is_locked,
)

router = APIRouter()


class CredentialIn(BaseModel):
    """POST — first-time setup of a user's own SIGNING credential.

    Since BE-5 this row is a signing credential and nothing else: the CR LOGIN
    is the shared presenter record, and `client_for()` authenticates every call
    with that. Migration 020 dropped NOT NULL from both CR-login columns for
    exactly this reason ("The per-user row is now a SIGNING credential").

    So `presentor_account_id` and `tpsi_password` are OPTIONAL here. They were
    required when each user held their own CR login; demanding them now asks
    the caller for a personal TPSI password that no longer exists, which made
    POST unreachable for a signing-only credential and forced a first save
    through PUT — auditing it as TPSI_CRED_ROTATE, a rotation of something that
    had never been set.
    """
    presentor_account_id: str | None = None
    tpsi_password: str | None = None
    eservice_user_id: str | None = None
    eservice_password: str | None = None
    deposit_account_no: str | None = None


class CredentialUpdateIn(BaseModel):
    """PUT — rotation. EVERY field is optional, because changing one must not
    require re-supplying the others. Omitted fields keep their stored value
    (see _opt); an explicit null clears."""
    presentor_account_id: str | None = None
    tpsi_password: str | None = None
    eservice_user_id: str | None = None
    eservice_password: str | None = None
    deposit_account_no: str | None = None


def _opt(body, name: str):
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
    """Map a TPSI failure onto a response the UI can act on.

    CR REPORTS A LIST, AND THE LIST IS THE POINT. `TpsiValidationError` and
    `TpsiSignatureError` carry `.faults` — every problem CR found, as
    (code, message) pairs — and flattening them into `str(exc)` sent the
    operator round the loop one fault at a time. They travel as `problems`,
    the same structured shape `/tpsi/filings/prepare` already uses for mapper
    problems, which the fault panel already knows how to render.

    `kind` distinguishes the two rejections, because the remedies are in
    different places: a validation fault means fix the company record or the
    form; a signature fault means the signatory is not authorised for this
    company at CR, and no amount of editing the return will help.
    """
    if isinstance(exc, (LookupError, ValueError)):
        return HTTPException(400, str(exc))
    if isinstance(exc, TpsiPasswordExpiredError):
        return HTTPException(409, str(exc))

    if isinstance(exc, (TpsiValidationError, TpsiSignatureError)):
        signature = isinstance(exc, TpsiSignatureError)
        return HTTPException(502, {
            "message": ("The Companies Registry rejected the signature."
                        if signature else
                        "The Companies Registry rejected this return."),
            "problems": [list(f) for f in (exc.faults or [])],
            "kind": ("account_locked" if account_is_locked(exc)
                     else "signature" if signature else "validation"),
        })

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
        presentor_account_id=_opt(body, "presentor_account_id"),
        tpsi_password=_opt(body, "tpsi_password"),
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
    body: CredentialUpdateIn, user=Depends(require_permission("tpsi", "write"))
):
    meta = credentials.rotate_credential(
        user_id=user["id"],
        presentor_account_id=_opt(body, "presentor_account_id"),
        tpsi_password=_opt(body, "tpsi_password"),
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
    """The firm's single CR filing identity.

    `tpsi_password` is OPTIONAL on purpose: omitted, the stored one stands. The
    common edit is the deposit account, and making that require the password to
    be retyped from memory risks storing a typo — which surfaces only at CR as a
    failed authentication, and CR locks an account after repeated failures. It
    is required only when nothing is stored yet (enforced in set_shared).
    """
    presentor_account_id: str
    tpsi_password: str | None = None
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
            tpsi_password=_opt(body, "tpsi_password"),
            deposit_account_no=_opt(body, "deposit_account_no"),
            updated_by=user["id"],
            rotated=body.rotated,
        )
    except ValueError as exc:
        # "nothing stored yet, so supply one" — the caller's problem to fix.
        raise HTTPException(400, str(exc))
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
async def balance(
    account_no: str | None = None,
    user=Depends(require_permission("tpsi", "read")),
):
    """The deposit balance, for whichever account GSHK files from.

    `account_no` is OPTIONAL and normally omitted. An ordinary user may see the
    balance — it decides whether a filing can go ahead — but has no business
    knowing or supplying the shared account NUMBER, and requiring it here would
    have forced the frontend to fetch and hold a super-admin-only field. The
    shared presenter record is the source, exactly as it is for a submit.
    """
    try:
        shared = shared_credentials.load_for_use()
        resolved = _deposit_account(account_no, shared)
        client = client_for(user, shared)
        amount: Decimal = reads.check_balance(client, resolved)
    except Exception as exc:
        raise _handle(exc)

    # The trail records WHICH account was read — that is internal, and an audit
    # entry naming no account would be useless.
    await audit_auth(user, client)
    await log_event(
        user_id=user["id"],
        user_display_name=user["display_name"],
        action_type=ev.TPSI_BALANCE_CHECK,
        event_code=ev.TPSI_BALANCE_CHECK,
        entity_type="tpsi",
        entity_id=resolved,
        metadata={"account_no": resolved},
    )

    # The RESPONSE does not echo the account number back unless the caller
    # already supplied it. The balance is what a filer needs; the shared
    # account's number is a super-admin-only field (GET /tpsi/shared-credential)
    # and must not leak out of a read any `tpsi:read` holder can make.
    body = {"balance": str(amount)}
    if account_no:
        body["account_no"] = account_no
    return body


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


class PrepareIn(BaseModel):
    entity_id: str
    nar1_case_id: str
    #: The return's own year. Defaults to the current HK year -- a return
    #: prepared in January for last year's anniversary passes it explicitly.
    year: int | None = None
    form_filing_id: str | None = None
    #: Deliberately a raw dict, not a Pydantic sub-model. `map_entity` reads the
    #: ABSENCE of a key as meaning something: no `is_corporate` means a natural
    #: person, and a natural person without `person_id` is a MappingError rather
    #: than a statutory field that quietly vanishes. A sub-model would fill
    #: every omitted key with None and erase that distinction -- the same trap
    #: `_opt` exists for on the credential endpoints.
    #: Shape: {"name", "capacity", "person_id", "date", "is_corporate"}.
    signatory: dict | None = None


def _loader_failed(entity_id: str, exc: Exception) -> HTTPException:
    """A transport failure inside nar1_source, named as such.

    The loader has an observed, un-eliminated failure mode against Supabase's
    edge (`httpx.RemoteProtocolError: Server disconnected`, a Cloudflare 400).
    db/supabase.py now removes the one cause that was ours -- the unsynchronised
    lazy sub-client init this loader's five-way concurrent read hit cold -- but
    a network between here and Supabase can still drop a connection, and that
    must arrive as an upstream failure the caller can retry deliberately, not as
    an unhandled 500 that reads like a bug in the mapper.

    Deliberately NOT retried here. The failure is a concurrent read; re-issuing
    the same concurrent read does not make it likelier to succeed, and a retry
    of a partially-completed fan-out doubles real work for no gain.
    """
    return HTTPException(
        502,
        f"could not load entity {entity_id} from the profile store "
        f"(nar1_source.load_entity_graph): {type(exc).__name__}: {exc}",
    )


@router.post("/filings/prepare", status_code=201)
async def prepare_filing(
    body: PrepareIn, user=Depends(require_permission("tpsi", "write"))
):
    """Build the NAR1 XML server-side and open a filing (BE-1).

    The frontend posts identifiers, never XML. That is not ergonomics: if the
    client could supply form_xml it could file a document no one in G-FlowDesk
    ever reviewed, and the audit trail would show only that we sent it.

    Declared above the other /filings routes so the literal path is matched
    before any /filings/{filing_id} pattern.
    """
    # BEFORE anything else: a case CR already holds must not get a second draft.
    #
    # Nothing in the system writes stage 'superseded', so a new draft is simply
    # the NEWEST row for the case. current_filing() returns it, and case detail
    # then reports "Data Verification" for a return CR has already registered —
    # while nar1_case_registry, which prefers a filed stage, still reports
    # "Completed". One case, two contradictory badges, and the live filing
    # hidden behind a draft that can never advance.
    #
    # blocking_filing() is the right question here for the same reason the
    # manual path uses it: "has this return been filed?" is about ANY attempt,
    # not the latest one.
    try:
        blocking = nar1_cases.blocking_filing(body.nar1_case_id)
        case = nar1_cases.get_case(body.nar1_case_id)
    except LookupError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise _handle(exc)

    if case.get("manual_receipt"):
        raise HTTPException(
            409,
            "this case was completed off-portal; opening a CR filing against "
            "it would put two filings in the register for one return",
        )
    if blocking and blocking.get("stage") in nar1_cases.CR_FILED_STAGES:
        raise HTTPException(
            409,
            f"CR already holds this return (form status "
            f"'{blocking.get('stage')}'); preparing another filing would "
            "hide it behind a draft that cannot be advanced",
        )

    # Hong Kong's year, not UTC's: for the first eight hours of every HK working
    # day UTC is still on yesterday's date, and on 1 January that is the wrong
    # year on the statutory form.
    year = body.year or (datetime.now(timezone.utc) + timedelta(hours=8)).year

    try:
        graph = await nar1_source.load_entity_graph(body.entity_id)
    except LookupError as exc:
        # "no entity <id>" -- the caller's identifier is wrong, not the loader.
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise _loader_failed(body.entity_id, exc)

    # selectCapacityDesc for a body-corporate secretary cannot be derived from
    # the company profile — it depends on who at GSHK signs. It used to be a
    # refusal; Levi 2026-08-30 made it an operator choice, stored on the case by
    # PATCH /cases/{id}. Read from there rather than accepted as a request
    # field, so the value that gets filed is the one the operator saw on screen
    # and the audit trail recorded, not one this call could differ on.
    #
    # This router still invents NO default. An unchosen capacity stays None and
    # the mapper still refuses — the refusal simply now has a remedy on screen.
    capacity = None
    if body.nar1_case_id:
        try:
            capacity = (nar1_cases.get_case(body.nar1_case_id)
                        or {}).get("signatory_capacity")
        except LookupError:
            # A bad case id is the /cases endpoints' error to raise, not this
            # one's; prepare must not 404 on a field it merely consults.
            capacity = None

    try:
        # `signatory` is still passed straight through: an explicit override
        # replaces the whole signer, capacity included.
        data = nar1_mapper.map_entity(graph, year=year, signatory=body.signatory,
                                      signatory_capacity=capacity)
        form_xml = nar1.build_nar1_xml(data)
    except nar1_mapper.MappingError as exc:
        # The whole list, in a structured field the UI can render as CR's own
        # fault list does. No filing row is opened: a draft for an entity that
        # cannot be filed is one nobody can ever advance.
        raise HTTPException(400, {"message": "entity cannot be filed as a NAR1",
                                  "problems": exc.problems})
    except Exception as exc:
        raise _handle(exc)

    try:
        row = filings.create_filing(
            entity_id=body.entity_id,
            form_code="Nar1",
            form_xml=form_xml,
            user_id=user["id"],
            nar1_case_id=body.nar1_case_id,
            form_filing_id=body.form_filing_id,
        )
    except Exception as exc:
        raise _handle(exc)

    await log_event(
        user_id=user["id"], user_display_name=user["display_name"],
        action_type=ev.TPSI_FILING_CREATED, event_code=ev.TPSI_FILING_CREATED,
        entity_type="tpsi_filing", entity_id=row["id"],
        case_id=body.nar1_case_id,
        # Identifiers only. The XML is the whole statutory return and is
        # already stored on the filing row; the signatory dict is not repeated
        # here either, since map_entity's output is what was actually filed.
        metadata={"form_code": "Nar1", "entity_id": body.entity_id, "year": year},
    )
    return row


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


@router.get(
    "/filings/{filing_id}/pdf",
    # Without these the generated schema advertises application/json for the
    # one binary route in this router, and every consumer that reads it --
    # client codegen, the docs page -- is told the wrong thing.
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}},
                     "description": "The rendered NAR1 preview."}},
)
async def filing_pdf(
    filing_id: str, user=Depends(require_permission("tpsi", "read"))
):
    """Form NAR1 + Schedule 1/2, from the CR-validated snapshot (BE-2).

    `read`, not `write`: nothing is sent to CR, nothing is charged, and nothing
    is stored. It is still permission-gated, because a statutory return is data
    about real people -- residential addresses and partial identity numbers.

    Rendered on demand rather than saved to Storage: `validated_xml` is the
    single source, so a re-render can never drift from it, and there is no
    stale artefact to garbage-collect when a filing is re-validated after a
    field fix.

    409 before validation, not 404: the filing exists, it simply has no
    CR-validated payload yet, and the caller's fix is to validate -- not to look
    somewhere else. Also 409 for any form code other than NAR1: there is one
    renderer and it is a NAR1 renderer.
    """
    try:
        row = filings.get_filing(filing_id)
    except Exception as exc:
        raise _handle(exc)

    # Checked BEFORE the validated_xml gate: the form code never changes, so
    # "validate it first" would send the caller round a loop that still ends
    # here. POST /filings accepts every code in FORM_FEES, and the renderer
    # fills CR's NAR1 form only -- fed an Nd2a it would not fail, it would emit
    # a document headed "Form NAR1 / Annual Return" carrying the few tags whose
    # names coincide and dropping every ND2A particular. A missing code is
    # refused too: assuming NAR1 is the same mistake, made silently.
    form_code = (row.get("form_code") or "").strip()
    if form_code.lower() != "nar1":
        raise HTTPException(
            409,
            f"this filing is a {form_code or '(no form code recorded)'} form; "
            "only NAR1 has a renderer, so there is no preview to show",
        )

    if not row.get("validated_xml"):
        raise HTTPException(
            409,
            "this filing has not been validated by CR yet, so there is no "
            "validated XML to render",
        )

    try:
        # validated_xml, never request_xml and never the live profile: the admin
        # double-confirms an irreversible, chargeable submit off this document,
        # so it has to be the one CR is actually holding.
        # CR's OWN FORM, not a summary of it (Levi 2026-08-30). This is what
        # the Client Verification screen shows and what the Submission stage's
        # "Download NAR1" hands over, so it has to be the document the client
        # and CR would both recognise.
        # The company type is not in the validated XML — `coyStatus` comes back
        # ABSENT from a real validateForm — so it is read off the profile. A
        # missing entity is not a reason to fail the preview: the resolver
        # defaults to "private", which is what 5,987 of DEV's 5,998 companies
        # are.
        try:
            entity = nar1_cases.entity_for(row.get("entity_id")) or {}
        except Exception:  # noqa: BLE001
            entity = {}
        pdf = nar1_form_fill.render(
            row["validated_xml"],
            company_type=nar1_form_fill.company_type_from_profile(
                entity.get("company_type")
            ),
        )
    except (ValueError, nar1_form_fill.FormFillError) as exc:
        # A stored payload CR accepted but we cannot parse is a data problem,
        # not an unhandled 500 that reads like a crash in the renderer.
        raise HTTPException(422, str(exc))

    await log_event(
        user_id=user["id"], user_display_name=user["display_name"],
        action_type=ev.DOCUMENT_GENERATED, event_code=ev.DOCUMENT_GENERATED,
        entity_type="tpsi_filing", entity_id=filing_id,
        case_id=row.get("nar1_case_id"),
        # Identifiers and provenance only. The document's whole content is the
        # statutory return, and it is already stored on the filing row.
        metadata={"document": "NAR1+Schedule", "source": "validated_xml",
                  "bytes": len(pdf)},
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="NAR1-{filing_id}.pdf"',
            # This is a preview of a document that changes whenever the filing
            # is re-validated. A cached copy is a copy of something CR may no
            # longer be holding.
            "Cache-Control": "no-store",
        },
    )


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
    except filings.ManualCompletionInterlock as exc:
        # 409, not 400: nothing about the request is malformed — the case was
        # filed off-portal and this filing must not go any further towards the
        # chargeable call. Refused before CR ever sees the signature.
        raise HTTPException(409, str(exc))
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
    except filings.ManualCompletionInterlock as exc:
        raise HTTPException(409, str(exc))
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


@router.get("/filings/{filing_id}/summary")
async def filing_summary(
    filing_id: str, user=Depends(require_permission("tpsi", "read"))
):
    """What is actually about to be filed — read back out of the frozen XML.

    Deliberately NOT `/cases/{id}/return-data`. That reads the company profile
    and answers "what would we build today?", which is right for Data
    Verification. Submission is irreversible, and the thing submitted is the
    snapshot: if the profile moved after validation, this still shows what CR
    will receive, and the difference is the operator's cue to restart
    verification rather than a surprise on the receipt.

    No CR call, nothing charged. The presenter account is NOT included — it
    stays a super-admin-only field (see `_deposit_account`).
    """
    try:
        row = filings.get_filing(filing_id)
    except Exception as exc:
        raise _handle(exc)

    # `validated_xml` is CR's OWN signed document and is what the submit sends;
    # `request_xml` is only what we proposed. Prefer the signed copy so the
    # summary shows what CR holds, and fall back only before validation.
    form_xml = row.get("validated_xml") or row.get("request_xml")
    if not form_xml:
        raise HTTPException(409, "this filing has no form to summarise yet")

    try:
        summary = nar1_summary.summarise(form_xml)
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    return {
        **summary,
        "form_code": row["form_code"],
        "stage": row.get("stage"),
        "validated_at": row.get("validated_at"),
        "signed_at": row.get("signed_at"),
        # Which copy the rows above were read from. An operator confirming an
        # irreversible charge should be able to tell "CR's signed document"
        # from "what we were about to send".
        "source": "validated_xml" if row.get("validated_xml") else "request_xml",
    }


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
