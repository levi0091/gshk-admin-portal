"""The Submission stage's "Final summary · to be filed" (wireframe_v11 s20 §4).

WHY THIS PARSES THE XML AND DOES NOT RE-READ THE COMPANY.

Submission is the irreversible step, and the thing being submitted is the
**frozen snapshot** — the CR-validated XML on the filing row. `nar1_return_data`
answers a different question ("what would we build from the profile today?")
and is right for Data Verification, where the profile IS the subject. Using it
here would show the operator a summary assembled from data that may have moved
since validation, and they would confirm an irreversible charge against it. The
two must not be interchangeable, which is why this is a separate module rather
than a flag on that one.

So: the summary is read back out of the same bytes that go to CR. If the
profile changed after validation, this still shows what will actually be filed
— and the difference is the operator's cue to restart verification.

`form_xml` IS NOT A DOCUMENT. `nar1.build_nar1_xml` returns a bare FRAGMENT —
no root element, and a `cr:` prefix that is never declared, because CR's SOAP
envelope supplies both. So it has to be wrapped before any parser will touch it
(`ParseError: unbound prefix` otherwise), and the wrapper is discarded. Matching
is on localnames: there is one vocabulary here, so that is unambiguous and it
survives CR changing the prefix.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

#: The address element order CR uses, flattened to one human line.
_ADDR_PARTS = ("flatFlrBlk", "bldg", "stEstLotVlg", "dstCtyStatePostal", "ctryRegion")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(node, name: str):
    for child in node.iter():
        if _local(child.tag) == name:
            return child
    return None


def _text(node, name: str) -> str | None:
    found = _find(node, name) if node is not None else None
    if found is None or found.text is None:
        return None
    value = found.text.strip()
    return value or None


def _children(node, name: str) -> list:
    """Direct-ish descendants with this localname, in document order."""
    if node is None:
        return []
    return [c for c in node.iter() if _local(c.tag) == name]


def _address_line(node) -> str | None:
    if node is None:
        return None
    parts = []
    for name in _ADDR_PARTS:
        child = next((c for c in node if _local(c.tag) == name), None)
        if child is not None and child.text and child.text.strip():
            parts.append(child.text.strip())
    return ", ".join(parts) or None


def _party_name(node) -> str | None:
    """An officer or allottee is an individual or a body corporate."""
    corp = _text(node, "corpEngName") or _text(node, "corpChiName")
    if corp:
        return corp
    surname = _text(node, "indvEngSname") or _text(node, "indvSurname")
    other = _text(node, "indvEngOname") or _text(node, "indvOtherName")
    name = ", ".join(p for p in (surname, other) if p)
    return name or _text(node, "indvChiName")


#: Any URI works — nothing is validated against a schema here; the declarations
#: exist only so the undeclared prefixes resolve.
#:
#: `ds:` is XML-DSig and appears in `validated_xml` ONLY: that column is CR's
#: signed document, so it carries a <ds:Signature> block. Measured on DEV
#: filing a8a297f2: `cr` in both columns, `ds` in the validated one, neither
#: ever declared inline. Omitting `ds` here fails at the byte where the
#: signature starts — 4,609 characters in — which reads like corruption rather
#: than a missing declaration.
_WRAPPER = (
    '<gfd:wrap xmlns:cr="urn:cr" xmlns:ds="http://www.w3.org/2000/09/xmldsig#"'
    ' xmlns:gfd="urn:gfd">{}</gfd:wrap>'
)


def summarise(form_xml: str) -> dict:
    """The rows the Submission card shows, read out of the filed XML.

    Raises `ValueError` on unparseable XML rather than returning a hollow
    summary — a Submission card with every row blank in front of an
    irreversible charge is worse than an error that says so.
    """
    try:
        root = ET.fromstring(_WRAPPER.format(form_xml))
    except ET.ParseError as exc:
        raise ValueError(f"filing XML could not be parsed: {exc}") from exc

    share_classes = []
    for cap in _children(root, "shareCapital"):
        share_classes.append({
            "name": _text(cap, "clsOfShares"),
            "currency": _text(cap, "currency"),
            "total_issued": _text(cap, "noOfShareIssuedOnThisCls"),
            "paid_up": _text(cap, "paidUpCapital"),
        })

    schedule1 = _find(root, "schedule1")
    allottees = _children(schedule1, "allottee") if schedule1 is not None else []

    directors = _children(root, "indDir") + _children(root, "corpDir")
    secretaries = _children(root, "indSec") + _children(root, "corpSec")

    return {
        "company_name": _text(root, "compNameE") or _text(root, "compNameC"),
        "company_name_zh": _text(root, "compNameC"),
        "br_number": _text(root, "brNo"),
        "year": _text(root, "yearAnnualReturn"),
        "registered_office": _address_line(_find(root, "roAddr")),
        "directors": [n for d in directors if (n := _party_name(d))],
        "secretaries": [n for s in secretaries if (n := _party_name(s))],
        "share_classes": share_classes,
        # Schedule 1 is the members list. Counted from the filed XML rather
        # than from `shareholdings`, so a member added since validation does
        # NOT silently appear in a summary of a return that never had them.
        "member_count": len(allottees),
        "members": [n for a in allottees if (n := _party_name(a))][:20],
        "has_schedule_1": schedule1 is not None,
        "signatory": {
            # selectPersonId is the e-Service User ID and CR verifies it is
            # authorised for this company. It identifies a person and is not a
            # secret, but it is also not something the summary needs, and the
            # presenter/deposit account deliberately never leaves the
            # super-admin-only read (routers/tpsi.py `_deposit_account`).
            "name": _text(root, "selectPersonName"),
            "capacity": _text(root, "selectCapacityDesc"),
            "date": _text(root, "signatoryDate"),
        },
    }
