"""The field map is only worth what these tests prove about it.

`services/nar1_form/field_map.py` names 365 fields that CR named `fill_7_P.3`.
Every one of those names is an ASSERTION about which box on the printed form a
value lands in, and a wrong one is invisible: the PDF fills without complaint
and the client approves a return with their director's building name in the
street box.

So nothing here trusts the map. Each test re-derives the fact from CR's own
documents — the blank form's widget geometry and printed labels, and the two
worked specimens — and fails if the map has drifted from either. A CR revision
of the form breaks these loudly, which is the entire point of committing a
generated map rather than deriving one at runtime.
"""
import re
from pathlib import Path

import pytest

pypdf = pytest.importorskip("pypdf")
from pypdf import PdfReader  # noqa: E402

from services.nar1_form import field_map as fm  # noqa: E402

DOCS = Path(__file__).resolve().parents[2] / "docs"
FILLABLE = DOCS / "NAR1_fillable.pdf"
SPECIMEN_PRIVATE = DOCS / "NAR1(private)_Specimen-e.pdf"

CJK = re.compile(r"[⺀-鿿豈-﫿＀-￯]")


# ---------------------------------------------------------------------------
# Reading the form
# ---------------------------------------------------------------------------

def _qualified_name(obj) -> str:
    """Walk /Parent to build the dotted field name pypdf fills by."""
    parts, cur, guard = [], obj, 0
    while cur is not None and guard < 6:
        if cur.get("/T"):
            parts.append(str(cur.get("/T")))
        parent = cur.get("/Parent")
        cur = parent.get_object() if parent else None
        guard += 1
    return ".".join(reversed(parts))


def _widgets(page) -> dict:
    """Qualified name -> rectangle, normalised so x0<x1 and y0<y1."""
    out = {}
    for annot in (page.get("/Annots") or []):
        obj = annot.get_object()
        r = [float(v) for v in obj["/Rect"]]
        out[_qualified_name(obj)] = (
            min(r[0], r[2]), min(r[1], r[3]), max(r[0], r[2]), max(r[1], r[3])
        )
    return out


def _text_runs(page) -> list:
    runs = []

    def visitor(text, cm, tm, font, size):
        stripped = text.strip()
        if stripped:
            runs.append((tm[4], tm[5], stripped))

    page.extract_text(visitor_text=visitor)
    return runs


@pytest.fixture(scope="module")
def form():
    if not FILLABLE.exists():
        pytest.skip(f"{FILLABLE.name} not present")
    return PdfReader(str(FILLABLE))


@pytest.fixture(scope="module")
def specimen():
    if not SPECIMEN_PRIVATE.exists():
        pytest.skip(f"{SPECIMEN_PRIVATE.name} not present")
    return PdfReader(str(SPECIMEN_PRIVATE))


@pytest.fixture(scope="module")
def all_fields(form):
    return set(form.get_fields() or {})


# ---------------------------------------------------------------------------
# Every name in the map is a real field
# ---------------------------------------------------------------------------

