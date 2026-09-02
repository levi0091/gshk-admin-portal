"""Rendering CR's Form NAR1 from a validated return.

THE FAILURE THIS GUARDS AGAINST is not a crash. It is a return that renders
beautifully and is WRONG: a third director silently dropped because the printed
form holds two, a day and a year transposed because CR sends two date formats,
a private company's section 5 completed when the form says it must not be.
Every one of those produces a document a client would approve and CR would
register.

So the assertions here are about content and completeness, read back out of the
rendered PDF, rather than about the call not raising.
"""
import re

import pytest

pytest.importorskip("pypdf")
from pypdf import PdfReader  # noqa: E402
import io  # noqa: E402

from services.nar1_form import field_map as fm  # noqa: E402
from services.nar1_form import fill  # noqa: E402


# ---------------------------------------------------------------------------
# Building a return
# ---------------------------------------------------------------------------

def _address(prefix="Flat 1"):
    return f"""
      <cr:stdAddress>
        <cr:flatFlrBlk>{prefix}</cr:flatFlrBlk>
        <cr:bldg>Tower</cr:bldg>
        <cr:stEstLotVlg>1 Test Street</cr:stEstLotVlg>
        <cr:dstCtyStatePostal>CENTRAL</cr:dstCtyStatePostal>
        <cr:ctryRegion>HKG</cr:ctryRegion>
      </cr:stdAddress>"""


def _ind_dir(surname):
    return f"""
      <cr:indDir>
        <cr:dirInd>Y</cr:dirInd>
        <cr:indvEngSname>{surname}</cr:indvEngSname>
        <cr:indvEngOname>Tai Man</cr:indvEngOname>
        {_address()}
        <cr:indvHkidNo>A123</cr:indvHkidNo>
      </cr:indDir>"""


def _corp_dir(name):
    return f"""
      <cr:corpDir>
        <cr:dirInd>Y</cr:dirInd>
        <cr:corpEngName>{name}</cr:corpEngName>
        {_address()}
        <cr:corpBrNo>99999999</cr:corpBrNo>
      </cr:corpDir>"""


def _member(surname, shares):
    return f"""
        <cr:shareHolderGrp>
          <cr:sharesAlloted>{shares}</cr:sharesAlloted>
          <cr:shType>1</cr:shType>
          <cr:allotteeRec>
            <cr:allottee>
              <cr:allotteeType>I</cr:allotteeType>
              <cr:indvSurname>{surname}</cr:indvSurname>
              <cr:indvOtherName>Siu Ming</cr:indvOtherName>
              <cr:allotteeAddr>
                <cr:flatFlrBlk>Room A</cr:flatFlrBlk>
                <cr:bldg>ABC Building</cr:bldg>
                <cr:stEstLotVlg>888 Queens Road</cr:stEstLotVlg>
                <cr:dstCtyStatePostal>CENTRAL</cr:dstCtyStatePostal>
                <cr:ctryRegion>HKG</cr:ctryRegion>
              </cr:allotteeAddr>
            </cr:allottee>
          </cr:allotteeRec>
        </cr:shareHolderGrp>"""


