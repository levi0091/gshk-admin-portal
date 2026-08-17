"""services/nar1_pdf.py — Form NAR1 + Schedule 1 from CR's validated XML.

Reads CR's own shipped example out of tests/fixtures/cr-examples, never docs/.
docs/ is .gitignore'd and absent in CI, and the last time a test reached into it
the suite went red on a clean checkout while three parametrised tests silently
collected zero cases.
"""
from pathlib import Path

import pytest

from services import nar1_pdf

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "cr-examples"

SAMPLE_PATH = (
    _FIXTURES / "validateForm"
    / "validate_NAR1(Private Company, Schedule 1).xml"
)

#: Hard failure, never a skip. The fixture is committed, so absence means a
#: broken checkout — and a skipped renderer test is a renderer nobody ran.
if not SAMPLE_PATH.exists():
    raise RuntimeError(f"CR fixture missing: {SAMPLE_PATH}")

SAMPLE = SAMPLE_PATH.read_text(encoding="utf8")


# ---------------------------------------------------------------------------
# parse_validated_xml
# ---------------------------------------------------------------------------


def test_parses_scalars_off_the_form_model():
    data = nar1_pdf.parse_validated_xml(SAMPLE)
    assert data["brNo"] == "00000001"
    assert data["language"] == "E"


def test_parses_a_nested_container():
    addr = nar1_pdf.parse_validated_xml(SAMPLE)["roAddr"]
    assert addr["ctryRegion"] == "HKG"
    assert addr["dstCtyStatePostal"] == "CENTRAL"


def test_parses_a_repeating_wrapper_into_a_list():
    """Two share classes in, two out. A parser that returns the last one only
    produces a PDF that silently understates the company's capital."""
    caps = nar1_pdf.parse_validated_xml(SAMPLE)["shareCapitals"]
    assert isinstance(caps, list)
    assert len(caps) == 2
    assert caps[1]["clsOfShares"] == "Preference"


def test_parses_a_single_child_wrapper_into_a_list_too():
    """One director in CR's example, and it must STILL be a list.

    This is the case that breaks a naive parser: a wrapper with exactly one
    child looks like a plain container, parses as a dict, and every downstream
    `for director in ...` then iterates the director's FIELDS instead.
    """
    dirs = nar1_pdf.parse_validated_xml(SAMPLE)["indDirList"]
    assert isinstance(dirs, list)
    assert len(dirs) == 1
    assert dirs[0]["indvEngSname"] == "CHAN"


def test_parses_schedule_1_shareholder_groups():
    sched = nar1_pdf.parse_validated_xml(SAMPLE)["schedule1"]
    groups = sched["shares"][0]["shareHolderGrps"]
    assert [g["sharesAlloted"] for g in groups] == ["100", "900"]


def test_parses_the_joint_holding_as_two_allottees():
    """The Preference group is shType 2 — a JOINT holding of one block of
    shares by two people. Flattening it to one allottee misstates the register.
    """
    sched = nar1_pdf.parse_validated_xml(SAMPLE)["schedule1"]
    group = sched["shares"][1]["shareHolderGrps"][0]
    assert group["shType"] == "2"
    assert len(group["allotteeRec"]) == 2
    assert group["allotteeRec"][0]["allotteeType"] == "I"
    assert group["allotteeRec"][1]["allotteeType"] == "C"


def test_parsing_is_namespace_prefix_agnostic():
    """CR's prefix is CR's to change; the parser must not be pinned to `cr:`."""
    renamed = SAMPLE.replace("cr:", "ns9:").replace("xmlns:cr=", "xmlns:ns9=")
    assert nar1_pdf.parse_validated_xml(renamed)["brNo"] == "00000001"


def test_parses_the_exact_shape_that_gets_stored_in_validated_xml():
    """THE shape this module actually receives in production.

    `filings.validate` stores `soap.extract_submission(response)`, which is a
    VERBATIM text slice of <cr:submission>...</cr:submission>. The xmlns:cr
    declaration lives on the enclosing method element, which the slice cuts
    away — so what lands in the column is not well-formed XML on its own. Every
    other test here feeds a whole SOAP envelope and would never notice.
    """
    from services.tpsi.soap import extract_submission

    stored = extract_submission(SAMPLE.encode("utf8"))
    assert "xmlns:cr" not in stored  # the premise: the prefix is dangling
    data = nar1_pdf.parse_validated_xml(stored)
    assert data["brNo"] == "00000001"
    assert len(data["shareCapitals"]) == 2
    assert nar1_pdf.render(stored).startswith(b"%PDF-")


