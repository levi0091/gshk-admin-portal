"""Form NAR1 + Schedule 1/2, rendered from CR's own validated XML.

WHAT IT RENDERS FROM, and why it matters: `tpsi_filings.validated_xml` -- the
snapshot CR handed back at validateForm time -- never the live entity profile and
never our own `request_xml`. All three can differ: someone edits a director's
address after validation and before submission, and a preview drawn from
anywhere else would show the admin a document CR is not holding. CR also fills
several fields itself during validation (`compNameE`, `compNameC`, `coyStatus`,
`formCode`, `natureDesc`, `dateReturnMadeUp`), so its copy is strictly the more
complete one. The admin double-confirms an irreversible, chargeable submit on
the strength of this page, so it has to be the thing being submitted.

Deliberately NOT a facsimile of CR's printed form. This is a review document: an
admin checks that what CR validated is what they meant to file. Chasing pixel
fidelity with the government's own layout would buy nothing and break on every
CR revision.
"""
import html
import re
import xml.etree.ElementTree as ET
from io import BytesIO
from typing import NamedTuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------

#: MSung-Light is Adobe-CNS1 -- TRADITIONAL Chinese, which is what Hong Kong
#: company and person names are written in. STSong-Light (the other obvious
#: candidate) is Adobe-GB1, i.e. Simplified. Both encode UCS-2 identically at
#: this layer, so the difference shows only in the glyphs a reader picks, and
#: picking the Simplified face for a HK statutory return is the wrong default.
#:
#: This is a CID font referenced BY NAME, not embedded: reportlab ships the
#: metrics and the CMap, the viewer supplies the glyphs. That keeps a ~10MB CJK
#: TTF out of the repo and a system font package off Railway and CI. The cost is
#: that a viewer with no CJK font at all shows blanks -- acceptable for an
#: internal review document, and the reason `render_text` exists, so tests assert
#: on what the document SAYS rather than on how a given reader drew it.
CJK_FONT = "MSung-Light"

try:
    pdfmetrics.registerFont(UnicodeCIDFont(CJK_FONT))
    _CJK_AVAILABLE = True
except Exception:  # noqa: BLE001 - a missing CMap must not break the import
    _CJK_AVAILABLE = False

#: CJK ideographs and radicals, kana, Hangul, compatibility forms, and the
#: fullwidth block -- CR's own example carries a fullwidth bracket ("Business
#: Name (If any)" with U+FF08), so the last range is not optional.
#: Spelled as codepoints rather than literal characters so this line stays
#: readable, greppable and pure ASCII in the source.
_CJK_RANGES = (
    (0x2E80, 0x9FFF),   # radicals .. CJK unified ideographs (incl. kana)
    (0xA960, 0xA97F),   # Hangul Jamo Extended-A
    (0xAC00, 0xD7AF),   # Hangul syllables
    (0xF900, 0xFAFF),   # CJK compatibility ideographs
    (0xFE30, 0xFE4F),   # CJK compatibility forms
    (0xFF00, 0xFFEF),   # halfwidth and fullwidth forms
)
_CJK_RUN = re.compile(
    "[" + "".join(rf"\u{lo:04X}-\u{hi:04X}" for lo, hi in _CJK_RANGES) + "]+"
)

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

#: Repeating wrappers: <shareCapitals> holds many <shareCapital>. The parser has
#: to know these, or a single-child wrapper parses as a dict and the PDF shows
#: one row where the company has several -- or worse, a caller iterating it walks
#: the single officer's FIELDS instead of the officer list.
#:
#: Not derivable from nar1_schema.json by shape: <schedule1> also has exactly one
#: child element (<shares>) and is emphatically not a list. Hence an explicit
#: vocabulary, backstopped by the "more than one identically-named child" rule in
#: `_is_repeating` for anything CR adds later.
_REPEATING = frozenset({
    "shareCapitals", "indSecList", "corpSecList", "indDirList", "corpDirList",
    "resDirList", "shares", "shareHolderGrps", "allotteeRec",
})

