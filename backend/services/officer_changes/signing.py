"""verifyPinSigning and submitForm for ND2A / ND2B.

SIGNING (spec §5, §8; answers 8 and 17). An ND2A needs a CONSENT signature
for each newly appointed director — CR's interface carries `selectPersonId`
inside the appointment and a `PinSign` over it — and every form needs the
OVERALL signature. Following CR's reference program (`createEFormSignatureV2`,
the non-FormSigner branch):

  1. each consent `<cr:PinSign URI="#S<n>">` is computed over that director's
     bean as an XMLSerializer emits it — the element sliced from the validated
     bytes with `xmlns:cr` declared right after the tag name, exactly as
     `filings._extract_eform` treats the EForm — and placed inside
     `<cr:formDataSignatures>` within the EForm;
  2. the overall `<cr:PinSign URI="#eForm">` is computed LAST, over the EForm
     that now contains the consents, and appended to `EFormSignatures` below
     CR's own signature;
  3. one `verifyPinSigning` call carries them all.

Each director consents with their OWN stored e-Registry credential (GSHK set
the account up and keeps it, answer 8); the overall signature is the signed-in
user's own e-Service account, as on NAR1. No officer's account is used for
anything but their own consent.

SUBMITTING. ND2A and ND2B are free: no deposit account goes on the request (CR's
submit examples carry none), there is no balance to read, no return date to
wait for and no NAR1 drift check. What stays is everything that protects the
register: the case must not be closed or already filed, the client must have
been asked to confirm, and the filing must be signed.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from services.tpsi import filings
from services.tpsi.crypto import build_pin_sign, signing_public_key_pem
from services.tpsi.errors import TpsiError
from services.tpsi.soap import (
    CR_NS, DS_NS, append_to_signatures, parse_response, text_of,
)

_BEANS = ("appOfNpBean", "appOfBcBean")


class ConsentCredentialMissing(Exception):
    """A new director's stored e-Registry credential is incomplete."""


def bean_fragment(submission_xml: str, bean_id: str) -> str:
    """The bean CR's reference program digests for consent `bean_id`."""
    pattern = rf'<(\w+:)?({"|".join(_BEANS)})\b[^>]*\bid="{re.escape(bean_id)}"[^>]*>'
    match = re.search(pattern, submission_xml)
    if not match:
        raise ValueError(f"the validated form has no appointment with id {bean_id!r}")
    prefix, tag = match.group(1) or "", match.group(2)
    close = f"</{prefix}{tag}>"
    end = submission_xml.find(close, match.end())
    if end == -1:
        raise TpsiError(f"unterminated <{tag} id={bean_id!r}> in the validated payload")
    sliced = submission_xml[match.start(): end + len(close)]
    if prefix and f"xmlns:{prefix[:-1]}=" not in sliced.split(">", 1)[0]:
        sliced = re.sub(rf"^<{prefix}{tag}\b",
                        f'<{prefix}{tag} xmlns:{prefix[:-1]}="{CR_NS}"', sliced, count=1)
    return sliced


def insert_form_data_signatures(submission_xml: str, fragment: str) -> str:
    """Put consent signatures inside <formDataSignatures>, creating it after
    </formModel> when the payload does not carry one."""
    if not fragment:
        return submission_xml
    empty = re.search(r"<(\w+:)?formDataSignatures\s*/>", submission_xml)
    if empty:
        prefix = empty.group(1) or ""
        return (submission_xml[: empty.start()]
                + f"<{prefix}formDataSignatures>{fragment}</{prefix}formDataSignatures>"
                + submission_xml[empty.end():])
    closing = re.search(r"</(\w+:)?formDataSignatures>", submission_xml)
    if closing:
        return submission_xml[: closing.start()] + fragment + submission_xml[closing.start():]
    model_end = re.search(r"</(\w+:)?formModel>", submission_xml)
    if not model_end:
        raise TpsiError("no <formModel> in the validated payload")
    prefix = model_end.group(1) or ""
    return (submission_xml[: model_end.end()]
            + f"<{prefix}formDataSignatures>{fragment}</{prefix}formDataSignatures>"
            + submission_xml[model_end.end():])


def declared_signatory(submission_xml: str) -> str | None:
    """The FORM-LEVEL selectPersonId — a direct child of formModel. NAR1's
    `filings.declared_signatory_id` reads the first one in the document, which
    on an ND2A is a new director's consent id, not the signatory."""
    # The stored slice carries no namespace declarations (they live on CR's
    # response element), so it is parsed inside a wrapper that declares them.
    try:
        root = ET.fromstring(f'<w xmlns:cr="{CR_NS}" xmlns:ds="{DS_NS}">'
                             f"{submission_xml}</w>")
    except ET.ParseError:
        return None
    model = next((el for el in root.iter() if el.tag.endswith("formModel")), None)
    if model is None:
        return None
    for child in model:
        if child.tag.split("}")[-1] == "selectPersonId":
            return (child.text or "").strip() or None
    return None


