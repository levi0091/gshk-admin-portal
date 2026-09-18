"""The approved return against the CR-validated one, box by box (Levi 2026-09-18).

What has to be true for the Data Verification viewer to be trusted:

  * nothing lights up that did not change, and nothing that changed is missed —
    every highlight is exactly one listed change;
  * the list names the change in the reader's terms: WHO (the director's
    name), WHAT (the field), the two values, and the page;
  * a fact printed on page after page (the BR number, the made-up date) is one
    change, not nine;
  * the one box that differs by construction — the signature date — never
    shows;
  * the highlight is drawn on the page the reader looks at, and leaves the
    value readable.
"""
import pytest

pytest.importorskip("pypdf")

from services.nar1_form import compare, field_map as fm, fill  # noqa: E402
from tests.test_nar1_form_fill import build_xml  # noqa: E402

INCORPORATED = "2020-02-01"


def _compare(approved, validated):
    return compare.compare(approved, validated, incorporated_on=INCORPORATED)


def _page_index(xml, template_page, occurrence=0):
    """The 0-based output page of the `occurrence`-th copy of a template page."""
    pages = fill._composed(xml, company_type="private", presenter=None,
                           signed_on="", incorporated_on=INCORPORATED)
    seen = -1
    for index, (page, _values) in enumerate(pages.items):
        if page == template_page:
            seen += 1
            if seen == occurrence:
                return index
    raise AssertionError(f"no copy {occurrence} of template page {template_page}")


# ---------------------------------------------------------------------------
# Nothing moved
# ---------------------------------------------------------------------------

def test_the_same_return_has_no_changes_and_no_highlights():
    xml = build_xml()
    result = _compare(xml, xml)
    assert result.changes == []
    assert result.highlight == frozenset()


def test_the_client_copy_and_crs_copy_of_an_unchanged_return_agree():
    """THE COMMON CASE. The client approves `request_xml`, which has no
    made-up date; CR's copy has one. The client's copy derives it from the
    same anniversary rule CR uses, so an unchanged return compares clean —
    a warning on every case would teach operators to ignore the warning."""
    approved = build_xml(date=None, year="2026")          # request shape
    validated = build_xml(date="01/02/2026", year="2026")  # CR's copy
    assert _compare(approved, validated).changes == []


# ---------------------------------------------------------------------------
# One change, fully described
# ---------------------------------------------------------------------------

def test_a_changed_address_line_is_one_named_change_on_its_page():
    approved = build_xml()
    validated = approved.replace(
        "<cr:bldg>Test Tower</cr:bldg>", "<cr:bldg>New Tower</cr:bldg>")
    result = _compare(approved, validated)

    assert result.changes == [{
        "section": "Company particulars",
        "field": "Registered office — building",
        "approved": "Test Tower",
        "validated": "New Tower",
        "note": None,
        "pages": [1],
    }]
    assert result.highlight == {(0, fm.MAIN_1["ro_building"])}


def test_a_directors_change_names_the_director():
    approved = build_xml(directors=("CHAN",))
    validated = approved.replace("<cr:indvHkidNo>A123</cr:indvHkidNo>",
                                 "<cr:indvHkidNo>B456</cr:indvHkidNo>")
    [change] = _compare(approved, validated).changes
    assert change["section"] == "Director — CHAN Tai Man"
    assert change["field"] == "HKID number (partial)"
    assert (change["approved"], change["validated"]) == ("A123", "B456")
    assert change["pages"] == [_page_index(validated, fm.PAGE_DIRECTOR_INDIVIDUAL) + 1]


def test_every_highlight_is_a_listed_change_and_every_change_is_highlighted():
    """The one-to-one property the viewer rests on."""
    approved = build_xml(directors=("CHAN", "LEE"))
    validated = (approved
                 .replace("<cr:compNameE>TEST COMPANY LIMITED",
                          "<cr:compNameE>TEST CO LIMITED")
                 .replace("<cr:bldg>Test Tower</cr:bldg>",
                          "<cr:bldg>New Tower</cr:bldg>"))
    result = _compare(approved, validated)
    listed_pages = {p for change in result.changes for p in change["pages"]}
    highlighted_pages = {index + 1 for index, _field in result.highlight}
    assert listed_pages == highlighted_pages
    assert len(result.highlight) >= len(result.changes)