def _every_mapped_name():
    """Walk the map's dicts and tuples and yield (where, semantic, qualified)."""
    simple = {
        "MAIN_1": fm.MAIN_1, "MAIN_2": fm.MAIN_2,
        "SECRETARY_INDIVIDUAL": fm.SECRETARY_INDIVIDUAL,
        "SECRETARY_CORPORATE": fm.SECRETARY_CORPORATE,
        "DIRECTOR_INDIVIDUAL": fm.DIRECTOR_INDIVIDUAL,
        "DIRECTOR_CORPORATE_HEADER": fm.DIRECTOR_CORPORATE_HEADER,
        "RESERVE_DIRECTOR": fm.RESERVE_DIRECTOR,
        "MEMBERS_AND_SIGNATURE": fm.MEMBERS_AND_SIGNATURE,
        "SIGNATURE_STRIKE": fm.SIGNATURE_STRIKE,
        "SHARE_CAPITAL_TOTALS": fm.SHARE_CAPITAL_TOTALS,
        "SCHEDULE_1_HEADER": fm.SCHEDULE_1_HEADER,
        "SCHEDULE_1_PAGING": fm.SCHEDULE_1_PAGING,
        "SCHEDULE_2_HEADER": fm.SCHEDULE_2_HEADER,
        "SCHEDULE_2_PAGING": fm.SCHEDULE_2_PAGING,
        "SHEET_A": fm.SHEET_A, "SHEET_B": fm.SHEET_B,
        "SHEET_C": fm.SHEET_C, "SHEET_E": fm.SHEET_E,
    }
    for where, mapping in simple.items():
        for semantic, qualified in mapping.items():
            yield where, semantic, qualified

    slotted = {
        "DIRECTOR_CORPORATE": fm.DIRECTOR_CORPORATE,
        "SCHEDULE_1": fm.SCHEDULE_1,
        "SCHEDULE_2": fm.SCHEDULE_2,
        "SHEET_D": fm.SHEET_D,
    }
    for where, slots in slotted.items():
        for i, slot in enumerate(slots):
            for semantic, qualified in slot.items():
                yield f"{where}[{i}]", semantic, qualified

    for page in (11, 12, 13, 14, 15):
        for semantic, qualified in fm.sheet_header(page).items():
            yield f"sheet_header({page})", semantic, qualified

    for row in range(fm.SHARE_CAPITAL_ROWS):
        for column in ("class", "currency", "total_number",
                       "total_amount", "paid_up"):
            yield "share_capital", f"{row}/{column}", fm.share_capital(row, column)


def test_every_mapped_field_exists_in_CRs_form(all_fields):
    """A name that is not in the PDF fills nothing, silently. pypdf does not
    raise on an unknown field — it just does not write it — so without this the
    first sign of a typo is a blank box on a client's statutory return."""
    missing = [
        f"{where}.{semantic} -> {qualified}"
        for where, semantic, qualified in _every_mapped_name()
        if qualified not in all_fields
    ]
    assert not missing, "field names not present in NAR1_fillable.pdf:\n  " + \
        "\n  ".join(missing)


def test_no_field_is_mapped_to_two_different_names():
    """Two semantic names on one box means one of them is wrong, and the second
    write silently overwrites the first."""
    seen = {}
    clashes = []
    for where, semantic, qualified in _every_mapped_name():
        key = f"{where}.{semantic}"
        if qualified in seen and seen[qualified].split(".")[0] == where:
            clashes.append(f"{qualified}: {seen[qualified]} and {key}")
        seen[qualified] = key
    assert not clashes, "one PDF field, two meanings:\n  " + "\n  ".join(clashes)


# ---------------------------------------------------------------------------
# The names agree with the form's own printed labels
# ---------------------------------------------------------------------------

def _label_left_of(rect, runs, all_rects):
    """Latin label text immediately left of a box, ignoring text inside other
    boxes — on this form the neighbour to the left is often a field.

    Two subtleties, both learned from wrong answers this returned:

    - The nearest FOUR runs are taken (by distance leftward), then re-sorted
      into READING order before joining. Joining in nearest-first order gives
      "English Name in" for "Name in English", which then fails to match a
      label that is perfectly correct.
    - CR's PDF splits words across text-showing operations, so "Email Address"
      arrives as "E" + "mail Address". Callers therefore compare with
      `_squash`, which drops whitespace from both sides.
    """
    x0, y0, x1, y1 = rect

    def outside_every_field(x, y):
        return not any(a <= x <= b and c <= y <= d for (a, c, b, d) in all_rects)

    candidates = sorted(
        [(x, y, t) for (x, y, t) in runs
         if x < x0 and y0 - 2 <= y <= y1 + 2 and outside_every_field(x, y)],
        key=lambda r: -r[0],
    )[:4]
    candidates.sort(key=lambda r: r[0])
    return " ".join(CJK.sub("", t).strip(" ／/·,") for _, _, t in candidates).strip()


def _squash(text: str) -> str:
    """Lowercase with all whitespace removed — see `_label_left_of`."""
    return "".join(text.split()).lower()


