"""Fill CR's own Form NAR1 from the XML CR validated.

WHAT THIS REPLACES. `services/nar1_pdf.py` renders a branded table of the
fields in the validated XML, and its docstring defends that: "Deliberately NOT
a facsimile of CR's printed form." That was a fair call for the admin's
pre-submit check and the wrong document for the person it is actually shown to.
During Client Verification the portal emails a director a PDF and asks them to
approve their own company's statutory return. A director knows what Form NAR1
looks like — they have signed them for years. They cannot check a field table
against anything. So this fills the real form.

WHAT IT RENDERS FROM. `tpsi_filings.validated_xml` — the snapshot CR handed
back at validateForm time — never the live entity profile and never our own
`request_xml`. All three can differ: someone edits a director's address after
validation and before submission, and a document drawn from anywhere else would
show the client something CR is not holding.

WHAT THE XML DOES NOT CARRY, measured against a real validated filing on DEV
(T0001137, 2026-08-30): `coyStatus`, `nature` and `natureDesc` are ABSENT even
after validation, though the schema says CR fills them. So the company type —
which decides a tick in section 3, whether section 5 is completed, and whether
members go on Schedule 1 or Schedule 2 — cannot be read from the XML and is
passed in by the caller. Guessing it from the presence of a financial period
would be wrong for exactly the companies that matter.

Also measured there: `dateReturnMadeUp` comes back as **dd/mm/yyyy**, not the
ISO the schema's other dates use. `split_date` accepts both rather than
assuming, because getting it wrong silently swaps the day and the year on a
statutory return.

OVERFLOW IS NOT OPTIONAL. The printed form holds one natural-person secretary,
one natural-person director, two body-corporate directors, and two members per
schedule. Real companies exceed all of those. A truncated statutory return does
not merely look incomplete — it MISSTATES THE COMPANY, and it is a return
someone is being asked to approve. So every officer and member beyond the
printed capacity goes onto the continuation sheet CR provides for it, and
`_assert_nothing_dropped` re-counts the output against the input before the
bytes are returned.

THE NOTES ARE DROPPED. Pages 16-27 of the blank form are CR's printed guidance
for whoever completes it by hand. Twelve pages of that attached to a return a
client is being asked to read is noise.
"""
from __future__ import annotations

import io
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, NameObject, NumberObject, TextStringObject

from services.nar1_form import appearance
from services.nar1_form import field_map as fm
from services.tpsi.forms.cr_vocabularies import (
    HKG,
    display_country,
    display_district,
)

# update_page_form_field_values() builds a pypdf-native appearance stream for
# every field it touches, and warns whenever CR's subsetted form fonts cannot
# encode the value -- including plain ASCII, because those fonts are
# subsetted to only the glyphs CR's own printed form needs. That has nothing
# to do with NeedAppearances or with what a viewer draws: the warning fires
# regardless, one line per field, because pypdf always attempts to build the
# stream. Restored 2026-09-01 after Task 3 baked the actual text layer
# ourselves -- these particular streams are now built and then never used,
# so the corruption the warning describes cannot happen here, and its
# remedy (auto_regenerate=True) is the opposite of what this module wants:
# that would hand rendering back to the CR-subsetted fonts this block exists
# to stop depending on. Scoped to this one pypdf logger only -- it silences
# this specific message and nothing else.
logging.getLogger("pypdf.generic._appearance_stream").setLevel(logging.ERROR)

#: CR's blank form, COMMITTED BESIDE THIS MODULE rather than read from
#: `docs/`. It is a runtime dependency, not documentation: without it every
#: client-verification email fails. `docs/` is in .gitignore, so a copy living
#: there is on one laptop — absent from CI, absent from Railway, and absent
#: from any fresh clone. Read-only; never modified in place.
TEMPLATE = Path(__file__).resolve().parent / "form" / "NAR1_fillable.pdf"

#: Who CR contacts about the filing. GSHK, not the client, and the SAME on
#: every return GSHK files -- which is why it is a constant here rather than
#: something a caller has to remember to pass.
#:
#: Verbatim from GSHK's own filed NAR1 (Kanenas Holding Limited, 2026). It
#: previously carried the name and `no-reply@getstarted.hk` and nothing else,
#: so the presenter box rendered with an empty Address, Tel and Reference and
#: named a mailbox that does not accept replies -- on the one block of the
#: form whose whole purpose is to tell CR where to write back.
#:
#: `no-reply@` is the address the portal SENDS from (see CLAUDE.md); it is not
#: the address CR should answer. Those are different jobs and were conflated.
DEFAULT_PRESENTER = {
    "name": "Get Started HK Limited",
    "address": ("Suite C, Level 7, World Trust Tower, 50 Stanley Street, "
                "Central, Hong Kong"),
    "tel": "2813 7600",
    "email": "info@getstarted.hk",
}

#: What CR's own returns put in a box with nothing to report, rather than
#: leaving it blank -- on a statutory declaration an empty box reads as "not
#: answered" and a dash reads as "none". Taken from GSHK's filed specimen,
#: which uses BOTH and not interchangeably: "N/A" for a whole numbered section
#: that does not apply to this company, "-" for a particular that is absent
#: from a block otherwise filled in.
NONE_GIVEN = "-"
NOT_APPLICABLE = "N/A"


#: The sizes CR uses that are not `appearance.DEFAULT_SIZE`, keyed by the
#: field's name on the template. Read off a real filed return rather than off
#: the template's `/DA`, which is Acrobat's and disagrees: the BR number in the
#: header box is 14pt on EVERY page, and the company name in field 1 is 12pt.
#:
#: Built from field_map's own constants rather than a regex over field names.
#: `fill_1_P.6` is a BRN header and `fill_6_P.6` is a director's surname --
#: a pattern loose enough to catch every header also catches those.
def _br_number_fields() -> set[str]:
    groups = (fm.MAIN_1, fm.MAIN_2, fm.SECRETARY_INDIVIDUAL,
              fm.SECRETARY_CORPORATE, fm.DIRECTOR_INDIVIDUAL,
              fm.DIRECTOR_CORPORATE_HEADER, fm.RESERVE_DIRECTOR,
              fm.MEMBERS_AND_SIGNATURE,
              # NOT fm.SCHEDULE_1 / fm.SCHEDULE_2 -- those are row TUPLES.
              # `"br_number" in <tuple>` is False, so naming them here fails
              # silently and both Schedule pages print their BRN at 10pt.
              fm.SCHEDULE_1_HEADER, fm.SCHEDULE_2_HEADER)
    names = {group["br_number"] for group in groups if "br_number" in group}
    for page in range(fm.PAGE_SHEET_A, fm.PAGE_SHEET_E + 1):
        names.add(fm.sheet_header(page)["br_number"])
    return names


FIELD_SIZES = {name: 14.0 for name in _br_number_fields()}
FIELD_SIZES[fm.MAIN_1["company_name"]] = 12.0

#: A schedule's page numbers belong to the page FOOTER rather than to the
#: return, and CR fills them in the footer's own face and size -- Arial 8pt
#: regular, measured at 8.04pt on the specimen's Schedule 1, against the
#: 9.96pt Times New Roman Bold of the statutory values above it. They are the
#: only two values on the whole form CR does not set in Times.
FOOTER_SIZE = 8.0
FOOTER_FIELDS = frozenset(
    tuple(fm.SCHEDULE_1_PAGING.values()) + tuple(fm.SCHEDULE_2_PAGING.values())
)
FIELD_SIZES.update({name: FOOTER_SIZE for name in FOOTER_FIELDS})

#: The Latin face for the fields not set in the return's Times.
FIELD_FACES = {name: appearance.FONT_SANS for name in FOOTER_FIELDS}

