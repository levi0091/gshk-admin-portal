"""The pre-submit drift gate (spec §6).

WHAT IT STOPS. `POST /tpsi/filings/{id}/submit` sends the CR-signed snapshot
stored on the filing row. That snapshot was built and validated when the case
was prepared — possibly weeks earlier — and the company record can move
underneath it. The client approved one document; CR would receive another. The
submit is chargeable and irreversible, so the check has to happen before the
first CR call, not after.

HOW IT COMPARES, AND WHY THIS WAY.

It rebuilds the return from today's master data with exactly the pair `prepare`
uses (`nar1_source.load_entity_graph` then `nar1_mapper.map_entity`), and diffs
the resulting XML against the `request_xml` stored on the filing.

`request_xml` — not `validated_xml`, not `signed_xml`. All three carry the same
particulars, but only `request_xml` came out of `build_nar1_xml`, so it is
comparable with a fresh build element for element: same schema order, same
whitespace, same numeric formatting. CR's copies add a `ds:Signature` block, a
`PinSign` block and CR-filled fields, and diffing against those would mean
canonicalising two different documents — manufacturing exactly the false
positives §6's "failure mode this must not introduce" warns about.
`filings.validate()` re-sends `request_xml` verbatim, so it IS the faithful
record of what CR validated.

The false-positive direction blocks a legitimate filing near a statutory
deadline; the false-negative direction files a wrong return. Both are addressed
by comparing like with like, never by loosening the rule.

WHAT IS IGNORED, AND WHY EACH ONE.

  signatoryDate    — the declaration date, `_hk_today()` at build time. Not a
                     particular of the company, and it changes every day by
                     construction, so comparing it would block every filing not
                     submitted on the day it was prepared.
  presenter fields — GSHK's own contact block, not filed particulars of the
                     subject company.

Everything else is compared, which is the blocking rule as chosen: any
difference in filed particulars.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import xml.etree.ElementTree as ET

#: Same wrapper `nar1_summary` uses, and for the same reason: `build_nar1_xml`
#: returns a bare fragment whose `cr:` prefix is never declared, because CR's
#: SOAP envelope supplies it. Without this every parse dies on "unbound prefix".
_WRAPPER = (
    '<gfd:wrap xmlns:cr="urn:cr" xmlns:ds="http://www.w3.org/2000/09/xmldsig#"'
    ' xmlns:gfd="urn:gfd">{}</gfd:wrap>'
)

#: Leaf localnames excluded from the comparison. See the module docstring —
#: every entry is a field that is not a particular of the company.
IGNORED_LEAVES = frozenset({
    "signatoryDate",
    # The presenter block. GSHK's own details; `nar1_form.fill.DEFAULT_PRESENTER`.
    "presenterName", "presenterAddr", "presenterTelNo", "presenterFaxNo",
    "presenterEmail", "presenterRef",
})

#: Ancestors whose whole subtree is excluded. `PinSign` carries the signing
#: credential hash and must never be read, compared or logged; `Signature` is
#: CR's digest over the document. Neither appears in a `request_xml`, but a
#: caller passing a signed document must not have its credentials diffed.
IGNORED_SUBTREES = frozenset({"PinSign", "Signature", "EFormSignatures"})

#: Human labels for the containers a path runs through, so a refusal reads
#: "Director (individual) 2 · Address · Building" and not
#: "indDirList/indDir[2]/stdAddress/bldg". Anything absent falls back to its own
#: element name, which is still better than nothing and cannot crash.
_GROUP_LABELS = {
    "roAddr": "Registered office",
    "stdAddress": "Address",
    "allotteeAddr": "Address",
    "shareCapitals": "Share capital",
    "shareCapital": "Share class",
    "indSecList": "Company secretary (individual)",
    "indSec": "Company secretary (individual)",
    "corpSecList": "Company secretary (body corporate)",
    "corpSec": "Company secretary (body corporate)",
    "indDirList": "Director (individual)",
    "indDir": "Director (individual)",
    "corpDirList": "Director (body corporate)",
    "corpDir": "Director (body corporate)",
    "resDirList": "Reserve director",
    "resDir": "Reserve director",
    "schedule1": "Schedule 1",
    "schedule2": "Schedule 2",
    "share": "Share class",
    "shareHolderGrp": "Shareholder group",
    "allotteeRec": "Allottee",
    "allottee": "Allottee",
}

_FIELD_LABELS = {
    "brNo": "Business Registration number",
    "compNameE": "Company name (English)",
    "compNameC": "Company name (Chinese)",
    "yearAnnualReturn": "Year of annual return",
    "emailAddr": "Email address",
    "telNo": "Telephone number",
    "flatFlrBlk": "Flat / floor / block",
    "bldg": "Building",
    "stEstLotVlg": "Street / estate / lot / village",
    "dstCtyStatePostal": "District / city / state",
    "ctryRegion": "Country / region",
    "addrLangInd": "Address language",
    "indvChiName": "Name (Chinese)",
    "indvEngSname": "Surname (English)",
    "indvEngOname": "Other names (English)",
    "indvEmailAddr": "Email address",
    "indvHkidNo": "HKID number",
    "indvPptNo": "Passport number",
    "indvPptIssCtry": "Passport issuing country",
    "corpChiName": "Name (Chinese)",
    "corpEngName": "Name (English)",
    "corpBrNo": "Business Registration number",
    "corpEmailAddr": "Email address",
    "clsOfShares": "Class of shares",
    "currency": "Currency",
    "noOfShareIssuedOnThisCls": "Shares issued",
    "issuedCapital": "Issued capital",
    "paidUpCapital": "Paid-up capital",
    "sharesAlloted": "Shares allotted",
    "indvSurname": "Surname (English)",
    "indvOtherName": "Other names (English)",
    "selectPersonName": "Signatory name",
    "selectCapacityDesc": "Signatory capacity",
    "selectPersonId": "Signatory user ID",
}


class DriftError(Exception):
    """The comparison itself could not be made.

    Distinct from "the documents differ": a graph that will not load, or an
    unparseable stored XML, is an operational failure. Reporting it as drift
    would send the operator to restart verification for a problem restarting
    cannot fix.
    """


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def flatten(fragment: str) -> dict:
    """Every leaf value in the document, keyed by an indexed path.

    Repeats are positional (`indDir[2]`), never sorted: director one and
    director two are different people and swapping them is a real change to the
    return.

    Empty leaves are dropped, because `build_nar1_xml` omits blank elements
    entirely — so an absent element and an empty one must not read as a
    difference.
    """
    try:
        root = ET.fromstring(_WRAPPER.format(fragment or ""))
    except ET.ParseError as exc:
        raise DriftError(f"filing XML could not be parsed: {exc}") from exc

    out = {}

    def walk(node, path):
        counts = {}
        for child in node:
            name = _local(child.tag)
            if name in IGNORED_SUBTREES:
                continue
            counts[name] = counts.get(name, 0) + 1
            index = counts[name]
            # An index only where one is needed. `roAddr[1]/bldg` is noise;
            # `indDir[2]/...` is the whole point.
            step = f"{name}[{index}]" if index > 1 else name
            where = f"{path}/{step}" if path else step
            if len(child):
                walk(child, where)
                continue
            if name in IGNORED_LEAVES:
                continue
            text = (child.text or "").strip()
            if text:
                out[where] = text

    walk(root, "")
    return out


def _label(path: str) -> str:
    """`indDirList/indDir[2]/stdAddress/bldg` becomes
    "Director (individual) 2 · Address · Building"."""
    # (label, index) pairs rather than finished strings, because the list
    # element and its repeating child share a label — `indDirList/indDir[2]`
    # must read "Director (individual) 2", not "Director (individual) · Director
    # (individual) 2".
    parts: list = []
    segments = path.split("/")
    for segment in segments[:-1]:
        name, _, rest = segment.partition("[")
        index = rest.rstrip("]")
        label = _GROUP_LABELS.get(name)
        if label is None:
            continue          # a pure container with no user-facing meaning
        if parts and parts[-1][0] == label:
            # Same group, deeper element: keep whichever index is known.
            parts[-1] = (label, index or parts[-1][1])
        else:
            parts.append((label, index))
    leaf = segments[-1].partition("[")[0]
    rendered = [f"{label} {index}" if index else label for label, index in parts]
    rendered.append(_FIELD_LABELS.get(leaf, leaf))
    return " · ".join(rendered)


def compare(validated_xml: str, current_xml: str) -> list:
    """Every field that differs, each with both values.

    A refusal that says only "the data differs" leaves the operator to diff a
    nine-page statutory form by eye, so the shape here is what the screen
    renders directly: label, path, validated value, current value.

    Sorted by path, so two runs over the same pair report in the same order.
    """
    before = flatten(validated_xml)
    after = flatten(current_xml)

    differences = []
    for path in sorted(set(before) | set(after)):
        old = before.get(path)
        new = after.get(path)
        if old == new:
            continue
        differences.append({
            "path": path,
            "field": _label(path),
            # None means the field is not in that version at all — a director
            # added or removed, not merely edited. The UI renders those as
            # "(absent)"; flattening them to "" here would hide the difference
            # between an empty value and no field.
            "validated": old,
            "current": new,
        })
    return differences


def _run_async(coro_factory):
    """Await a coroutine from synchronous code that is itself inside a loop.

    `filings.submit` is sync and is called directly from an async route handler,
    so a loop is already running on this thread and `asyncio.run` would raise.
    Running it on a short-lived thread of its own is what lets this gate reuse
    `load_entity_graph` VERBATIM — and reusing it is the point. A second,
    sequential loader written for this path would be a second definition of
    "the company's data", and the gate would eventually measure drift against
    something `prepare` never builds.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro_factory())).result()


