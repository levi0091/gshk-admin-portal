"""Typed TPSI errors, and the SOAP Fault parser that produces them.

CR reports every error as a SOAP Fault carrying a LIST of fault beans. Keeping
the whole list matters: a NAR1 with four bad fields should surface four
messages, not send the user round the loop four times.
"""
from xml.etree import ElementTree as ET

SOAP_11 = "http://schemas.xmlsoap.org/soap/envelope/"
SOAP_12 = "http://www.w3.org/2003/05/soap-envelope/"

# Fault codes that mean "the signature or signatory is wrong", not "the data is
# wrong". They need a different message and a different remedy.
_SIGNATURE_CODES = {
    "ERR_MSG_NO_ASSOCIATION",
    "ERR_MSG_NO_USERSIGN",
    "ERR_MSG_USER_ACC_CLOSED",
    "ERR_MSG_USER_ACC_LOCKED",
    "ERR_MSG_NO_ACCOUNT",
    "ERR_MSG_SIGN_DATE_EARLY",
    "ERR_MSG_SIGNATORY_NIN_NOT_AUTH",
    "ERR_MSG_SIGNATORY_NOT_AUTH",
}


class TpsiError(Exception):
    """Base for every TPSI failure."""


class TpsiAuthError(TpsiError):
    """Authentication rejected. NEVER retried — CR locks accounts."""


class TpsiPasswordExpiredError(TpsiAuthError):
    """TPSI password is past its 180-day life; changeTpsiPassword is required."""


class TpsiUnavailableError(TpsiError):
    """Transport failure, or a call made outside the TEST service window."""


class _FaultError(TpsiError):
    def __init__(self, faults: list[tuple[str, str]]):
        self.faults = faults
        super().__init__("; ".join(f"{c}: {m}" for c, m in faults) or "TPSI fault")


class TpsiValidationError(_FaultError):
    """CR rejected the form data. `.faults` holds every reported problem."""


class TpsiSignatureError(_FaultError):
    """CR rejected the signature or the signatory's authority."""


def _local(tag: str) -> str:
    """Local name of a possibly-namespaced tag — prefixes are not stable."""
    return tag.rsplit("}", 1)[-1]


def _find_fault(root: ET.Element) -> ET.Element | None:
    for el in root.iter():
        if _local(el.tag) == "Fault":
            return el
    return None


def raise_for_fault(xml_bytes: bytes) -> None:
    """Raise the appropriate TpsiError if the payload is a SOAP Fault.

    A no-op for successful responses, so callers can apply it unconditionally.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise TpsiUnavailableError(f"malformed response from TPSI: {exc}") from exc

    fault = _find_fault(root)
    if fault is None:
        return

    faults: list[tuple[str, str]] = []
    for bean in fault.iter():
        if _local(bean.tag) != "webServiceFaultBeans":
            continue
        code = message = ""
        for child in bean:
            if _local(child.tag) == "faultCode":
                code = (child.text or "").strip()
            elif _local(child.tag) == "faultString":
                message = (child.text or "").strip()
        faults.append((code, message))

    if not faults:
        # A Fault with no beans: surface faultstring so the cause isn't lost.
        text = ""
        for el in fault:
            if _local(el.tag) == "faultstring":
                text = (el.text or "").strip()
        raise TpsiError(text or "unspecified TPSI fault")

    if any(code in _SIGNATURE_CODES for code, _ in faults):
        raise TpsiSignatureError(faults)
    raise TpsiValidationError(faults)