@pytest.mark.parametrize("page_no, qualified, expected_in_label", [
    # Page 3 — the company secretary block, the densest labelling on the form.
    (3, fm.SECRETARY_INDIVIDUAL["surname_en"], "Surname"),
    (3, fm.SECRETARY_INDIVIDUAL["other_names_en"], "Other Names"),
    (3, fm.SECRETARY_INDIVIDUAL["addr_building"], "Building"),
    (3, fm.SECRETARY_INDIVIDUAL["addr_district"], "District"),
    (3, fm.SECRETARY_INDIVIDUAL["email"], "Email Address"),
    (3, fm.SECRETARY_INDIVIDUAL["hkid_partial"], "Hong Kong Identity Card"),
    # Page 5 — the director block carries country/region the secretary lacks,
    # because a director's correspondence address may be outside Hong Kong.
    (5, fm.DIRECTOR_INDIVIDUAL["addr_country"], "Country"),
    (5, fm.DIRECTOR_INDIVIDUAL["surname_en"], "Surname"),
    (5, fm.DIRECTOR_INDIVIDUAL["passport_country"], "Issuing Country"),
    # Page 1 — registered office.
    (1, fm.MAIN_1["ro_building"], "Building"),
    (1, fm.MAIN_1["ro_district"], "District"),
    # Page 9 — Schedule 1.
    (9, fm.SCHEDULE_1_HEADER["class_total_issued"], "Total Number of Issued"),
    (9, fm.SCHEDULE_1[0]["addr_building"], "Building"),
])
def test_the_name_matches_the_forms_printed_label(
    form, page_no, qualified, expected_in_label
):
    page = form.pages[page_no - 1]
    widgets = _widgets(page)
    assert qualified in widgets, f"{qualified} is not on page {page_no}"
    label = _label_left_of(widgets[qualified], _text_runs(page),
                           list(widgets.values()))
    assert _squash(expected_in_label) in _squash(label), (
        f"{qualified} on page {page_no} is labelled {label!r}, "
        f"which does not contain {expected_in_label!r}"
    )


# ---------------------------------------------------------------------------
# The names agree with what CR itself filled in its specimen
# ---------------------------------------------------------------------------

def _specimen_value(specimen_page, rect):
    """Text whose origin falls inside a box on the flattened specimen."""
    x0, y0, x1, y1 = rect
    return [t for (x, y, t) in _text_runs(specimen_page)
            if x0 - 2 <= x <= x1 + 2 and y0 - 3 <= y <= y1 + 3]