def build_xml(*, directors=("CHAN",), corporate_directors=(),
              secretaries=1, members=("WONG",), date="01/02/2026",
              share_classes=1):
    """A validated return, in CR's own shape: a BARE fragment with undeclared
    `cr:` prefixes, exactly as `tpsi_filings.validated_xml` stores it."""
    capitals = "".join(f"""
        <cr:shareCapital>
          <cr:clsOfShares>Class{i}</cr:clsOfShares>
          <cr:currency>HKD</cr:currency>
          <cr:noOfShareIssuedOnThisCls>100</cr:noOfShareIssuedOnThisCls>
          <cr:issuedCapital>100</cr:issuedCapital>
          <cr:paidUpCapital>100</cr:paidUpCapital>
        </cr:shareCapital>""" for i in range(share_classes))

    secs = "".join(f"""
      <cr:indSec>
        <cr:indvEngSname>SEC{i}</cr:indvEngSname>
        <cr:indvEngOname>Ling</cr:indvEngOname>
        {_address()}
      </cr:indSec>""" for i in range(secretaries))

    return f"""
    <cr:submission>
      <cr:EForm><cr:formModel>
        <cr:brNo>T0001137</cr:brNo>
        <cr:compNameE>TEST COMPANY LIMITED</cr:compNameE>
        <cr:compNameC>測試有限公司</cr:compNameC>
        <cr:formCode>NAR1</cr:formCode>
        <cr:dateReturnMadeUp>{date}</cr:dateReturnMadeUp>
        <cr:dateReturnFrom>2025-01-01</cr:dateReturnFrom>
        <cr:dateReturnTo>2025-12-31</cr:dateReturnTo>
        <cr:roAddr>
          <cr:flatFlrBlk>Flat A, 12/F</cr:flatFlrBlk>
          <cr:bldg>Test Tower</cr:bldg>
          <cr:stEstLotVlg>1 Test Street</cr:stEstLotVlg>
          <cr:dstCtyStatePostal>CENTRAL</cr:dstCtyStatePostal>
          <cr:ctryRegion>HKG</cr:ctryRegion>
        </cr:roAddr>
        <cr:selectPersonName>Wong Mei Ling</cr:selectPersonName>
        <cr:shareCapitals>{capitals}</cr:shareCapitals>
        <cr:indSecList>{secs}</cr:indSecList>
        <cr:indDirList>{"".join(_ind_dir(d) for d in directors)}</cr:indDirList>
        <cr:corpDirList>
          {"".join(_corp_dir(c) for c in corporate_directors)}
        </cr:corpDirList>
        <cr:schedule1><cr:shares><cr:share>
          <cr:clsOfShares>Ordinary</cr:clsOfShares>
          <cr:noOfShareIssuedOnThisCls>1000</cr:noOfShareIssuedOnThisCls>
          <cr:shareHolderGrps>
            {"".join(_member(m, 100) for m in members)}
          </cr:shareHolderGrps>
        </cr:share></cr:shares></cr:schedule1>
      </cr:formModel></cr:EForm>
    </cr:submission>"""


