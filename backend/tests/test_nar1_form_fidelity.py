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

@pytest.mark.parametrize("capacity, struck, kept", [
    # A BODY-CORPORATE capacity reads "<office in the body corporate> of the
    # <office the BODY CORPORATE holds in the filing company> (Body Corporate)".
    # GSHK is the client's company secretary and a GSHK director signs for it,
    # so the name on the line is GSHK and the word to keep is Company Secretary.
    ("Director of the Company Secretary (Body Corporate)",
     "strike_director", "strike_company_secretary"),
    ("Authorized Person of the Company Secretary (Body Corporate)",
     "strike_director", "strike_company_secretary"),
    # The same body corporate sitting as a DIRECTOR instead.
    ("Director of the Director (Body Corporate)",
     "strike_company_secretary", "strike_director"),
    # An INDIVIDUAL capacity simply IS the office held.
    ("Director", "strike_company_secretary", "strike_director"),
    ("Company Secretary", "strike_director", "strike_company_secretary"),
])
def test_the_signature_line_strikes_the_capacity_that_does_not_apply(
        capacity, struck, kept):
    """The printed line reads "董事 Director／公司秘書 Company Secretary *" over
    "*請刪去不適用者 Delete whichever does not apply", and the renderer deleted
    NEITHER — so every return the portal has produced claimed the signatory was
    both, on the one line that says who is answerable for the return.

    CR implements the deletion as two dropdowns whose only non-blank option is
    a long rule; selecting it strikes the word through.
    """
    values = values_of(fill.render_fields(build_xml(capacity=capacity)))
    assert values[fm.SIGNATURE_STRIKE[struck]] == [fm.STRIKE_THROUGH]
    # The word that DOES apply keeps the template's blank option — the
    # dropdowns are always present, so "not struck" is a value, not an absence.
    assert values[fm.SIGNATURE_STRIKE[kept]] != [fm.STRIKE_THROUGH]


@pytest.mark.parametrize("capacity", [
    "Authorized Representative",
    "Authorized Representative of the Authorized Representative (Body Corporate)",
])
def test_a_capacity_that_is_neither_strikes_neither(capacity):
    """CR's vocabularies also carry Authorized Representative and Authorized
    Person, which are neither of the two printed words. Striking one would
    assert an office the signatory does not hold, so both are left standing —
    the form is then no worse than it was, and not false."""
    values = values_of(fill.render_fields(build_xml(capacity=capacity)))
    assert values[fm.SIGNATURE_STRIKE["strike_director"]] != [fm.STRIKE_THROUGH]
    assert values[fm.SIGNATURE_STRIKE["strike_company_secretary"]] \
        != [fm.STRIKE_THROUGH]


def test_a_return_with_no_capacity_recorded_still_renders():
    """`tpsi_filings.validated_xml` rows frozen before the capacity picker
    existed carry no selectCapacityDesc. Striking nothing is the old behaviour;
    raising would make an already-validated filing unprintable."""
    values = values_of(fill.render_fields(build_xml(capacity="")))
    assert values[fm.SIGNATURE_STRIKE["strike_director"]] != [fm.STRIKE_THROUGH]
    assert values[fm.SIGNATURE_STRIKE["strike_company_secretary"]] \
        != [fm.STRIKE_THROUGH]


def test_the_strike_survives_flattening():
    """The shipped return is FLAT, and `bake()` refuses to flatten a value it
    cannot draw rather than deleting it silently. A strike that vanished at
    flattening would be the same defect wearing a tick."""
    pdf = fill.render(build_xml(
        capacity="Director of the Company Secretary (Body Corporate)"))
    reader = PdfReader(io.BytesIO(pdf))
    assert not (reader.pages[7].get("/Annots") or []), \
        "page 8 still carries widgets; the shipped return must be flat"
    # Drawn as page content: a rule across the struck word's box.
    assert "Director" in reader.pages[7].extract_text()