#: The fields CR sets in the REGULAR face rather than bold. On a real filed
#: return every statutory value is bold and the presenter's block -- who filed
#: this, and where to write back -- is not. That contrast is how CR separates
#: the return's content from the administrative note identifying the filer, so
#: rendering the whole page bold loses a distinction the form is making.
#:
#: WEIGHT IS THE WHOLE OF IT. The block is set at the return's own 10pt: all
#: six of its values measure 9.96pt on the specimen, the same as the statutory
#: values above them. Rendering it a point smaller as well turned CR's
#: contrast into a footnote CR does not print.
REGULAR_WEIGHT_FIELDS = frozenset(
    fm.MAIN_1[key] for key in (
        "presenter_name", "presenter_address", "presenter_tel",
        "presenter_fax", "presenter_email", "presenter_reference",
    )
)


#: THE FIELDS CR CENTRES. Everything not named here is left-aligned.
#:
#: This does NOT come from the template's `/Q`, and must not be rebuilt from
#: it. Acrobat put `/Q 1` on 287 of the form's 298 text widgets, the business
#: name, the mortgages box, every officer's name and every address line among
#: them -- and CR's own filed return left-aligns all of those. Honouring `/Q`
#: put a director's surname in the middle of its box, which is the most
#: visible single difference between the two documents.
#:
#: There is no rule to derive: the same word, "Ordinary", is centred in
#: section 11's table and left-aligned in Schedule 1's header. It is CR's
#: layout, so every group below was read off the specimen and is listed.
def _centred_fields() -> set[str]:
    names = set(_br_number_fields())              # the header box, at 14pt
    names.add(fm.MAIN_1["company_name"])          # section 1
    # Sections 4 and 5 -- one digit-pair per ruled cell.
    names.update(fm.MAIN_1[key] for key in (
        "return_date_dd", "return_date_mm", "return_date_yyyy",
        "fin_period_from_dd", "fin_period_from_mm", "fin_period_from_yyyy",
        "fin_period_to_dd", "fin_period_to_mm", "fin_period_to_yyyy",
    ))
    # Sections 8 and 10. Section 7's email and section 9's mortgages total are
    # deliberately NOT here: CR sets "Nil" against the left of a 492pt box.
    names.update(fm.MAIN_2[key] for key in ("phone", "members_no_capital"))
    # Section 11 -- every cell of the table and of the Total row.
    for row in range(fm.SHARE_CAPITAL_ROWS):
        for column in ("class", "currency", "total_number", "total_amount",
                       "paid_up"):
            names.add(fm.share_capital(row, column))
    names.update(fm.SHARE_CAPITAL_TOTALS.values())
    # A registration or identity number in its own ruled cell, wherever an
    # officer block appears -- the main form and every continuation sheet.
    officer_blocks = (
        fm.SECRETARY_INDIVIDUAL, fm.SECRETARY_CORPORATE,
        fm.DIRECTOR_INDIVIDUAL, fm.RESERVE_DIRECTOR,
        *fm.DIRECTOR_CORPORATE,
        fm.SHEET_A, fm.SHEET_B, fm.SHEET_C, *fm.SHEET_D,
    )
    for block in officer_blocks:
        names.update(block[key]
                     for key in ("hkid_partial", "tcsp_licence",
                                 "own_br_number")
                     if key in block)
    # Page 8 -- the continuation-sheet counts and the signature block.
    names.update(fm.MEMBERS_AND_SIGNATURE[key] for key in (
        "count_sheet_a", "count_sheet_b", "count_sheet_c", "count_sheet_d",
        "count_sheet_e", "count_schedule_1", "count_schedule_2",
        "signed_name", "signed_date",
    ))
    # The schedules. `share_class` is deliberately absent -- see above.
    for header in (fm.SCHEDULE_1_HEADER, fm.SCHEDULE_2_HEADER):
        names.update(header[key] for key in (
            "return_date_dd", "return_date_mm", "return_date_yyyy",
            "br_number", "class_total_issued",
        ))
    for slot in (*fm.SCHEDULE_1, *fm.SCHEDULE_2):
        names.update(slot[key] for key in ("shares_held", "percentage")
                     if key in slot)
    names.update(FOOTER_FIELDS)
    # Every continuation sheet's own date-and-BR header.
    for page in range(fm.PAGE_SHEET_A, fm.PAGE_SHEET_E + 1):
        names.update(fm.sheet_header(page).values())
    return names


CENTRED_FIELDS = frozenset(_centred_fields())


class FormFillError(RuntimeError):
    """The return could not be rendered onto CR's form."""


# ---------------------------------------------------------------------------
# Reading the validated XML
# ---------------------------------------------------------------------------

def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


#: Wrappers whose value is a LIST, not a record. Spelled out because shape
#: alone cannot tell them apart: <schedule1> also has exactly one child element
#: and is emphatically not a list. Inherited from the renderer this replaces,
#: which learned the vocabulary the hard way.
_REPEATING = frozenset({
    "shareCapitals", "indSecList", "corpSecList", "indDirList", "corpDirList",
    "resDirList", "shares", "shareHolderGrps", "allotteeRec",
})


def _is_repeating(element) -> bool:
    if _localname(element.tag) in _REPEATING:
        return True
    kids = list(element)
    return len(kids) > 1 and len({_localname(k.tag) for k in kids}) == 1


def _to_dict(element):
    children = list(element)
    if not children:
        return (element.text or "").strip()
    if _is_repeating(element):
        return [_to_dict(child) for child in children]
    out = {}
    for child in children:
        name = _localname(child.tag)
        value = _to_dict(child)
        if name in out:
            existing = out[name]
            out[name] = (existing + [value] if isinstance(existing, list)
                         else [existing, value])
        else:
            out[name] = value
    return out


#: The validated XML is a BARE FRAGMENT with undeclared prefixes — `cr:` in
#: both request and validated forms, plus `ds:` XML-DSig in the validated one.
#: Forgetting the ds declaration fails 4,609 bytes in and reads like file
#: corruption rather than a missing namespace.
_WRAPPER = (
    '<root xmlns:cr="urn:cr" xmlns:ds="http://www.w3.org/2000/09/xmldsig#">'
    "{}</root>"
)


def parse_validated_xml(xml: str) -> dict:
    """CR's validated fragment as nested dicts and lists."""
    if not (xml or "").strip():
        raise FormFillError("no validated XML on this filing; nothing to render")
    try:
        root = ET.fromstring(_WRAPPER.format(xml))
    except ET.ParseError as exc:
        raise FormFillError(f"could not parse the validated XML: {exc}") from exc
    parsed = _to_dict(root)
    if not isinstance(parsed, dict):
        raise FormFillError("the validated XML did not parse to a record")
    found = _find_form_model(parsed)
    if found is None:
        raise FormFillError(
            "the validated XML carries no recognisable NAR1 form model "
            "(no brNo / compNameE / roAddr at any level)"
        )
    return found


#: Fields that only the form model has, used to recognise it.
_MODEL_MARKERS = ("brNo", "compNameE", "roAddr")


def _find_form_model(node, depth: int = 0):
    """Search for the level carrying the return itself.

    A plain "unwrap while there is exactly one child dict" loop does NOT work:
    a signed return is <submission><EForm>...</EForm><EFormSignatures>...
    </EFormSignatures></submission>, so the very first level already has TWO
    dict children and the loop stops on the wrapper. Measured on a real
    validated filing, whose top level parsed to {EForm, EFormSignatures}.
    """
    if depth > 6 or not isinstance(node, dict):
        return None
    if any(marker in node for marker in _MODEL_MARKERS):
        return node
    for value in node.values():
        if isinstance(value, dict):
            found = _find_form_model(value, depth + 1)
            if found is not None:
                return found
    return None


