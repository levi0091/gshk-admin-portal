"""Fidelity against GSHK's own filed NAR1 (Kanenas Holding Limited, 2026).

Every test here names a difference found by laying the generated return beside
that specimen page for page. None of them is cosmetic in the sense that
matters: a director is asked to APPROVE this document and CR is asked to
register it, and each of these changed what the printed page says -- an empty
Total under a share capital table, a signatory's name sitting in the date box,
a district printed as the transmission code CR accepts rather than the name CR
prints.

The suite that existed before this one asserted that values reached the right
FIELDS. These assert what the reader of the page actually sees.
"""
import io

import pytest

pytest.importorskip("pypdf")
from pypdf import PdfReader  # noqa: E402

from services.nar1_form import appearance as ap  # noqa: E402
from services.nar1_form import field_map as fm  # noqa: E402
from services.nar1_form import fill  # noqa: E402
from tests.test_nar1_form_fill import build_xml, values_of  # noqa: E402


# ---------------------------------------------------------------------------
# Section 11 -- the share capital table
# ---------------------------------------------------------------------------

def test_the_share_capital_total_row_is_filled():
    """It was BLANK on every return ever generated.
    `field_map.SHARE_CAPITAL_TOTALS` existed from the day the map was written
    and nothing ever referenced it."""
    values = values_of(fill.render(build_xml()))
    assert values[fm.SHARE_CAPITAL_TOTALS["currency"]] == ["HKD"]
    assert values[fm.SHARE_CAPITAL_TOTALS["total_number"]] == ["100"]
    assert values[fm.SHARE_CAPITAL_TOTALS["total_amount"]] == ["100.00"]
    assert values[fm.SHARE_CAPITAL_TOTALS["paid_up"]] == ["100.00"]


def test_the_total_row_sums_the_classes_rather_than_copying_one():
    """Three classes of 100 total 300. Copying the first row's figure would
    under-report the company's issued capital by two thirds."""
    values = values_of(fill.render(build_xml(share_classes=3)))
    assert values[fm.SHARE_CAPITAL_TOTALS["total_number"]] == ["300"]
    assert values[fm.SHARE_CAPITAL_TOTALS["total_amount"]] == ["300.00"]
    assert values[fm.SHARE_CAPITAL_TOTALS["paid_up"]] == ["300.00"]


def test_classes_in_different_currencies_state_no_money_total():
    """HKD 100 plus USD 100 is not 200 of anything, and CR's Total row has a
    single currency cell. The share COUNT still totals -- a share is a share
    whatever it was paid for in -- but the amounts are omitted rather than
    added across currencies."""
    xml = build_xml(share_classes=2).replace(
        "<cr:currency>HKD</cr:currency>", "<cr:currency>USD</cr:currency>", 1)
    values = values_of(fill.render(xml))
    assert values[fm.SHARE_CAPITAL_TOTALS["total_number"]] == ["200"]
    assert fm.SHARE_CAPITAL_TOTALS["currency"] not in values
    assert fm.SHARE_CAPITAL_TOTALS["total_amount"] not in values


def test_the_amount_column_is_an_amount_and_the_number_column_is_a_count():
    """CR transmits "100" for both and prints "100" and "100.00". Rendering
    the raw string made the Total Number and Total Amount columns identical at
    a glance, which is exactly the pair a director is checking."""
    values = values_of(fill.render(build_xml()))
    assert values[fm.share_capital(0, "total_number")] == ["100"]
    assert values[fm.share_capital(0, "total_amount")] == ["100.00"]


@pytest.mark.parametrize("raw, count, amount", [
    ("10000", "10,000", "10,000.00"),
    ("1234567", "1,234,567", "1,234,567.00"),
    ("0.5", "0.5", "0.50"),
])
def test_figures_are_grouped_the_way_CR_prints_them(raw, count, amount):
    assert fill.format_count(raw) == count
    assert fill.format_amount(raw) == amount


def test_an_unparseable_figure_is_printed_as_it_stands():
    """These values have already been accepted by CR. One this cannot parse is
    to be shown verbatim, never blanked or guessed at."""
    assert fill.format_count("about 100") == "about 100"
    assert fill.format_amount("") == ""
    assert fill.format_count("") == ""