def test_one_corporate_secretary_fills_12b_and_attaches_no_continuation_sheet():
    """5,603 of 5,604 rendered returns carried a Continuation Sheet B naming
    "GETSTA", because the mapper emitted the one company secretary twice —
    once from `company_secretaries` and once from `entity_officers`, whose
    `corporate_name` holds Viewpoint's entity code. Page 8 then declared
    "Continuation Sheet B: 1" for a sheet that should not exist.

    Asserted on the RENDERED form: one corpSec fills section 12B and the sheet
    count stays 0.
    """
    values = values_of(fill.render_fields(
        build_xml(secretaries=0,
                  corporate_secretaries=("Get Started HK Limited",))))
    assert values[fm.SECRETARY_CORPORATE["name_en"]] == ["Get Started HK Limited"]
    # Field 19 — blank on every return before this, because the secretary
    # register has no BR column and nothing resolved the party's entity.
    assert values[fm.SECRETARY_CORPORATE["own_br_number"]] == ["67169839"]
    assert values[fm.MEMBERS_AND_SIGNATURE["count_sheet_b"]] == ["0"]


def test_two_corporate_secretaries_still_fill_continuation_sheet_b():
    """The duplicate was removed, not the capability."""
    values = values_of(fill.render_fields(
        build_xml(secretaries=0,
                  corporate_secretaries=("First Secretary Limited",
                                         "Second Secretary Limited"))))
    assert values[fm.MEMBERS_AND_SIGNATURE["count_sheet_b"]] == ["1"]


def test_the_share_capital_total_row_is_filled():
    """It was BLANK on every return ever generated.
    `field_map.SHARE_CAPITAL_TOTALS` existed from the day the map was written
    and nothing ever referenced it."""
    values = values_of(fill.render_fields(build_xml()))
    assert values[fm.SHARE_CAPITAL_TOTALS["currency"]] == ["HKD"]
    assert values[fm.SHARE_CAPITAL_TOTALS["total_number"]] == ["100"]
    assert values[fm.SHARE_CAPITAL_TOTALS["total_amount"]] == ["100.00"]
    assert values[fm.SHARE_CAPITAL_TOTALS["paid_up"]] == ["100.00"]


def test_the_total_row_sums_the_classes_rather_than_copying_one():
    """Three classes of 100 total 300. Copying the first row's figure would
    under-report the company's issued capital by two thirds."""
    values = values_of(fill.render_fields(build_xml(share_classes=3)))
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
    values = values_of(fill.render_fields(xml))
    assert values[fm.SHARE_CAPITAL_TOTALS["total_number"]] == ["200"]
    assert fm.SHARE_CAPITAL_TOTALS["currency"] not in values
    assert fm.SHARE_CAPITAL_TOTALS["total_amount"] not in values


def test_the_amount_column_is_an_amount_and_the_number_column_is_a_count():
    """CR transmits "100" for both and prints "100" and "100.00". Rendering
    the raw string made the Total Number and Total Amount columns identical at
    a glance, which is exactly the pair a director is checking."""
    values = values_of(fill.render_fields(build_xml()))
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
    """The member's own holding, and the class total above it. `issued_per_class`
    is deliberately NOT the holding, so a total copied from the wrong place
    cannot pass by coinciding with it."""
    values = values_of(fill.render_fields(build_xml(issued_per_class=5000)))
    assert values[fm.SCHEDULE_1[0]["shares_held"]] == ["100"]
    assert values[fm.SCHEDULE_1_HEADER["class_total_issued"]] == ["5,000"]


def test_the_schedule_class_total_is_section_11s_figure_for_that_class():
    """Schedule 1's "Total Number of Issued Shares in this Class" printed EMPTY
    on every return the portal has produced, while section 11 three pages
    earlier printed the number correctly.

    The renderer read `noOfShareIssuedOnThisCls` off the schedule node, where
    CR's schema has no such element: `schedule1/shares/share` carries
    `clsOfShares` and nothing else about the class, and CR's remark on it says
    the total "must match with the total number of issued shares for that class
    in the Share Capital section". So the schedule refers to section 11, and
    the renderer has to follow the reference.
    """
    values = values_of(fill.render_fields(build_xml(issued_per_class=12345)))
    assert values[fm.SCHEDULE_1_HEADER["share_class"]] == ["Class0"]
    assert values[fm.SCHEDULE_1_HEADER["class_total_issued"]] == ["12,345"]
    # The same figure section 11 states for that class — one number, one source.
    assert values[fm.share_capital(0, "total_number")] == ["12,345"]