def _get(node, *path, default=""):
    """Walk a path, tolerating absent levels — CR omits empty branches."""
    cur = node
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    if isinstance(cur, (dict, list)):
        return default
    return (cur or "").strip() or default


def _node(node, *path):
    """Same walk, but for a sub-record rather than a scalar."""
    cur = node
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return {}
        cur = cur[key]
    return cur if isinstance(cur, dict) else {}


def _as_list(value):
    """CR emits one child bare and several as a list."""
    if value in (None, "", {}, []):
        return []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    return [value] if isinstance(value, dict) else []


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------

_ISO_DATE = re.compile(r"^(\d{4})-?(\d{2})-?(\d{2})$")
_HK_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")

#: Hong Kong keeps a fixed UTC+8 and has had no summer time since 1979, so a
#: fixed offset is EXACT here rather than an approximation -- and it needs no
#: `tzdata` wheel on the image, which a `ZoneInfo("Asia/Hong_Kong")` would on
#: both Windows and a slim Linux base. Same constant and same reason as
#: `services/tpsi/forms/nar1_mapper.py`.
_HKT = timezone(timedelta(hours=8))


def _hk_date(moment: datetime) -> str:
    """`moment` as the dd/mm/yyyy of the day it was in Hong Kong.

    A naive datetime is read as UTC, which is what Railway and Supabase both
    run and what `tpsi_filings.signed_at` is stored in. The conversion is the
    whole point: a return generated at 02:00 in the Hong Kong office is
    18:00 the previous day in UTC, and a statutory form dated the day before
    it was made is a small, permanent, printed lie.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(_HKT).strftime("%d/%m/%Y")


def signature_date(signed_on) -> str:
    """The date beside the signature, in the dd/mm/yyyy its boxes are labelled
    for.

    THIS REVERSES "blank when the caller supplies nothing" (Levi 2026-09-04).
    That rule was written because "a date printed beside an unsigned signature
    block would assert something untrue" -- but NEITHER caller ever supplied
    one, so every NAR1 the portal has produced went to a director, and would
    have gone to CR, with an empty Date box. On CR's own filed return that box
    is filled, and an empty one reads as an unfinished form rather than as a
    scrupulous abstention. So an absent value now means TODAY IN HONG KONG:
    the day this copy of the return was made.

    A real signing date still wins where one exists -- `tpsi_filings.signed_at`
    is passed by both callers once CR's PIN signing has succeeded -- so a
    return downloaded a week after it was signed carries the day it was signed,
    not the day it was printed.

    Accepts a datetime, a CR date in either of `split_date`'s two formats, or
    an ISO timestamp. Anything else falls back to today rather than to blank:
    blank is the failure being fixed here.
    """
    if isinstance(signed_on, datetime):
        return _hk_date(signed_on)
    text = str(signed_on or "").strip()
    if not text:
        return datetime.now(_HKT).strftime("%d/%m/%Y")
    # A plain date is already expressed in whatever terms the caller meant, so
    # it is taken verbatim -- shifting "2026-07-25" by a timezone would move a
    # date somebody typed. Only a TIMESTAMP gets converted.
    dd, mm, yyyy = split_date(text)
    if yyyy:
        return f"{dd}/{mm}/{yyyy}"
    try:
        return _hk_date(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return datetime.now(_HKT).strftime("%d/%m/%Y")


def split_date(value: str) -> tuple[str, str, str]:
    """A CR date into the form's DD, MM, YYYY boxes.

    BOTH formats, because CR uses both: `dateReturnMadeUp` came back as
    "01/01/2026" from a real validateForm, while the schema's other dates are
    ISO. Assuming one would silently transpose day and year on the other.

    Returns three empty strings for an absent or unrecognised date rather than
    raising — an optional date must leave three empty boxes, and a missing
    REQUIRED one is the caller's error to name.
    """
    text = (value or "").strip()
    iso = _ISO_DATE.match(text)
    if iso:
        year, month, day = iso.groups()
        return day, month, year
    hk = _HK_DATE.match(text)
    if hk:
        day, month, year = hk.groups()
        return day.zfill(2), month.zfill(2), year
    return "", "", ""


#: `company_type` values this module understands, and the box each ticks.
COMPANY_TYPES = ("private", "public", "guarantee")


def company_type_from_profile(value: str | None) -> str:
    """`entities.company_type` -> one of COMPANY_TYPES.

    Free text out of the Viewpoint ETL, and mostly ABSENT: measured on DEV
    2026-08-30, 5,987 of 5,998 entities carry NULL and the remaining 11 say
    "Private company limited by shares". So the default is "private", which is
    both the honest reading of GSHK's book and the safe one — it ticks the box
    that leaves section 5 empty and makes the section 16 statement, which is
    what a private company's return does.

    A caller who knows better should pass `company_type` to `render` directly.
    """
    text = (value or "").strip().lower()
    if "guarantee" in text:
        return "guarantee"
    # "public" must be checked after guarantee: a guarantee company is not a
    # public one, but its description can mention neither or both.
    if "public" in text or "listed" in text:
        return "public"
    return "private"


def _company_name(model: dict) -> str:
    """English and Chinese on one line, as CR's own specimen prints them."""
    parts = [_get(model, "compNameE"), _get(model, "compNameC")]
    return "  ".join(p for p in parts if p)


#: The presenter's Reference box, measured off CR's template: 176.9pt wide and
#: 14.0pt tall -- ONE line, of which 158.1pt is inside `appearance._INSET`.
#: `test_the_reference_box_is_the_width_the_fitter_assumes` re-measures it, so
#: a new template revision fails a test rather than quietly overflowing.
PRESENTER_REFERENCE_WIDTH = 158.1

#: The smallest the reference may be set. `layout()` will shrink a value to a
#: 4pt floor, which its own docstring calls a grey smear; nothing CR prints on
#: this form is smaller than the 8pt page footer. 7pt is the point below which
#: a reference stops being something a person can read back over the telephone
#: to CR, which is the only thing this box is for.
PRESENTER_REFERENCE_MIN_SIZE = 7.0

#: `NAR1/<year>/<company name>` (Levi 2026-09-04). GSHK's own handle on the
#: filing -- CR quotes it back on any correspondence about the return -- and it
#: was rendering EMPTY because `DEFAULT_PRESENTER` carries no reference and
#: nothing derived one. The year is the return's own made-up-to year, not the
#: calendar year: a 2026 return filed late in 2027 is still the 2026 return,
#: and the reference has to agree with the form it is printed on.
PRESENTER_REFERENCE_PREFIX = "NAR1"

#: What a shortened name ends with. Three ASCII full stops rather than U+2026:
#: `draw_value` raises on a codepoint the face cannot draw, and a reference is
#: not worth a chance of failing to render a whole statutory return over.
_ELLIPSIS = "..."


def _reference_fits(text: str) -> bool:
    """Whether `text` fits the Reference box at the smallest size it may use.

    Measured in the REGULAR face, because the presenter's block is the one
    group CR does not set in bold (`REGULAR_WEIGHT_FIELDS`), and measuring the
    bold one would shorten names that would have fitted.
    """
    appearance.register_fonts()
    return appearance.measure(
        text, PRESENTER_REFERENCE_MIN_SIZE, bold=False
    ) <= PRESENTER_REFERENCE_WIDTH