def test_parse_refuses_xml_with_no_form_model():
    with pytest.raises(ValueError):
        nar1_pdf.parse_validated_xml("<soap:Envelope/>")


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


def test_render_returns_a_real_pdf():
    out = nar1_pdf.render(SAMPLE)
    assert out.startswith(b"%PDF-")
    assert out.rstrip().endswith(b"%%EOF")


def test_render_produces_a_structurally_complete_pdf():
    """Byte signature alone would pass on a truncated file. A PDF whose xref
    table is missing opens as a blank or broken document in every viewer, and
    every mocked test in this file would still be green."""
    out = nar1_pdf.render(SAMPLE)
    assert b"/Type /Catalog" in out or b"/Type/Catalog" in out
    assert b"startxref" in out
    assert len(out) > 2000


def test_the_pdf_carries_the_company_and_the_br_number():
    """Rendered bytes are opaque, so assert on the text layer -- a PDF that
    looks right but names the wrong company is the failure that matters."""
    text = nar1_pdf.render_text(SAMPLE)
    assert "00000001" in text
    assert "Annual Return" in text


def test_the_form_row_shows_the_code_cr_carries_and_never_invents_nar1():
    """CR fills `formCode` in during validation, so it is absent from every
    request-side fixture. A hard-coded "NAR1" fallback turns that absence into
    an assertion — and on any other form code it is a false one. A blank row is
    a fact the reviewer can act on; an invented NAR1 is not.
    """
    rows = nar1_pdf._return_rows(nar1_pdf.parse_validated_xml(SAMPLE))
    assert ["Form", ""] in rows
    assert ["Form", "Nar1"] in nar1_pdf._return_rows({"formCode": "Nar1"})


def test_the_pdf_lists_every_director_and_secretary():
    text = nar1_pdf.render_text(SAMPLE)
    assert "CHAN" in text
    assert "TEST COMPANY LIMITED" in text


def test_the_pdf_shows_both_share_classes_not_just_the_first():
    text = nar1_pdf.render_text(SAMPLE)
    assert "Ordinary" in text
    assert "Preference" in text


def test_the_pdf_includes_schedule_1():
    text = nar1_pdf.render_text(SAMPLE)
    assert "Schedule 1" in text
    assert "900" in text


def test_the_pdf_names_the_signatory_and_the_capacity_they_sign_in():
    """The admin double-confirms an irreversible, chargeable submit off this
    page. Who signs, and in what capacity, is the part CR will hold them to."""
    text = nar1_pdf.render_text(SAMPLE)
    assert "Company Secretary" in text
    assert "TEST1234" in text


def test_the_pdf_renders_chinese_names():
    """CR's example carries Chinese names throughout. Dropping them, or
    rendering them as boxes, hides half the register from the reviewer."""
    text = nar1_pdf.render_text(SAMPLE)
    assert "陳大文" in text


def test_chinese_text_survives_into_the_pdf_bytes():
    """render_text could be right while the PDF itself drops the glyphs. A CID
    font must be registered and actually referenced by the page."""
    out = nar1_pdf.render(SAMPLE)
    assert nar1_pdf.CJK_FONT.encode() in out


def test_render_refuses_xml_with_no_form_model():
    """Better an error than a blank form that looks like a real NAR1."""
    with pytest.raises(ValueError):
        nar1_pdf.render("<soap:Envelope/>")


def test_render_survives_a_form_model_with_nothing_in_it():
    """An empty-but-present formModel is not a corrupt payload; it is a form
    with no data. It must render as an obviously-empty document, not crash."""
    out = nar1_pdf.render(
        '<cr:formModel xmlns:cr="urn:x"><cr:brNo></cr:brNo></cr:formModel>'
    )
    assert out.startswith(b"%PDF-")


# ---------------------------------------------------------------------------
# The PDF as a PDF — parsed back out, not inspected as flowables
# ---------------------------------------------------------------------------
#
# render_text walks the SAME flowable objects render() builds, so it proves the
# content is right and proves nothing about the file. These tests re-open the
# emitted bytes with an independent PDF parser, which is the only thing that
# catches a renderer that produces a structurally broken document while every
# other assertion in this file stays green.


