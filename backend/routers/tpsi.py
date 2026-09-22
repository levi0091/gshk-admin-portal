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
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from middleware.auth import require_permission, require_super_admin
from db.supabase import get_supabase
from services import audit_events as ev
from services import nar1_cases, nar1_cr_status, nar1_prepare, nar1_return_year
from services.nar1_form import fill as nar1_form_fill
from services.nar1_form.appearance import AppearanceError
from services.audit_service import log_event
from services import audit_subject
from services.tpsi import credentials, filings, reads, shared_credentials
# ALIASED, because this router already has a route handler called `doc_status`
# (GET /tpsi/doc-status) and the bare name would be shadowed by it at
# definition time — silently, and only at the one call site below.
from services.tpsi import doc_status as cr_doc_status
from services.tpsi.forms import nar1, nar1_mapper, nar1_source, nar1_summary
from services.tpsi.forms.cr_vocabularies import default_capacity
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
    #: The name CR holds for that e-Service account, filed as
    #: associatedPersonName when a return is signed for a body corporate. CR
    #: checks it against the account and refuses a mismatch as an
    #: authorisation failure, so it is entered, never derived from
    #: users.display_name.
    eservice_person_name: str | None = None
    eservice_password: str | None = None
    deposit_account_no: str | None = None


class CredentialUpdateIn(BaseModel):
    """PUT — rotation. EVERY field is optional, because changing one must not
    require re-supplying the others. Omitted fields keep their stored value
    (see _opt); an explicit null clears."""
    presentor_account_id: str | None = None
    tpsi_password: str | None = None
    eservice_user_id: str | None = None
    eservice_person_name: str | None = None
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