def test_a_schedule_class_missing_from_section_11_refuses_rather_than_printing_blank():
    """Members listed under a class the Share Capital section does not declare.
    CR would refuse the pair, and a blank box is how the defect above survived
    a green suite for so long."""
    xml = build_xml().replace(
        "<cr:clsOfShares>Class0</cr:clsOfShares>\n          <cr:shareHolderGrps>",
        "<cr:clsOfShares>Nonesuch</cr:clsOfShares>\n          <cr:shareHolderGrps>")
    with pytest.raises(fill.FormFillError) as exc:
        fill.render_fields(xml)
    assert "Nonesuch" in str(exc.value)


# ---------------------------------------------------------------------------
# Page 8 -- the signature block
# ---------------------------------------------------------------------------

def test_the_signatory_name_is_on_the_name_line_not_in_the_date_box():
    """THE FIELD MAP HAD THESE THE WRONG WAY ROUND. `signed_name` pointed at
    fill_12_P.8 -- the Date box -- so every generated return showed the
    signatory floating above "日DD / 月MM / 年YYYY" and left "姓名 Name"
    blank."""
    # A FILED return, so both boxes carry something: the swap this test exists
    # for is invisible on a copy whose date box is legitimately empty.
    values = values_of(fill.render_fields(build_xml(),
                                          submitted_on="2026-11-01"))
    assert values[fm.MEMBERS_AND_SIGNATURE["signed_name"]] == ["Wong Mei Ling"]
    assert values[fm.MEMBERS_AND_SIGNATURE["signed_date"]] == ["01/11/2026"]


def test_a_submission_date_lands_in_the_date_box():
    """It is not in the validated XML -- CR does not hand one back -- so it is
    the caller's to supply."""
    values = values_of(fill.render_fields(build_xml(),
                                          submitted_on="2026-07-25"))
    assert values[fm.MEMBERS_AND_SIGNATURE["signed_date"]] == ["25/07/2026"]


def test_the_date_box_is_empty_until_the_return_has_been_FILED():
    """THIS REVERSES "the box is never left empty" (Levi 2026-09-22).

    That rule dated an unfiled copy TODAY, which made the date wrong in two
    ways at once: a director approving on 28 October saw 28 October on a
    return CR would not receive until 1 November, and a copy downloaded twice
    on different days showed two different dates for one return. CR's box
    carries the day the return was FILED -- so until CR has it, the portal
    has no date to print and prints none.
    """
    values = values_of(fill.render_fields(build_xml()))
    assert fm.MEMBERS_AND_SIGNATURE["signed_date"] not in values


def test_an_absent_date_is_blank_rather_than_today():
    """The unit behind the rendered form. Neither an empty string nor None is
    "today": both mean nothing has been filed."""
    assert fill.signature_date("") == ""
    assert fill.signature_date(None) == ""


def test_a_value_no_date_can_be_read_out_of_prints_nothing():
    """Falling back to today would print a date that is not the filing date
    and cannot be distinguished from one that is. Blank is the honest
    failure."""
    assert fill.signature_date("whenever it was") == ""


def test_a_submission_timestamp_is_converted_to_hong_kong_not_truncated():
    """`tpsi_filings.submitted_at` arrives as a UTC timestamptz -- Railway and
    Supabase both run UTC. A return filed at 01:00 in the Hong Kong office is
    17:00 the previous day in UTC, and printing that day is a permanent
    misstatement of when the return was filed."""
    assert fill.signature_date("2026-07-25T02:30:00+00:00") == "25/07/2026"
    assert fill.signature_date("2026-07-25T17:00:00+00:00") == "26/07/2026"
    assert fill.signature_date("2026-07-25T17:00:00Z") == "26/07/2026"