def sign(client, filing_id: str, *, signatory_user_id: str, eservice_password: str,
         consents: list[dict]) -> dict:
    """One consent PinSign per `consents` row (`{bean_id, user_id, password}`),
    then the overall signature, in ONE verifyPinSigning call."""
    filing = filings.get_filing(filing_id)
    filings._refuse_if_case_finished(filing, "signing this filing")
    if filing["stage"] != filings.STAGE_VALIDATED:
        raise ValueError("filing must be validated before it can be signed")
    validated = filing["validated_xml"]
    declared = declared_signatory(validated)
    if declared and declared.casefold() != (signatory_user_id or "").casefold():
        raise filings.SignatoryMismatch(
            f"this form names e-Service account '{declared}' as its signatory, but "
            f"you are signing as '{signatory_user_id}'")
    for consent in consents:
        if not (consent.get("user_id") and consent.get("password") and consent.get("bean_id")):
            raise ConsentCredentialMissing(
                f"the consent signature for {consent.get('bean_id') or 'a new director'} "
                "has no stored e-Registry credential")

    key = signing_public_key_pem(validated)
    consent_xml = "".join(
        build_pin_sign(bean_fragment(validated, c["bean_id"]), c["user_id"],
                       c["password"], key, uri=f"#{c['bean_id']}")
        for c in consents)
    with_consents = insert_form_data_signatures(validated, consent_xml)
    overall = build_pin_sign(filings._extract_eform(with_consents), signatory_user_id,
                             eservice_password, key)
    signed = append_to_signatures(with_consents, overall)

    try:
        raw = client.post_form("verifyPinSigning", filing["form_code"], signed)
        result = text_of(parse_response(raw, "verifyPinSigningResponse"), "result") or ""
    except TpsiError as exc:
        filings._update(filing_id, {
            "stage": filings.STAGE_SIGNING_FAILED,
            "cr_error": {"faults": getattr(exc, "faults", []), "message": str(exc)}})
        raise
    filings._update(filing_id, {"stage": filings.STAGE_SIGNED, "signed_xml": signed,
                                "signed_at": filings._now(), "cr_error": None})
    return {"filing_id": filing_id, "result": result, "consents": len(consents)}


_DOC_REF = re.compile(r"\(\s*([A-Z0-9]+)\s*\)")


def with_document_ref(receipt: dict) -> dict:
    """CR's receipt, verbatim, plus the document reference where CR put it.

    MEASURED on CR TEST (2026-10-02, case 141946253): a FREE form's receipt
    carries no payment block, so `refNo`, `transactionDate`, `transactionTime`
    and `totalAmount` all come back empty, and the document reference exists
    only inside `docCodesWithBarcode` — "ND2B (T0022892651)". It is lifted into
    `documentRefNo` (an added key: CR's own fields are never rewritten)."""
    if receipt.get("refNo") or receipt.get("documentRefNo"):
        return receipt
    match = _DOC_REF.search(receipt.get("docCodesWithBarcode") or "")
    return {**receipt, "documentRefNo": match.group(1)} if match else receipt


def submit(client, filing_id: str, *, confirm: bool) -> dict:
    """submitForm{Code} for a signed filing. Returns the filing row's receipt."""
    filing = filings.get_filing(filing_id)
    filings._refuse_if_case_finished(filing, "submitting it to CR")
    if confirm is not True:
        raise filings.SubmitGateError("Confirm the filing before it is sent to CR")
    if filing["stage"] != filings.STAGE_SIGNED:
        raise ValueError("filing must be signed before it can be submitted")
    try:
        raw = client.post_form("submitForm", filing["form_code"], filing["signed_xml"])
        receipt = with_document_ref(filings.parse_receipt(raw))
    except TpsiError as exc:
        filings._update(filing_id, {
            "stage": filings.STAGE_SUBMISSION_FAILED,
            "cr_error": {"faults": getattr(exc, "faults", []), "message": str(exc)}})
        raise
    filings._update(filing_id, {
        "stage": filings.STAGE_SUBMITTED, "receipt": receipt, "fee_amount": "0",
        "submitted_at": filings._now(), "cr_error": None})
    filings._write_back_receipt(filing, receipt)
    return {"filing_id": filing_id, "receipt": receipt}