_BRAND_INDIGO = colors.HexColor("#242C66")
_BORDER = colors.HexColor("#E2E4ED")
_BG_HEAD = colors.HexColor("#F5F6FB")
_MUTED = colors.HexColor("#7C80A3")


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _is_repeating(element) -> bool:
    """A wrapper whose value is a list, not a record.

    The named set first; then the structural fallback -- two or more children
    that all share one tag name can only be a repeat. That fallback deliberately
    does NOT fire on a single child, because a one-item wrapper is
    indistinguishable by shape from a plain container (<schedule1><shares>).
    """
    if _localname(element.tag) in _REPEATING:
        return True
    kids = list(element)
    return len(kids) > 1 and len({_localname(k.tag) for k in kids}) == 1


def _node(element) -> "dict | str":
    children = list(element)
    if not children:
        return (element.text or "").strip()
    out: dict = {}
    for child in children:
        name = _localname(child.tag)
        if _is_repeating(child):
            # The wrapper's value is the list of its children's values.
            out[name] = [_node(grandchild) for grandchild in child]
            continue
        value = _node(child)
        if name in out:
            existing = out[name]
            out[name] = (
                existing + [value] if isinstance(existing, list) else [existing, value]
            )
        else:
            out[name] = value
    return out


def _find_form_model(element):
    if _localname(element.tag) == "formModel":
        return element
    for child in element:
        found = _find_form_model(child)
        if found is not None:
            return found
    return None


def _fragment(xml: str):
    """Last resort: a bare <formModel> whose namespace prefix is not declared.

    CR's own payloads are whole SOAP envelopes and parse directly. This handles a
    formModel sliced out of one by something upstream, where the `cr:` prefix has
    been left dangling -- binding it to a throwaway URI is enough, because
    everything downstream matches on LOCAL names anyway.
    """
    match = re.search(r"<(\w+:)?formModel[\s/>]", xml)
    if not match:
        raise ValueError("no <formModel> in the validated payload")
    prefix = match.group(1) or ""
    close = f"</{prefix}formModel>"
    end = xml.find(close)
    if end == -1:
        raise ValueError("unterminated <formModel> in the validated payload")
    text = xml[match.start(): end + len(close)]
    if prefix:
        ns = prefix.rstrip(":")
        # Only bind it if the element does not already declare it -- injecting a
        # second xmlns:cr onto the same tag is a duplicate-attribute parse error.
        if f"xmlns:{ns}=" not in text.split(">", 1)[0]:
            text = text.replace(
                f"<{prefix}formModel", f'<{prefix}formModel xmlns:{ns}="urn:cr"', 1
            )
    try:
        return ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"unparseable <formModel>: {exc}") from exc