def _presenter_reference(model: dict, year: str) -> str:
    """`NAR1/<year>/<company name>`, shortened to fit its one-line box.

    The ENGLISH name, and the Chinese one only when there is no English: the
    box holds about 46 characters at the floor size and `_company_name`'s
    "English  中文" pair would be truncated to the point of naming neither.

    The NAME is what gets shortened, never the prefix -- "NAR1/2026/" is what
    makes this a reference rather than a company name, and a reference missing
    its year is worse than one missing the last word of "... HOLDINGS LIMITED".
    Whole words go first, so the result still reads as a name.
    """
    name = (_get(model, "compNameE") or _get(model, "compNameC") or "").strip()
    # A return with no made-up-to date is malformed and `_assert_nothing_dropped`
    # will say so; the reference should not be the thing that fails first.
    prefix = f"{PRESENTER_REFERENCE_PREFIX}/{year or datetime.now(_HKT).year}/"
    if not name:
        return prefix.rstrip("/")
    if _reference_fits(prefix + name):
        return prefix + name

    words = name.split()
    while len(words) > 1:
        words.pop()
        candidate = f"{prefix}{' '.join(words)}{_ELLIPSIS}"
        if _reference_fits(candidate):
            return candidate
    # One word wider than the whole box -- a Chinese name, or a run-on. Cut it
    # a character at a time rather than give up and print nothing.
    stem = words[0]
    while stem:
        stem = stem[:-1]
        candidate = f"{prefix}{stem}{_ELLIPSIS}"
        if _reference_fits(candidate):
            return candidate
    return prefix.rstrip("/")


# --- numbers ---------------------------------------------------------------
#
# CR transmits a bare numeral and PRINTS it grouped: its own return shows
# "10,000" shares and "10,000.00" of capital where the XML carries "10000"
# for both. Rendering the raw string made a five-figure share capital read as
# "10000" and made the count and the amount indistinguishable at a glance --
# which is exactly the pair a director is being asked to check.