def _reader():
    from io import BytesIO

    from pypdf import PdfReader

    return PdfReader(BytesIO(nar1_pdf.render(SAMPLE)))


def test_the_emitted_bytes_open_as_a_pdf():
    assert len(_reader().pages) >= 2


def test_the_text_layer_of_the_real_pdf_carries_the_return():
    text = "\n".join(page.extract_text() for page in _reader().pages)
    assert "00000001" in text
    assert "Annual Return" in text
    assert "CHAN" in text
    assert "TEST COMPANY LIMITED" in text
    assert "Company Secretary" in text


def test_schedule_1_starts_on_its_own_page():
    pages = [page.extract_text() for page in _reader().pages]
    assert "Schedule 1 - particulars of members" not in pages[0]
    assert any("Schedule 1 - particulars of members" in p for p in pages[1:])


def test_no_table_is_wider_than_the_printable_page():
    """Column widths are fractions of the content box, so this can only fail if
    a fraction list stops summing to 1. It is the cheap structural guard against
    the failure the text assertions cannot see: a table running off the paper."""
    from reportlab.platypus import KeepTogether, Table

    def tables(flow):
        for item in flow:
            if isinstance(item, Table):
                yield item
            elif isinstance(item, KeepTogether):
                yield from tables(item._content)

    found = list(tables(nar1_pdf._flow(nar1_pdf.parse_validated_xml(SAMPLE))))
    assert found
    for table in found:
        assert sum(table._argW) <= nar1_pdf._CONTENT_W + 0.01


def test_render_handles_a_listed_company_schedule_2():
    """The other NAR1 shape CR ships. Schedule 2 lives under a different key,
    and a renderer that only knows schedule1 silently omits the entire member
    register for a listed company."""
    listed = (
        _FIXTURES / "validateForm" / "validate_NAR1(Listed Company, Schedule 2).xml"
    ).read_text(encoding="utf8")
    text = nar1_pdf.render_text(listed)
    assert "Schedule 2 - particulars of members" in text
    assert nar1_pdf.render(listed).startswith(b"%PDF-")


# ---------------------------------------------------------------------------
# Officer particulars CR's own fixtures never exercise
# ---------------------------------------------------------------------------
#
# CR ships one substantive director, one corporate director, one secretary of
# each kind, and nobody with a former name or an alternate appointment. So the
# whole alternate-director, former-name and individual-TCSP surface is invisible
# to every fixture-driven test in this file — a field could be dropped on the
# floor and the suite would stay green. These payloads are built from
# services/tpsi/forms/nar1_schema.json, which is the authority on which fields
# exist; CR's examples remain the authority on XML shape, and these follow it.


def _model(inner: str) -> str:
    """A bare <formModel>. Every lookup in the module is on the LOCAL name, so
    the namespace prefix is irrelevant here and dropping it keeps these
    hand-built payloads readable."""
    return f"<formModel><brNo>00000001</brNo>{inner}</formModel>"


ALTERNATE_DIRECTORS = _model("""
  <indDirList>
    <indDir>
      <dirInd>Y</dirInd><altDirInd>N</altDirInd><altTo></altTo>
      <indvEngSname>CHAN</indvEngSname><indvEngOname>TAI MAN</indvEngOname>
      <stdAddress><ctryRegion>HKG</ctryRegion></stdAddress>
      <indvHkidNo>A123</indvHkidNo>
    </indDir>
    <indDir>
      <dirInd>N</dirInd><altDirInd>Y</altDirInd><altTo>CHAN TAI MAN</altTo>
      <indvEngSname>WONG</indvEngSname><indvEngOname>SIU MING</indvEngOname>
      <stdAddress><ctryRegion>HKG</ctryRegion></stdAddress>
      <indvHkidNo>B456</indvHkidNo>
    </indDir>
  </indDirList>
""")

FORMER_AND_ALIAS_NAMES = _model("""
  <indSecList>
    <indSec>
      <indvEngSname>SMITH</indvEngSname><indvEngOname>JOHN</indvEngOname>
      <indvPrevEngName>JONES JOHN</indvPrevEngName>
      <indvPrevChiName>鍾斯</indvPrevChiName>
      <indvAlsEngName>JOHNNY</indvAlsEngName>
      <indvAlsChiName>尊尼</indvAlsChiName>
      <stdAddress><ctryRegion>HKG</ctryRegion></stdAddress>
      <indvHkidNo>C789</indvHkidNo>
      <indvTcspNo>TC/2024/001</indvTcspNo>
      <exempted>N</exempted>
    </indSec>
  </indSecList>
""")