def test_a_plain_date_is_taken_verbatim_and_never_shifted():
    """A date somebody typed is already in the terms they meant. Only a
    TIMESTAMP gets a timezone applied -- shifting "2026-07-25" would move it."""
    assert fill.signature_date("2026-07-25") == "25/07/2026"
    assert fill.signature_date("25/07/2026") == "25/07/2026"
    assert fill.signature_date("5/7/2026") == "05/07/2026"


def test_the_continuation_sheet_counts_are_all_answered():
    """A blank count row reads as "nobody said whether pages are missing from
    this bundle". The specimen writes a nought in each of the five."""
    values = values_of(fill.render_fields(build_xml()))
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
    values = values_of(fill.render_fields(build_xml()))
    m1 = fm.MAIN_1
    assert values[m1["presenter_name"]] == ["Get Started HK Limited"]
    address = values[m1["presenter_address"]][0]
    assert "World Trust Tower" in address and "Stanley Street" in address
    assert values[m1["presenter_tel"]] == ["2813 7600"]
    assert values[m1["presenter_email"]] == ["info@getstarted.hk"]
    assert "no-reply" not in address + values[m1["presenter_email"]][0]


def test_the_reference_is_the_form_the_year_and_the_company():
    """`NAR1/<year>/<company name>` (Levi 2026-09-04). The box rendered EMPTY
    -- `DEFAULT_PRESENTER` carries no reference and nothing derived one -- on
    the only line of the form that tells CR which of GSHK's files a piece of
    correspondence belongs to."""
    values = values_of(fill.render_fields(build_xml()))
    assert values[fm.MAIN_1["presenter_reference"]] == \
        ["NAR1/2026/TEST COMPANY LIMITED"]


def test_the_reference_year_is_the_returns_own_not_the_calendar_year():
    """A 2025 return filed late is still the 2025 return. Stamping it with the
    year it happened to be printed would give two different references to one
    filing."""
    values = values_of(fill.render_fields(build_xml(date="01/02/2025")))
    assert values[fm.MAIN_1["presenter_reference"]].pop().startswith(
        "NAR1/2025/")


def test_the_reference_box_is_the_width_the_fitter_assumes():
    """`PRESENTER_REFERENCE_WIDTH` is transcribed from CR's template, so it can
    drift if the template is ever replaced. Re-measure it here rather than let
    a new revision overflow the box in silence."""
    pymupdf = pytest.importorskip("pymupdf")
    page = pymupdf.open(str(fill.TEMPLATE))[0]
    for widget in page.widgets():
        if widget.field_name != fm.MAIN_1["presenter_reference"]:
            continue
        rect = widget.rect
        assert rect.width - 2 * ap._INSET == pytest.approx(
            fill.PRESENTER_REFERENCE_WIDTH, abs=0.5)
        # ONE line. If a future template makes this box taller the fitter can
        # be relaxed, but until then a two-line reference would overflow.
        assert ap._lines_that_fit(
            rect.height, fill.PRESENTER_REFERENCE_MIN_SIZE) == 1
        return
    pytest.fail("the Reference widget is not on page 1 of CR's template")


def test_a_long_company_name_is_shortened_rather_than_shrunk_to_nothing():
    """The box is one line of 158pt. `layout()` would take a 65-character name
    down toward its 4pt floor -- the same grey smear the presenter's address
    was rescued from, except this box cannot wrap out of it. So the NAME is
    shortened, on a word boundary, and the prefix that makes it a reference
    survives."""
    long_name = "A VERY LONG HONG KONG COMPANY NAME (INTERNATIONAL) LIMITED"
    xml = build_xml().replace("TEST COMPANY LIMITED", long_name)
    reference = values_of(fill.render_fields(xml))[
        fm.MAIN_1["presenter_reference"]].pop()

    assert reference.startswith("NAR1/2026/")
    assert reference.endswith("...")
    assert long_name.startswith(reference[len("NAR1/2026/"):-len("...")].strip())
    ap.register_fonts()
    assert ap.measure(reference, fill.PRESENTER_REFERENCE_MIN_SIZE,
                      bold=False) <= fill.PRESENTER_REFERENCE_WIDTH


