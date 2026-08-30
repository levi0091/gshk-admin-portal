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
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, NameObject, NumberObject, TextStringObject

from services.nar1_form import field_map as fm

# pypdf warns "contains characters not supported by font encoding" for every
# value it writes, including plain ASCII, because it cannot build an appearance
# stream from CR's subsetted form fonts. It does not have to: the document sets
# NeedAppearances, so the VIEWER draws the values from the form's own fonts —
# verified by rasterising a real filled return, Chinese company names included.
# The warning is therefore noise, and one line per field drowns real logs.
logging.getLogger("pypdf.generic._appearance_stream").setLevel(logging.ERROR)

#: CR's blank form, COMMITTED BESIDE THIS MODULE rather than read from
#: `docs/`. It is a runtime dependency, not documentation: without it every
#: client-verification email fails. `docs/` is in .gitignore, so a copy living
#: there is on one laptop — absent from CI, absent from Railway, and absent
#: from any fresh clone. Read-only; never modified in place.
TEMPLATE = Path(__file__).resolve().parent / "form" / "NAR1_fillable.pdf"

#: Who CR contacts about the filing. GSHK, not the client.
DEFAULT_PRESENTER = {
    "name": "Get Started HK Limited",
    "email": "no-reply@getstarted.hk",
}


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


def _address(node: dict) -> dict:
    """CR's stdAddress/roAddr/allotteeAddr block. One shape, three names."""
    return {
        "flat_floor": _get(node, "flatFlrBlk"),
        "building": _get(node, "bldg"),
        "street": _get(node, "stEstLotVlg"),
        "district_city_state": _get(node, "dstCtyStatePostal"),
        "country": _get(node, "ctryRegion"),
    }


def _yes(value: str) -> bool:
    return (value or "").strip().upper() == "Y"


# ---------------------------------------------------------------------------
# Block writers — one per repeated shape on the form
# ---------------------------------------------------------------------------

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
        block["passport_country"]: _get(person, "indvPptIssCtry"),
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
        block["shares_held"]: _get(group, "sharesAlloted"),
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