def test_a_share_count_reaches_the_schedule_grouped_too():
    values = values_of(fill.render(build_xml()))
    assert values[fm.SCHEDULE_1[0]["shares_held"]] == ["100"]
    assert values[fm.SCHEDULE_1_HEADER["class_total_issued"]] == ["1,000"]


# ---------------------------------------------------------------------------
# Page 8 -- the signature block
# ---------------------------------------------------------------------------

def test_the_signatory_name_is_on_the_name_line_not_in_the_date_box():
    """THE FIELD MAP HAD THESE THE WRONG WAY ROUND. `signed_name` pointed at
    fill_12_P.8 -- the Date box -- so every generated return showed the
    signatory floating above "日DD / 月MM / 年YYYY" and left "姓名 Name"
    blank."""
    values = values_of(fill.render(build_xml()))
    assert values[fm.MEMBERS_AND_SIGNATURE["signed_name"]] == ["Wong Mei Ling"]
    assert fm.MEMBERS_AND_SIGNATURE["signed_date"] not in values


def test_a_supplied_signing_date_lands_in_the_date_box():
    """It is not in the validated XML -- CR does not hand one back -- so it is
    the caller's to supply, and blank when they do not. A date printed beside
    an unsigned signature block would assert something untrue."""
    values = values_of(fill.render(build_xml(), signed_on="2026-07-25"))
    assert values[fm.MEMBERS_AND_SIGNATURE["signed_date"]] == ["25/07/2026"]


def test_the_continuation_sheet_counts_are_all_answered():
    """A blank count row reads as "nobody said whether pages are missing from
    this bundle". The specimen writes a nought in each of the five."""
    values = values_of(fill.render(build_xml()))
    ms = fm.MEMBERS_AND_SIGNATURE
    for key in ("count_sheet_a", "count_sheet_b", "count_sheet_c",
                "count_sheet_d", "count_sheet_e"):
        assert values[ms[key]] == ["0"], f"{key} was left blank"
    assert values[ms["count_schedule_1"]] == ["1"]
    assert values[ms["count_schedule_2"]] == ["0"]


# ---------------------------------------------------------------------------
# The presenter's block
# ---------------------------------------------------------------------------

def test_the_presenter_block_carries_GSHKs_whole_address_not_just_a_name():
    """This is the one block that tells CR where to write back about the
    filing. It rendered with an empty Address, Tel and Reference and named
    `no-reply@` -- the address the portal SENDS from, a different job that had
    been conflated with this one."""
    values = values_of(fill.render(build_xml()))
    m1 = fm.MAIN_1
    assert values[m1["presenter_name"]] == ["Get Started HK Limited"]
    address = values[m1["presenter_address"]][0]
    assert "World Trust Tower" in address and "Stanley Street" in address
    assert values[m1["presenter_tel"]] == ["2813 7600"]
    assert values[m1["presenter_email"]] == ["info@getstarted.hk"]
    assert "no-reply" not in address + values[m1["presenter_email"]][0]


def test_the_presenter_address_wraps_rather_than_shrinking_to_a_smear():
    """CR's box is 185pt wide, 66pt tall and set at 9pt -- sized for more than
    one line. Fitting GSHK's address across it on a single line drove the
    renderer to its 4pt floor, which is unreadable."""
    ap.register_fonts()
    rect = (0.0, 0.0, 185.5, 66.5)
    lines, size = ap.layout(fill.DEFAULT_PRESENTER["address"], rect,
                            size=fill.PRESENTER_SIZE, bold=False)
    assert len(lines) > 1, "the address did not wrap"
    assert size >= 8.0, f"the address was shrunk to {size}pt instead of wrapped"
    assert " ".join(lines) == fill.DEFAULT_PRESENTER["address"]


# ---------------------------------------------------------------------------
# Coded vocabularies: CR takes a code and PRINTS a name
# ---------------------------------------------------------------------------

def test_a_hong_kong_district_prints_its_name_not_its_code():
    values = values_of(fill.render(build_xml()))
    assert values[fm.MAIN_1["ro_district"]] == ["Central"]


def test_a_country_prints_its_name_not_its_code():
    """The reference return's director is Swedish. The XML says "SWE"."""
    xml = build_xml().replace("<cr:ctryRegion>HKG</cr:ctryRegion>",
                              "<cr:ctryRegion>SWE</cr:ctryRegion>")
    values = values_of(fill.render(xml))
    assert values[fm.DIRECTOR_INDIVIDUAL["addr_country"]] == ["Sweden"]