def test_the_reference_is_never_drawn_below_the_legible_floor():
    """Shortening is pointless if the renderer then shrinks it anyway. What is
    actually drawn has to be at least `PRESENTER_REFERENCE_MIN_SIZE`."""
    ap.register_fonts()
    long_name = "A VERY LONG HONG KONG COMPANY NAME (INTERNATIONAL) LIMITED"
    xml = build_xml().replace("TEST COMPANY LIMITED", long_name)
    reference = values_of(fill.render_fields(xml))[
        fm.MAIN_1["presenter_reference"]].pop()
    rect = (0.0, 0.0, fill.PRESENTER_REFERENCE_WIDTH + 2 * ap._INSET, 14.02)
    lines, size = ap.layout(reference, rect, size=ap.DEFAULT_SIZE, bold=False)
    assert len(lines) == 1
    assert size >= fill.PRESENTER_REFERENCE_MIN_SIZE, \
        f"the reference drew at {size}pt"


def test_a_caller_with_its_own_reference_scheme_still_wins():
    values = values_of(fill.render_fields(
        build_xml(),
        presenter=dict(fill.DEFAULT_PRESENTER, reference="GS/2026/0042")))
    assert values[fm.MAIN_1["presenter_reference"]] == ["GS/2026/0042"]


def test_the_presenter_address_wraps_rather_than_shrinking_to_a_smear():
    """CR's box is 185pt wide and 66pt tall -- sized for more than one line,
    and CR's own return does wrap it across two. Fitting GSHK's address across
    it on a single line drove the renderer to its 4pt floor, unreadable."""
    ap.register_fonts()
    rect = (0.0, 0.0, 185.5, 66.5)
    lines, size = ap.layout(fill.DEFAULT_PRESENTER["address"], rect,
                            size=ap.DEFAULT_SIZE, bold=False)
    assert len(lines) > 1, "the address did not wrap"
    assert size >= 8.0, f"the address was shrunk to {size}pt instead of wrapped"
    assert " ".join(lines) == fill.DEFAULT_PRESENTER["address"]


# ---------------------------------------------------------------------------
# Coded vocabularies: CR takes a code and PRINTS a name
# ---------------------------------------------------------------------------

def test_a_hong_kong_district_prints_its_name_not_its_code():
    values = values_of(fill.render_fields(build_xml()))
    assert values[fm.MAIN_1["ro_district"]] == ["Central"]


def test_a_country_prints_its_name_not_its_code():
    """The reference return's director is Swedish. The XML says "SWE"."""
    xml = build_xml().replace("<cr:ctryRegion>HKG</cr:ctryRegion>",
                              "<cr:ctryRegion>SWE</cr:ctryRegion>")
    values = values_of(fill.render_fields(xml))
    assert values[fm.DIRECTOR_INDIVIDUAL["addr_country"]] == ["Sweden"]


def test_a_passport_issuing_country_prints_its_name_too():
    xml = build_xml().replace(
        "<cr:indvHkidNo>A123</cr:indvHkidNo>",
        "<cr:indvPptIssCtry>SWE</cr:indvPptIssCtry>"
        "<cr:indvPptNo>AA253</cr:indvPptNo>")
    values = values_of(fill.render_fields(xml))
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
    values = values_of(fill.render_fields(xml))
    assert values[fm.DIRECTOR_INDIVIDUAL["addr_district_city_state"]] == \
        ["Stockholm 11859"]


# ---------------------------------------------------------------------------
# Boxes with nothing to report
# ---------------------------------------------------------------------------