def _filing_subject(
    row: Optional[dict] = None,
    *,
    filing_id: Optional[str] = None,
    entity_id: Optional[str] = None,
    nar1_case_id: Optional[str] = None,
) -> dict:
    """Which case and which company a CR filing event is about.

    Every `tpsi_filing` audit row used to carry a filing uuid and nothing else,
    so the whole CR half of the trail rendered with an empty subject — you could
    see that a return was validated, signed and submitted without being able to
    tell for whom. `tpsi_filings` already knows: it holds the entity and, for a
    NAR1, the case.

    ALSO FIXES WHAT WENT INTO `case_id`. Two routes wrote `nar1_case_id` there,
    but that column holds an ENTITY id by repo convention (routers/cases.py
    ::_audit_target) — a case id in it is invisible to every company-scoped
    query, which is exactly the trail these rows belong in. The case id now goes
    where it belongs, in `subject_id`.

    TWO STAGES, and the split is the point. The IDS come from what the caller
    already has and cost nothing; the NAMES need a lookup and are best-effort.
    So a Supabase failure downgrades the row to ids without a company name,
    rather than dropping the subject altogether.

    TOTALLY DEFENSIVE, and that is not belt-and-braces. This is spread into a
    `log_event(**...)` call, so it is evaluated by the CALLER — outside the
    try/except that makes an audit write unable to fail its operation. A raise
    here would turn a successful, chargeable CR submission into a 500.
    """
    try:
        if row is None and filing_id:
            row = filings.get_filing(filing_id)
    except Exception:  # noqa: BLE001
        row = None
    row = row or {}

    entity_id = entity_id or row.get("entity_id")
    case_id = nar1_case_id or row.get("nar1_case_id")
    if not entity_id and not case_id:
        return {}

    company: dict = {"id": entity_id} if entity_id else {}
    case: dict = {"id": case_id} if case_id else {}
    try:
        sb = get_supabase()
        if entity_id:
            company = (sb.table("entities").select("id, company_name, br_number")
                       .eq("id", entity_id).single().execute()).data or company
        if case_id:
            case = (sb.table("nar1_cases").select("id, case_no")
                    .eq("id", case_id).single().execute()).data or case
    except Exception as exc:  # noqa: BLE001
        print(f"[routers.tpsi] WARN: could not name the audit subject for filing "
              f"{filing_id or row.get('id')}: {exc}", file=sys.stderr)

    out = {"case_id": entity_id, "company_name": company.get("company_name")}
    if case_id:
        return {**out, **audit_subject.for_case(case, module=audit_subject.CR_FILING)}
    return {**out, **audit_subject.for_company(
        company, module=audit_subject.CR_FILING)}


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
    # Before the ValueError branch it subclasses: the builder's refusals are a
    # list, and the fault panel renders `problems` one per line.
    if isinstance(exc, nar1.FormValidationError):
        return HTTPException(400, {
            "message": ("The return cannot be built from the company record: "
                        "the Companies Registry would refuse these values."),
            "problems": exc.problems()})
    if isinstance(exc, (LookupError, ValueError)):
        return HTTPException(400, str(exc))
    if isinstance(exc, TpsiPasswordExpiredError):
        return HTTPException(409, str(exc))

    if isinstance(exc, (TpsiValidationError, TpsiSignatureError)):
        signature = isinstance(exc, TpsiSignatureError)
        # 422, NOT 502 (fixed 2026-08-31). A CR fault is a SUCCESSFUL exchange:
        # CR was reached, understood the request, and said no. Calling that a
        # Bad Gateway was a category error with a real cost — a 5xx lets
        # Cloudflare and Railway replace the response body with their own HTML
        # error page, and `api.js` falls back to `resp.statusText` when the body
        # will not parse as JSON. So the operator saw "502 Bad Gateway" while
        # CR had actually said "Br No does not exist.", and the fault list this
        # dict exists to carry never reached the screen at all.
        #
        # 502 still means what it says below: CR could not be reached.
        return HTTPException(422, {
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
        # `kind` rather than a bare string: the screen must not offer "wait for
        # the Mon-Fri window" to a PROD operator whose call simply timed out.
        # See TpsiUnavailableError for why APP_ENV cannot answer this.
        return HTTPException(503, {
            "message": str(exc),
            "kind": getattr(exc, "kind", "unreachable"),
        })
    # A CR FAULT WITH NO FAULT BEANS — still CR answering, so still a 422.
    #
    # `raise_for_fault` produces a bare `TpsiError` when the SOAP Fault carries
    # no `webServiceFaultBeans` — which is what a refusal from CR's SOAP STACK
    # looks like, as opposed to one from its business rules. That put the most
    # useful error text in the app on the one status code whose body does not
    # survive the edge: on 2026-09-16 every *Check with CR now* returned
    #
    #     Message part {…}docStatusEnquiry was not recognized.
    #     (Does it exist in service WSDL?)
    #
    # — the exact sentence naming the bug — and the operator read "Could not
    # reach the server", because Cloudflare replaced the 502 body with its own
    # page, which carries no `Access-Control-Allow-Origin`, so `fetch` rejected
    # before `api.js` could read anything at all. The same reasoning that moved
    # validation and signature faults off 502 on 2026-08-31 applies here and was
    # simply not carried to the unlabelled case.
    #
    # 502 IS KEPT FOR `TpsiAuthError` ABOVE, deliberately: there the meaning is
    # carried by the frontend's static hint ("could not be reached, or refused
    # our login — stop, a repeated login failure is what locks a CR account"),
    # which needs no body to survive.
    if isinstance(exc, TpsiError):
        return HTTPException(422, {
            "message": str(exc) or "The Companies Registry refused this request.",
            "problems": [],
            "kind": "fault",
        })
    # A `RuntimeError` IS STILL A 502, and deliberately not a 500: it is what
    # this router's own collaborators raise when a write fails (a Postgrest FK
    # violation out of `filings.create_filing`, the advisory lock refusing in
    # `tokens._connect_for_lock`), and those are HANDLED failures —
    # `test_create_filing_other_failures_are_handled_not_a_500` is the rule.
    # Its message may not survive the edge, which is a real and separate
    # problem; turning every one of them into "the server broke" is not the fix.
    if isinstance(exc, RuntimeError):
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
        eservice_person_name=_opt(body, "eservice_person_name"),
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
        eservice_person_name=_opt(body, "eservice_person_name"),
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


@router.post("/cases/{case_id}/refresh-status")
async def refresh_cr_status(
    case_id: str, user=Depends(require_permission("tpsi", "read")),
):
    """Ask CR what it has done with this case's return, and record the answer.

    THE BUTTON THAT WAS REMOVED, PUT BACK BECAUSE ITS THREE OBJECTIONS ARE NOW
    FALSE. `StageConfirmation` carried a "Check CR status" control until
    2026-09-02, removed because (a) nothing persisted — the result lived in
    `useState`; (b) nothing ever reached `registered`, since no code path wrote
    it; and (c) the case already read Completed, so there was no state left to
    advance. Migration 043 gives the answer a home, `filings.mark_registered`
    writes the stage, and `completed` is gone — the case now sits on CR's own
    answer, which starts at "not checked".

    The fourth objection stands and is answered differently: this spends a CR
    AUTHENTICATION, and repeated CR auth failures lock the account. So the
    NORMAL path is `jobs/poll_cr_status`, which logs in once for the whole book;
    this is the exception, for an operator who needs the answer now.

    `tpsi:read`, exactly as `GET /tpsi/doc-status` and `GET /tpsi/balance` are:
    the level reflects the effect on CR and on money, and this has neither.
    Precedent for a case-subject route gated on a TPSI module is
    `POST /cases/{id}/manual-submit`, which takes `tpsi:submit`.

    POST, not GET, because it writes: a GET that changes a statutory record is
    a GET a mail-security gateway or a browser prefetch would fire for you.
    """
    try:
        case = nar1_cases.get_case(case_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc))

    filing = nar1_cases.current_filing(case_id)

    # Refused BEFORE a CR session is opened, and named. "Nothing happened" on a
    # case that was never filed is indistinguishable from a broken button.
    blocked = nar1_cr_status.due_for_check(case, filing)
    if blocked:
        raise HTTPException(409, {
            "message": f"this case cannot be checked with CR — {blocked}",
            "reason": "not_checkable",
        })

    try:
        client = client_for(user)
        result = nar1_cr_status.refresh(client, case, filing)
    except Exception as exc:
        raise _handle(exc)

    await audit_auth(user, client)
    await nar1_cr_status.record(
        result, case,
        user_id=user["id"], user_display_name=user["display_name"],
    )

    return {
        "cr_status": cr_doc_status.describe(result.get("cr_text"),
                                            result.get("code")),
        "checked": result.get("checked", False),
        # Present when CR answered but the reply could not be attributed to THIS
        # return — several documents under one case number. Not an error and not
        # a status: nothing was written, and the screen says why rather than
        # showing a badge nobody can act on.
        "skipped": result.get("skipped"),
        "changed": result.get("changed", False),
        "previous": result.get("previous"),
        "document_ref_no": result.get("document_ref_no"),
        "checked_at": result.get("checked_at"),
    }


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


def _entity_or_empty(entity_id: str) -> dict:
    """The company row (for its incorporation date and name), or {}.

    Never a reason to fail a prepare: without it the year falls back to the
    Hong Kong year, which is what every prepare did before the year existed.
    """
    try:
        return nar1_cases.entity_for(entity_id) or {}
    except Exception:  # noqa: BLE001
        return {}


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

    # The one door `filings._refuse_if_case_finished` cannot cover: it guards a
    # filing that already exists, and this route makes a new one. Closing a case
    # supersedes every live filing, so without this a closed case could be given
    # a fresh draft and walked back up the whole chain.
    if case.get("closed_at"):
        raise HTTPException(409, {
            "message": (
                f"case {case.get('case_no') or case.get('id')} was closed and "
                "is not proceeding, so no filing may be opened against it. "
                "Closing cannot be undone; open a new case if the return is "
                "going ahead after all."
            ),
            "reason": "case_closed",
        })

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

    # ONE OWNER FOR THE BUILD (services/nar1_prepare, 2026-09-17). Everything
    # that used to be inline here -- the Hong Kong year, the stored signing
    # capacity and its fallback, the signing identity, the mapper call -- moved
    # there when Client Verification became the first stage and
    # `cases.send_verification` acquired the need to build a return before CR
    # has seen it. A second copy would be free to drift, and the way anyone
    # would find out is a client approving a document built by different rules
    # from the one that gets filed.
    #
    # The HTTP mapping stays here, because it is the only part the two callers
    # do differently.
    # Resolved here as well as inside the builder, because the audit row below
    # records which year was filed and "whatever it defaulted to" is not an
    # answer a trail can give years later. Hong Kong's year, not UTC's: for the
    # first eight hours of every HK working day UTC is still on yesterday's
    # date, and on 1 January that is the wrong year on the statutory form.
    #
    # THE CASE'S YEAR WINS (Levi 2026-09-18). A case is one annual return and
    # names its year (`nar1_cases.ar_period_year`, chosen at Client
    # Verification), so the filing is built for that year — the one the client
    # was asked to approve. An explicit `year` that disagrees is REFUSED rather
    # than obeyed: honouring it would file a different year from the approved
    # one, and ignoring it silently would tell the caller it had been used.
    # Read once, here, and reused for the draft rebuild below.
    try:
        live = nar1_cases.current_filing(body.nar1_case_id)
    except Exception:  # noqa: BLE001 — a missing live filing is not an error
        live = None
    year, year_source = nar1_return_year.resolve(case, live)
    if not year:
        # MANDATORY and never defaulted (Levi 2026-09-19). An explicit `year`
        # does not stand in for the case's: the year is chosen, and audited, on
        # Client Verification — where the client is asked to approve it — not
        # asserted by whoever calls this.
        raise HTTPException(409, {
            "message": (f"case {case.get('case_no') or case.get('id')} has no "
                        f"return year: {nar1_return_year.NO_YEAR}."),
            "reason": "return_year_required"})
    if body.year and int(body.year) != year:
        raise HTTPException(409, {
            "message": (f"case {case.get('case_no') or case.get('id')} files "
                        f"the {year} annual return, not {body.year}. Change "
                        f"the year on the case (Client Verification) instead."),
            "reason": "return_year"})
    try:
        claimed = nar1_return_year.claim(case, year)
    except nar1_return_year.YearRefused as exc:
        raise HTTPException(exc.status, {"message": str(exc),
                                         "reason": "return_year",
                                         "held_by": exc.held_by})
    if claimed:
        entity_row = _entity_or_empty(body.entity_id)
        await log_event(
            user_id=user["id"], user_display_name=user["display_name"],
            action_type=ev.CASE_FIELD_UPDATED, event_code=ev.CASE_FIELD_UPDATED,
            # The cases router's convention (`routers/cases._audit_target`):
            # the case in entity_id/subject, its COMPANY in case_id.
            entity_type="nar1_case", entity_id=case["id"],
            case_id=case.get("entity_id"),
            company_name=entity_row.get("company_name"),
            **audit_subject.for_case(case),
            old_value=None, new_value=str(year),
            metadata={"field": "ar_period_year", "fixed_by": "filing_prepare",
                      "resolved_from": year_source},
        )

    try:
        form_xml = await nar1_prepare.build_form_xml(
            entity_id=body.entity_id,
            nar1_case_id=body.nar1_case_id,
            user_id=user["id"],
            year=year,
            signatory=body.signatory,
        )
    except LookupError as exc:
        # "no entity <id>" -- the caller's identifier is wrong, not the loader.
        raise HTTPException(400, str(exc))
    except nar1_prepare.LoaderFailed as exc:
        raise _loader_failed(exc.entity_id, exc.cause)
    except nar1_mapper.MappingError as exc:
        # The whole list, in a structured field the UI can render as CR's own
        # fault list does. No filing row is opened: a draft for an entity that
        # cannot be filed is one nobody can ever advance.
        raise HTTPException(400, {"message": "entity cannot be filed as a NAR1",
                                  "problems": exc.problems})
    except Exception as exc:
        raise _handle(exc)

    # REBUILD THE CASE'S OWN DRAFT rather than opening a second filing.
    #
    # `filings.validate()` re-sends the stored request_xml verbatim, so a draft
    # built before the operator fixed an address -- or chose a different signing
    # capacity -- would go to CR unchanged however many times they pressed
    # Validate. On case NAR-2026-0065 the case read
    # `signatory_capacity='Company Secretary'` while its stored XML still said
    # selectCapacityDesc 'Director', and CR's identical refusal read as "my
    # correction did nothing".
    #
    # Only draft and validation_failed move (REBUILDABLE_STAGES, enforced inside
    # the UPDATE). A validated filing is left alone: its snapshot is what the
    # client approves and what gets filed, and discarding one is `Restart
    # verification`'s job. A rebuild that loses the race returns False and falls
    # through to a new row rather than reporting a refresh that did not happen.
    row = None
    if body.nar1_case_id:
        if live and live.get("stage") in filings.REBUILDABLE_STAGES:
            try:
                row = filings.rebuild_draft(live["id"], form_xml)
            except Exception as exc:
                raise _handle(exc)

    if row is None:
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
        **_filing_subject(row, entity_id=body.entity_id,
                          nar1_case_id=body.nar1_case_id),
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
        **_filing_subject(row, entity_id=body.entity_id,
                          nar1_case_id=body.nar1_case_id),
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
    """Form NAR1 + Schedule 1/2, from the filing's own return (BE-2).

    `read`, not `write`: nothing is sent to CR, nothing is charged, and nothing
    is stored. It is still permission-gated, because a statutory return is data
    about real people -- residential addresses and partial identity numbers.

    Rendered on demand rather than saved to Storage: the filing row is the
    single source, so a re-render can never drift from it, and there is no
    stale artefact to garbage-collect when a filing is re-validated after a
    field fix.

    CR's validated copy when there is one, the prepared `request_xml` otherwise
    -- see the comment at the payload below for why the second was added and why
    it cannot weaken the guarantee the Submission stage rests on. 409, not 404,
    when there is neither: the filing exists, it simply carries nothing to draw.
    Also 409 for any form code other than NAR1: there is one renderer and it is
    a NAR1 renderer.

    A CASE at Client Verification usually has no filing at all, so that screen
    does not use this endpoint -- see `cases.preview_verification`.
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

    # WHAT THE CLIENT AND THE ADMIN ARE LOOKING AT.
    #
    # `validated_xml` FIRST, and that is the guarantee the Submission stage
    # rests on: the admin double-confirms an irreversible, chargeable submit off
    # this document, and by then the filing is validated, so the fallback below
    # can never apply at that point.
    #
    # `request_xml` SECOND (2026-09-17). This used to be a flat 409 — "this
    # filing has not been validated by CR yet" — which was right while Client
    # Verification was the SECOND stage. It is the first stage now, so the
    # screen showing this preview is reached BEFORE CR has seen the return, and
    # the refusal fired on every case at stage 1. `request_xml` is what
    # `filings.validate()` sends to CR verbatim, so it is the document that will
    # be filed.
    payload = row.get("validated_xml") or row.get("request_xml")
    if not payload:
        raise HTTPException(
            409,
            "this filing carries no return to draw — neither a CR-validated "
            "snapshot nor a prepared one. Open the case again to rebuild it.",
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
        # The case, for the OFF-PORTAL filing date only — a return signed on
        # paper and lodged by hand never writes `tpsi_filings.submitted_at`, so
        # reading the filing row alone re-dated every manual return to whatever
        # day it was downloaded. Skipped once the filing answers for itself, and
        # tolerant of a missing case for the same reason as the entity above: a
        # preview must not fail over the row that only supplies its date.
        case = {}
        if not row.get("submitted_at") and row.get("nar1_case_id"):
            try:
                case = nar1_cases.get_case(row["nar1_case_id"]) or {}
            except Exception:  # noqa: BLE001
                case = {}
        pdf = nar1_form_fill.render(
            payload,
            company_type=nar1_form_fill.company_type_from_profile(
                entity.get("company_type")
            ),
            # The day CR received this return, and EMPTY until it did. A
            # preview taken before filing is a preview of an unfiled return.
            submitted_on=nar1_cases.filed_on(row, case),
            # Section 4's date on a draft CR has not validated; CR's own value
            # wins once it has. See `fill.made_up_date`.
            incorporated_on=entity.get("incorporation_date"),
        )
    except (ValueError, nar1_form_fill.FormFillError, AppearanceError) as exc:
        # A stored payload CR accepted but we cannot parse is a data problem,
        # not an unhandled 500 that reads like a crash in the renderer.
        raise HTTPException(422, str(exc))

    await log_event(
        user_id=user["id"], user_display_name=user["display_name"],
        action_type=ev.DOCUMENT_GENERATED, event_code=ev.DOCUMENT_GENERATED,
        entity_type="tpsi_filing", entity_id=filing_id,
        **_filing_subject(row),
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
    """`read`: no CR-side effect and no charge (spec §6).

    REFUSED BEFORE THE RETURN DATE (Levi 2026-09-18). CR will not validate an
    annual return whose made-up date — the incorporation anniversary in the
    return's year — has not arrived. It says so twice, in its own words
    (`ERR_MSG_NO_FUTURE_DATE` "Date to which this Return is Made Up cannot be a
    future date", and `NAR1_ERR000023PRIVATECOYINVALIDRTNDATE` "Please submit
    the annual return within 42 days after anniversary"), and the second of
    those reads as if a late return were refused, which it is not. So the
    portal answers first, with the two dates and the two ways out. Fails OPEN
    when either date is unknown, exactly as the submit gate does: CR, which
    has its own register, stays the check for what we cannot compute.
    """
    try:
        early = filings.before_return_date(filings.get_filing(filing_id))
    except Exception:  # noqa: BLE001 — fail open; `validate` below reads the
        early = None   # same row and reports a real failure in its own terms.
    if early:
        return_date, today = early
        days = (return_date - today).days
        raise HTTPException(409, {
            "message": (
                f"CR will not validate this return yet. It is made up to "
                f"{return_date.strftime('%d/%m/%Y')} — the company's "
                f"incorporation anniversary in the return's year — which is "
                f"{days} day{'' if days == 1 else 's'} away, and an annual return "
                f"cannot be made up to a future date. Validate on or after "
                f"{return_date.strftime('%d/%m/%Y')}, or, if this case should be "
                f"filing an earlier year, restart verification and choose that "
                f"year on Client Verification. Nothing was sent to CR."),
            "reason": "before_return_date",
            "return_date": return_date.isoformat(),
        })

    try:
        row = filings.validate(client_for(user), filing_id)
    except Exception as exc:
        raise _handle(exc)

    await log_event(
        user_id=user["id"], user_display_name=user["display_name"],
        action_type=ev.TPSI_VALIDATE, event_code=ev.TPSI_VALIDATE,
        entity_type="tpsi_filing", entity_id=filing_id,
        **_filing_subject(filing_id=filing_id),
        metadata={"stage": row["stage"]},
    )
    return {"filing_id": filing_id, "stage": row["stage"], "form_status": form_status(row)}


class SignIn(BaseModel):
    """Deliberately empty. A NAR1 is signed with the logged-in user's OWN
    e-Service credential and nothing else (Levi, Q1 2026-08-30).

    It used to accept `signatory_user_id` + `eservice_password` so a client
    director could supply their credentials live (spec D4). That is gone: it
    made the signing account a free-text field on a statutory declaration, and
    for the body-corporate secretary that every real GSHK client has, the
    e-Service credential is the ONLY record of who actually signed — the return
    itself names the corporate secretary and carries no person id.

    The two withdrawn fields are still DECLARED, and refused in the handler
    with a 400. `extra="forbid"` alone was the obvious way to do this and leaks:
    FastAPI's 422 body echoes the rejected input, so a stale client posting
    `eservice_password` would get the signing password back in the response —
    and into any log that records response bodies. Declaring them keeps the
    value inside the model, where nothing renders it.

    `extra="forbid"` still applies to everything else, so a typo'd field name
    stops rather than being ignored.
    """
    model_config = ConfigDict(extra="forbid")

    signatory_user_id: str | None = None
    eservice_password: str | None = None


@router.post("/filings/{filing_id}/sign")
async def sign_filing(
    filing_id: str, body: SignIn, user=Depends(require_permission("tpsi", "write"))
):
    # Refused, never ignored. Ignoring would be the dangerous outcome: a stale
    # client posting a director's credentials would get a 200 and a signature
    # applied under the LOGGED-IN user's account instead — a different person's
    # statutory declaration, reported as success. The message names the fields
    # and never echoes their values.
    if body.signatory_user_id is not None or body.eservice_password is not None:
        raise HTTPException(
            400,
            "a NAR1 is signed with your own e-Service account and no other; "
            "signatory_user_id and eservice_password are no longer accepted. "
            "Send an empty body. If you meant to sign as someone else, they "
            "must sign in themselves.",
        )

    # credentials.load_eservice lives INSIDE the try now, not before it: a
    # None it returns must map to a clean 400 via _handle like every other
    # TPSI endpoint (see /balance), not surface as an unhandled 500.
    try:
        pair = credentials.load_eservice(user["id"])
        if pair is None:
            raise HTTPException(
                400,
                "you have no e-Service signing password stored, so you cannot "
                "sign this return. Add one under CR Credentials. A NAR1 is "
                "signed with your own e-Service account and no other.",
            )
        signatory, password = pair

        result = filings.sign(client_for(user), filing_id, signatory, password)
    except filings.SignatoryMismatch as exc:
        # 409, like the off-portal interlock below: the request is well formed,
        # the filing is simply not one this user may sign.
        raise HTTPException(409, str(exc))
    except filings.CaseClosedInterlock as exc:
        # Its own branch above the off-portal one: both are 409, and both would
        # be caught by a bare `SubmitGateError`, but the two say different
        # things and the operator's next move differs. Never a 400 — nothing
        # about the request is malformed; the case simply ended.
        raise HTTPException(409, {"message": str(exc), "reason": "case_closed"})
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
        **_filing_subject(filing_id=filing_id),
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
    except filings.CaseClosedInterlock as exc:
        # Its own branch above the off-portal one: both are 409, and both would
        # be caught by a bare `SubmitGateError`, but the two say different
        # things and the operator's next move differs. Never a 400 — nothing
        # about the request is malformed; the case simply ended.
        raise HTTPException(409, {"message": str(exc), "reason": "case_closed"})
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
        **_filing_subject(filing_id=filing_id),
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
        **_filing_subject(filing_id=filing_id),
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
        **_filing_subject(filing_id=filing_id),
        metadata={"deposit_account": account, "confirm": body.confirm},
    )
    try:
        result = filings.submit(
            client_for(user, shared), filing_id, body.confirm, account
        )
    except filings.DriftDetected as exc:
        # Spec §6. Its own branch above the general gate: the operator needs the
        # FIELDS, and `str(exc)` is only the headline. Audited with the field
        # names but not the values — an audit row is not the place to repeat a
        # director's residential address, and the values are one click away on
        # the two records being compared.
        await log_event(
            user_id=user["id"], user_display_name=user["display_name"],
            action_type=ev.TPSI_SUBMISSION_FAILED,
            event_code=ev.TPSI_SUBMISSION_FAILED,
            entity_type="tpsi_filing", entity_id=filing_id,
            **_filing_subject(filing_id=filing_id),
            metadata={"reason": str(exc), "gate": True, "drift": True,
                      "fields": [d["field"] for d in exc.differences]},
        )
        raise HTTPException(409, {"message": str(exc), "reason": "drift",
                                  "differences": exc.differences})
    except filings.RecordCheckFailed as exc:
        # Its own branch, above the general gate, for the same reason
        # DriftDetected has one: it carries a LIST. Flattened into
        # `str(exc)` by the general branch below, the mapper's faults arrived
        # as one run-on sentence and were drawn as one — which is the thing
        # being fixed (Levi 2026-09-03). The fault TEXT is audited; it names
        # parties and countries but no personal particulars.
        await log_event(
            user_id=user["id"], user_display_name=user["display_name"],
            action_type=ev.TPSI_SUBMISSION_FAILED,
            event_code=ev.TPSI_SUBMISSION_FAILED,
            entity_type="tpsi_filing", entity_id=filing_id,
            **_filing_subject(filing_id=filing_id),
            metadata={"reason": str(exc), "gate": True,
                      "check": exc.reason, "problems": exc.problems},
        )
        raise HTTPException(409, {"message": str(exc), "reason": exc.reason,
                                  "problems": exc.problems})
    except filings.SubmitGateError as exc:
        await log_event(
            user_id=user["id"], user_display_name=user["display_name"],
            action_type=ev.TPSI_SUBMISSION_FAILED,
            event_code=ev.TPSI_SUBMISSION_FAILED,
            entity_type="tpsi_filing", entity_id=filing_id,
            **_filing_subject(filing_id=filing_id),
            metadata={"reason": str(exc), "gate": True},
        )
        raise HTTPException(409, str(exc))
    except Exception as exc:
        await log_event(
            user_id=user["id"], user_display_name=user["display_name"],
            action_type=ev.TPSI_SUBMISSION_FAILED,
            event_code=ev.TPSI_SUBMISSION_FAILED,
            entity_type="tpsi_filing", entity_id=filing_id,
            **_filing_subject(filing_id=filing_id),
            metadata={"reason": str(exc)},
        )
        raise _handle(exc)

    await log_event(
        user_id=user["id"], user_display_name=user["display_name"],
        action_type=ev.TPSI_SUBMISSION_SUCCESS,
        event_code=ev.TPSI_SUBMISSION_SUCCESS,
        entity_type="tpsi_filing", entity_id=filing_id,
        **_filing_subject(filing_id=filing_id),
        metadata={
            "caseNo": result["receipt"].get("caseNo"),
            "totalAmount": result["receipt"].get("totalAmount"),
        },
    )
    return result