def test_a_passport_issuing_country_prints_its_name_too():
    xml = build_xml().replace(
        "<cr:indvHkidNo>A123</cr:indvHkidNo>",
        "<cr:indvPptIssCtry>SWE</cr:indvPptIssCtry>"
        "<cr:indvPptNo>AA253</cr:indvPptNo>")
    values = values_of(fill.render(xml))
    assert values[fm.DIRECTOR_INDIVIDUAL["passport_country"]] == ["Sweden"]


def test_an_overseas_city_line_is_left_exactly_as_filed():
    """`dstCtyStatePostal` is a controlled code only for a Hong Kong address.
    Everywhere else it is free text -- a city, a state, a postcode -- and must
    survive untouched, casing and all."""
    xml = (build_xml()
           .replace("<cr:dstCtyStatePostal>CENTRAL</cr:dstCtyStatePostal>",
                    "<cr:dstCtyStatePostal>Stockholm 11859"
                    "</cr:dstCtyStatePostal>")
           .replace("<cr:ctryRegion>HKG</cr:ctryRegion>",
                    "<cr:ctryRegion>SWE</cr:ctryRegion>"))
    values = values_of(fill.render(xml))
    assert values[fm.DIRECTOR_INDIVIDUAL["addr_district_city_state"]] == \
        ["Stockholm 11859"]


# ---------------------------------------------------------------------------
# Boxes with nothing to report
# ---------------------------------------------------------------------------

def test_a_section_that_does_not_apply_says_so_rather_than_going_blank():
    """The specimen uses N/A for a whole numbered section that does not apply
    to this company and a dash for a single absent particular, and does not
    use them interchangeably."""
    values = values_of(fill.render(build_xml()))
    m1, m2, ms = fm.MAIN_1, fm.MAIN_2, fm.MEMBERS_AND_SIGNATURE
    assert values[m1["business_name"]] == ["N/A"]         # s2, no trade name
    assert values[m1["fin_period_from_mm"]] == ["N/A"]    # s5, private company
    assert values[m1["fin_period_to_mm"]] == ["N/A"]
    assert values[ms["records_description"]] == ["N/A"]   # s15, kept at the RO
    assert values[ms["records_address"]] == ["N/A"]
    assert values[m2["email_address"]] == ["-"]           # s7
    assert values[m2["members_no_capital"]] == ["-"]      # s10


def test_a_public_company_still_states_its_financial_period():
    """The N/A on section 5 is "a private company need not complete this",
    not a blanket. A public company's real dates must not be overwritten."""
    values = values_of(fill.render(build_xml(), company_type="public"))
    assert values[fm.MAIN_1["fin_period_from_mm"]] == ["01"]
    assert values[fm.MAIN_1["fin_period_to_mm"]] == ["12"]


def test_an_absent_particular_of_a_real_officer_is_dashed():
    """The director in the fixture has a surname, an address and an HKID and
    none of the rest -- exactly like the specimen's Swedish director, whose
    Chinese name, previous names, alias, flat and building all read "-"."""
    values = values_of(fill.render(build_xml()))
    block = fm.DIRECTOR_INDIVIDUAL
    for key in ("name_zh", "prev_name_zh", "prev_name_en", "alias_zh",
                "alias_en", "passport_country", "passport_partial",
                "alternate_to"):
        assert values[block[key]] == ["-"], f"{key} was left blank"
    # ...and a particular that IS on record is untouched.
    assert values[block["surname_en"]] == ["CHAN"]
    assert values[block["hkid_partial"]] == ["A123"]


def test_an_officer_page_with_no_officer_stays_BLANK_not_dashed():
    """CR's form is static, so a company with no natural-person secretary
    still files page 3 -- and the specimen files it EMPTY. A dash says "this
    officer has no Chinese name"; a blank page says "there is no such
    officer". Dashing an unused page would assert an officer into existence.
    """
    values = values_of(fill.render(build_xml(secretaries=0)))
    for key in ("name_zh", "surname_en", "addr_flat_floor", "prev_name_en"):
        assert fm.SECRETARY_INDIVIDUAL[key] not in values, \
            f"the empty secretary page filled {key}"


