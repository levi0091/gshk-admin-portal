"""The filing ledger: per-attempt chain state for a TPSI submission.

Why this exists at all: CR's order is validate -> sign -> submit, and each step
consumes the previous step's CR-signed payload. Holding that chain server-side
is what makes the submit gate real — a client cannot assert "already validated"
and skip straight to the chargeable call.
"""
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from db.supabase import get_supabase
from services.tpsi.config import FORM_FEES
from services.tpsi.errors import TpsiError
from services.tpsi.soap import extract_submission, parse_response, text_of

_TABLE = "tpsi_filings"

# The FORM status vocabulary (migration 018). Distinct from the WORKFLOW status,
# which lives on nar1_cases and answers a different question: this says where the
# document is in CR's process, not where the case is in GSHK's.
#
# Failure is split per step on purpose. "validation_failed" means fix the data
# and retry for free; "submission_failed" means CR rejected a chargeable call.
# Collapsing both into one `failed`, as the original vocabulary did, loses the
# only distinction that changes what the user should do next.
STAGE_DRAFT = "draft"
STAGE_VALIDATED = "validated"
STAGE_VALIDATION_FAILED = "validation_failed"
STAGE_SIGNED = "signed"
STAGE_SIGNING_FAILED = "signing_failed"
STAGE_SUBMITTED = "submitted"
STAGE_SUBMISSION_FAILED = "submission_failed"
STAGE_REGISTERED = "registered"
STAGE_SUPERSEDED = "superseded"
STAGE_EDRIVE = "edrive"

#: The nine the UI reports, in lifecycle order. `edrive` is a valid stored value
#: (upload_edrive() still works) but is not offered in the UI, so it is not here.
FORM_STATUSES = (
    STAGE_DRAFT,
    STAGE_VALIDATED,
    STAGE_VALIDATION_FAILED,
    STAGE_SIGNED,
    STAGE_SIGNING_FAILED,
    STAGE_SUBMITTED,
    STAGE_SUBMISSION_FAILED,
    STAGE_REGISTERED,
    STAGE_SUPERSEDED,
)

#: Human labels for the form status. The UI shows these beside — never merged
#: with — the workflow status.
FORM_STATUS_LABELS = {
    STAGE_DRAFT: "Not yet sent to CR",
    STAGE_VALIDATED: "Validated by CR",
    STAGE_VALIDATION_FAILED: "Rejected at validation",
    STAGE_SIGNED: "Signed",
    STAGE_SIGNING_FAILED: "Rejected at signing",
    STAGE_SUBMITTED: "Filed with CR",
    STAGE_SUBMISSION_FAILED: "Rejected at submission",
    STAGE_REGISTERED: "Registered by CR",
    STAGE_SUPERSEDED: "Superseded by a later attempt",
    STAGE_EDRIVE: "Sent to CR e-Drive",
}

#: Stages a filing can never move on from.
TERMINAL_STAGES = (STAGE_SUBMITTED, STAGE_REGISTERED, STAGE_EDRIVE, STAGE_SUPERSEDED)

#: A failure at any step. Kept as a tuple so callers test membership rather than
#: string-matching a suffix.
FAILURE_STAGES = (
    STAGE_VALIDATION_FAILED, STAGE_SIGNING_FAILED, STAGE_SUBMISSION_FAILED,
)