def _compose(model: dict, *, company_type: str, presenter: dict) -> _Pages:
    """Lay the return out across CR's pages, overflowing where it must."""
    pages = _Pages()
    br_number = _get(model, "brNo")
    dd, mm, yyyy = split_date(_get(model, "dateReturnMadeUp"))
    from_dd, from_mm, from_yyyy = split_date(_get(model, "dateReturnFrom"))
    to_dd, to_mm, to_yyyy = split_date(_get(model, "dateReturnTo"))
    ro = _address(_node(model, "roAddr"))

    # ---- page 1 ----------------------------------------------------------
    m1 = fm.MAIN_1
    page1 = {
        m1["br_number"]: br_number,
        m1["company_name"]: _company_name(model),
        m1["business_name"]: _get(model, "brName"),
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
        m1["presenter_reference"]: presenter.get("reference", ""),
        m1[f"type_{company_type}"]: fm.CHECKBOX_ON,
    }
    # "A private company needs not complete this section" -- the form says so
    # on section 5 itself. Filling it anyway would be a statement about
    # financial statements that a private company does not deliver.
    if company_type != "private":
        page1.update({
            m1["fin_period_from_dd"]: from_dd,
            m1["fin_period_from_mm"]: from_mm,
            m1["fin_period_from_yyyy"]: from_yyyy,
            m1["fin_period_to_dd"]: to_dd,
            m1["fin_period_to_mm"]: to_mm,
            m1["fin_period_to_yyyy"]: to_yyyy,
        })
    pages.add(fm.PAGE_MAIN_1, page1)

    # ---- page 2 ----------------------------------------------------------
    m2 = fm.MAIN_2
    page2 = {
        m2["br_number"]: br_number,
        m2["email_address"]: _get(model, "emailAddr"),
        m2["phone"]: _get(model, "telNo"),
        # The form asks for NIL rather than a blank: on a statutory
        # declaration an empty box reads as "not answered".
        m2["mortgages_total"]: _get(model, "totalAmountMortCharge") or "NIL",
        m2["members_no_capital"]: _get(model, "memberNumAtDateReturn"),
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
            _get(capital, "noOfShareIssuedOnThisCls")
        page2[fm.share_capital(row, "total_amount")] = _get(capital, "issuedCapital")
        page2[fm.share_capital(row, "paid_up")] = _get(capital, "paidUpCapital")
    pages.add(fm.PAGE_MAIN_2, page2)

    # ---- officers, with overflow -----------------------------------------
    ind_secs = _as_list(model.get("indSecList"))
    corp_secs = _as_list(model.get("corpSecList"))
    ind_dirs = _as_list(model.get("indDirList"))
    corp_dirs = _as_list(model.get("corpDirList"))
    res_dirs = _as_list(model.get("resDirList"))

    if ind_secs:
        values = _individual_officer(fm.SECRETARY_INDIVIDUAL, ind_secs[0],
                                     hk_only=True)
        values[fm.SECRETARY_INDIVIDUAL["br_number"]] = br_number
        pages.add(fm.PAGE_SECRETARY_INDIVIDUAL, values)
    if corp_secs:
        values = _corporate_officer(fm.SECRETARY_CORPORATE, corp_secs[0],
                                    hk_only=True)
        values[fm.SECRETARY_CORPORATE["br_number"]] = br_number
        pages.add(fm.PAGE_SECRETARY_CORPORATE, values)
    if ind_dirs:
        values = _individual_officer(fm.DIRECTOR_INDIVIDUAL, ind_dirs[0],
                                     hk_only=False)
        values[fm.DIRECTOR_INDIVIDUAL["br_number"]] = br_number
        pages.add(fm.PAGE_DIRECTOR_INDIVIDUAL, values)
    if corp_dirs:
        values = {fm.DIRECTOR_CORPORATE_HEADER["br_number"]: br_number}
        for slot, body in zip(fm.DIRECTOR_CORPORATE,
                              corp_dirs[:fm.DIRECTOR_CORPORATE_SLOTS]):
            values.update(_corporate_officer(slot, body, hk_only=False))
        pages.add(fm.PAGE_DIRECTOR_CORPORATE, values)
    if res_dirs:
        values = _individual_officer(fm.RESERVE_DIRECTOR, res_dirs[0],
                                     hk_only=False)
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

    for chunk in _chunk(rows, fm.SCHEDULE_SLOTS):
        values = {
            schedule_head["br_number"]: br_number,
            schedule_head["return_date_dd"]: dd,
            schedule_head["return_date_mm"]: mm,
            schedule_head["return_date_yyyy"]: yyyy,
            schedule_head["share_class"]: chunk[0][0],
            schedule_head["class_total_issued"]: chunk[0][1],
        }
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
    }
    if company_type == "private":
        page8[ms["statement_private"]] = fm.CHECKBOX_ON
    for name, page_no in (("count_sheet_a", fm.PAGE_SHEET_A),
                          ("count_sheet_b", fm.PAGE_SHEET_B),
                          ("count_sheet_c", fm.PAGE_SHEET_C),
                          ("count_sheet_d", fm.PAGE_SHEET_D),
                          ("count_sheet_e", fm.PAGE_SHEET_E)):
        count = pages.count_of(page_no)
        if count:
            page8[ms[name]] = str(count)
    if schedule_count:
        page8[ms["count_schedule_2" if listed else "count_schedule_1"]] = \
            str(schedule_count)

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
    """
    expected_officers = (
        len(_as_list(model.get("indSecList")))
        + len(_as_list(model.get("corpSecList")))
        + len(_as_list(model.get("indDirList")))
        + len(_as_list(model.get("corpDirList")))
        + len(_as_list(model.get("resDirList")))
    )
    capacity = {
        fm.PAGE_SECRETARY_INDIVIDUAL: 1, fm.PAGE_SECRETARY_CORPORATE: 1,
        fm.PAGE_DIRECTOR_INDIVIDUAL: 1,
        fm.PAGE_DIRECTOR_CORPORATE: fm.DIRECTOR_CORPORATE_SLOTS,
        fm.PAGE_RESERVE_DIRECTOR: 1,
        fm.PAGE_SHEET_A: 1, fm.PAGE_SHEET_B: 1, fm.PAGE_SHEET_C: 1,
        fm.PAGE_SHEET_D: fm.SHEET_D_SLOTS,
    }
    # Capacity, not occupancy: a page with one of its two slots used still has
    # room for the other, so this can only ever over-count -- which is the safe
    # direction for a check whose job is to catch UNDER-provisioning.
    provisioned = sum(capacity.get(page_no, 0) for page_no, _ in pages.items)
    if provisioned < expected_officers:
        raise FormFillError(
            f"the return has {expected_officers} officers but only "
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

    # Without this most viewers draw the boxes and none of the values: pypdf
    # writes /V but no appearance stream, and NeedAppearances asks the viewer
    # to generate them.
    writer.set_need_appearances_writer(True)

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
    return buffer.getvalue()


def render(validated_xml: str, *, company_type: str = "private",
           presenter: dict | None = None) -> bytes:
    """CR's Form NAR1, filled from the XML CR validated.

    `company_type` is one of "private", "public", "guarantee". It cannot be
    read from the XML -- `coyStatus` comes back ABSENT from a real
    validateForm, measured on DEV 2026-08-30 -- and it decides the section 3
    tick, whether section 5 is completed, whether the section 16 statement is
    made, and whether members go on Schedule 1 or Schedule 2. Defaulting it to
    "private" matches essentially all of GSHK's book; a caller that knows
    better should say so.
    """
    if company_type not in COMPANY_TYPES:
        raise FormFillError(
            f"company_type must be one of {COMPANY_TYPES}, not {company_type!r}"
        )
    if not TEMPLATE.exists():
        raise FormFillError(f"CR's blank form is missing: {TEMPLATE}")

    model = parse_validated_xml(validated_xml)
    pages = _compose(model, company_type=company_type,
                     presenter=presenter or DEFAULT_PRESENTER)
    _assert_nothing_dropped(model, pages)
    return _render(pages)
