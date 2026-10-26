"""SOAP envelope construction and response parsing for TPSI.

Verified against CR's shipped example files in docs/Web Form Example/ — those
supersede the .docx appendix, which shows a different (and wrong) request shape.

Both directions use the SAME convention:

    envelope : http://schemas.xmlsoap.org/soap/envelope/   (SOAP 1.1)
    cr       : http://interfaces.service.webservice.icris3e.cr.gov.hk/
    ds       : http://www.w3.org/2000/09/xmldsig#

soap:Body carries an operation wrapper (cr:validateForm, cr:verifyPinSigning,
cr:uploadToEdrive, cr:submitForm) around cr:submission.

Because the two directions match, the CR-signed payload from validateForm is
carried forward AS RECEIVED. CR's <Signature id="CR"> is a detached XML-DSig
whose digest covers canonicalised form content, so it is spliced as text and
never round-tripped through a parser — re-serialising would silently invalidate
it and CR rejects the signature with no useful error.

Reading is namespace-aware, by LOCAL NAME. Never match on a prefix string.
"""
import re
from xml.etree import ElementTree as ET

from services.tpsi.errors import TpsiError, raise_for_fault

SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
CR_NS = "http://interfaces.service.webservice.icris3e.cr.gov.hk/"
DS_NS = "http://www.w3.org/2000/09/xmldsig#"

# URL path segment -> soap:Body wrapper element. They are NOT the same string
# for e-Drive: the path says uploadToEdriveForm, the body says uploadToEdrive.
OPERATIONS = {
    "validateForm": "validateForm",
    "verifyPinSigning": "verifyPinSigning",
    "uploadToEdriveForm": "uploadToEdrive",
    "submitForm": "submitForm",
}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def wrap_envelope(body_xml: str) -> bytes:
    """Envelope + Body around an already-built body element.

    Used directly by the read APIs, whose bodies are their own operation
    elements (cr:enquireDepositAccount, cr:docStatusEnquiry) rather than a
    submission.
    """
    return (
        f'<soap:Envelope xmlns:soap="{SOAP_NS}">'
        f"<soap:Body>{body_xml}</soap:Body>"
        "</soap:Envelope>"
    ).encode("utf-8")


def build_envelope(operation: str, submission_xml: str) -> bytes:
    """Wrap <cr:submission> in its operation wrapper and the SOAP envelope.

    `operation` is the URL path prefix (e.g. "submitForm"); the wrapper element
    is looked up from OPERATIONS because the two differ for e-Drive.
    """
    wrapper = OPERATIONS[operation]
    return wrap_envelope(
        f'<cr:{wrapper} xmlns:ds="{DS_NS}" xmlns:cr="{CR_NS}">'
        f"{submission_xml}"
        f"</cr:{wrapper}>"
    )


def build_submission(
    form_xml: str,
    signatures_xml: str = "",
    deposit_account_no: str | None = None,
) -> str:
    """Build <cr:submission> for a first (validate) request.

    `form_xml` is the inner content of <cr:formModel>. <cr:EFormSignatures> is
    emitted EMPTY on validate — CR fills it in on the response. That empty
    element is required: CR's own validate examples all carry it.
    """
    parts = [
        "<cr:submission>",
        '<cr:EForm id="eForm">',
        '<cr:formModel id="formData">',
        form_xml,
        "</cr:formModel>",
        "</cr:EForm>",
        f"<cr:EFormSignatures>{signatures_xml}</cr:EFormSignatures>",
    ]
    if deposit_account_no:
        parts.append(f"<cr:depositAccountNo>{deposit_account_no}</cr:depositAccountNo>")
    parts.append("</cr:submission>")
    return "".join(parts)


def parse_response(xml_bytes: bytes, response_tag: str) -> ET.Element:
    """Return the named response element, raising the right error on a fault."""
    raise_for_fault(xml_bytes)
    root = ET.fromstring(xml_bytes)
    for el in root.iter():
        if _local(el.tag) == response_tag:
            return el
    raise TpsiError(f"no <{response_tag}> in TPSI response")


def text_of(el: ET.Element, local_name: str) -> str | None:
    for child in el.iter():
        if _local(child.tag) == local_name:
            return (child.text or "").strip()
    return None


def find_all(el: ET.Element, local_name: str) -> list[ET.Element]:
    return [c for c in el.iter() if _local(c.tag) == local_name]


def extract_submission(xml_bytes: bytes) -> str:
    """Slice <cr:submission>…</cr:submission> out of a response, VERBATIM.

    Deliberately a text slice, not a parse-and-reserialise: CR's signature
    digest covers the exact bytes, and ElementTree would renormalise namespace
    declarations, attribute order and whitespace.

    The prefix is discovered from the document rather than assumed, because a
    prefix is not part of the contract even though CR consistently uses `cr`.
    """
    raise_for_fault(xml_bytes)
    text = xml_bytes.decode("utf-8")
    match = re.search(r"<(\w+:)?submission[\s>]", text)
    if not match:
        raise TpsiError("no <submission> in TPSI response")
    prefix = match.group(1) or ""
    start = match.start()
    close = f"</{prefix}submission>"
    end = text.rindex(close) + len(close)
    return text[start:end]


def append_to_signatures(submission_xml: str, fragment: str) -> str:
    """Insert a fragment just before </EFormSignatures>.

    CR requires the overall signature to sit inside EFormSignatures BELOW its
    own <Signature id="CR">, which is what appending achieves. Handles the
    self-closing form that a validate request produces.
    """
    match = re.search(r"</(\w+:)?EFormSignatures>", submission_xml)
    if match:
        return submission_xml[: match.start()] + fragment + submission_xml[match.start():]

    empty = re.search(r"<(\w+:)?EFormSignatures\s*/>", submission_xml)
    if empty:
        prefix = empty.group(1) or ""
        return (
            submission_xml[: empty.start()]
            + f"<{prefix}EFormSignatures>{fragment}</{prefix}EFormSignatures>"
            + submission_xml[empty.end():]
        )
    raise TpsiError("no <EFormSignatures> in the submission payload")


def append_deposit_account(submission_xml: str, account_no: str) -> str:
    """Add <cr:depositAccountNo> as the last child of <cr:submission>.

    Submit only — it appears in no other operation's examples.
    """
    match = re.search(r"</(\w+:)?submission>", submission_xml)
    if not match:
        raise TpsiError("no </submission> in the payload")
    prefix = match.group(1) or ""
    tag = f"<{prefix}depositAccountNo>{account_no}</{prefix}depositAccountNo>"
    return submission_xml[: match.start()] + tag + submission_xml[match.start():]