def parse_validated_xml(xml: str) -> dict:
    """CR's validated payload -> nested dicts/lists keyed by element name.

    Namespace-agnostic: request and response share one namespace convention, but
    the prefix is CR's to change, so every lookup is on the LOCAL name. That is
    also why the whole document is parsed and the formModel found by name rather
    than sliced out as text -- the byte-exact slicing in
    `filings._extract_eform` exists because a signature digest covers those exact
    bytes, and nothing here is signing anything.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        root = _fragment(xml)

    model = _find_form_model(root)
    if model is None:
        raise ValueError("no <formModel> in the validated payload")
    parsed = _node(model)
    return parsed if isinstance(parsed, dict) else {}


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _rich(value) -> str:
    """Escape for reportlab's mini-markup, and switch fonts across CJK runs.

    reportlab does no font fallback inside a Paragraph: a Helvetica run
    containing Chinese renders as nothing at all. Wrapping only the CJK runs
    keeps Latin in the document's own face instead of pushing every English name
    through a Chinese font.
    """
    text = "" if value is None else str(value)
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if not _CJK_AVAILABLE:
        return escaped
    return _CJK_RUN.sub(
        lambda m: f'<font name="{CJK_FONT}">{m.group(0)}</font>', escaped
    )


def _plain(markup: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", markup))


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

#: A4 less the 18mm side margins. Column widths are given as FRACTIONS of this,
#: so a column can never be specified wider than the page it has to fit on.
_CONTENT_W = 210 * mm - 36 * mm


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "nar1Title", parent=base["Title"], fontSize=15,
            textColor=_BRAND_INDIGO, spaceAfter=2 * mm, alignment=0,
        ),
        "note": ParagraphStyle(
            "nar1Note", parent=base["BodyText"], fontSize=7.5, leading=10,
            textColor=_MUTED,
        ),
        "h2": ParagraphStyle(
            "nar1H2", parent=base["Heading2"], fontSize=10.5,
            textColor=_BRAND_INDIGO, spaceBefore=5 * mm, spaceAfter=1.5 * mm,
        ),
        "cell": ParagraphStyle(
            "nar1Cell", parent=base["BodyText"], fontSize=7.5, leading=9.5,
            spaceBefore=0, spaceAfter=0,
        ),
        "head": ParagraphStyle(
            "nar1Head", parent=base["BodyText"], fontSize=7.5, leading=9.5,
            spaceBefore=0, spaceAfter=0, textColor=_BRAND_INDIGO,
            fontName="Helvetica-Bold",
        ),
    }


def _table(rows: list[list], fractions: list[float], styles: dict) -> Table:
    """Header row + body, every cell a Paragraph.

    Cells are Paragraphs rather than bare strings for one reason that matters: a
    bare string in a reportlab Table does not wrap. A Hong Kong address is
    routinely 80 characters and would run straight off the right edge of the page
    -- the exact "passes every test, unreadable on paper" failure this document
    exists to avoid.
    """
    widths = [f * _CONTENT_W for f in fractions]
    body = [[Paragraph(_rich(c), styles["head"]) for c in rows[0]]] + [
        [Paragraph(_rich(c), styles["cell"]) for c in row] for row in rows[1:]
    ]
    table = Table(body, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, _BORDER),
        ("BACKGROUND", (0, 0), (-1, 0), _BG_HEAD),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def _as_list(value) -> list:
    if value is None or value == "":
        return []
    return value if isinstance(value, list) else [value]


def _get(record, *keys) -> str:
    """First non-empty of several keys, as a string. Nested dicts never leak."""
    for key in keys:
        value = record.get(key) if isinstance(record, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _addr(addr) -> str:
    if not isinstance(addr, dict):
        return ""
    return ", ".join(
        part for part in (
            _get(addr, "flatFlrBlk"), _get(addr, "bldg"), _get(addr, "stEstLotVlg"),
            _get(addr, "dstCtyStatePostal"), _get(addr, "ctryRegion"),
        ) if part
    )


def _name(record: dict, *, corporate: bool) -> str:
    """One display name per party, English first with the Chinese beside it."""
    if corporate:
        english = _get(record, "corpEngName")
        chinese = _get(record, "corpChiName")
    else:
        english = " ".join(
            part for part in (
                _get(record, "indvEngSname", "indvSurname"),
                _get(record, "indvEngOname", "indvOtherName"),
            ) if part
        )
        chinese = _get(record, "indvChiName")
    return " / ".join(part for part in (english, chinese) if part) or "(no name given)"


_YES_NO = {"Y": "Yes", "N": "No"}
_LANGUAGES = {"E": "English", "C": "Chinese"}


def _pairs(spec, header=("Field", "Value")) -> list[list[str]]:
    """(label, value, always) -> table rows.

    `always=True` keeps a MANDATORY field visible even when it is empty. On a
    review document a blank statutory field is information -- it is the
    reviewer's cue that something is missing -- whereas a blank optional field is
    noise.
    """
    rows = [list(header)]
    rows.extend([label, value] for label, value, always in spec if value or always)
    return rows


def _return_rows(data: dict) -> list[list[str]]:
    return _pairs([
        # No "NAR1" fallback. CR fills formCode in during validation, so a blank
        # here means the payload never carried one -- a fact worth showing on a
        # document whose whole job is spotting what is missing. Defaulting the
        # field would let any other form code print as an annual return.
        ("Form", _get(data, "formCode"), True),
        ("Filing language",
         _LANGUAGES.get(_get(data, "language"), _get(data, "language")), True),
        ("Year of annual return", _get(data, "yearAnnualReturn"), True),
        ("Made up to", _get(data, "dateReturnMadeUp"), False),
        ("Financial statements period", " to ".join(
            p for p in (_get(data, "dateReturnFrom"), _get(data, "dateReturnTo")) if p
        ), False),
        ("Members without share capital", _get(data, "memberNumAtDateReturn"), False),
        ("Redelivery of document ref.", _get(data, "docReferenceNo"), False),
        ("Members listed in Schedule 1",
         _YES_NO.get(_get(data, "shareholderListedInSch1"), ""), False),
        ("Members listed in Schedule 2",
         _YES_NO.get(_get(data, "shareholderListedInSch2"), ""), False),
        ("Members listed on CD-ROM",
         _YES_NO.get(_get(data, "shareholderListedInCdrom"), ""), False),
    ])


def _company_rows(data: dict) -> list[list[str]]:
    return _pairs([
        ("Business Registration No.", _get(data, "brNo"), True),
        # compNameE/compNameC are filled in BY CR during validation, so they are
        # present in a real validated payload and absent from a request. Shown
        # unconditionally: a blank company name on a document about to be filed
        # is the single most important thing for a reviewer to notice.
        ("Company name (English)", _get(data, "compNameE"), True),
        ("Company name (Chinese)", _get(data, "compNameC"), False),
        ("Business name", _get(data, "brName"), False),
        ("Type of company", _get(data, "coyStatus"), False),
        ("Business nature", " ".join(
            p for p in (_get(data, "nature"), _get(data, "natureDesc")) if p
        ), False),
        ("Registered office", _addr(data.get("roAddr")), True),
        ("Email", _get(data, "emailAddr"), False),
        ("Telephone", _get(data, "telNo"), False),
        ("Mortgages and charges", _get(data, "totalAmountMortCharge"), False),
        ("Company records kept at", " - ".join(
            p for p in (_get(data, "companyRecord"), _get(data, "address")) if p
        ), False),
    ])


def _signatory_rows(data: dict) -> list[list[str]]:
    return _pairs([
        ("Signatory name", _get(data, "selectPersonName"), True),
        ("Signatory user ID", _get(data, "selectPersonId"), True),
        ("Capacity", _get(data, "selectCapacityDesc"), True),
        ("Date signed", _get(data, "signatoryDate"), True),
        # Present only when the signature is given by a body corporate -- the
        # open question for GSHK, and the block a reviewer must check hardest.
        ("Signing body corporate BR no.", _get(data, "selectAssoBrNo"), False),
        ("Individual signing for it", _get(data, "associatedPersonName"), False),
        ("Their user ID", _get(data, "associatedPersonId"), False),
        ("Their capacity", _get(data, "associatedCapacityDesc"), False),
    ], header=("Item", "Value"))


class _Section(NamedTuple):
    """One officer table, and which particulars nar1_schema.json puts on it.

    The columns follow the SECTION, not the officer's legal form. corpDir and
    corpSec are both bodies corporate and carry different fields: corpSec has a
    TCSP licence number, corpDir has none at all. Keying off `corporate` alone
    gave corporate directors a column that could never hold anything, and gave
    individual secretaries no licence column when the schema defines one.
    """
    heading: str
    key: str
    corporate: bool
    #: carries dirInd / altDirInd / altTo
    director: bool
    #: the licence-number field, or None where CR defines none for this section
    tcsp: str | None


_PARTY_SECTIONS = (
    _Section("Directors - natural persons", "indDirList", False, True, None),
    _Section("Directors - body corporate", "corpDirList", True, True, None),
    _Section("Reserve directors", "resDirList", False, False, None),
    _Section("Company secretary - natural person", "indSecList", False, False,
             "indvTcspNo"),
    _Section("Company secretary - body corporate", "corpSecList", True, False,
             "corpTcspNo"),
)


def _director_role(record: dict) -> str:
    """Substantive director, alternate, or both -- and whose alternate.

    Without this an alternate director prints identically to a substantive one,
    which misstates who actually holds the office on the register the admin is
    approving. The `altTo` name is half the particular: "an alternate" without
    "to whom" is not a statement of anything.
    """
    dir_ind = _get(record, "dirInd")
    alt_ind = _get(record, "altDirInd")
    alt_to = _get(record, "altTo")
    roles = []
    if dir_ind == "Y":
        roles.append("Director")
    if alt_ind == "Y":
        roles.append(
            f"Alternate director to {alt_to}" if alt_to
            else "Alternate director (alternate to not stated)"
        )
    if roles:
        return "; ".join(roles)
    if dir_ind or alt_ind:
        # Both flags carried, neither a Y. Report them rather than let the
        # section heading assert a role CR's payload is denying.
        return (f"Director: {_YES_NO.get(dir_ind, dir_ind or '-')}; "
                f"Alternate: {_YES_NO.get(alt_ind, alt_ind or '-')}")
    return "(not stated)"


def _other_names(person: dict) -> str:
    """Former and alias names, English beside Chinese, as `_name` does.

    Absent from every CR fixture, which is why they were being dropped without
    a single test noticing. A director filed under a former name the reviewer
    cannot see is a director the reviewer cannot check.
    """
    previous = " / ".join(p for p in (
        _get(person, "indvPrevEngName"), _get(person, "indvPrevChiName")) if p)
    alias = " / ".join(p for p in (
        _get(person, "indvAlsEngName"), _get(person, "indvAlsChiName")) if p)
    return "; ".join(p for p in (
        f"Formerly {previous}" if previous else "",
        f"Alias {alias}" if alias else "",
    ) if p)


def _tcsp(record: dict, licence_key: str) -> str:
    """The licence number, or the exemption being claimed instead of one.

    CR's rule (nar1_schema.json): `exempted` must be Y when the licence number
    is empty and N when it is given, and `reason` is required when exempted is
    Y. So a blank cell would hide a claim the company is making about itself --
    on CR's own example both secretaries claim exemption, and neither the claim
    nor its reason appeared anywhere on the page.
    """
    licence = _get(record, licence_key)
    exempted = _get(record, "exempted")
    reason = _get(record, "reason")
    parts = [licence] if licence else []
    if exempted == "Y":
        parts.append(f"Exempt: {reason}" if reason else "Exempt (no reason given)")
    elif exempted == "N" and not licence:
        # CR would reject this pairing. Say so rather than render an empty cell.
        parts.append("Not exempt, no licence no. given")
    return "; ".join(parts) or "(not stated)"


def _party_table(entries: list[dict], section: _Section, styles: dict) -> Table:
    """Columns assembled per section, widths normalised so they always fit.

    Weights rather than hand-picked fractions: the column set now varies with
    the section AND with the data, and a fraction list per combination is a
    table that runs off the page the first time someone adds a column.
    """
    columns: list[tuple[str, float, object]] = [
        ("Name", 26, lambda e: _name(e, corporate=section.corporate)),
    ]
    if section.director:
        columns.append(("Role", 17, _director_role))
    # Suppressed when no one in this table has one, following `% held`: a column
    # blank on every row reads as missing data rather than "not applicable".
    if not section.corporate and any(_other_names(e) for e in entries):
        columns.append(("Former / alias names", 18, _other_names))
    columns.append(("Address", 36, lambda e: _addr(e.get("stdAddress"))))
    if section.corporate:
        columns.append(("BR no.", 12, lambda e: _get(e, "corpBrNo")))
    else:
        columns.append(("Identification", 18, _identification))
    if section.tcsp:
        columns.append(
            ("TCSP licence", 18, lambda e, k=section.tcsp: _tcsp(e, k))
        )

    total = sum(weight for _, weight, _ in columns)
    rows = [[header for header, _, _ in columns]]
    rows.extend([cell(entry) for _, _, cell in columns] for entry in entries)
    return _table(rows, [weight / total for _, weight, _ in columns], styles)


def _identification(person: dict) -> str:
    """CR carries a partial HKID or a partial passport, never both in practice."""
    hkid = _get(person, "indvHkidNo")
    passport = _get(person, "indvPptNo")
    issuer = _get(person, "indvPptIssCtry")
    parts = []
    if hkid:
        parts.append(f"HKID {hkid}")
    if passport:
        parts.append(f"Passport {passport}" + (f" ({issuer})" if issuer else ""))
    return "; ".join(parts)


def _members_flow(data: dict, styles: dict) -> list:
    """Schedule 1 (non-listed) or Schedule 2 (listed) -- whichever CR carries.

    Both are rendered. A renderer that knows only `schedule1` silently omits the
    entire member register of a listed company, and an omission on a statutory
    return reads exactly like a company with no members.
    """
    flow: list = []
    for key, label in (("schedule1", "Schedule 1"), ("schedule2", "Schedule 2")):
        schedule = data.get(key)
        # isinstance, as _flow already does for share capitals and officers. An
        # empty <share/> parses to "" and share.get() then raises
        # AttributeError -- which is not ValueError, so it sails past the
        # endpoint's 422 handler and becomes the unhandled 500 that handler
        # exists to prevent.
        shares = [
            s for s in (_as_list(schedule.get("shares"))
                        if isinstance(schedule, dict) else [])
            if isinstance(s, dict)
        ]
        if not shares:
            continue
        flow.append(PageBreak())
        flow.append(Paragraph(f"{label} - particulars of members", styles["title"]))
        flow.append(Paragraph(
            "One row per allottee. Where a block of shares is held jointly "
            "(CR's shType 2), the number of shares is shown once against the "
            "first holder.",
            styles["note"],
        ))
        # perOfShares exists on Schedule 2 only. Carrying the column into a
        # Schedule 1 anyway leaves a permanently blank column, which on a
        # document whose whole job is spotting missing data reads as an error.
        groups = [
            g
            for share in shares
            for g in _as_list(share.get("shareHolderGrps"))
            if isinstance(g, dict)
        ]
        pct = any(_get(g, "perOfShares") for g in groups)

        for share in shares:
            rows = [
                ["Shareholder", "Type", "Shares allotted"]
                + (["% held"] if pct else [])
                + ["Address", "Remarks"]
            ]
            for group in _as_list(share.get("shareHolderGrps")):
                if not isinstance(group, dict):
                    continue
                allottees = [
                    a for a in _as_list(group.get("allotteeRec"))
                    if isinstance(a, dict)
                ]
                # A group with no readable allottee still carries a share
                # figure, and dropping the row would take that block of shares
                # off a document about share capital. _name() names it "(no
                # name given)".
                allottees = allottees or [{}]
                # shType is CR's own Shareholder Type -- 1 individual, 2 joint
                # (nar1_schema.json). Read it rather than infer the same fact
                # from list position, which mislabels the second allottee of a
                # shType 1 group as a joint holder. Position is the fallback
                # only where CR carries no shType at all.
                sh_type = _get(group, "shType")
                joint = sh_type == "2" if sh_type else len(allottees) > 1
                for index, allottee in enumerate(allottees):
                    corporate = _get(allottee, "allotteeType") == "C"
                    rows.append(
                        [
                            _name(allottee, corporate=corporate),
                            "Body corporate" if corporate else "Individual",
                            # A joint holding is ONE block of shares held by
                            # several people. Repeating the figure against each
                            # of them would multiply the company's issued
                            # capital on the page.
                            _get(group, "sharesAlloted") if index == 0
                            else ("(joint)" if joint else "(sole holding)"),
                        ]
                        + ([_get(group, "perOfShares") if index == 0 else ""]
                           if pct else [])
                        + [
                            _addr(allottee.get("allotteeAddr")),
                            _get(allottee, "remarks"),
                        ]
                    )
            widths = (
                [0.22, 0.11, 0.12, 0.08, 0.35, 0.12] if pct
                else [0.24, 0.12, 0.13, 0.39, 0.12]
            )
            flow.append(KeepTogether([
                Paragraph(
                    f"Class of shares: {_get(share, 'clsOfShares') or '(unnamed)'}",
                    styles["h2"],
                ),
                _table(rows, widths, styles),
            ]))
    return flow


def _flow(data: dict) -> list:
    styles = _styles()
    flow: list = [
        Paragraph("Form NAR1 - Annual Return", styles["title"]),
        Paragraph(
            "Rendered from the XML the Companies Registry returned at "
            "validation. This is the document CR is holding, not the current "
            "contents of the company profile.",
            styles["note"],
        ),
        Spacer(1, 3 * mm),
        Paragraph("Return particulars", styles["h2"]),
        _table(_return_rows(data), [0.34, 0.66], styles),
        Paragraph("Company particulars", styles["h2"]),
        _table(_company_rows(data), [0.34, 0.66], styles),
    ]

    caps = [c for c in _as_list(data.get("shareCapitals")) if isinstance(c, dict)]
    if caps:
        flow.append(Paragraph("Share capital", styles["h2"]))
        flow.append(_table(
            [["Class of shares", "Currency", "Shares issued", "Issued capital",
              "Paid up"]]
            + [[_get(c, "clsOfShares"), _get(c, "currency"),
                _get(c, "noOfShareIssuedOnThisCls"), _get(c, "issuedCapital"),
                _get(c, "paidUpCapital")] for c in caps],
            [0.28, 0.12, 0.20, 0.20, 0.20], styles,
        ))

    for section in _PARTY_SECTIONS:
        entries = [e for e in _as_list(data.get(section.key)) if isinstance(e, dict)]
        if not entries:
            continue
        flow.append(Paragraph(section.heading, styles["h2"]))
        flow.append(_party_table(entries, section, styles))

    flow.append(Paragraph("Signatory", styles["h2"]))
    flow.append(_table(_signatory_rows(data), [0.34, 0.66], styles))

    flow.extend(_members_flow(data, styles))
    return flow


def _footer(br_no: str, validated_at: str | None, stage: str | None):
    """Provenance on every page: which company, WHEN CR validated, and where the
    filing stands now.

    The when and the stage matter because the snapshot can outlive its own
    validation. `filings.validate` sets stage=validation_failed on a rejected
    re-validation but leaves `validated_xml` untouched, so the page above this
    footer -- headed "this is the document CR is holding" -- may be the previous
    attempt. Nothing else on the document dates it.
    """
    when = validated_at or "(time not recorded)"
    line = f"Form NAR1 preview - BR {br_no or '(none)'} - CR-validated {when}"
    if stage:
        line += f" - filing stage: {stage}"

    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(_MUTED)
        canvas.drawString(18 * mm, 10 * mm, line)
        canvas.drawRightString(210 * mm - 18 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    return draw


def render(
    xml: str, *, validated_at: str | None = None, stage: str | None = None
) -> bytes:
    """Form NAR1 + Schedule 1/2 as PDF bytes.

    `validated_at` and `stage` come off the filing row and are stamped in the
    footer. Both optional, because the XML alone is a complete document -- but
    the caller that has them should pass them: without a date, a snapshot CR
    has since rejected is indistinguishable from a fresh one.

    Raises ValueError when the payload carries no <formModel> -- better an error
    than a blank form that looks like a real NAR1.
    """
    data = parse_validated_xml(xml)
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=18 * mm,
        title=("Form NAR1 - " + (_get(data, "compNameE") or _get(data, "brNo"))).strip(),
        author="G-FlowDesk",
        subject="Annual Return (NAR1) - preview of the CR-validated filing",
    )
    footer = _footer(_get(data, "brNo"), validated_at, stage)
    document.build(_flow(data), onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def _table_text(table: Table) -> list[str]:
    out: list[str] = []
    for row in table._cellvalues:
        for cell in row:
            out.append(_plain(cell.text) if isinstance(cell, Paragraph) else str(cell))
    return out


def render_text(xml: str) -> str:
    """The same content as plain text.

    Exists for the tests: PDF bytes are opaque, and a PDF that renders
    beautifully while naming the wrong company is exactly the failure worth
    catching. This walks the SAME flowables `render` builds, so asserting on it
    asserts on what the document actually says.
    """
    parts: list[str] = []
    for item in _flow(parse_validated_xml(xml)):
        if isinstance(item, Paragraph):
            parts.append(_plain(item.text))
        elif isinstance(item, KeepTogether):
            for inner in item._content:
                if isinstance(inner, Paragraph):
                    parts.append(_plain(inner.text))
                elif isinstance(inner, Table):
                    parts.extend(_table_text(inner))
        elif isinstance(item, Table):
            parts.extend(_table_text(item))
    return "\n".join(parts)