@pytest.mark.parametrize("page_no, qualified, expected", [
    # CR's worked example: GREAT RICH SUCCESS LIMITED, BR 88888888, return
    # date 23/05/2025, registered office Room 8801-8803, 88/F, Happy
    # Commercial Building, 1 Queensway.
    (1, fm.MAIN_1["br_number"], "88888888"),
    (1, fm.MAIN_1["company_name"], "GREAT RICH SUCCESS LIMITED"),
    (1, fm.MAIN_1["return_date_dd"], "23"),
    (1, fm.MAIN_1["ro_flat_floor_block"], "Room 8801-8803, 88/F"),
    (1, fm.MAIN_1["ro_building"], "Happy Commercial Building"),
    (1, fm.MAIN_1["ro_street"], "1 Queensway"),
    (1, fm.MAIN_1["presenter_name"], "QualiSec Services Limited"),
    (1, fm.MAIN_1["presenter_email"], "qss@abc.com"),
    (2, fm.MAIN_2["email_address"], "greatrichsuccess@abc.com"),
    (2, fm.MAIN_2["phone"], "12345678"),
    (2, fm.MAIN_2["mortgages_total"], "HK$999,999"),
    # Schedule 1: class Ordinary, 10,000 issued; first member Chan Tai Yat
    # holding 3,000 at Room A, 12/F, ABC Building, 888 Queen's Road Central.
    (9, fm.SCHEDULE_1_HEADER["share_class"], "Ordinary"),
    (9, fm.SCHEDULE_1_HEADER["class_total_issued"], "10,000"),
    (9, fm.SCHEDULE_1[0]["surname_en"], "Chan"),
    (9, fm.SCHEDULE_1[0]["other_names_en"], "Tai Yat"),
    (9, fm.SCHEDULE_1[0]["shares_held"], "3,000"),
    (9, fm.SCHEDULE_1[0]["addr_flat_floor"], "Room A, 12/F"),
    (9, fm.SCHEDULE_1[0]["addr_building"], "ABC Building"),
    (9, fm.SCHEDULE_1[0]["addr_street"], "888 Queen"),
    (9, fm.SCHEDULE_1[0]["addr_country"], "Hong Kong"),
    (9, fm.SCHEDULE_1[1]["name_en_corp"], "Billion Profits Limited"),
    (9, fm.SCHEDULE_1[1]["shares_held"], "2,000"),
    (9, fm.SCHEDULE_1[1]["addr_flat_floor"], "Room 2808-2810, 28/F"),
    (9, fm.SCHEDULE_1[1]["addr_building"], "Happy Commercial Building"),
    (9, fm.SCHEDULE_1[1]["addr_street"], "1 Queensway"),
    (9, fm.SCHEDULE_1_HEADER["br_number"], "88888888"),
])
def test_the_box_holds_what_CR_put_in_it(form, specimen, page_no,
                                         qualified, expected):
    """Ground truth. CR filled its own form; the value it wrote must land in
    the box this map claims it belongs to.

    The specimen also carries instructional CALLOUTS positioned beside the
    boxes they describe, so a value being PRESENT among the hits is the
    assertion — not the hits being exactly one thing.
    """
    widgets = _widgets(form.pages[page_no - 1])
    assert qualified in widgets
    hits = _specimen_value(specimen.pages[page_no - 1], widgets[qualified])
    assert any(expected in h for h in hits), (
        f"{qualified} (page {page_no}) should hold {expected!r}; "
        f"the specimen has {hits!r} in that box"
    )


# ---------------------------------------------------------------------------
# Structural facts the filler depends on
# ---------------------------------------------------------------------------

def test_pages_16_and_beyond_carry_no_fields(form):
    """They are CR's printed Notes for Completion, and the filler drops them.
    If a future revision puts a field on page 16, dropping it would silently
    discard data."""
    for index in range(fm.LAST_FIELD_PAGE, len(form.pages)):
        assert not (form.pages[index].get("/Annots") or []), (
            f"page {index + 1} has fields but the filler treats "
            f"everything after page {fm.LAST_FIELD_PAGE} as printed notes"
        )


def test_every_checkbox_uses_the_on_state_the_filler_ticks_with(form):
    """The filler writes CHECKBOX_ON everywhere. A box with a different state
    name would not tick — and would not error either."""
    fields = form.get_fields() or {}
    wrong = [
        name for name, spec in fields.items()
        if str(spec.get("/FT")) == "/Btn"
        and spec.get("/_States_")
        and fm.CHECKBOX_ON not in list(spec["/_States_"])
    ]
    assert not wrong, f"checkboxes whose on-state is not {fm.CHECKBOX_ON}: {wrong}"


def test_the_strike_through_option_is_really_offered(form):
    """The signature line expresses capacity by STRIKING OUT the word that does
    not apply, via a dropdown whose only non-blank option is a long rule. If
    CR's rule string changes, writing the old one selects nothing."""
    fields = form.get_fields() or {}
    for qualified in fm.SIGNATURE_STRIKE.values():
        options = [str(o) for o in (fields[qualified].get("/Opt") or [])]
        assert fm.STRIKE_THROUGH in options, (
            f"{qualified} does not offer the strike-through rule this map "
            f"expects; its options are {options!r}"
        )


# ---------------------------------------------------------------------------
# The same check, applied to EVERY block rather than a sample
# ---------------------------------------------------------------------------
#
# The parametrised cases above are spot-checks on five pages. This walks every
# officer, schedule and continuation-sheet block in the map and asserts that a
# semantic name implying a printed label actually sits beside that label. It is
# what makes the other ten pages trustworthy: the first draft of the schedules
# was wrong in exactly the way a sample missed, because the two member slots on
# one page are numbered differently from each other.