CORPORATE_DIRECTORS = _model("""
  <corpDirList>
    <corpDir>
      <dirInd>Y</dirInd><altDirInd>N</altDirInd><altTo></altTo>
      <corpEngName>HOLDCO LIMITED</corpEngName>
      <stdAddress><ctryRegion>HKG</ctryRegion></stdAddress>
      <corpBrNo>00000002</corpBrNo>
    </corpDir>
    <corpDir>
      <dirInd>N</dirInd><altDirInd>Y</altDirInd><altTo>HOLDCO LIMITED</altTo>
      <corpEngName>STANDIN LIMITED</corpEngName>
      <stdAddress><ctryRegion>HKG</ctryRegion></stdAddress>
      <corpBrNo>00000003</corpBrNo>
    </corpDir>
  </corpDirList>
""")


def test_an_alternate_director_never_renders_as_a_substantive_one():
    """The defect this test exists for: with no alternate-director column an
    alternate is indistinguishable from a substantive director on the page, so
    the officer register the admin approves misstates who actually holds the
    office."""
    lines = nar1_pdf.render_text(ALTERNATE_DIRECTORS).splitlines()
    assert lines[lines.index("CHAN TAI MAN") + 1] == "Director"
    assert lines[lines.index("WONG SIU MING") + 1] == \
        "Alternate director to CHAN TAI MAN"


def test_an_alternate_body_corporate_director_is_marked_too():
    """corpDir carries dirInd/altDirInd/altTo exactly as indDir does."""
    lines = nar1_pdf.render_text(CORPORATE_DIRECTORS).splitlines()
    assert lines[lines.index("HOLDCO LIMITED") + 1] == "Director"
    assert lines[lines.index("STANDIN LIMITED") + 1] == \
        "Alternate director to HOLDCO LIMITED"


def test_former_and_alias_names_reach_the_page():
    """Absent from every CR fixture, so nothing else here would notice them
    being dropped — which is exactly why they were."""
    text = nar1_pdf.render_text(FORMER_AND_ALIAS_NAMES)
    assert "Formerly JONES JOHN / 鍾斯" in text
    assert "Alias JOHNNY / 尊尼" in text


def test_the_former_names_column_is_absent_when_nobody_carries_one():
    """Same instinct as `% held`: a column blank on every row of a table reads
    as missing data rather than as "not applicable"."""
    assert "Former / alias names" not in nar1_pdf.render_text(SAMPLE)


def test_the_individual_secretary_shows_its_tcsp_licence():
    """The corporate secretary table showed corpTcspNo and the individual one
    showed nothing — an asymmetry with no basis in the schema, which defines
    indvTcspNo/exempted/reason on indSec just as it does on corpSec."""
    assert "TC/2024/001" in nar1_pdf.render_text(FORMER_AND_ALIAS_NAMES)


def test_both_secretaries_licence_exemption_claims_reach_the_page():
    """CR's own fixture has both secretaries claiming exemption with a reason,
    and neither the claim nor the reason appeared anywhere on the document.
    Whether a company secretary is licensed is a statutory particular."""
    text = nar1_pdf.render_text(SAMPLE)
    assert "Exempt: reason" in text   # indSec
    assert "Exempt: Reason" in text   # corpSec


def test_the_corporate_director_table_carries_no_tcsp_column():
    """nar1_schema.json defines no corpTcspNo on corpDir, so the column could
    never be anything but blank there. Falls out of making the columns follow
    the section rather than the person's legal form."""
    text = nar1_pdf.render_text(CORPORATE_DIRECTORS)
    assert "HOLDCO LIMITED" in text
    assert "TCSP" not in text


# ---------------------------------------------------------------------------
# How old is this snapshot?
# ---------------------------------------------------------------------------