def _decimal(value: str):
    """`value` as a Decimal, or None if it is not a plain number.

    None is the "leave it alone" signal. These fields have already been
    accepted by CR, so a value this cannot parse is one to print verbatim, not
    one to blank or to guess at.
    """
    text = (value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def format_count(value: str) -> str:
    """A share COUNT: grouped, and never given decimals. "10000" -> "10,000"."""
    number = _decimal(value)
    if number is None:
        return (value or "").strip()
    if number == number.to_integral_value():
        return f"{number.to_integral_value():,}"
    return f"{number:,}"


def format_amount(value: str) -> str:
    """A money AMOUNT: grouped, and always to two decimals.

    "10000" -> "10,000.00". The decimals are the point: they are what
    distinguishes the Total Amount column from the Total Number column beside
    it when both hold the same figure, which is the ordinary case for a
    company whose shares were issued at $1.
    """
    number = _decimal(value)
    if number is None:
        return (value or "").strip()
    return f"{number.quantize(Decimal('0.01')):,}"


def _address(node: dict) -> dict:
    """CR's stdAddress/roAddr/allotteeAddr block. One shape, three names.

    The district and the country are turned back into the names CR PRINTS.
    Both travel as codes -- "CENTRAL", "SWE" -- and rendering the code put
    block capitals on the form where GSHK's own specimen reads "Central" and
    "Sweden". The district is only a code for a Hong Kong address; everywhere
    else the column is free text and is left exactly as it stands.
    """
    country_code = _get(node, "ctryRegion")
    district = _get(node, "dstCtyStatePostal")
    return {
        "flat_floor": _get(node, "flatFlrBlk"),
        "building": _get(node, "bldg"),
        "street": _get(node, "stEstLotVlg"),
        "district_city_state": (display_district(district)
                                if country_code.upper() == HKG else district),
        "country": display_country(country_code),
    }


def _yes(value: str) -> bool:
    return (value or "").strip().upper() == "Y"


# ---------------------------------------------------------------------------
# Block writers — one per repeated shape on the form
# ---------------------------------------------------------------------------

def _mark_absent(values: dict, block: dict, keys) -> None:
    """Write "-" into the named boxes of a block that have nothing in them.

    ONLY EVER CALLED ON A BLOCK THAT HAS CONTENT. CR's form is static, so a
    company with no natural-person secretary still files page 3 -- and that
    page is BLANK on GSHK's specimen, not a column of dashes. A dash means
    "this officer has no Chinese name"; a blank page means "there is no such
    officer", and the two must not be confused on a statutory return.
    """
    for key in keys:
        name = block.get(key)
        if name and not values.get(name):
            values[name] = NONE_GIVEN


#: The particulars GSHK's specimen dashes when a person or body has none.
#: Deliberately NOT every empty box in the block: the free-text "Reason" for
#: holding no TCSP licence and a member's "Remarks" are left blank there,
#: because an empty prose box already reads as "nothing to say" while an empty
#: NAME box reads as an omission.
_ABSENT_INDIVIDUAL = ("name_zh", "prev_name_zh", "prev_name_en", "alias_zh",
                      "alias_en", "addr_flat_floor", "addr_building",
                      "hkid_partial", "passport_country", "passport_partial",
                      "alternate_to")
_ABSENT_CORPORATE = ("name_zh", "addr_flat_floor", "addr_building",
                     "alternate_to")
_ABSENT_MEMBER = ("name_zh", "name_en_corp", "surname_en", "other_names_en",
                  "addr_flat_floor", "addr_building")


def _individual_officer(block: dict, person: dict, *, hk_only: bool) -> dict:
    """s12A / s13A / s13C and their continuation sheets.

    `hk_only` distinguishes the secretary — whose correspondence address must
    be in Hong Kong and whose fourth line is a plain District — from the
    director family, whose address may be overseas and whose fourth line is
    CR's combined District/City/Province/State/Postal Code.
    """
    address = _address(_node(person, "stdAddress"))
    values = {
        block["name_zh"]: _get(person, "indvChiName"),
        block["surname_en"]: _get(person, "indvEngSname"),
        block["other_names_en"]: _get(person, "indvEngOname"),
        block["prev_name_zh"]: _get(person, "indvPrevChiName"),
        block["prev_name_en"]: _get(person, "indvPrevEngName"),
        block["alias_zh"]: _get(person, "indvAlsChiName"),
        block["alias_en"]: _get(person, "indvAlsEngName"),
        block["addr_flat_floor"]: address["flat_floor"],
        block["addr_building"]: address["building"],
        block["addr_street"]: address["street"],
        block["email"]: _get(person, "indvEmailAddr"),
        block["hkid_partial"]: _get(person, "indvHkidNo"),
        block["passport_country"]: display_country(
            _get(person, "indvPptIssCtry")),
        block["passport_partial"]: _get(person, "indvPptNo"),
    }
    if hk_only:
        values[block["addr_district"]] = address["district_city_state"]
    else:
        values[block["addr_district_city_state"]] = address["district_city_state"]
        values[block["addr_country"]] = address["country"]

    if "tcsp_licence" in block:
        values[block["tcsp_licence"]] = _get(person, "indvTcspNo")
        if _yes(_get(person, "exempted")):
            values[block["tcsp_not_required"]] = fm.CHECKBOX_ON
            values[block["tcsp_reason"]] = _get(person, "reason")

    if "capacity_director" in block:
        if _yes(_get(person, "dirInd")):
            values[block["capacity_director"]] = fm.CHECKBOX_ON
        if _yes(_get(person, "altDirInd")):
            values[block["capacity_alternate"]] = fm.CHECKBOX_ON
            values[block["alternate_to"]] = _get(person, "altTo")
    _mark_absent(values, block, _ABSENT_INDIVIDUAL)
    return values


def _corporate_officer(block: dict, body: dict, *, hk_only: bool) -> dict:
    """s12B / s13B and their continuation sheets."""
    address = _address(_node(body, "stdAddress"))
    values = {
        block["name_zh"]: _get(body, "corpChiName"),
        block["name_en"]: _get(body, "corpEngName"),
        block["addr_flat_floor"]: address["flat_floor"],
        block["addr_building"]: address["building"],
        block["addr_street"]: address["street"],
        block["email"]: _get(body, "corpEmailAddr"),
        block["own_br_number"]: _get(body, "corpBrNo"),
    }
    if hk_only:
        values[block["addr_district"]] = address["district_city_state"]
    else:
        values[block["addr_district_city_state"]] = address["district_city_state"]
        values[block["addr_country"]] = address["country"]

    if "tcsp_licence" in block:
        values[block["tcsp_licence"]] = _get(body, "corpTcspNo")
        if _yes(_get(body, "exempted")):
            values[block["tcsp_not_required"]] = fm.CHECKBOX_ON
            values[block["tcsp_reason"]] = _get(body, "reason")

    if "capacity_director" in block:
        if _yes(_get(body, "dirInd")):
            values[block["capacity_director"]] = fm.CHECKBOX_ON
        if _yes(_get(body, "altDirInd")):
            values[block["capacity_alternate"]] = fm.CHECKBOX_ON
            values[block["alternate_to"]] = _get(body, "altTo")
    _mark_absent(values, block, _ABSENT_CORPORATE)
    return values


def _member(block: dict, allottee: dict, group: dict, *, listed: bool) -> dict:
    """One member row on Schedule 1 or 2.

    `allotteeType` is "I" for an individual and "C" for a body corporate, and
    they use DIFFERENT boxes: a company's name goes in the single "Name in
    English" line, not in the surname box.
    """
    address = _address(_node(allottee, "allotteeAddr"))
    corporate = (_get(allottee, "allotteeType") or "I").upper() == "C"
    values = {
        block["shares_held"]: format_count(_get(group, "sharesAlloted")),
        block["addr_flat_floor"]: address["flat_floor"],
        block["addr_building"]: address["building"],
        block["addr_street"]: address["street"],
        block["addr_city"]: address["district_city_state"],
        block["addr_country"]: address["country"],
        block["remarks"]: _get(allottee, "remarks"),
    }
    if corporate:
        values[block["name_zh"]] = _get(allottee, "corpChiName")
        values[block["name_en_corp"]] = _get(allottee, "corpEngName")
    else:
        values[block["name_zh"]] = _get(allottee, "indvChiName")
        values[block["surname_en"]] = _get(allottee, "indvSurname")
        values[block["other_names_en"]] = _get(allottee, "indvOtherName")
    # shType 2 = joint shareholder.
    if _get(group, "shType") == "2":
        values[block["jointly_held"]] = fm.CHECKBOX_ON
    if listed and "percentage" in block:
        values[block["percentage"]] = _get(group, "percentage")
    _mark_absent(values, block, _ABSENT_MEMBER)
    return values


# ---------------------------------------------------------------------------
# Page assembly
# ---------------------------------------------------------------------------

class _Pages:
    """Output pages in order, each a (template page, values) pair.

    Values are accumulated rather than written as they are computed because a
    continuation sheet is a COPY of a template page: the same field names
    appear on every copy, so each copy needs its own value set.
    """

    def __init__(self):
        self.items: list[tuple[int, dict]] = []

    def add(self, template_page: int, values: dict) -> None:
        self.items.append((template_page, {
            k: v for k, v in values.items() if v not in (None, "", {})
        }))

    def count_of(self, template_page: int) -> int:
        return sum(1 for page, _ in self.items if page == template_page)


def _chunk(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _share_capital_totals(capitals: list[dict]) -> dict:
    """Section 11's "總數 Total" row: the four boxes under the class rows.

    THIS ROW WAS NEVER FILLED. `field_map.SHARE_CAPITAL_TOTALS` has existed
    since the map was written and nothing referenced it, so every generated
    return showed its share classes above an empty Total -- on the section a
    director checks most closely, and beside a specimen that fills it.

    The three totals are SUMMED from the class rows rather than read from the
    XML, because CR's NAR1 schema carries no total: the printed form derives
    it, and so must this. A class whose figure will not parse makes the whole
    column blank rather than a total that silently omits it -- an
    under-reported share capital is a misstatement, and an absent one is
    visibly absent.

    The currency box is filled only when every class shares one currency. A
    company with an HKD class and a USD class has no single total to state,
    and CR's one-cell Total row cannot express one; the amounts are dropped
    with it for the same reason, while the share COUNT still totals because a
    share is a share whatever it was paid for in.
    """
    if not capitals:
        return {}
    totals: dict[str, str] = {}
    counts = [_decimal(_get(c, "noOfShareIssuedOnThisCls")) for c in capitals]
    if all(n is not None for n in counts):
        totals[fm.SHARE_CAPITAL_TOTALS["total_number"]] = \
            format_count(str(sum(counts)))

    currencies = {_get(c, "currency") for c in capitals}
    if len(currencies) != 1 or not next(iter(currencies)):
        return totals
    totals[fm.SHARE_CAPITAL_TOTALS["currency"]] = next(iter(currencies))
    for column, tag in (("total_amount", "issuedCapital"),
                        ("paid_up", "paidUpCapital")):
        amounts = [_decimal(_get(c, tag)) for c in capitals]
        if all(a is not None for a in amounts):
            totals[fm.SHARE_CAPITAL_TOTALS[column]] = \
                format_amount(str(sum(amounts)))
    return totals


def _compose(model: dict, *, company_type: str, presenter: dict,
             signed_on: str = "") -> _Pages:
    """Lay the return out across CR's pages, overflowing where it must."""
    pages = _Pages()
    br_number = _get(model, "brNo")
    # The date beside the signature. NOT in the validated XML -- CR hands none
    # back -- so it is the caller's to supply, and TODAY IN HONG KONG when they
    # supply nothing. See `signature_date`: it used to be blank, and blank is
    # what every return the portal has ever produced carried.
    signed_date = signature_date(signed_on)
    dd, mm, yyyy = split_date(_get(model, "dateReturnMadeUp"))
    from_dd, from_mm, from_yyyy = split_date(_get(model, "dateReturnFrom"))
    to_dd, to_mm, to_yyyy = split_date(_get(model, "dateReturnTo"))
    ro = _address(_node(model, "roAddr"))

    # ---- page 1 ----------------------------------------------------------
    m1 = fm.MAIN_1
    page1 = {
        m1["br_number"]: br_number,
        m1["company_name"]: _company_name(model),
        m1["business_name"]: _get(model, "brName") or NOT_APPLICABLE,
        m1["business_nature_code"]: _get(model, "nature"),
        m1["business_nature_desc"]: _get(model, "natureDesc"),
        m1["return_date_dd"]: dd,
        m1["return_date_mm"]: mm,
        m1["return_date_yyyy"]: yyyy,
        m1["ro_flat_floor_block"]: ro["flat_floor"],
        m1["ro_building"]: ro["building"],
        m1["ro_street"]: ro["street"],
        m1["ro_district"]: ro["district_city_state"],
        m1["presenter_name"]: presenter.get("name", ""),
        m1["presenter_address"]: presenter.get("address", ""),
        m1["presenter_tel"]: presenter.get("tel", ""),
        m1["presenter_fax"]: presenter.get("fax", ""),
        m1["presenter_email"]: presenter.get("email", ""),
        # Derived, not blank, and derived from THIS return: the year is the
        # one in section 4 above it. A caller that keeps its own reference
        # scheme can still pass one.
        m1["presenter_reference"]: (presenter.get("reference")
                                    or _presenter_reference(model, yyyy)),
        m1[f"type_{company_type}"]: fm.CHECKBOX_ON,
    }
    # "A private company needs not complete this section" -- the form says so
    # on section 5 itself. Filling it anyway would be a statement about
    # financial statements that a private company does not deliver.
    #
    # NOT LEFT BLANK EITHER. GSHK's specimen writes "N/A" across the section,
    # in the month box of each date group, so the reader can tell "this
    # company does not deliver financial statements" from "somebody forgot the
    # accounting period". The day and year boxes stay empty, as they do there.
    if company_type != "private":
        page1.update({
            m1["fin_period_from_dd"]: from_dd,
            m1["fin_period_from_mm"]: from_mm,
            m1["fin_period_from_yyyy"]: from_yyyy,
            m1["fin_period_to_dd"]: to_dd,
            m1["fin_period_to_mm"]: to_mm,
            m1["fin_period_to_yyyy"]: to_yyyy,
        })
    else:
        page1[m1["fin_period_from_mm"]] = NOT_APPLICABLE
        page1[m1["fin_period_to_mm"]] = NOT_APPLICABLE
    pages.add(fm.PAGE_MAIN_1, page1)

    # ---- page 2 ----------------------------------------------------------
    m2 = fm.MAIN_2
    page2 = {
        m2["br_number"]: br_number,
        m2["email_address"]: _get(model, "emailAddr") or NONE_GIVEN,
        m2["phone"]: _get(model, "telNo"),
        # The form asks for a stated nil rather than a blank: on a statutory
        # declaration an empty box reads as "not answered". Spelt "Nil" as
        # GSHK's own return spells it, not "NIL".
        m2["mortgages_total"]:
            format_amount(_get(model, "totalAmountMortCharge")) or "Nil",
        # Section 10 is for a company with NO share capital, so on the returns
        # this portal files it is nearly always the dash.
        m2["members_no_capital"]:
            format_count(_get(model, "memberNumAtDateReturn")) or NONE_GIVEN,
    }
    capitals = _as_list(_node(model, "shareCapitals").get("shareCapital")) \
        or _as_list(model.get("shareCapitals"))
    if len(capitals) > fm.SHARE_CAPITAL_ROWS:
        # CR provides no continuation sheet for section 11, so a company with
        # more classes than rows cannot be shown truthfully on this form --
        # and must not be shown untruthfully.
        raise FormFillError(
            f"this company has {len(capitals)} share classes and CR's printed "
            f"section 11 holds {fm.SHARE_CAPITAL_ROWS}, with no continuation "
            f"sheet for it. The return cannot be rendered on the official form."
        )
    for row, capital in enumerate(capitals):
        page2[fm.share_capital(row, "class")] = _get(capital, "clsOfShares")
        page2[fm.share_capital(row, "currency")] = _get(capital, "currency")
        page2[fm.share_capital(row, "total_number")] = \
            format_count(_get(capital, "noOfShareIssuedOnThisCls"))
        page2[fm.share_capital(row, "total_amount")] = \
            format_amount(_get(capital, "issuedCapital"))
        page2[fm.share_capital(row, "paid_up")] = \
            format_amount(_get(capital, "paidUpCapital"))
    page2.update(_share_capital_totals(capitals))
    pages.add(fm.PAGE_MAIN_2, page2)

    # ---- officers, with overflow -----------------------------------------
    ind_secs = _as_list(model.get("indSecList"))
    corp_secs = _as_list(model.get("corpSecList"))
    ind_dirs = _as_list(model.get("indDirList"))
    corp_dirs = _as_list(model.get("corpDirList"))
    res_dirs = _as_list(model.get("resDirList"))

    # CR's NAR1 is a STATIC form: a section's page is filed whether or not the
    # section has content. The reference return carries an empty natural-person
    # secretary page, an empty body-corporate director page and an empty
    # reserve-director page, and files all three.
    #
    # These used to be conditional, so a typical private company rendered six
    # pages instead of nine and every section below the gap moved. The client
    # verification email names pages ("Page 5: Director's details"), so a page
    # set that shifts with the officer mix points the reader at the wrong
    # section. Continuation sheets stay conditional below -- those really are
    # overflow, and CR's own form says so.
    if ind_secs:
        values = _individual_officer(fm.SECRETARY_INDIVIDUAL, ind_secs[0],
                                     hk_only=True)
    else:
        values = {}
    values[fm.SECRETARY_INDIVIDUAL["br_number"]] = br_number
    pages.add(fm.PAGE_SECRETARY_INDIVIDUAL, values)

    if corp_secs:
        values = _corporate_officer(fm.SECRETARY_CORPORATE, corp_secs[0],
                                    hk_only=True)
    else:
        values = {}
    values[fm.SECRETARY_CORPORATE["br_number"]] = br_number
    pages.add(fm.PAGE_SECRETARY_CORPORATE, values)

    if ind_dirs:
        values = _individual_officer(fm.DIRECTOR_INDIVIDUAL, ind_dirs[0],
                                     hk_only=False)
    else:
        values = {}
    values[fm.DIRECTOR_INDIVIDUAL["br_number"]] = br_number
    pages.add(fm.PAGE_DIRECTOR_INDIVIDUAL, values)

    values = {fm.DIRECTOR_CORPORATE_HEADER["br_number"]: br_number}
    for slot, body in zip(fm.DIRECTOR_CORPORATE,
                          corp_dirs[:fm.DIRECTOR_CORPORATE_SLOTS]):
        values.update(_corporate_officer(slot, body, hk_only=False))
    pages.add(fm.PAGE_DIRECTOR_CORPORATE, values)

    if res_dirs:
        values = _individual_officer(fm.RESERVE_DIRECTOR, res_dirs[0],
                                     hk_only=False)
    else:
        values = {}
    values[fm.RESERVE_DIRECTOR["br_number"]] = br_number
    pages.add(fm.PAGE_RESERVE_DIRECTOR, values)

    def sheet_header_values(page_no):
        head = fm.sheet_header(page_no)
        return {
            head["br_number"]: br_number,
            head["return_date_dd"]: dd,
            head["return_date_mm"]: mm,
            head["return_date_yyyy"]: yyyy,
        }

    for extra in ind_secs[1:]:
        values = sheet_header_values(fm.PAGE_SHEET_A)
        values.update(_individual_officer(fm.SHEET_A, extra, hk_only=True))
        pages.add(fm.PAGE_SHEET_A, values)
    for extra in corp_secs[1:]:
        values = sheet_header_values(fm.PAGE_SHEET_B)
        values.update(_corporate_officer(fm.SHEET_B, extra, hk_only=True))
        pages.add(fm.PAGE_SHEET_B, values)
    for extra in ind_dirs[1:]:
        values = sheet_header_values(fm.PAGE_SHEET_C)
        values.update(_individual_officer(fm.SHEET_C, extra, hk_only=False))
        pages.add(fm.PAGE_SHEET_C, values)
    for pair in _chunk(corp_dirs[fm.DIRECTOR_CORPORATE_SLOTS:], fm.SHEET_D_SLOTS):
        values = sheet_header_values(fm.PAGE_SHEET_D)
        for slot, body in zip(fm.SHEET_D, pair):
            values.update(_corporate_officer(slot, body, hk_only=False))
        pages.add(fm.PAGE_SHEET_D, values)

    # ---- members, with overflow ------------------------------------------
    #
    # A LISTED company reports members on Schedule 2 and only those holding at
    # least 5% of a class; a non-listed one reports every member on Schedule 1.
    # CR keeps both under <schedule1> in the XML regardless, so the company
    # type -- not the element name -- decides which sheet is printed.
    listed = company_type == "public"
    schedule_page = fm.PAGE_SCHEDULE_2 if listed else fm.PAGE_SCHEDULE_1
    schedule_slots = fm.SCHEDULE_2 if listed else fm.SCHEDULE_1
    schedule_head = fm.SCHEDULE_2_HEADER if listed else fm.SCHEDULE_1_HEADER
    schedule_paging = fm.SCHEDULE_2_PAGING if listed else fm.SCHEDULE_1_PAGING

    rows = []
    for share in _as_list(_node(model, "schedule1").get("shares")):
        share_class = _get(share, "clsOfShares")
        total = _get(share, "noOfShareIssuedOnThisCls")
        for group in _as_list(share.get("shareHolderGrps")):
            for allottee in _as_list(group.get("allotteeRec")):
                rows.append((share_class, total, group, allottee))

    # ALWAYS at least one chunk, even with zero members. `_chunk(rows, ...)`
    # on an empty list yields nothing, which used to drop the Schedule page
    # entirely -- an 8-page document that STILL ticked "members are listed on
    # Schedule 1/2" on page 8, pointing at a sheet that was not in the file.
    # CR's form is static the same way pages 3-7 are (see "CR'S FORM IS
    # STATIC" below): the schedule is filed whether or not it has rows.
    for chunk in (list(_chunk(rows, fm.SCHEDULE_SLOTS)) or [()]):
        values = {
            schedule_head["br_number"]: br_number,
            schedule_head["return_date_dd"]: dd,
            schedule_head["return_date_mm"]: mm,
            schedule_head["return_date_yyyy"]: yyyy,
        }
        if chunk:
            values[schedule_head["share_class"]] = chunk[0][0]
            values[schedule_head["class_total_issued"]] = \
                format_count(chunk[0][1])
        for slot, (_cls, _total, group, allottee) in zip(schedule_slots, chunk):
            values.update(_member(slot, allottee, group, listed=listed))
        pages.add(schedule_page, values)

    schedule_count = pages.count_of(schedule_page)
    # "Page __ of __" on every schedule sheet, so a page separated from the
    # bundle still says how many there were.
    numbered = 0
    for page_no, values in pages.items:
        if page_no == schedule_page:
            numbered += 1
            values[schedule_paging["page_no"]] = str(numbered)
            values[schedule_paging["page_of"]] = str(schedule_count)

    # ---- page 8 ----------------------------------------------------------
    ms = fm.MEMBERS_AND_SIGNATURE
    page8 = {
        ms["br_number"]: br_number,
        ms["members_in_schedule_2" if listed else "members_in_schedule_1"]:
            fm.CHECKBOX_ON,
        ms["signed_name"]: _get(model, "selectPersonName"),
        ms["signed_date"]: signed_date,
        # s15 is "the address where the company's records are kept IF NOT at
        # the registered office". The validated XML carries no such address --
        # by not carrying one it says they are kept at the registered office --
        # so both cells state that rather than trailing off blank.
        ms["records_description"]: NOT_APPLICABLE,
        ms["records_address"]: NOT_APPLICABLE,
    }
    if company_type == "private":
        page8[ms["statement_private"]] = fm.CHECKBOX_ON
    # ZERO IS AN ANSWER HERE. "This Return includes the following Continuation
    # Sheet(s)" is a count of what is attached, and GSHK's specimen writes a 0
    # in each of the five boxes rather than leaving them empty -- a blank
    # count row reads as an unanswered question about whether pages are
    # missing from the bundle.
    for name, page_no in (("count_sheet_a", fm.PAGE_SHEET_A),
                          ("count_sheet_b", fm.PAGE_SHEET_B),
                          ("count_sheet_c", fm.PAGE_SHEET_C),
                          ("count_sheet_d", fm.PAGE_SHEET_D),
                          ("count_sheet_e", fm.PAGE_SHEET_E)):
        page8[ms[name]] = str(pages.count_of(page_no))
    page8[ms["count_schedule_1"]] = str(0 if listed else schedule_count)
    page8[ms["count_schedule_2"]] = str(schedule_count if listed else 0)

    pages.add(fm.PAGE_MEMBERS_AND_SIGNATURE, page8)

    # CR'S OWN ORDER, which is simply ascending page number: the main form
    # 1-8, then Schedule 1 and 2, then Continuation Sheets A-E. Pages are
    # BUILT in a different order (page 8 needs the sheet counts, so it cannot
    # be composed until the sheets exist), and shipping them in build order
    # put the continuation sheets ahead of the schedules -- a document CR
    # prints one way and the client reads another.
    #
    # A STABLE sort, which matters: several pages share a template number
    # (three Sheet C copies, two Schedule 1 pages) and their order among
    # themselves is the order the officers and members were laid out in.
    pages.items.sort(key=lambda item: item[0])
    return pages


def _assert_nothing_dropped(model: dict, pages: _Pages) -> None:
    """Re-count the output against the input.

    Truncation is the failure mode that matters here: a return missing its
    third director still LOOKS like a valid NAR1, and it is a document a client
    is being asked to approve and CR is being asked to register. So the counts
    are checked rather than trusted, after composition and before any bytes are
    produced.

    PER OFFICER KIND, not pooled into one total. Pages 3-7 are now
    unconditionally present (CR's form is static -- see `_compose`), so a
    single combined "capacity of every page present" figure always includes
    the 6 phantom slots of the four other kinds' main pages -- 1 secretary
    (natural person) + 1 secretary (body corporate) + 1 director (natural
    person) + 2 director (body corporate) + 1 reserve director -- whether or
    not that kind has any officers at all. A director cannot occupy a
    secretary's box, so that phantom capacity must not be able to cover for
    a genuinely missing director. Demonstrated in review: a return with 4
    individual directors and only the ONE main-page slot laid out (no Sheet C
    added) passed the pooled check, because the other 5 phantom slots alone
    already exceeded 4.
    """
    counts = {
        "indSecList": len(_as_list(model.get("indSecList"))),
        "corpSecList": len(_as_list(model.get("corpSecList"))),
        "indDirList": len(_as_list(model.get("indDirList"))),
        "corpDirList": len(_as_list(model.get("corpDirList"))),
        "resDirList": len(_as_list(model.get("resDirList"))),
    }
    # Capacity, not occupancy, within each kind: a page with one of its two
    # slots used still has room for the other, so this can only ever
    # over-count within a kind -- the safe direction for a check whose job
    # is to catch UNDER-provisioning. It must NOT be summed ACROSS kinds.
    per_kind = (
        ("secretary (natural person)", "indSecList",
         1 + pages.count_of(fm.PAGE_SHEET_A)),
        ("secretary (body corporate)", "corpSecList",
         1 + pages.count_of(fm.PAGE_SHEET_B)),
        ("director (natural person)", "indDirList",
         1 + pages.count_of(fm.PAGE_SHEET_C)),
        ("director (body corporate)", "corpDirList",
         fm.DIRECTOR_CORPORATE_SLOTS
         + pages.count_of(fm.PAGE_SHEET_D) * fm.SHEET_D_SLOTS),
        ("reserve director", "resDirList", 1),
    )
    for label, key, provisioned in per_kind:
        expected = counts[key]
        if provisioned < expected:
            raise FormFillError(
                f"the return has {expected} {label} officers but only "
                f"{provisioned} slots were laid out; some would be silently "
                f"dropped from the form"
            )

    members = sum(
        len(_as_list(group.get("allotteeRec")))
        for share in _as_list(_node(model, "schedule1").get("shares"))
        for group in _as_list(share.get("shareHolderGrps"))
    )
    schedule_pages = (pages.count_of(fm.PAGE_SCHEDULE_1)
                      + pages.count_of(fm.PAGE_SCHEDULE_2))
    if schedule_pages * fm.SCHEDULE_SLOTS < members:
        raise FormFillError(
            f"the return has {members} members but only "
            f"{schedule_pages * fm.SCHEDULE_SLOTS} schedule slots were laid "
            f"out; some would be silently dropped from the form"
        )


def _qualified_name(obj) -> str:
    """The dotted field name, walking /Parent."""
    parts, cur, guard = [], obj, 0
    while cur is not None and guard < 6:
        if cur.get("/T"):
            parts.append(str(cur.get("/T")))
        parent = cur.get("/Parent")
        cur = parent.get_object() if parent else None
        guard += 1
    return ".".join(reversed(parts))


#: Field properties that live on the PARENT of a widget in CR's form. When a
#: page is duplicated its widgets are detached from those parents and given
#: their own names, so these have to come down with them or the copy loses its
#: type, its checkbox states and its font.
_INHERITED = ("/FT", "/Ff", "/Opt", "/DA", "/MaxLen", "/Q")


def _add_page(writer: PdfWriter, template_page: int, suffix: str) -> dict:
    """Append one copy of a template page; return {original name: name here}.

    WHY THE FIELDS ARE RENAMED. An AcroForm field is identified by name across
    the WHOLE document, not per page. Two copies of Continuation Sheet C keep
    the same `fill_6_P.13`, so filling the second overwrites the first and both
    render the same director. Renaming each copy's widgets makes them distinct
    fields; the returned mapping is how the caller addresses them.

    WHY THE NAMES ARE READ FROM THE SOURCE. `writer.add_page` does not carry
    the widget's `/Parent` across, and in CR's form the name lives on that
    parent — every widget on page 1 answers `/T = "1"` once copied, and the
    dotted name is unrecoverable from the copy. So both the name and the
    inherited field properties are read from the source page and applied to the
    copy by position; `add_page` preserves annotation order, which is what
    makes the pairing sound.

    A fresh PdfReader per call, because pypdf's writer takes ownership of the
    page objects handed to it — reusing one reader's page for two copies makes
    both copies the same object.
    """
    source = PdfReader(str(TEMPLATE))
    source_page = source.pages[template_page - 1]
    source_annots = list(source_page.get("/Annots") or [])

    writer.add_page(source_page)
    copied_annots = list(writer.pages[-1].get("/Annots") or [])
    if len(copied_annots) != len(source_annots):
        raise FormFillError(
            f"page {template_page} copied with {len(copied_annots)} widgets "
            f"but the template has {len(source_annots)}; the pairing by "
            f"position that names them is no longer safe"
        )

    fields = writer._root_object["/AcroForm"]["/Fields"]
    mapping = {}
    for source_annot, copied_annot in zip(source_annots, copied_annots):
        original = _qualified_name(source_annot.get_object())
        if not original:
            continue
        obj = copied_annot.get_object()
        parent = source_annot.get_object().get("/Parent")
        if parent is not None:
            inherited = parent.get_object()
            for key in _INHERITED:
                if key in inherited and key not in obj:
                    obj[NameObject(key)] = inherited[key]
        if "/Parent" in obj:
            del obj["/Parent"]
        renamed = f"{original}{suffix}"
        obj[NameObject("/T")] = TextStringObject(renamed)
        mapping[original] = renamed
        fields.append(copied_annot)
    return mapping


def _render(pages: _Pages) -> bytes:
    """Write the composed pages onto copies of CR's template."""
    template = PdfReader(str(TEMPLATE))
    writer = PdfWriter()

    # Carry over the template's AcroForm — its default resources and font
    # dictionary — but start with an EMPTY field list, because every field is
    # re-registered per page copy by _add_page. Cloning the original list would
    # leave 365 fields pointing at pages this document does not contain.
    acroform = template.trailer["/Root"]["/AcroForm"].clone(writer)
    acroform[NameObject("/Fields")] = ArrayObject()
    writer._root_object[NameObject("/AcroForm")] = writer._add_object(acroform)

    for index, (template_page, values) in enumerate(pages.items):
        mapping = _add_page(writer, template_page, f"__p{index}")
        if not values:
            continue
        renamed = {mapping[name]: value for name, value in values.items()
                   if name in mapping}
        missing = set(values) - set(mapping)
        if missing:
            # A name that is not on the page it was composed for fills nothing
            # and says nothing. Since every one of them is a statutory value,
            # that has to be loud.
            raise FormFillError(
                f"page {template_page} does not carry {sorted(missing)}; "
                f"the field map and the composer disagree"
            )
        writer.update_page_form_field_values(
            writer.pages[-1], renamed, auto_regenerate=False
        )

    # Read-only, because the client is being asked to APPROVE this document,
    # not to edit it. Bit 1 of /Ff is ReadOnly.
    for page in writer.pages:
        for annot in (page.get("/Annots") or []):
            obj = annot.get_object()
            flags = int(obj.get("/Ff", 0)) | 1
            obj[NameObject("/Ff")] = NumberObject(flags)

    # Every page copy carries its own clone of the template's fonts and CR's
    # logo, so a nine-page return weighs 6.3MB before this and 0.9MB after —
    # the difference between a document that emails and one that bounces.
    # Deduplicates identical objects only; nothing visible changes.
    writer.compress_identical_objects()

    buffer = io.BytesIO()
    writer.write(buffer)
    # The values are drawn as page content in fonts we embed, and the widgets
    # are hidden. Until this call the document still renders through CR's
    # non-embedded /PMingLiU, which is what made the emailed copy and the
    # portal preview disagree.
    try:
        return appearance.bake(buffer.getvalue(), sizes=FIELD_SIZES,
                               regular=REGULAR_WEIGHT_FIELDS,
                               centred=CENTRED_FIELDS, faces=FIELD_FACES)
    except appearance.AppearanceError as exc:
        # Translated rather than left to propagate: every caller of
        # `render()` already catches `FormFillError` (routers/cases.py,
        # routers/tpsi.py) and turns it into a 422 naming the problem. An
        # uncaught AppearanceError would surface as an opaque 500 instead of
        # "this character on this field cannot be rendered."
        raise FormFillError(str(exc)) from exc


def render(validated_xml: str, *, company_type: str = "private",
           presenter: dict | None = None, signed_on: str = "") -> bytes:
    """CR's Form NAR1, filled from the XML CR validated.

    `company_type` is one of "private", "public", "guarantee". It cannot be
    read from the XML -- `coyStatus` comes back ABSENT from a real
    validateForm, measured on DEV 2026-08-30 -- and it decides the section 3
    tick, whether section 5 is completed, whether the section 16 statement is
    made, and whether members go on Schedule 1 or Schedule 2. Defaulting it to
    "private" matches essentially all of GSHK's book; a caller that knows
    better should say so.

    `signed_on` is the date beside the signature -- `tpsi_filings.signed_at`
    once CR's PIN signing has succeeded, and nothing before that. Empty means
    TODAY IN HONG KONG, not an empty box; see `signature_date`.
    """
    if company_type not in COMPANY_TYPES:
        raise FormFillError(
            f"company_type must be one of {COMPANY_TYPES}, not {company_type!r}"
        )
    if not TEMPLATE.exists():
        raise FormFillError(f"CR's blank form is missing: {TEMPLATE}")

    model = parse_validated_xml(validated_xml)
    pages = _compose(model, company_type=company_type,
                     presenter=presenter or DEFAULT_PRESENTER,
                     signed_on=signed_on)
    _assert_nothing_dropped(model, pages)
    return _render(pages)