def values_of(pdf_bytes) -> dict:
    """Every filled field, keyed by the name it had on CR's template.

    The renderer suffixes each page copy's fields (`fill_6_P.13__p7`) so two
    continuation sheets do not collide; this strips that back off, keeping ALL
    values per original name so a test can assert on both copies.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    out = {}
    for name, spec in (reader.get_fields() or {}).items():
        value = spec.get("/V")
        if value in (None, ""):
            continue
        original = re.sub(r"__p\d+$", "", name)
        out.setdefault(original, []).append(str(value))
    return out


def text_of(pdf_bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


# ---------------------------------------------------------------------------
# The basics
# ---------------------------------------------------------------------------

def test_it_renders_CRs_own_form_not_a_summary():
    """The whole point: the client sees Form NAR1, not our field table."""
    pdf = fill.render(build_xml())
    assert "Annual Return" in text_of(pdf)
    assert "Form NAR1" in text_of(pdf)


def test_the_printed_notes_are_dropped():
    """Pages 16-27 are CR's guidance for someone completing the form by hand.
    Twelve pages of it attached to a return a client must read is noise."""
    pdf = fill.render(build_xml())
    assert len(PdfReader(io.BytesIO(pdf)).pages) < 16
    assert "Notes for Completion" not in text_of(pdf)


def test_the_company_identifies_itself_on_every_page():
    """A page separated from the bundle must still say which company it is."""
    values = values_of(fill.render(build_xml()))
    for header in (fm.MAIN_1["br_number"], fm.MAIN_2["br_number"],
                   fm.SECRETARY_INDIVIDUAL["br_number"]):
        assert values.get(header) == ["T0001137"]


def test_the_return_is_read_only():
    """The client is asked to APPROVE this, not to edit it."""
    reader = PdfReader(io.BytesIO(fill.render(build_xml())))
    for page in reader.pages:
        for annot in (page.get("/Annots") or []):
            assert int(annot.get_object().get("/Ff", 0)) & 1, \
                "a field is still editable"


def test_it_refuses_a_filing_with_no_validated_xml():
    with pytest.raises(fill.FormFillError, match="no validated XML"):
        fill.render("")


# ---------------------------------------------------------------------------
# Dates — CR sends two formats
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("given, expected", [
    ("01/02/2026", ("01", "02", "2026")),   # what a real validateForm returned
    ("2026-02-01", ("01", "02", "2026")),   # what the schema implies
    ("20260201", ("01", "02", "2026")),
    ("1/2/2026", ("01", "02", "2026")),     # unpadded
    ("", ("", "", "")),
    ("not a date", ("", "", "")),
])
def test_both_of_CRs_date_formats_are_read_the_same_way(given, expected):
    """A real `dateReturnMadeUp` came back "01/01/2026" while the schema's
    other dates are ISO. Assuming one silently transposes day and year on the
    other — on a statutory return, on the date the whole filing hangs from."""
    assert fill.split_date(given) == expected


def test_the_return_date_lands_in_the_right_boxes():
    values = values_of(fill.render(build_xml(date="09/03/2026")))
    assert values[fm.MAIN_1["return_date_dd"]] == ["09"]
    assert values[fm.MAIN_1["return_date_mm"]] == ["03"]
    assert values[fm.MAIN_1["return_date_yyyy"]] == ["2026"]


# ---------------------------------------------------------------------------
# Company type
# ---------------------------------------------------------------------------

def test_a_private_company_ticks_private_and_leaves_section_5_empty():
    """"A private company needs not complete this section" — the form's own
    instruction. Filling it would assert something about financial statements
    a private company does not deliver."""
    values = values_of(fill.render(build_xml(), company_type="private"))
    assert values[fm.MAIN_1["type_private"]] == [fm.CHECKBOX_ON]
    assert fm.MAIN_1["type_public"] not in values
    for field in ("fin_period_from_dd", "fin_period_to_yyyy"):
        assert fm.MAIN_1[field] not in values


def test_a_public_company_ticks_public_and_completes_section_5():
    values = values_of(fill.render(build_xml(), company_type="public"))
    assert values[fm.MAIN_1["type_public"]] == [fm.CHECKBOX_ON]
    assert fm.MAIN_1["type_private"] not in values
    assert values[fm.MAIN_1["fin_period_from_yyyy"]] == ["2025"]


def test_a_guarantee_company_ticks_guarantee():
    values = values_of(fill.render(build_xml(), company_type="guarantee"))
    assert values[fm.MAIN_1["type_guarantee"]] == [fm.CHECKBOX_ON]


def test_only_a_private_company_makes_the_section_16_statement():
    """It is a statement of fact about not having invited public subscription,
    so it is never ticked speculatively."""
    private = values_of(fill.render(build_xml(), company_type="private"))
    public = values_of(fill.render(build_xml(), company_type="public"))
    assert fm.MEMBERS_AND_SIGNATURE["statement_private"] in private
    assert fm.MEMBERS_AND_SIGNATURE["statement_private"] not in public


def test_a_listed_company_uses_schedule_2_and_a_private_one_schedule_1():
    private = values_of(fill.render(build_xml(), company_type="private"))
    public = values_of(fill.render(build_xml(), company_type="public"))
    assert fm.MEMBERS_AND_SIGNATURE["members_in_schedule_1"] in private
    assert fm.MEMBERS_AND_SIGNATURE["members_in_schedule_2"] in public
    assert fm.SCHEDULE_1_HEADER["share_class"] in private
    assert fm.SCHEDULE_2_HEADER["share_class"] in public


def test_an_unknown_company_type_is_refused_rather_than_guessed():
    with pytest.raises(fill.FormFillError, match="company_type"):
        fill.render(build_xml(), company_type="llc")


# ---------------------------------------------------------------------------
# Overflow — the failure that would actually reach CR
# ---------------------------------------------------------------------------

def test_a_single_director_stays_on_the_main_form():
    # NOT a text search. Page 5 itself prints "Use Continuation Sheet C if more
    # than 1 director is a natural person", so that phrase is on the main form
    # whether or not a sheet was added — the first version of this test looked
    # for it and failed on a correct document. The absence of the sheet's own
    # FIELDS is the fact worth asserting.
    values = values_of(fill.render(build_xml(directors=("CHAN",))))
    assert values[fm.DIRECTOR_INDIVIDUAL["surname_en"]] == ["CHAN"]
    assert fm.SHEET_C["surname_en"] not in values
    # The COUNT still prints, as a nought. "This Return includes the following
    # Continuation Sheet(s)" is a question about what is attached, and a blank
    # box there reads as "nobody said" rather than "none" -- CR's own returns
    # write 0 in all five.
    assert values[fm.MEMBERS_AND_SIGNATURE["count_sheet_c"]] == ["0"]


def test_three_directors_produce_two_continuation_sheets_and_lose_nobody():
    """The printed form holds ONE natural-person director. A return that
    quietly showed only the first would misstate the board, and it is a
    document a client approves and CR registers."""
    pdf = fill.render(build_xml(directors=("CHAN", "LEE", "WONG")))
    values = values_of(pdf)
    surnames = set(values[fm.DIRECTOR_INDIVIDUAL["surname_en"]]) | \
        set(values.get(fm.SHEET_C["surname_en"], []))
    assert surnames == {"CHAN", "LEE", "WONG"}
    assert "Continuation Sheet C" in text_of(pdf)


def test_the_form_says_how_many_continuation_sheets_it_carries():
    values = values_of(fill.render(build_xml(directors=("A", "B", "C"))))
    assert values[fm.MEMBERS_AND_SIGNATURE["count_sheet_c"]] == ["2"]


def test_three_corporate_directors_overflow_to_sheet_D():
    """Page 6 holds TWO; the third is the first to need Sheet D."""
    pdf = fill.render(build_xml(corporate_directors=("ALPHA LTD", "BETA LTD",
                                                     "GAMMA LTD")))
    values = values_of(pdf)
    names = set()
    for slot in fm.DIRECTOR_CORPORATE:
        names |= set(values.get(slot["name_en"], []))
    for slot in fm.SHEET_D:
        names |= set(values.get(slot["name_en"], []))
    assert names == {"ALPHA LTD", "BETA LTD", "GAMMA LTD"}


def test_two_secretaries_overflow_to_sheet_A():
    pdf = fill.render(build_xml(secretaries=2))
    values = values_of(pdf)
    assert values[fm.SECRETARY_INDIVIDUAL["surname_en"]] == ["SEC0"]
    assert values[fm.SHEET_A["surname_en"]] == ["SEC1"]


def test_five_members_produce_three_schedules_and_lose_nobody():
    """Two member slots per schedule page."""
    pdf = fill.render(build_xml(members=("A", "B", "C", "D", "E")))
    values = values_of(pdf)
    surnames = set(values[fm.SCHEDULE_1[0]["surname_en"]]) | \
        set(values.get(fm.SCHEDULE_1[1]["surname_en"], []))
    assert surnames == {"A", "B", "C", "D", "E"}
    assert values[fm.MEMBERS_AND_SIGNATURE["count_schedule_1"]] == ["3"]


def test_each_schedule_page_says_which_of_how_many_it_is():
    """A schedule page separated from the bundle still has to say so."""
    values = values_of(fill.render(build_xml(members=("A", "B", "C"))))
    assert sorted(values[fm.SCHEDULE_1_PAGING["page_no"]]) == ["1", "2"]
    assert set(values[fm.SCHEDULE_1_PAGING["page_of"]]) == {"2"}


def test_two_copies_of_one_sheet_do_not_share_a_field():
    """AcroForm fields are named across the WHOLE document, so two copies of
    Continuation Sheet C keep the same `fill_7_P.13` unless renamed — and the
    second fill silently overwrites the first, rendering the same director
    twice. This is the test for that renaming."""
    pdf = fill.render(build_xml(directors=("CHAN", "LEE", "WONG")))
    reader = PdfReader(io.BytesIO(pdf))
    names = [n for n in (reader.get_fields() or {})
             if n.startswith(fm.SHEET_C["surname_en"])]
    assert len(names) == 2, f"expected two distinct copies, got {names}"


def test_more_share_classes_than_the_printed_table_is_refused():
    """CR provides no continuation sheet for section 11, so this return cannot
    be shown truthfully — and must not be shown untruthfully."""
    with pytest.raises(fill.FormFillError, match="share classes"):
        fill.render(build_xml(share_classes=fm.SHARE_CAPITAL_ROWS + 1))


def test_the_officer_guard_checks_each_kind_separately_not_pooled():
    """Pages 3-7 are now UNCONDITIONALLY present (CR's form is static -- see
    'CR'S FORM IS STATIC' below), so a return with zero secretaries and zero
    corporate directors still has those pages' capacity sitting in the
    document: 1 secretary (natural person) + 1 secretary (body corporate) +
    1 director (natural person) + 2 director (body corporate) + 1 reserve
    director = 6 slots that exist whether or not anything occupies them. A
    combined 'total capacity >= total officers' check cannot tell a director
    from a secretary, so those 6 phantom slots can cover for a genuinely
    missing director. This builds the exact failure by hand: 4 individual
    directors in the model, but only the ONE main-page slot laid out and no
    Sheet C added -- the return the pooled guard let through."""
    model = {"indDirList": [{"indvEngSname": n} for n in ("A", "B", "C", "D")]}
    pages = fill._Pages()
    for page_no in (fm.PAGE_MAIN_1, fm.PAGE_MAIN_2,
                    fm.PAGE_SECRETARY_INDIVIDUAL, fm.PAGE_SECRETARY_CORPORATE,
                    fm.PAGE_DIRECTOR_INDIVIDUAL, fm.PAGE_DIRECTOR_CORPORATE,
                    fm.PAGE_RESERVE_DIRECTOR, fm.PAGE_MEMBERS_AND_SIGNATURE,
                    fm.PAGE_SCHEDULE_1):
        pages.add(page_no, {})
    with pytest.raises(fill.FormFillError,
                       match=r"4 director \(natural person\) officers"):
        fill._assert_nothing_dropped(model, pages)


def test_the_officer_guard_still_passes_a_correctly_laid_out_return():
    """The other half of the same fix: per-kind counting must not become
    per-kind OVER-strict. Four individual directors laid out correctly --
    one on the main page, three on Sheet C -- must still pass."""
    pdf = fill.render(build_xml(directors=("A", "B", "C", "D")))
    assert pdf  # did not raise


# ---------------------------------------------------------------------------
# Content lands where CR prints it
# ---------------------------------------------------------------------------

def test_the_registered_office_fills_its_four_lines():
    values = values_of(fill.render(build_xml()))
    assert values[fm.MAIN_1["ro_flat_floor_block"]] == ["Flat A, 12/F"]
    assert values[fm.MAIN_1["ro_building"]] == ["Test Tower"]
    assert values[fm.MAIN_1["ro_street"]] == ["1 Test Street"]
    # CR TRANSMITS A CODE AND PRINTS A NAME. The XML says "CENTRAL" -- the
    # district name with its spaces removed, which is the only spelling CR
    # accepts -- and CR's own form shows "Central". Rendering the code put
    # block capitals on the printed return.
    assert values[fm.MAIN_1["ro_district"]] == ["Central"]


def test_both_company_names_appear_on_the_name_line():
    values = values_of(fill.render(build_xml()))
    line = values[fm.MAIN_1["company_name"]][0]
    assert "TEST COMPANY LIMITED" in line
    assert "測試有限公司" in line


def test_no_mortgages_reads_Nil_rather_than_blank():
    """On a statutory declaration an empty box reads as "not answered"; the
    form asks for a stated nil. Spelt as GSHK's own filed return spells it."""
    values = values_of(fill.render(build_xml()))
    assert values[fm.MAIN_2["mortgages_total"]] == ["Nil"]


def test_a_director_address_uses_the_overseas_line_not_the_district_line():
    """A director's correspondence address may be outside Hong Kong, so CR
    gives it a combined District/City/Province/State/Postal Code line where the
    secretary gets a plain District. They are different boxes."""
    values = values_of(fill.render(build_xml()))
    assert values[fm.DIRECTOR_INDIVIDUAL["addr_district_city_state"]] == ["Central"]
    assert values[fm.DIRECTOR_INDIVIDUAL["addr_country"]] == ["Hong Kong"]
    # The secretary's plain District carries the same value on ITS block.
    assert values[fm.SECRETARY_INDIVIDUAL["addr_district"]] == ["Central"]


def test_the_document_is_small_enough_to_email():
    """Every page copy clones the template's fonts and CR's logo; without
    deduplication a nine-page return weighs over 6MB."""
    pdf = fill.render(build_xml(directors=("A", "B", "C"),
                                members=("A", "B", "C", "D")))
    assert len(pdf) < 4_000_000, f"{len(pdf)} bytes is too big to attach"


# ---------------------------------------------------------------------------
# CR's form is STATIC (client-confirmed 2026-09-01)
# ---------------------------------------------------------------------------

def test_the_return_is_always_CRs_nine_pages():
    """CR does not drop a section's page when the section is empty. The
    reference return carries an empty natural-person secretary page, an empty
    body-corporate director page and an empty reserve-director page, and files
    all three. Dropping them moved every later section's page number, which is
    what made the client's page references disagree with ours."""
    assert len(PdfReader(io.BytesIO(fill.render(build_xml()))).pages) == 9


def test_a_memberless_return_still_carries_a_schedule_page():
    """`_chunk(rows, ...)` on zero members yields nothing, which used to skip
    the Schedule page entirely -- an 8-page document that STILL ticked
    'members are shown on Schedule 1' on page 8 (see
    `test_a_listed_company_uses_schedule_2_and_a_private_one_schedule_1`),
    pointing at a sheet that was not in the file it was ticked on. Spec §1b:
    every return is pages 1-8 PLUS Schedule 1 or 2, always."""
    pdf = fill.render(build_xml(members=()))
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 9
    values = values_of(pdf)
    assert fm.SCHEDULE_1_HEADER["br_number"] in values, \
        "the Schedule 1 header page was dropped for having no member rows"
    assert values[fm.MEMBERS_AND_SIGNATURE["count_schedule_1"]] == ["1"]


def test_the_page_set_does_not_move_with_the_officer_mix():
    """The email tells the client 'Page 5: Director's details'. That is only
    true if page 5 is the director page for every company."""
    one = PdfReader(io.BytesIO(fill.render(build_xml()))).pages
    corp = PdfReader(io.BytesIO(fill.render(
        build_xml(corporate_directors=("ALPHA LTD",))))).pages
    assert len(one) == len(corp) == 9


def test_share_capital_is_on_page_2_and_directors_on_page_5():
    """The two page numbers hardcoded into the client email.

    Text is whitespace-normalised before matching: CR's own template renders
    "Director  (Natural Person)" with a double space between the words (a
    kerning artefact of the static artwork, present before this change and
    unrelated to it), which a literal single-space match would miss."""
    pages = PdfReader(io.BytesIO(fill.render(build_xml()))).pages
    page2_text = re.sub(r"\s+", " ", pages[1].extract_text() or "")
    page5_text = re.sub(r"\s+", " ", pages[4].extract_text() or "")
    assert "Share Capital" in page2_text
    assert "Director (Natural Person)" in page5_text


def test_continuation_sheets_are_still_conditional():
    """Those genuinely ARE overflow -- CR's form says 'Use Continuation Sheet
    C if more than 1 director is a natural person'.

    The exact count, not merely '> 9': `len(overflow) > 9` would pass for a
    40-page document just as happily as the correct 11-page one, and would
    not have caught a Sheet C page silently duplicated or dropped."""
    plain = PdfReader(io.BytesIO(fill.render(build_xml()))).pages
    overflow = PdfReader(io.BytesIO(fill.render(
        build_xml(directors=("CHAN", "LEE", "WONG"))))).pages
    assert len(plain) == 9
    # 9 base pages (main 1-8 + one Schedule 1 page) + 2 extra Sheet C pages
    # for LEE and WONG, the directors beyond the one CHAN occupies on page 5.
    assert len(overflow) == 11