def _capacity_for(filing: dict, graph: dict, default_capacity, nar1_mapper):
    """`selectCapacityDesc`, resolved exactly as `prepare` resolves it.

    The case's stored choice first, then the body-corporate default. Getting
    this wrong would make every body-corporate filing — which is every real
    GSHK client — report a spurious difference on the signatory capacity and
    block the submit.
    """
    from services import nar1_cases

    case_id = filing.get("nar1_case_id")
    if case_id:
        try:
            capacity = (nar1_cases.get_case(case_id) or {}).get("signatory_capacity")
        except Exception:  # noqa: BLE001 — the same tolerance `prepare` shows
            capacity = None
        if capacity:
            return capacity

    try:
        resolved = nar1_mapper._derive_signatory(graph)
    except Exception:  # noqa: BLE001
        return None
    if not resolved:
        return None
    return default_capacity(is_corporate=resolved.get("is_corporate") is True)


def current_xml_for(filing: dict) -> str:
    """Rebuild this filing's return from today's master data.

    Uses the year the STORED document declares, so a return prepared in
    December and submitted in January is not reported as drifting by a year it
    never had.
    """
    from services.tpsi.forms import nar1, nar1_mapper, nar1_source
    from services.tpsi.forms.cr_vocabularies import default_capacity

    entity_id = filing.get("entity_id")
    if not entity_id:
        raise DriftError("this filing has no company to compare against")

    stored = flatten(filing.get("request_xml") or "")
    try:
        year = int(stored.get("yearAnnualReturn"))
    except (TypeError, ValueError):
        raise DriftError(
            "the stored filing declares no year of annual return, so there is "
            "nothing to rebuild it against"
        )

    try:
        graph = _run_async(lambda: nar1_source.load_entity_graph(entity_id))
    except LookupError as exc:
        raise DriftError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — operational, not drift
        raise DriftError(
            f"the company record could not be reloaded to check for changes: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    capacity = _capacity_for(filing, graph, default_capacity, nar1_mapper)

    try:
        data = nar1_mapper.map_entity(graph, year=year,
                                      signatory_capacity=capacity)
        return nar1.build_nar1_xml(data)
    except nar1_mapper.MappingError as exc:
        # The company can no longer be mapped at all — which is itself a change
        # since validation, and a decisive reason not to submit.
        raise DriftError(
            "the company record can no longer be mapped to a NAR1: "
            + "; ".join(exc.problems)
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise DriftError(
            f"the return could not be rebuilt from the company record: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


def differences_for(filing: dict) -> list:
    """The gate's answer: [] when the stored return still matches the company."""
    return compare(filing.get("request_xml") or "", current_xml_for(filing))
