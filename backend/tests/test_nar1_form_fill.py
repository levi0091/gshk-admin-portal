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


def _split(party):
    """A fixture party is "NAME", or ("NAME", "email@x") when it has one."""
    return party if isinstance(party, tuple) else (party, "")


def _corp_dir(party):
    name, email = _split(party)
    email_node = f"<cr:corpEmailAddr>{email}</cr:corpEmailAddr>" if email else ""
    return f"""
      <cr:corpDir>
        <cr:dirInd>Y</cr:dirInd>
        <cr:corpEngName>{name}</cr:corpEngName>
        {_address()}
        {email_node}
        <cr:corpBrNo>99999999</cr:corpBrNo>
      </cr:corpDir>"""


def _corp_sec(party):
    """A body-corporate company secretary — section 12B, and Continuation
    Sheet B once there is more than one."""
    name, email = _split(party)
    email_node = f"<cr:corpEmailAddr>{email}</cr:corpEmailAddr>" if email else ""
    return f"""
      <cr:corpSec>
        <cr:corpEngName>{name}</cr:corpEngName>
        {_address()}
        {email_node}
        <cr:corpBrNo>67169839</cr:corpBrNo>
        <cr:corpTcspNo>TC000807</cr:corpTcspNo>
      </cr:corpSec>"""


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
              secretaries=1, corporate_secretaries=(), members=("WONG",),
              date="01/02/2026", year="2026", share_classes=1,
              issued_per_class=100, company_email="",
              capacity="Director of the Company Secretary (Body Corporate)"):
    """A validated return, in CR's own shape: a BARE fragment with undeclared
    `cr:` prefixes, exactly as `tpsi_filings.validated_xml` stores it.

    `date=None` is the OTHER shape, and since 2026-09-17 the commoner one: a
    `request_xml` CR has not validated yet. CR writes `dateReturnMadeUp` during
    validateForm -- its own validate example omits it and its submit example
    carries it -- so an unvalidated return has `yearAnnualReturn` and no date.
    This fixture used to model only the validated shape, which is how every
    stage-1 PDF went out with section 4 empty behind a green suite.

    IN CR'S SHAPE MEANS CR'S SCHEMA, INCLUDING WHAT IT LEAVES OUT. `schedule1/
    shares/share` carries `clsOfShares` and NOTHING ELSE about the class --
    there is no `noOfShareIssuedOnThisCls` node there, and CR's remark on
    `clsOfShares` says why: "The total number of issued shares for each Class
    must match with the total number of issued shares for that class in the
    Share Capital section." The total lives in section 11 and the schedule
    refers to it.

    This fixture used to invent that node, and name the schedule's class
    "Ordinary" while the share capitals were "Class0" -- so it asserted a
    number the mapper never emits, against a class that did not exist. That is
    why Schedule 1's "Total Number of Issued Shares in this Class" box printed
    EMPTY on every rendered return with a green test suite above it.
    """
    capitals = "".join(f"""
        <cr:shareCapital>
          <cr:clsOfShares>Class{i}</cr:clsOfShares>
          <cr:currency>HKD</cr:currency>
          <cr:noOfShareIssuedOnThisCls>{issued_per_class}</cr:noOfShareIssuedOnThisCls>
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
        {f"<cr:emailAddr>{company_email}</cr:emailAddr>" if company_email else ""}
        <cr:formCode>NAR1</cr:formCode>
        {f"<cr:yearAnnualReturn>{year}</cr:yearAnnualReturn>" if year else ""}
        {f"<cr:dateReturnMadeUp>{date}</cr:dateReturnMadeUp>" if date else ""}
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
        <cr:selectCapacityDesc>{capacity}</cr:selectCapacityDesc>
        <cr:shareCapitals>{capitals}</cr:shareCapitals>
        <cr:indSecList>{secs}</cr:indSecList>
        <cr:corpSecList>
          {"".join(_corp_sec(s) for s in corporate_secretaries)}
        </cr:corpSecList>
        <cr:indDirList>{"".join(_ind_dir(d) for d in directors)}</cr:indDirList>
        <cr:corpDirList>
          {"".join(_corp_dir(c) for c in corporate_directors)}
        </cr:corpDirList>
        <cr:schedule1><cr:shares><cr:share>
          <cr:clsOfShares>Class0</cr:clsOfShares>
          <cr:shareHolderGrps>
            {"".join(_member(m, 100) for m in members)}
          </cr:shareHolderGrps>
        </cr:share></cr:shares></cr:schedule1>
      </cr:formModel></cr:EForm>
    </cr:submission>"""


def values_of(pdf_bytes) -> dict:
    """Every filled field, keyed by the name it had on CR's template.

    Pass it `fill.render_fields(...)`, not `fill.render(...)`: the shipped
    return is flattened -- `bake()` removes every field, because a phone drew
    them over the text layer -- so it has no `/V` left to read.

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
    values = values_of(fill.render_fields(build_xml()))
    for header in (fm.MAIN_1["br_number"], fm.MAIN_2["br_number"],
                   fm.SECRETARY_INDIVIDUAL["br_number"]):
        assert values.get(header) == ["T0001137"]


def test_the_return_has_nothing_left_to_edit():
    """The client is asked to APPROVE this, not to edit it. That used to be
    done by marking each field read-only; `bake()` now flattens the return, so
    there is no field left to type into -- the stronger form of the same
    guarantee, and the one a phone's viewer cannot second-guess."""
    reader = PdfReader(io.BytesIO(fill.render(build_xml())))
    assert "/AcroForm" not in reader.trailer["/Root"]
    for page in reader.pages:
        for annot in (page.get("/Annots") or []):
            assert annot.get_object().get("/Subtype") != "/Widget", \
                "a form field survived on the shipped return"


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
    values = values_of(fill.render_fields(build_xml(date="09/03/2026")))
    assert values[fm.MAIN_1["return_date_dd"]] == ["09"]
    assert values[fm.MAIN_1["return_date_mm"]] == ["03"]
    assert values[fm.MAIN_1["return_date_yyyy"]] == ["2026"]


# ---------------------------------------------------------------------------
# "Date to which this Return is Made Up" on a return CR has not validated yet
#
# THE REGRESSION (Levi 2026-09-18). CR fills `dateReturnMadeUp` itself, during
# validateForm. Until 2026-09-17 every rendered return was `validated_xml` and
# the box was always full. Client Verification then became the FIRST stage, so
# the client is sent `request_xml` -- which CR has not seen and which never
# carries the date -- and section 4, the Schedule 1 header and every
# continuation sheet's header all went out blank.
# ---------------------------------------------------------------------------

def _made_up(values, head):
    return tuple(values.get(head[k], [""])[0]
                 for k in ("return_date_dd", "return_date_mm", "return_date_yyyy"))


def test_an_unvalidated_return_prints_the_incorporation_anniversary():
    """Levi's own example: incorporated 15 March 2025, so the 2026 return is
    made up to 15 March 2026."""
    values = values_of(fill.render_fields(
        build_xml(date=None, year="2026"), incorporated_on="2025-03-15"))
    assert _made_up(values, fm.MAIN_1) == ("15", "03", "2026")


def test_the_schedule_header_carries_the_same_date():
    """The box in the report: Schedule 1's own "Date to which this Return is
    Made Up", which a page separated from the bundle has to carry."""
    values = values_of(fill.render_fields(
        build_xml(date=None, year="2026"), incorporated_on="2025-03-15"))
    assert _made_up(values, fm.SCHEDULE_1_HEADER) == ("15", "03", "2026")


def test_every_continuation_sheet_header_carries_it_too():
    values = values_of(fill.render_fields(
        build_xml(date=None, year="2026", directors=("CHAN", "LEE")),
        incorporated_on="2025-03-15"))
    head = fm.sheet_header(fm.PAGE_SHEET_C)
    assert _made_up(values, head) == ("15", "03", "2026")


def test_the_anniversary_is_in_the_RETURNS_year_not_this_one():
    """A 2024 return prepared late is still made up to the 2024 anniversary,
    and the presenter's reference printed beside it must agree."""
    values = values_of(fill.render_fields(
        build_xml(date=None, year="2024"), incorporated_on="2019-07-01"))
    assert _made_up(values, fm.MAIN_1) == ("01", "07", "2024")
    assert values[fm.MAIN_1["presenter_reference"]][0].startswith("NAR1/2024/")


def test_a_29_february_incorporation_is_made_up_to_28_february_in_a_common_year():
    """The clamp `fees.return_date_for` applies -- the same rule the late fee
    and the early-filing gate are measured from, so the three cannot disagree."""
    values = values_of(fill.render_fields(
        build_xml(date=None, year="2026"), incorporated_on="2024-02-29"))
    assert _made_up(values, fm.MAIN_1) == ("28", "02", "2026")


def test_a_date_object_is_taken_as_well_as_supabases_iso_string():
    from datetime import date

    values = values_of(fill.render_fields(
        build_xml(date=None, year="2026"), incorporated_on=date(2025, 3, 15)))
    assert _made_up(values, fm.MAIN_1) == ("15", "03", "2026")


def test_CRs_own_date_wins_over_the_derived_one():
    """Once CR has validated, the date it wrote is the one on its register and
    the one to print -- derivation is only for the return CR has not seen."""
    values = values_of(fill.render_fields(
        build_xml(date="31/10/2026", year="2026"), incorporated_on="2025-03-15"))
    assert _made_up(values, fm.MAIN_1) == ("31", "10", "2026")


def test_with_neither_a_CR_date_nor_an_incorporation_date_the_boxes_stay_empty():
    """Nothing to derive from, and inventing a statutory date is worse than
    leaving CR to fill it on validation."""
    values = values_of(fill.render_fields(build_xml(date=None, year="2026")))
    assert _made_up(values, fm.MAIN_1) == ("", "", "")


def test_an_unreadable_incorporation_date_leaves_the_boxes_empty_not_a_crash():
    """The preview must still render; a bad profile value is not worth a 422
    on the whole return."""
    values = values_of(fill.render_fields(
        build_xml(date=None, year="2026"), incorporated_on="not a date"))
    assert _made_up(values, fm.MAIN_1) == ("", "", "")


def test_CRs_own_request_example_renders_the_date_CR_itself_filled_in():
    """END TO END, ON CR'S OWN PAIR OF DOCUMENTS. `validate_NAR1(Private
    Company, Schedule 1).xml` is the request -- no `dateReturnMadeUp` -- and
    `submit_NAR1.xml` is the same company (BR 00000001, return year 2020) after
    CR validated it, carrying the date CR wrote. Rendering the REQUEST must
    print the date CR went on to write, read from CR's document, not retyped.
    """
    from pathlib import Path

    from services.tpsi.soap import extract_submission

    examples = Path(__file__).resolve().parent / "fixtures" / "cr-examples"
    request = extract_submission((
        examples / "validateForm" / "validate_NAR1(Private Company, Schedule 1).xml"
    ).read_bytes())
    assert "dateReturnMadeUp" not in request   # the shape stage 1 renders
    cr_wrote = re.search(
        r"<cr:dateReturnMadeUp>([^<]+)</cr:dateReturnMadeUp>",
        (examples / "submission" / "submit_NAR1.xml").read_text(encoding="utf-8"),
    ).group(1)                                  # "31/10/2020"

    values = values_of(fill.render_fields(request, incorporated_on="2012-10-31"))
    assert _made_up(values, fm.MAIN_1) == fill.split_date(cr_wrote)


# ---------------------------------------------------------------------------
# Company type
# ---------------------------------------------------------------------------

def test_a_private_company_ticks_private_and_leaves_section_5_empty():
    """"A private company needs not complete this section" — the form's own
    instruction. Filling it would assert something about financial statements
    a private company does not deliver."""
    values = values_of(fill.render_fields(build_xml(), company_type="private"))
    assert values[fm.MAIN_1["type_private"]] == [fm.CHECKBOX_ON]
    assert fm.MAIN_1["type_public"] not in values
    for field in ("fin_period_from_dd", "fin_period_to_yyyy"):
        assert fm.MAIN_1[field] not in values


def test_a_public_company_ticks_public_and_completes_section_5():
    values = values_of(fill.render_fields(build_xml(), company_type="public"))
    assert values[fm.MAIN_1["type_public"]] == [fm.CHECKBOX_ON]
    assert fm.MAIN_1["type_private"] not in values
    assert values[fm.MAIN_1["fin_period_from_yyyy"]] == ["2025"]


def test_a_guarantee_company_ticks_guarantee():
    values = values_of(fill.render_fields(build_xml(), company_type="guarantee"))
    assert values[fm.MAIN_1["type_guarantee"]] == [fm.CHECKBOX_ON]


def test_only_a_private_company_makes_the_section_16_statement():
    """It is a statement of fact about not having invited public subscription,
    so it is never ticked speculatively."""
    private = values_of(fill.render_fields(build_xml(), company_type="private"))
    public = values_of(fill.render_fields(build_xml(), company_type="public"))
    assert fm.MEMBERS_AND_SIGNATURE["statement_private"] in private
    assert fm.MEMBERS_AND_SIGNATURE["statement_private"] not in public


def test_a_listed_company_uses_schedule_2_and_a_private_one_schedule_1():
    private = values_of(fill.render_fields(build_xml(), company_type="private"))
    public = values_of(fill.render_fields(build_xml(), company_type="public"))
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
    values = values_of(fill.render_fields(build_xml(directors=("CHAN",))))
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
    xml = build_xml(directors=("CHAN", "LEE", "WONG"))
    values = values_of(fill.render_fields(xml))
    surnames = set(values[fm.DIRECTOR_INDIVIDUAL["surname_en"]]) | \
        set(values.get(fm.SHEET_C["surname_en"], []))
    assert surnames == {"CHAN", "LEE", "WONG"}
    shipped = text_of(fill.render(xml))
    assert "Continuation Sheet C" in shipped
    assert {"CHAN", "LEE", "WONG"} <= set(shipped.split())


def test_the_form_says_how_many_continuation_sheets_it_carries():
    values = values_of(fill.render_fields(build_xml(directors=("A", "B", "C"))))
    assert values[fm.MEMBERS_AND_SIGNATURE["count_sheet_c"]] == ["2"]


def test_three_corporate_directors_overflow_to_sheet_D():
    """Page 6 holds TWO; the third is the first to need Sheet D."""
    pdf = fill.render_fields(build_xml(
        corporate_directors=("ALPHA LTD", "BETA LTD", "GAMMA LTD")))
    values = values_of(pdf)
    names = set()
    for slot in fm.DIRECTOR_CORPORATE:
        names |= set(values.get(slot["name_en"], []))
    for slot in fm.SHEET_D:
        names |= set(values.get(slot["name_en"], []))
    assert names == {"ALPHA LTD", "BETA LTD", "GAMMA LTD"}


def test_two_secretaries_overflow_to_sheet_A():
    pdf = fill.render_fields(build_xml(secretaries=2))
    values = values_of(pdf)
    assert values[fm.SECRETARY_INDIVIDUAL["surname_en"]] == ["SEC0"]
    assert values[fm.SHEET_A["surname_en"]] == ["SEC1"]


def test_five_members_produce_three_schedules_and_lose_nobody():
    """Two member slots per schedule page."""
    pdf = fill.render_fields(build_xml(members=("A", "B", "C", "D", "E")))
    values = values_of(pdf)
    surnames = set(values[fm.SCHEDULE_1[0]["surname_en"]]) | \
        set(values.get(fm.SCHEDULE_1[1]["surname_en"], []))
    assert surnames == {"A", "B", "C", "D", "E"}
    assert values[fm.MEMBERS_AND_SIGNATURE["count_schedule_1"]] == ["3"]


def test_each_schedule_page_says_which_of_how_many_it_is():
    """A schedule page separated from the bundle still has to say so."""
    values = values_of(fill.render_fields(build_xml(members=("A", "B", "C"))))
    assert sorted(values[fm.SCHEDULE_1_PAGING["page_no"]]) == ["1", "2"]
    assert set(values[fm.SCHEDULE_1_PAGING["page_of"]]) == {"2"}


def test_two_copies_of_one_sheet_do_not_share_a_field():
    """AcroForm fields are named across the WHOLE document, so two copies of
    Continuation Sheet C keep the same `fill_7_P.13` unless renamed — and the
    second fill silently overwrites the first, rendering the same director
    twice. This is the test for that renaming."""
    pdf = fill.render_fields(build_xml(directors=("CHAN", "LEE", "WONG")))
    reader = PdfReader(io.BytesIO(pdf))
    names = [n for n in (reader.get_fields() or {})
             if n.startswith(fm.SHEET_C["surname_en"])]
    assert len(names) == 2, f"expected two distinct copies, got {names}"


def _pages_naming(pdf_bytes, names) -> dict:
    """{name: [1-based page numbers whose text layer carries it]}."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    words = [set((page.extract_text() or "").split()) for page in reader.pages]
    return {name: [i + 1 for i, found in enumerate(words) if name in found]
            for name in names}


@pytest.mark.parametrize("shape", [
    # The first return reported on PROD (2026-09-19): 8 shareholders and 2
    # directors. Four Schedule 1 pages, every one printing the same pile.
    dict(directors=("DIRALPHA", "DIRBRAVO"),
         members=tuple(f"MEMBER{c}" for c in "ABCDEFGH")),
    # The second: several of each, so Sheet C and Schedule 1 BOTH repeat. Every
    # continuation sheet and schedule page came out as overprinted text.
    dict(directors=("DIRALPHA", "DIRBRAVO", "DIRCHARLIE", "DIRDELTA"),
         members=tuple(f"MEMBER{c}" for c in "ABCDE")),
    # Every repeatable page at once: Sheets A, B, C and D and Schedule 1 each
    # printed at least twice.
    dict(directors=("DIRALPHA", "DIRBRAVO", "DIRCHARLIE"),
         secretaries=3,
         corporate_secretaries=("CSECA", "CSECB", "CSECC"),
         corporate_directors=tuple(f"CDIR{c}" for c in "ABCDEF"),
         members=tuple(f"MEMBER{c}" for c in "ABCDE")),
])
def test_every_officer_and_member_is_printed_on_exactly_one_page(shape):
    """THE SHIPPED DOCUMENT, read page by page (PROD 2026-09-19).

    Every copy of a repeated page printed every copy's values on top of each
    other. `_fill` deduplicates identical objects, so the four Schedule 1
    copies ended up pointing at ONE content stream. `bake()` then merged each
    page's drawn layer through pypdf's `replace_contents`, which rewrites the
    page's existing stream object in place, so every copy's layer landed on
    that shared stream and every copy showed all of them. Pages 1-8 were
    right only because no two of them share a template page.

    Nothing caught it: every other test here asks whether a name is ANYWHERE
    in the document, and a name printed on four pages passes that. The
    question that matters on a statutory return is which page it is on, and
    that it is on no other."""
    shape = {"secretaries": 0, **shape}
    names = (shape["directors"] + shape["members"]
             + tuple(f"SEC{i}" for i in range(shape["secretaries"]))
             + shape.get("corporate_secretaries", ())
             + shape.get("corporate_directors", ()))
    found = _pages_naming(fill.render(build_xml(**shape)), names)
    wrong = {name: pages for name, pages in found.items() if len(pages) != 1}
    assert not wrong, f"printed on other than exactly one page: {wrong}"


def test_a_schedule_page_prints_its_own_two_members_and_nobody_elses():
    """The same failure, stated as the reader sees it: page 9 of an
    eight-member return is Schedule 1 page 1 and holds members A and B."""
    members = tuple(f"MEMBER{c}" for c in "ABCDEFGH")
    found = _pages_naming(fill.render(build_xml(members=members)), members)
    by_page: dict[int, set] = {}
    for name, pages in found.items():
        for page in pages:
            by_page.setdefault(page, set()).add(name)
    assert by_page == {9: {"MEMBERA", "MEMBERB"}, 10: {"MEMBERC", "MEMBERD"},
                       11: {"MEMBERE", "MEMBERF"}, 12: {"MEMBERG", "MEMBERH"}}


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
    values = values_of(fill.render_fields(build_xml()))
    assert values[fm.MAIN_1["ro_flat_floor_block"]] == ["Flat A, 12/F"]
    assert values[fm.MAIN_1["ro_building"]] == ["Test Tower"]
    assert values[fm.MAIN_1["ro_street"]] == ["1 Test Street"]
    # CR TRANSMITS A CODE AND PRINTS A NAME. The XML says "CENTRAL" -- the
    # district name with its spaces removed, which is the only spelling CR
    # accepts -- and CR's own form shows "Central". Rendering the code put
    # block capitals on the printed return.
    assert values[fm.MAIN_1["ro_district"]] == ["Central"]


def test_both_company_names_appear_on_the_name_line():
    values = values_of(fill.render_fields(build_xml()))
    line = values[fm.MAIN_1["company_name"]][0]
    assert "TEST COMPANY LIMITED" in line
    assert "測試有限公司" in line


def test_no_mortgages_reads_Nil_rather_than_blank():
    """On a statutory declaration an empty box reads as "not answered"; the
    form asks for a stated nil. Spelt as GSHK's own filed return spells it."""
    values = values_of(fill.render_fields(build_xml()))
    assert values[fm.MAIN_2["mortgages_total"]] == ["Nil"]


def test_a_director_address_uses_the_overseas_line_not_the_district_line():
    """A director's correspondence address may be outside Hong Kong, so CR
    gives it a combined District/City/Province/State/Postal Code line where the
    secretary gets a plain District. They are different boxes."""
    values = values_of(fill.render_fields(build_xml()))
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
    values = values_of(fill.render_fields(build_xml(members=())))
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


# ---------------------------------------------------------------------------
# The email boxes (migration 045)
#
# `_corporate_officer` has ALWAYS written corpEmailAddr into s12B / s13B. The
# box printed blank only because nothing upstream emitted the element, which
# is what CR raised a discrepancy notice about. These pin the wiring end to
# end, so a future change to the mapper cannot empty the box in silence.
# ---------------------------------------------------------------------------

def test_the_corporate_secretarys_email_is_printed_in_s12b():
    values = values_of(fill.render_fields(build_xml(
        corporate_secretaries=(("GET STARTED HK LIMITED",
                                "dataresources@getstarted.hk"),),
        secretaries=0,
    )))
    assert values[fm.SECRETARY_CORPORATE["email"]] == [
        "dataresources@getstarted.hk"]


def test_a_corporate_secretary_with_no_email_leaves_the_box_empty():
    """Not "None given" — that treatment is section 7's, where CR's own form
    asks a question the company must answer. An officer block simply has
    nothing to print."""
    values = values_of(fill.render_fields(build_xml(
        corporate_secretaries=("GET STARTED HK LIMITED",), secretaries=0,
    )))
    assert fm.SECRETARY_CORPORATE["email"] not in values


def test_the_corporate_directors_email_is_printed_in_s13b():
    values = values_of(fill.render_fields(build_xml(
        directors=(), corporate_directors=(("HOLDCO LIMITED",
                                            "board@holdco.example"),),
    )))
    # Page 6 prints two corporate directors; this is the first slot.
    assert values[fm.DIRECTOR_CORPORATE[0]["email"]] == ["board@holdco.example"]


def test_section_7_prints_the_companys_own_email_when_there_is_one():
    values = values_of(fill.render_fields(
        build_xml(company_email="hello@testco.example")))
    assert values[fm.MAIN_2["email_address"]] == ["hello@testco.example"]


def test_section_7_still_says_none_given_when_there_is_no_email():
    """The behaviour every return has had. Mapping the field changed nothing
    for a company nobody has typed an address onto."""
    values = values_of(fill.render_fields(build_xml()))
    assert values[fm.MAIN_2["email_address"]] == [fill.NONE_GIVEN]