#: semantic suffix -> label fragments, ANY of which is enough.
#:
#: Alternatives rather than one string, for two honest reasons. CR labels the
#: name boxes "姓氏 Surname" and "名字 Other Names" in the officer blocks but
#: only "英文姓名 Name in English" on the schedules, where the sub-labels sit
#: ABOVE the boxes rather than to their left. And this scan reads leftward, so
#: a two-word label can come back reversed ("Address Email"). Neither is a map
#: error, and tightening the scan to hide them would be fitting the test to the
#: extractor. The schedule name boxes are pinned exactly by
#: `test_the_box_holds_what_CR_put_in_it`, against CR's own specimen —
#: "Chan"/"Tai Yat" in slot 0, which is a stronger check than any label.
_LABEL_EXPECTATIONS = {
    "addr_building":    ("Building",),
    "addr_street":      ("Lot",),        # "Street／Estate／Lot／Village etc."
    "addr_district":    ("District",),
    # CR's combined overseas line, "District／City／Province／State／Postal
    # Code etc.". Only the director family has it; a secretary's address is
    # Hong Kong only and gets a plain District. Two different boxes, and
    # putting a HK district in one or an overseas state in the other misstates
    # the address — which is why they do not share a semantic name.
    "addr_district_city_state": ("Province",),
    "addr_city":        ("City",),
    "addr_country":     ("Country",),
    "addr_flat_floor":  ("Floor",),
    "surname_en":       ("Surname", "Name in English"),
    "other_names_en":   ("Other Names", "Name in English"),
    "name_zh":          ("Name in Chinese",),
    "email":            ("Email",),
    "remarks":          ("Remarks",),
    "passport_country": ("Issuing Country",),
    "hkid_partial":     ("Hong Kong Identity Card",),
    "tcsp_licence":     ("Licence No.",),
}

_BLOCKS = [
    (3, "SECRETARY_INDIVIDUAL", fm.SECRETARY_INDIVIDUAL),
    (4, "SECRETARY_CORPORATE", fm.SECRETARY_CORPORATE),
    (5, "DIRECTOR_INDIVIDUAL", fm.DIRECTOR_INDIVIDUAL),
    (6, "DIRECTOR_CORPORATE[0]", fm.DIRECTOR_CORPORATE[0]),
    (6, "DIRECTOR_CORPORATE[1]", fm.DIRECTOR_CORPORATE[1]),
    (7, "RESERVE_DIRECTOR", fm.RESERVE_DIRECTOR),
    (9, "SCHEDULE_1[0]", fm.SCHEDULE_1[0]),
    (9, "SCHEDULE_1[1]", fm.SCHEDULE_1[1]),
    (10, "SCHEDULE_2[0]", fm.SCHEDULE_2[0]),
    (10, "SCHEDULE_2[1]", fm.SCHEDULE_2[1]),
    (11, "SHEET_A", fm.SHEET_A),
    (12, "SHEET_B", fm.SHEET_B),
    (13, "SHEET_C", fm.SHEET_C),
    (14, "SHEET_D[0]", fm.SHEET_D[0]),
    (14, "SHEET_D[1]", fm.SHEET_D[1]),
]


@pytest.mark.parametrize("page_no, block_name, block",
                         _BLOCKS, ids=[b[1] for b in _BLOCKS])
def test_every_block_sits_beside_the_label_its_name_claims(
    form, page_no, block_name, block
):
    page = form.pages[page_no - 1]
    widgets = _widgets(page)
    runs = _text_runs(page)
    rects = list(widgets.values())

    wrong = []
    for semantic, qualified in block.items():
        expected = _LABEL_EXPECTATIONS.get(semantic)
        if expected is None:
            continue
        assert qualified in widgets, f"{block_name}.{semantic} not on page {page_no}"
        label = _label_left_of(widgets[qualified], runs, rects)
        if not any(_squash(want) in _squash(label) for want in expected):
            wrong.append(f"{semantic} -> {qualified}: labelled {label!r}, "
                         f"expected one of {expected!r}")

    assert not wrong, f"{block_name} on page {page_no}:\n  " + "\n  ".join(wrong)