# ---------------------------------------------------------------------------
# Facts printed on many pages, and the box that always differs
# ---------------------------------------------------------------------------

def test_a_made_up_date_cr_moved_is_one_change_across_every_page_it_is_on():
    """CR writes `dateReturnMadeUp` itself. If it disagrees with the date the
    client's copy derived, that is ONE change — flagged as CR's — carrying the
    page of section 4 and of every schedule header, not a line per page."""
    approved = build_xml(date=None, year="2026")
    validated = build_xml(date="02/02/2026", year="2026")
    [change] = _compare(approved, validated).changes

    assert change["field"] == "Date to which this return is made up"
    assert (change["approved"], change["validated"]) == ("01/02/2026", "02/02/2026")
    assert change["note"] and "Companies Registry" in change["note"]
    assert 1 in change["pages"]
    schedule = _page_index(validated, fm.PAGE_SCHEDULE_1) + 1
    assert schedule in change["pages"]


def test_the_signature_date_never_counts_as_a_change():
    """The client's copy is dated the day it was mailed and CR's copy the day
    it is shown. Different by construction; not a particular of the company."""
    xml = build_xml()
    before = fill._composed(xml, company_type="private", presenter=None,
                            signed_on="2026-09-01", incorporated_on=INCORPORATED)
    after = fill._composed(xml, company_type="private", presenter=None,
                           signed_on="2026-09-18", incorporated_on=INCORPORATED)
    assert compare.compare_pages(before, after).changes == []


def test_a_field_cr_fills_is_reported_as_crs():
    """`natureDesc` is blank on the client's copy — CR writes it on validation —
    so it appears as a change, and the list says whose change it is."""
    approved = build_xml()
    validated = approved.replace(
        "<cr:formCode>NAR1</cr:formCode>",
        "<cr:formCode>NAR1</cr:formCode><cr:natureDesc>Trading</cr:natureDesc>")
    [change] = _compare(approved, validated).changes
    assert change["field"] == "Business nature"
    assert change["approved"] is None and change["validated"] == "Trading"
    assert "Companies Registry" in change["note"]


# ---------------------------------------------------------------------------
# Pages that exist in only one of the two
# ---------------------------------------------------------------------------

def test_a_director_added_since_approval_is_listed_and_marked_on_the_new_sheet():
    approved = build_xml(directors=("CHAN",))
    validated = build_xml(directors=("CHAN", "LEE"))
    result = _compare(approved, validated)

    sheet_c = _page_index(validated, fm.PAGE_SHEET_C)
    added = [c for c in result.changes if c["section"] == "Director — LEE Tai Man"]
    assert added, result.changes
    assert all(c["approved"] is None for c in added)
    assert all(c["pages"] == [sheet_c + 1] for c in added)
    assert (sheet_c, fm.SHEET_C["surname_en"]) in result.highlight
    # And page 8's count of attached sheets moved with it.
    counts = [c for c in result.changes
              if c["field"] == "Continuation Sheet C — pages attached"]
    assert counts and (counts[0]["approved"], counts[0]["validated"]) == ("0", "1")


def test_a_director_removed_since_approval_is_listed_with_no_page_to_mark():
    """Nothing is left on the validated form to highlight, so the list is the
    only place the removal shows — and it must still show."""
    approved = build_xml(directors=("CHAN", "LEE"))
    validated = build_xml(directors=("CHAN",))
    removed = [c for c in _compare(approved, validated).changes
               if c["section"] == "Director — LEE Tai Man"]
    assert removed
    assert all(c["validated"] is None and c["pages"] == [] for c in removed)