def form_status(row: dict) -> dict:
    """The FORM status — where the document is in CR's process.

    Deliberately NOT merged with the case's workflow status, which answers a
    different question (where the case is in GSHK's process) and lives on
    nar1_cases. The UI reports the two side by side; collapsing them into one
    badge loses information in both directions.
    """
    stage = row["stage"]
    return {
        "code": stage,
        "label": FORM_STATUS_LABELS.get(stage, stage),
        "failed": stage in FAILURE_STAGES,
        "terminal": stage in TERMINAL_STAGES,
        # Present only on a failure, and it is the whole fault list: CR returns
        # every problem at once so one pass can fix them all.
        "faults": (row.get("cr_error") or {}).get("faults") or [],
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _insert(payload: dict) -> dict:
    return get_supabase().table(_TABLE).insert(payload).execute().data[0]


def _update(filing_id: str, payload: dict) -> None:
    get_supabase().table(_TABLE).update(payload).eq("id", filing_id).execute()


def get_filing(filing_id: str) -> dict:
    rows = get_supabase().table(_TABLE).select("*").eq("id", filing_id).execute().data
    if not rows:
        raise LookupError(f"no TPSI filing {filing_id}")
    return rows[0]


def supersede(filing_id: str) -> bool:
    """Retire an attempt CR has not filed. Returns whether a row moved.

    THE STAGE NOTHING EVER WROTE. `STAGE_SUPERSEDED` has existed since this
    module was written and `current_filing()` has always excluded it, but no
    caller ever set it — which is the defect migration 024's docstring records,
    and the reason `Restart verification` promised to discard the CR-signed
    snapshot and then left it in place. An operator who corrected the company
    details and restarted would re-send the client, and file, CR's OLD signed
    XML: the exact "show one document, file another" failure the verification
    gate exists to prevent.

    Conditional on the stage IN THE UPDATE, not read-then-written: a submit
    landing between a read and a write would otherwise be retired here, and the
    case would show no filing while CR held a registered return. The filter
    below can only ever match a row that is still un-filed at the moment
    Postgres applies it.
    """
    rows = (
        get_supabase().table(_TABLE)
        .update({"stage": STAGE_SUPERSEDED})
        .eq("id", filing_id)
        .not_.in_("stage", list(TERMINAL_STAGES))
        .execute()
        .data
    )
    return bool(rows)


def create_filing(
    *,
    entity_id: str,
    form_code: str,
    form_xml: str,
    user_id: str,
    nar1_case_id: str | None = None,
    form_filing_id: str | None = None,
) -> dict:
    """Open a filing attempt. Rejects an unknown form code before any CR call."""
    FORM_FEES[form_code]  # KeyError here beats a 400 from CR later
    return _insert(
        {
            "entity_id": entity_id,
            "form_code": form_code,
            "request_xml": form_xml,
            "presenter_user_id": user_id,
            "nar1_case_id": nar1_case_id,
            "form_filing_id": form_filing_id,
            "stage": STAGE_DRAFT,
        }
    )


def validate(client, filing_id: str) -> dict:
    """validateForm{Code}. No charge, no CR-side effect.

    On success CR returns the form with its own XML signature over it. That
    payload is carried forward VERBATIM — request and response share one
    namespace convention, so no rewriting is needed or wanted.

    Stage guard: refuses signed/submitted/edrive. This is the money invariant
    — the double-charge guard is the partial unique index
    `uq_tpsi_filings_submitted ... WHERE stage = 'submitted'`. Walking a
    submitted row's stage back to 'validated' would drop it from that index's
    coverage and let it be submitted again, so it must be impossible to reach
    from here, not just unlikely given call order. Re-validating a draft or an
    already-validated filing is legitimate (a user fixing field errors and
    retrying) and stays allowed.
    """
    from services.tpsi.soap import build_submission

    filing = get_filing(filing_id)
    if filing["stage"] in (STAGE_SIGNED,) + TERMINAL_STAGES:
        raise ValueError(
            f"filing is already {filing['stage']} and cannot be re-validated"
        )
    submission = build_submission(filing["request_xml"])

    try:
        raw = client.post_form("validateForm", filing["form_code"], submission)
        validated = extract_submission(raw)
    except TpsiError as exc:
        _update(
            filing_id,
            {
                "stage": STAGE_VALIDATION_FAILED,
                "cr_error": {"faults": getattr(exc, "faults", []), "message": str(exc)},
            },
        )
        raise

    _update(
        filing_id,
        {
            "stage": STAGE_VALIDATED,
            "validated_xml": validated,
            "validated_at": _now(),
            "cr_error": None,
        },
    )
    return get_filing(filing_id)


def _extract_eform(submission_xml: str) -> str:
    """The overall signature signs the <EForm> element, not the whole document.

    Sliced as text, prefix discovered from the document: the digest is over
    these exact bytes, so it must not be re-serialised.
    """
    import re as _re

    from services.tpsi.soap import CR_NS

    open_match = _re.search(r"<(\w+:)?EForm[\s>]", submission_xml)
    if not open_match:
        raise TpsiError("no <EForm> in the validated payload")
    prefix = open_match.group(1) or ""
    close = f"</{prefix}EForm>"
    end = submission_xml.find(close)
    if end == -1:
        raise TpsiError("unterminated <EForm> in the validated payload")
    sliced = submission_xml[open_match.start() : end + len(close)]

    # ...but the slice alone is NOT what CR digests. Its reference program does
    #     xml2String(xmlObj.getElementsByTagName('cr:EForm')[0])
    # i.e. XMLSerializer over the parsed subtree, and a serializer re-emits the
    # namespace declaration for every prefix the subtree uses. CR declares
    # xmlns:cr on the RESPONSE element, not on EForm, so the raw slice carries
    # no declaration and hashes to something CR never computes.
    # Injected as text rather than actually re-serialising, because everything
    # else about these bytes must survive untouched.
    if prefix and f"xmlns:{prefix[:-1]}=" not in sliced.split(">", 1)[0]:
        sliced = _re.sub(
            rf"^<{prefix}EForm\b",
            f'<{prefix}EForm xmlns:{prefix[:-1]}="{CR_NS}"',
            sliced,
            count=1,
        )
    return sliced


# ---------------------------------------------------------------------------
# The off-portal (wet-signature) interlock — BE-6
# ---------------------------------------------------------------------------
#
# nar1_cases.manual_conflict() guards the manual path against a live filing, but
# only in one direction. It deliberately allows a manual completion while a
# filing sits at 'validated' (the client changed their mind mid-chain), and
# 'validated' -> 'signed' -> 'submitted' is then free of any check that knows the
# case has already been filed on paper. That is one chargeable, IRREVERSIBLE
# call away from lodging the same statutory return with CR twice.
#
# So the interlock is two-way: every step of the e-Sign chain that puts a form in
# front of CR refuses a case whose return is already filed off-portal. It is read
# from the database on every call rather than cached, and it FAILS CLOSED — if
# the case cannot be read, the chargeable call does not happen.


class SubmitGateError(Exception):
    """A guard on the chargeable, irreversible submit refused.

    Defined here rather than in the Submit section below because
    ManualCompletionInterlock subclasses it and `sign` raises that.
    """


class ManualCompletionInterlock(SubmitGateError):
    """The case behind this filing was already filed off-portal.

    A SubmitGateError so `submit_filing` refuses, audits (TPSI_SUBMISSION_FAILED)
    and 409s it exactly like every other guard on the chargeable call. `sign` and
    `upload_edrive` raise it too and their routes handle it explicitly, so the
    refusal surfaces before the signature rather than at the charge.
    """


def manual_completion(filing: dict) -> dict | None:
    """The off-portal completion recorded against this filing's case, or None.

    A filing with no `nar1_case_id` (NNC1, or a bare TPSI filing) has no case to
    have been completed, so there is nothing to check.
    """
    case_id = filing.get("nar1_case_id")
    if not case_id:
        return None
    rows = (
        get_supabase().table("nar1_cases")
        .select("id,case_no,manual_receipt,manual_submitted_at")
        .eq("id", case_id)
        .limit(1)
        .execute()
        .data
    )
    case = (rows or [None])[0] or {}
    return case if case.get("manual_receipt") else None


def _refuse_if_filed_off_portal(filing: dict, action: str) -> None:
    case = manual_completion(filing)
    if case is None:
        return
    raise ManualCompletionInterlock(
        f"case {case.get('case_no') or case.get('id')} was already filed "
        f"off-portal (wet signature, receipt recorded "
        f"{case.get('manual_submitted_at') or 'earlier'}) — {action} would lodge "
        "the same annual return with CR a second time and charge the deposit "
        "account for it"
    )


def sign(client, filing_id: str, signatory_user_id: str, eservice_password: str) -> dict:
    """verifyPinSigning{Code}. No charge.

    NAR1 carries ONE overall signature by a single authorised individual — a
    director OR the company secretary. No consent signatures (spec D2).
    """
    from services.tpsi.crypto import build_pin_sign, signing_public_key_pem
    from services.tpsi.soap import append_to_signatures

    filing = get_filing(filing_id)
    # First, and before the stage check: a signature on a case already filed on
    # paper is the step that arms the chargeable one. Naming the real obstacle
    # here beats letting it surface a step later, at the charge.
    _refuse_if_filed_off_portal(filing, "signing this filing")
    if filing["stage"] != STAGE_VALIDATED:
        raise ValueError("filing must be validated before it can be signed")

    validated = filing["validated_xml"]
    pin_sign = build_pin_sign(
        _extract_eform(validated),
        signatory_user_id,
        eservice_password,
        # The certificate CR signed THIS response with — not
        # config.cr_public_key_pem, which is the change-password key. See
        # crypto.signing_public_key_pem.
        signing_public_key_pem(validated),
    )
    # CR: the overall signature goes inside EFormSignatures, BELOW its own.
    signed = append_to_signatures(validated, pin_sign)

    try:
        raw = client.post_form("verifyPinSigning", filing["form_code"], signed)
        element = parse_response(raw, "verifyPinSigningResponse")
        result = text_of(element, "result") or ""
    except TpsiError as exc:
        _update(
            filing_id,
            {"stage": STAGE_SIGNING_FAILED,
             "cr_error": {"faults": getattr(exc, "faults", []), "message": str(exc)}},
        )
        raise

    _update(
        filing_id,
        {"stage": STAGE_SIGNED, "signed_xml": signed,
         "signed_at": _now(), "cr_error": None},
    )
    return {"filing_id": filing_id, "result": result}


def upload_edrive(client, filing_id: str) -> dict:
    """uploadToEdriveForm{Code}. No charge.

    Terminal for TPSI: CR states the form is "inconvertible to TPSI format after
    submitting to e-Drive" — it must be finished in the Web Guided Wizard, so
    this filing can never go on to submitForm.
    """
    filing = get_filing(filing_id)
    # e-Drive is a lodgement channel, not a preview: STAGE_EDRIVE is one of
    # nar1_cases.CR_FILED_STAGES precisely because CR holds the return after it.
    # Blocking only sign/submit would leave this door open from 'validated'.
    _refuse_if_filed_off_portal(filing, "sending it to CR e-Drive")
    if filing["stage"] not in (STAGE_VALIDATED, STAGE_SIGNED):
        raise ValueError("filing must be validated before it can go to e-Drive")

    payload = filing.get("signed_xml") or filing["validated_xml"]
    raw = client.post_form("uploadToEdriveForm", filing["form_code"], payload)
    element = parse_response(raw, "uploadToEdriveResponse")
    result = text_of(element, "result") or ""

    _update(filing_id, {"stage": STAGE_EDRIVE})
    return {"filing_id": filing_id, "result": result}


# ---------------------------------------------------------------------------
# Submit — CHARGEABLE AND IRREVERSIBLE
# ---------------------------------------------------------------------------

#: The receipt vocabulary CR returns from submitForm. PUBLIC because the manual
#: (off-portal) path in services/nar1_cases.py validates a hand-entered receipt
#: against this same tuple — the Confirmation screen renders one template for
#: both paths, so the two shapes must not be allowed to drift apart (BE-6).
RECEIPT_FIELDS = (
    "caseNo", "brNo", "accNo", "chiCoyName", "engCoyName",
    "docCodesWithBarcode", "pymtNo", "pymtRefNo", "pymtMtd",
    "transactionDate", "transactionTime", "totalAmount", "refNo",
)
RECEIPT_LINE_FIELDS = ("rcptNo", "revCode", "docShtFrm", "revDesc", "amtChrg")


def parse_receipt(xml_bytes: bytes) -> dict:
    """CR's submitForm receipt — the only proof the filing landed."""
    from services.tpsi.soap import find_all

    element = parse_response(xml_bytes, "submitFormResponse")
    receipt = {f: text_of(element, f) for f in RECEIPT_FIELDS}
    receipt["paymentRcptList"] = [
        {f: text_of(line, f) for f in RECEIPT_LINE_FIELDS}
        for line in find_all(element, "paymentRcptList")
    ]
    return receipt


def _check_gate(filing: dict, confirm: bool, balance, quote) -> None:
    """The four conditions, in CR's own order. Server-side, always.

    Every one is checked against state this service holds, never against
    something the caller asserted — a client must not be able to claim it
    already validated and jump straight to the charge.
    """
    if filing["stage"] != STAGE_SIGNED:
        raise SubmitGateError(
            f"filing is '{filing['stage']}' — it must be signed "
            "(validate then sign, in that order) before it can be submitted"
        )
    if not filing.get("signed_xml"):
        raise SubmitGateError("no signed payload stored for this filing")
    # Checked against the fee THIS return will actually attract, computed from
    # the company's return date (services/tpsi/fees.py) -- and against the
    # HK$3,480 ceiling when that cannot be computed. Never against the flat
    # on-time fee: a NAR1 quoted at HK$105 was billed HK$2,610 on the test
    # environment, and comparing with HK$105 let a filing through that the
    # account could not cover. The failure then happened at CR, mid-charge.
    if balance < quote.amount:
        detail = (
            f"the fee for this return is HK${quote.amount} "
            f"({quote.band})"
            if quote.certain else
            f"this return could cost up to HK${quote.amount} ({quote.reason})"
        )
        raise SubmitGateError(
            f"deposit balance {balance} does not cover it: {detail}. "
            "Top up the deposit account before filing."
        )
    if confirm is not True:
        raise SubmitGateError("explicit confirmation is required to submit")


def preview(client, filing_id: str, deposit_account: str) -> dict:
    """Fee and live balance, with nothing sent to CR.

    Audited separately from the confirm, per CLAUDE.md — the preview and the
    decision to spend are two distinct events in the trail.
    """
    from services.tpsi import reads
    from services.tpsi.fees import MAX_FEE, ON_TIME_FEE

    filing = get_filing(filing_id)
    # The COMPUTED fee for THIS company's return date, not the flat on-time
    # figure. A return seven months late costs HK$2,610; quoting HK$105 both
    # misinformed the operator and let the balance gate pass a filing the
    # account could not cover.
    quote = fee_quote_for(filing)
    balance = reads.check_balance(client, deposit_account)
    return {
        "filing_id": filing_id,
        "form_code": filing["form_code"],
        "stage": filing["stage"],
        "fee": str(quote.amount),
        # The whole quote, so the screen can show the band and the return date
        # it was measured from. An operator can check those against the company
        # record; they cannot check a bare number.
        "fee_detail": quote.as_dict(),
        "fee_is_certain": quote.certain,
        "on_time_fee": str(ON_TIME_FEE),
        "max_fee": str(MAX_FEE),
        "balance": str(balance),
        "sufficient": balance >= quote.amount,
        "ready": filing["stage"] == STAGE_SIGNED and bool(filing.get("signed_xml")),
    }


def fee_quote_for(filing: dict):
    """The registration fee CR will charge for this filing.

    Computed from the company's return date and today's date (see
    services/tpsi/fees.py), which is what CR itself charges on. Returns an
    UNCERTAIN quote at the HK$3,480 ceiling whenever the inputs do not support
    a confident answer — never a confident wrong number, and never the on-time
    fee as a stand-in, because this value also gates the deposit balance.

    Never raises: it is called on the path to a chargeable submit, and a
    lookup failure must degrade to the ceiling rather than block a filing that
    is otherwise ready.
    """
    from services.tpsi import fees
    from services.tpsi.forms import nar1_summary

    if filing.get("form_code") != "Nar1":
        from services.tpsi.config import fee_for
        flat = fee_for(filing["form_code"])
        return fees.FeeQuote(flat, "fixed fee", None, None, True)

    try:
        entity = _entity_for_fee(filing.get("entity_id"))
    except Exception:  # noqa: BLE001
        return fees.uncertain("the company record could not be read")

    year = None
    has_share_capital = False
    xml = filing.get("validated_xml") or filing.get("request_xml")
    if xml:
        try:
            summary = nar1_summary.summarise(xml)
            year = summary.get("year")
            has_share_capital = bool(summary.get("share_classes"))
        except Exception:  # noqa: BLE001
            pass

    return fees.annual_return_fee(
        incorporation_date=(entity or {}).get("incorporation_date"),
        year=year,
        private_with_share_capital=fees.is_private_with_share_capital(
            entity, has_share_capital=has_share_capital),
    )


def _entity_for_fee(entity_id: str | None) -> dict:
    if not entity_id:
        return {}
    rows = (
        get_supabase().table("entities")
        .select("id,company_type,incorporation_date")
        .eq("id", entity_id).limit(1).execute().data or []
    )
    return rows[0] if rows else {}


def _charged_amount(receipt: dict, predicted) -> str:
    """What CR billed, falling back to our prediction only if the receipt is silent.

    `totalAmount` is the receipt's own figure and is the only authority on what
    left the deposit account. Falls back rather than raising: the money has
    already moved by the time this runs, and refusing to record a successful
    irreversible filing over a missing field would be the worse failure.
    """
    total = (receipt or {}).get("totalAmount")
    if total in (None, ""):
        return str(predicted)
    try:
        return str(Decimal(str(total)))
    except (InvalidOperation, ValueError):
        return str(predicted)


def submit(client, filing_id: str, confirm: bool, deposit_account: str) -> dict:
    """submitForm{Code} — CHARGEABLE AND IRREVERSIBLE.

    The fee leaves the deposit account and there is no un-submit. The stage
    guard also refuses a filing already at 'submitted' or parked in 'edrive'
    (CR: a form sent to e-Drive is "inconvertible to TPSI format"), so neither
    can be charged a second time or filed twice.
    """
    from services.tpsi import reads
    from services.tpsi.config import fee_for
    from services.tpsi.soap import append_deposit_account

    filing = get_filing(filing_id)
    # BEFORE any CR traffic at all, including the free balance read: this is the
    # chargeable, irreversible one, and a case already filed on paper must never
    # get as far as a request that could spend.
    _refuse_if_filed_off_portal(filing, "submitting it to CR")
    quote = fee_quote_for(filing)
    balance = reads.check_balance(client, deposit_account)  # LIVE, never cached
    _check_gate(filing, confirm, balance, quote)

    signed = filing["signed_xml"]
    body = (
        signed
        if "depositAccountNo" in signed
        else append_deposit_account(signed, deposit_account)
    )

    try:
        raw = client.post_form("submitForm", filing["form_code"], body)
        receipt = parse_receipt(raw)
    except TpsiError as exc:
        _update(
            filing_id,
            {
                "stage": STAGE_SUBMISSION_FAILED,
                "cr_error": {"faults": getattr(exc, "faults", []), "message": str(exc)},
            },
        )
        raise

    _update(
        filing_id,
        {
            "stage": STAGE_SUBMITTED,
            "receipt": receipt,
            # WHAT CR ACTUALLY CHARGED, not what we predicted. `fee_for` returns
            # the on-time NAR1 fee (HK$105); a late annual return is charged
            # HK$870-HK$3,480 and CR decides which tier applies. Measured on the
            # CR TEST environment 2026-08-27: a return 7 months past its
            # anniversary was billed HK$2,610 under revenue code 16, document
            # NAR1L -- the trailing "L" is CR's own marker for a late form.
            # Storing our prediction here made the filing row disagree with the
            # receipt beside it, which is the one place the numbers must match.
            "fee_amount": _charged_amount(receipt, quote.amount),
            "balance_at_submit": str(balance),
            "submitted_at": _now(),
            "cr_error": None,
        },
    )
    _write_back_receipt(filing, receipt)
    return {"filing_id": filing_id, "receipt": receipt}


def _write_back_receipt(filing: dict, receipt: dict) -> None:
    """Mirror the receipt onto the existing form_filings row.

    The case UI already reads form_filings, so the receipt lands where it is
    already looked for — no new columns on nar1_cases. Never raises: the filing
    has been submitted and charged by this point, and a bookkeeping failure must
    not turn a successful, irreversible submission into an error response.
    """
    if not filing.get("form_filing_id"):
        return
    try:
        get_supabase().table("form_filings").update(
            {
                "filed_with_cr": True,
                "filed_date": _now()[:10],
                "field_details": {"receipt": receipt},
            }
        ).eq("id", filing["form_filing_id"]).execute()
    except Exception as exc:  # noqa: BLE001 - see docstring
        print(
            f"[tpsi.filings] WARN: receipt write-back failed for filing "
            f"{filing.get('id')}: {exc}",
            file=sys.stderr,
        )