def test_a_prose_box_is_left_empty_rather_than_dashed():
    """The TCSP "Reason" and a member's "Remarks" stay blank on the specimen:
    an empty prose box already reads as "nothing to say", while an empty NAME
    box reads as an omission."""
    values = values_of(fill.render(build_xml()))
    assert fm.SECRETARY_INDIVIDUAL["tcsp_reason"] not in values
    assert fm.SCHEDULE_1[0]["remarks"] not in values


# ---------------------------------------------------------------------------
# What the page actually draws
# ---------------------------------------------------------------------------

def _content(pdf_bytes: bytes, page_index: int) -> bytes:
    """One page's own content stream -- the baked layer, not its widgets."""
    page = PdfReader(io.BytesIO(pdf_bytes)).pages[page_index]
    return page.get_contents().get_data()


#: What `draw_tick` writes into the page: a black stroke of a set width with
#: round caps and joins, then a fresh path. CR's own printed layer is filled
#: artwork from a different generator and carries no such preamble, so
#: counting these counts OUR ticks and nothing else.
_TICK_MARK = b"1 J\n1 j\nn\n"


def test_a_tick_is_drawn_into_the_page_and_not_left_to_the_widget():
    """CR's template does carry a working `/On` appearance stream, so a viewer
    that renders form widgets shows the tick and one that does not shows an
    UNTICKED box. That is not cosmetic: the boxes are section 3's company
    type, section 14's "members are listed in Schedule 1" and section 16's
    statement, so the same bytes read as a different statutory declaration
    depending on the renderer. It is the identical failure `bake()` exists to
    end for text, and it was left in place for the ticks.

    A stroked checkmark in the page's own content stream is what proves the
    tick no longer depends on the viewer -- one per ticked box, on the page
    that box is on.
    """
    pdf = fill.render(build_xml())
    reader = PdfReader(io.BytesIO(pdf))
    total = 0
    for page_index, page in enumerate(reader.pages):
        ticked = 0
        for annot in (page.get("/Annots") or []):
            obj = annot.get_object()
            if obj.get("/FT") != "/Btn" or not ap._is_ticked(obj):
                continue
            ticked += 1
            assert int(obj.get("/F", 0)) & 2, \
                "a ticked checkbox widget is still visible over the layer"
        drawn = _content(pdf, page_index).count(_TICK_MARK)
        assert drawn == ticked, (
            f"page {page_index + 1} has {ticked} ticked boxes but {drawn} "
            f"drawn ticks")
        total += ticked
    # Section 3 (private), section 14 (Schedule 1), section 16 (statement) and
    # the director's capacity. If this ever finds none, the test is vacuous.
    assert total >= 4, f"only {total} ticks found; the discovery broke"


def test_values_are_drawn_at_CRs_own_size_not_two_points_smaller():
    """THE "the fonts still look different" BUG. Every value on every page
    drew at 10pt where CR's template sets 12 -- a sixth smaller than the
    specimen, which beside it reads as a different typeface rather than a
    smaller one. The face was never wrong.
    """
    pdf = fill.render(build_xml())
    page1 = PdfReader(io.BytesIO(pdf)).pages[0]
    sizes = {}

    def visitor(text, cm, tm, font_dict, font_size):
        if text and text.strip():
            sizes[text.strip()] = font_size

    page1.extract_text(visitor_text=visitor)
    drawn = next((size for text, size in sizes.items()
                  if "Flat A, 12/F" in text), None)
    assert drawn == 12.0, f"the registered office drew at {drawn}pt, not 12pt"


def test_the_form_default_size_is_the_one_CRs_template_declares():
    """287 of the template's 318 text widgets carry `/DA "/PMingLiU 12 Tf"`.
    Nothing on Form NAR1 is set at 10pt by default."""
    assert ap.DEFAULT_SIZE == 12.0
    assert ap.da_size("/PMingLiU 12 Tf 0 g") == 12.0
    assert ap.da_size("/TimesNewRoman 9 Tf 0 g") == 9.0
    # 0 is the spec's auto-size, which is "CR did not say" -- the caller works
    # it out from the box.
    assert ap.da_size("/PMingLiU 0 Tf 0 g") is None
    assert ap.da_size(None) is None


def test_wrapping_never_rewrites_a_value_that_already_fits():
    """`_company_name` joins the English and Chinese names with a DOUBLE space
    on purpose. Running every value through `split()` collapsed it."""
    ap.register_fonts()
    name = "TEST COMPANY LIMITED  測試有限公司"
    assert ap.wrap(name, 500.0, 12.0) == [name]