def test_changes_are_listed_in_page_order():
    approved = build_xml(directors=("CHAN",))
    validated = (build_xml(directors=("CHAN", "LEE"))
                 .replace("<cr:bldg>Test Tower</cr:bldg>", "<cr:bldg>New Tower</cr:bldg>"))
    pages = [c["pages"][0] for c in _compare(approved, validated).changes
             if c["pages"]]
    assert pages == sorted(pages)


# ---------------------------------------------------------------------------
# The index — every box the composer writes has a name a reader understands
# ---------------------------------------------------------------------------

def test_every_box_the_composer_writes_is_indexed():
    """A box missing from the index would be reported under "Other" with its
    widget name — `fill_16_P.13` — which is no use to anybody."""
    xml = build_xml(directors=("A", "B", "C"), corporate_directors=("X", "Y", "Z"),
                    secretaries=2, corporate_secretaries=("S1", "S2"),
                    members=("M1", "M2", "M3"), share_classes=2)
    pages = fill._composed(xml, company_type="private", presenter=None,
                           signed_on="", incorporated_on=INCORPORATED)
    written = {widget for _page, values in pages.items for widget in values}
    assert written - set(compare.INDEX) == set()


def test_every_indexed_box_has_a_label():
    unlabelled = sorted({
        compare._GROUP_OF.get(key, key)
        for _block, _slot, key in compare.INDEX.values()
    } - set(compare._LABELS))
    assert unlabelled == []


def test_a_placeholder_dash_is_never_taken_for_a_name():
    """A member with no English name prints "-". The section must not read
    "Member — - -"."""
    assert compare._who("member", {"surname_en": "-", "other_names_en": "-",
                                   "name_en_corp": "HOLDCO LIMITED"}) \
        == "HOLDCO LIMITED"
    assert compare._who("member", {"surname_en": "-"}) is None


# ---------------------------------------------------------------------------
# The highlight on the page
# ---------------------------------------------------------------------------

def _carrot_boxes(pdf_bytes, page_index):
    fitz = pytest.importorskip("pymupdf")
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    carrot = (0xF3 / 255, 0x6C / 255, 0x32 / 255)
    return [d["rect"] for d in doc[page_index].get_drawings()
            if d.get("fill") and all(abs(a - b) < 0.02
                                     for a, b in zip(d["fill"], carrot))]


def test_the_highlight_is_drawn_behind_the_changed_box_and_nowhere_else():
    approved = build_xml()
    validated = approved.replace("<cr:bldg>Test Tower</cr:bldg>",
                                 "<cr:bldg>New Tower</cr:bldg>")
    result = _compare(approved, validated)
    pdf = fill.render(validated, incorporated_on=INCORPORATED,
                      highlight=result.highlight)

    assert len(_carrot_boxes(pdf, 0)) == 1
    for other_page in range(1, 9):
        assert _carrot_boxes(pdf, other_page) == []


def test_the_highlighted_value_still_prints_in_black():
    """The highlight sets a fill colour. Without restoring the canvas state the
    value drawn next would print in 22%-opaque carrot."""
    fitz = pytest.importorskip("pymupdf")
    approved = build_xml()
    validated = approved.replace("<cr:bldg>Test Tower</cr:bldg>",
                                 "<cr:bldg>New Tower</cr:bldg>")
    pdf = fill.render(validated, incorporated_on=INCORPORATED,
                      highlight=_compare(approved, validated).highlight)
    page = fitz.open(stream=pdf, filetype="pdf")[0]
    spans = [s for b in page.get_text("dict")["blocks"] for line in b.get("lines", [])
             for s in line["spans"] if "New Tower" in s["text"]]
    assert spans and all(s["color"] == 0 for s in spans)


def test_without_a_highlight_nothing_is_marked():
    """The clean copy — what Download saves — carries no review marks."""
    pdf = fill.render(build_xml(), incorporated_on=INCORPORATED)
    assert all(_carrot_boxes(pdf, i) == [] for i in range(0, 9))