def test_a_section_that_does_not_apply_says_so_rather_than_going_blank():
    """The specimen uses N/A for a whole numbered section that does not apply
    to this company and a dash for a single absent particular, and does not
    use them interchangeably."""
    values = values_of(fill.render_fields(build_xml()))
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
    values = values_of(fill.render_fields(build_xml(), company_type="public"))
    assert values[fm.MAIN_1["fin_period_from_mm"]] == ["01"]
    assert values[fm.MAIN_1["fin_period_to_mm"]] == ["12"]


def test_an_absent_particular_of_a_real_officer_is_dashed():
    """The director in the fixture has a surname, an address and an HKID and
    none of the rest -- exactly like the specimen's Swedish director, whose
    Chinese name, previous names, alias, flat and building all read "-"."""
    values = values_of(fill.render_fields(build_xml()))
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
    values = values_of(fill.render_fields(build_xml(secretaries=0)))
    for key in ("name_zh", "surname_en", "addr_flat_floor", "prev_name_en"):
        assert fm.SECRETARY_INDIVIDUAL[key] not in values, \
            f"the empty secretary page filled {key}"


def test_a_prose_box_is_left_empty_rather_than_dashed():
    """The TCSP "Reason" and a member's "Remarks" stay blank on the specimen:
    an empty prose box already reads as "nothing to say", while an empty NAME
    box reads as an omission."""
    values = values_of(fill.render_fields(build_xml()))
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
    that box is on. The boxes are counted on the FILLED form, because the
    shipped return has no checkbox widgets left: `bake()` removes them, since
    a phone that ignored their Hidden flag drew a second tick over ours.
    """
    pdf = fill.render(build_xml())
    filled = PdfReader(io.BytesIO(fill.render_fields(build_xml())))
    total = 0
    for page_index, page in enumerate(filled.pages):
        ticked = sum(1 for annot in (page.get("/Annots") or [])
                     if annot.get_object().get("/FT") == "/Btn"
                     and ap._is_ticked(annot.get_object()))
        drawn = _content(pdf, page_index).count(_TICK_MARK)
        assert drawn == ticked, (
            f"page {page_index + 1} has {ticked} ticked boxes but {drawn} "
            f"drawn ticks")
        total += ticked
    # Section 3 (private), section 14 (Schedule 1), section 16 (statement) and
    # the director's capacity. If this ever finds none, the test is vacuous.
    assert total >= 4, f"only {total} ticks found; the discovery broke"


def test_values_are_drawn_at_the_size_CR_PRINTS_not_the_size_it_types():
    """THE REPORT THAT REOPENED THIS: "the font looks smaller on the real form
    and the family looks different too."

    The size was the whole of it. Every value drew at the template's `/DA` 12pt
    where CR's own filed return prints 10, and a fifth too large is not read as
    a larger typeface -- it is read as a different one.

    `/DA` was the wrong source, not a misread one. Acrobat put the same
    `/PMingLiU 12 Tf` on 287 of the form's 298 text widgets, the BR-number
    header CR prints at 14pt and the presenter's block CR prints at 10pt
    regular among them. It is the appearance for TYPING into the blank form.
    The sizes now come from `appearance.DEFAULT_SIZE` and `fill.FIELD_SIZES`,
    both measured off the specimen.
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
    assert drawn == 10.0, f"the registered office drew at {drawn}pt, not 10pt"


def test_the_templates_DA_is_not_consulted_for_the_size():
    """`da_size()` and `_auto_size()` were deleted rather than left unused: an
    unreferenced reader of `/DA` is an invitation to wire it back in, and
    wiring it back in is exactly the regression this file's specimen tests
    exist to catch."""
    assert ap.DEFAULT_SIZE == 10.0
    assert not hasattr(ap, "da_size")
    assert not hasattr(ap, "_auto_size")


def test_wrapping_never_rewrites_a_value_that_already_fits():
    """`_company_name` joins the English and Chinese names with a DOUBLE space
    on purpose. Running every value through `split()` collapsed it."""
    ap.register_fonts()
    name = "TEST COMPANY LIMITED  測試有限公司"
    assert ap.wrap(name, 500.0, 12.0) == [name]