def test_the_footer_stamps_when_cr_validated_the_snapshot_and_the_stage():
    """`filings.validate`'s failure branch sets stage=validation_failed and
    leaves `validated_xml` in place, so a filing whose LATEST validation CR
    rejected still renders the previous snapshot — under a header reading "this
    is the document CR is holding". Harm is bounded (submit needs a fresh
    successful validate) but the page carried neither a stage nor a time, so
    nothing on it told the reviewer how old it was.

    Asserted through pypdf, not render_text: the footer is drawn on the canvas,
    not built as a flowable, so render_text cannot see it at all.
    """
    from io import BytesIO

    from pypdf import PdfReader

    out = nar1_pdf.render(
        SAMPLE, validated_at="2026-08-16T09:30:00+00:00", stage="validation_failed"
    )
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(out)).pages)
    assert "2026-08-16T09:30:00+00:00" in text
    assert "validation_failed" in text


def test_the_footer_says_so_when_no_validation_time_is_known():
    """A missing timestamp is reported, not quietly omitted — an undated
    snapshot must not read like a fresh one."""
    from io import BytesIO

    from pypdf import PdfReader

    out = nar1_pdf.render(SAMPLE)
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(out)).pages)
    assert "time not recorded" in text


# ---------------------------------------------------------------------------
# Schedule edge cases
# ---------------------------------------------------------------------------


def test_an_empty_share_element_does_not_crash_the_renderer():
    """<share/> parses to "" and share.get(...) then raises AttributeError —
    which is NOT ValueError, so it sails past the endpoint's 422 handler and
    surfaces as the unhandled 500 that handler exists to prevent. _flow already
    guards share capitals and officers this way; the schedules did not."""
    out = nar1_pdf.render(_model(
        "<schedule1><shares><share/></shares></schedule1>"
    ))
    assert out.startswith(b"%PDF-")


def test_an_empty_allottee_keeps_the_shares_on_the_page():
    """The group still carries a share figure. Dropping the unreadable allottee
    row would take that block of shares off a document about share capital, so
    the row stays with the holder named as missing."""
    text = nar1_pdf.render_text(_model("""
      <schedule1><shares><share>
        <clsOfShares>Ordinary</clsOfShares>
        <shareHolderGrps><shareHolderGrp>
          <sharesAlloted>1000</sharesAlloted>
          <shType>1</shType>
          <allotteeRec><allottee/></allotteeRec>
        </shareHolderGrp></shareHolderGrps>
      </share></shares></schedule1>
    """))
    assert "1000" in text
    assert "(no name given)" in text


def test_a_sole_holding_with_two_allottees_is_not_labelled_joint():
    """shType is CR's own Shareholder Type (1 = individual, 2 = joint) and was
    never read: `(joint)` was inferred from position in the allottee list, so a
    second allottee inside a shType 1 group was labelled a joint holder on the
    strength of nothing. Task 7 spent a round establishing what shType means;
    the renderer should read it rather than re-derive it more weakly."""
    text = nar1_pdf.render_text(_model("""
      <schedule1><shares><share>
        <clsOfShares>Ordinary</clsOfShares>
        <shareHolderGrps><shareHolderGrp>
          <sharesAlloted>500</sharesAlloted>
          <shType>1</shType>
          <allotteeRec>
            <allottee><allotteeType>I</allotteeType>
              <indvSurname>CHAN</indvSurname></allottee>
            <allottee><allotteeType>I</allotteeType>
              <indvSurname>WONG</indvSurname></allottee>
          </allotteeRec>
        </shareHolderGrp></shareHolderGrps>
      </share></shares></schedule1>
    """))
    assert "(joint)" not in text
    assert "(sole holding)" in text


def test_a_joint_holding_is_labelled_from_shtype_not_from_position():
    """CR's own Schedule 1 example: shType 2, two allottees. The figure is shown
    once — repeating it against each holder would multiply the company's issued
    capital on the page."""
    text = nar1_pdf.render_text(SAMPLE)
    assert "(joint)" in text


def test_the_percent_held_column_appears_only_where_cr_carries_it():
    """perOfShares is a Schedule 2 field. On a Schedule 1 the column would be
    blank on every row, and a blank column on a document whose job is spotting
    missing data reads as an error rather than as "not applicable"."""
    listed = (
        _FIXTURES / "validateForm" / "validate_NAR1(Listed Company, Schedule 2).xml"
    ).read_text(encoding="utf8")
    assert "% held" not in nar1_pdf.render_text(SAMPLE)
    assert "% held" in nar1_pdf.render_text(listed)
