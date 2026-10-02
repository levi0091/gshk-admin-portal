"""CR's Form ND2A as the client and CR receive it (spec §7, answer 15).

Every page CR's form needs, in CR's order; partial numbers on public pages and
full ones on the PI sheet; a flat file; nothing dropped. The typography is
asserted by measurement in test_nd2a_geometry.py.
"""
import io

import pytest
from pypdf import PdfReader

from services.officer_change_form import FormFillError, page_plan, render, render_fields
from services.officer_changes import form_xml, nd2a_mapper
from tests.officer_changes import cr_fixtures as fx

COMPANY = "KANENAS HOLDING LIMITED  卡尼納斯控股有限公司"


def _xml(path=None, *, graph_entries=None, mutate=None):
    graph, entries = graph_entries or fx.build_world(path)
    if mutate:
        mutate(graph, entries)
    return form_xml.build("Nd2a", nd2a_mapper.map_case(graph, entries))


def _text(pdf: bytes) -> list[str]:
    return [page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages]


@pytest.fixture(scope="module")
def overflow_xml():
    return _xml(graph_entries=fx.combined_world("ND2A", fx.ND2A_OVERFLOW,
                                                fx.ND2A_OVERFLOW_RENAMES))


@pytest.mark.parametrize("path", fx.files("ND2A"), ids=lambda p: p.name)
def test_every_example_renders_flat_on_crs_pages(path):
    xml = _xml(path)
    pdf = render("Nd2a", xml, company_name=COMPANY)
    reader = PdfReader(io.BytesIO(pdf))
    plan = page_plan("Nd2a", xml)
    assert len(reader.pages) == len(plan)
    assert [p["sheet"] for p in plan][:3] == ["1", "2", "3"]
    assert "/AcroForm" not in reader.trailer["/Root"]
    assert not any(a.get_object().get("/Subtype") == "/Widget"
                   for page in reader.pages for a in page.get("/Annots") or [])
    text = "\n".join(_text(pdf))
    assert "00000001" in text and "KANENAS HOLDING LIMITED" in text
    assert "None" not in text


def test_a_ceasing_officer_with_no_english_surname_still_renders():
    # A mononym (or a Viewpoint row with only given names): mapping passes, so
    # the renderer's drop guard must count the block by the name it does carry.
    leaver = next(p for p in fx.files("ND2A") if "Cease Individual Director" in p.name)

    def mononym(graph, entries):
        # Copies, never in place: the fixture worlds share their person rows.
        leaving = {e["person_id"] for e in entries if e.get("person_id")}
        graph["persons"] = {
            pid: ({**p, "surname": "", "given_names": "MADONNA", "full_name": ""}
                  if pid in leaving else p)
            for pid, p in graph["persons"].items()}

    xml = _xml(leaver, mutate=mononym)
    text = "\n".join(_text(render("Nd2a", xml, company_name=COMPANY)))
    assert "MADONNA" in text


def test_an_overseas_body_corporate_director_needs_no_br_number():
    # CR's worksheet: corpBrNo and selectAssoBrNo are Mandatory = N, and the
    # printed form's BR box is "only applicable to body corporate registered
    # in Hong Kong". Its absence must not block the form on any route.
    path = next(p for p in fx.files("ND2A") if "Appoint Corporate Director" in p.name)
    graph, entries = fx.build_world(path)
    for entry in entries:
        if entry.get("corporate_entity_id"):
            graph["entities"][entry["corporate_entity_id"]]["br_number"] = ""
    xml = form_xml.build("Nd2a", nd2a_mapper.map_case(graph, entries))
    assert "corpBrNo" not in xml and "selectAssoBrNo" not in xml
    assert "corpEngName" in xml
    try:   # the e-Sign route may refuse for other reasons; never for this one
        nd2a_mapper.map_case(graph, entries, for_esign=True)
    except nd2a_mapper.nm.MappingError as exc:
        assert "BR number" not in str(exc)


def test_an_appointment_adds_its_pi_sheet_and_a_cessation_does_not():
    director = next(p for p in fx.files("ND2A") if "Appoint Individual Director" in p.name)
    leaver = next(p for p in fx.files("ND2A") if "Cease Individual Director" in p.name)
    assert [p["sheet"] for p in page_plan("Nd2a", _xml(director))] == ["1", "2", "3", "PI"]
    assert [p["sheet"] for p in page_plan("Nd2a", _xml(leaver))] == ["1", "2", "3"]


def test_the_overflow_case_generates_every_sheet_in_crs_order(overflow_xml):
    plan = [p["sheet"] for p in page_plan("Nd2a", overflow_xml)]
    assert plan == ["1", "2", "3", "A", "A", "B", "B", "C", "PI", "PI", "PI"]
    pdf = render("Nd2a", overflow_xml, company_name=COMPANY)
    assert len(PdfReader(io.BytesIO(pdf)).pages) == 11
    pages = _text(pdf)
    assert "TEST COMPANY LIMITED" in pages[3] and "LEE" in pages[4]   # two Sheet A's
    assert "HO" in pages[5] and "WONG" in pages[6]           # two Sheet B's
    assert "TEST COMPANY LIMITED" in pages[7]                # one Sheet C


def test_page_three_counts_match_the_sheets_present(overflow_xml):
    filled = PdfReader(io.BytesIO(render_fields("Nd2a", overflow_xml, company_name=COMPANY)))
    values = {}
    for annot in filled.pages[2].get("/Annots") or []:
        obj = annot.get_object()
        values[str(obj.get("/T")).split("__p")[0]] = str(obj.get("/V") or "")
    assert (values["fill_18_P.3"], values["fill_19_P.3"], values["fill_20_P.3"],
            values["fill_21_P.3"]) == ("2", "2", "1", "3")


def test_the_clients_copy_drops_the_pi_sheets_but_still_counts_them(overflow_xml):
    plan = [p["sheet"] for p in page_plan("Nd2a", overflow_xml, public_only=True)]
    assert "PI" not in plan and len(plan) == 8
    pdf = render("Nd2a", overflow_xml, company_name=COMPANY, public_only=True)
    text = "\n".join(_text(pdf))
    assert "A123456" not in text and "H12345678" not in text  # no full numbers
    filled = PdfReader(io.BytesIO(render_fields("Nd2a", overflow_xml, public_only=True,
                                                company_name=COMPANY)))
    counts = {str(a.get_object().get("/T")).split("__p")[0]: str(a.get_object().get("/V") or "")
              for a in filled.pages[2].get("/Annots") or []}
    assert counts["fill_21_P.3"] == "3"


def test_public_pages_carry_partial_numbers_and_the_pi_sheet_the_full_ones():
    director = next(p for p in fx.files("ND2A") if "Appoint Individual Director" in p.name)
    pages = _text(render("Nd2a", _xml(director), company_name=COMPANY))
    assert "A123" in pages[1] and "A123456" not in pages[1]
    assert "H1234" in pages[1] and "H12345678" not in pages[1]
    assert "A123456" in pages[3] and "H12345678" in pages[3]


def test_a_secretary_with_no_identity_document_has_no_pi_sheet_and_no_none():
    secretary = next(p for p in fx.files("ND2A") if "Appoint Individual Secretary" in p.name)

    def strip_ids(graph, entries):
        graph["identity_documents"][entries[0]["person_id"]] = []
        graph["persons"][entries[0]["person_id"]]["full_name_zh"] = ""

    xml = _xml(secretary, mutate=strip_ids)
    assert "PI" not in [p["sheet"] for p in page_plan("Nd2a", xml)]
    text = "\n".join(_text(render("Nd2a", xml, company_name=COMPANY)))
    assert "None" not in text and "NIL" not in text


def test_a_director_with_no_identity_document_still_gets_a_pi_sheet():
    director = next(p for p in fx.files("ND2A") if "Appoint Individual Director" in p.name)

    def strip_ids(graph, entries):
        graph["identity_documents"][entries[0]["person_id"]] = []

    xml = _xml(director, mutate=strip_ids)
    assert [p["sheet"] for p in page_plan("Nd2a", xml)][-1] == "PI"
    assert "NIL" not in "\n".join(_text(render("Nd2a", xml, company_name=COMPANY)))


def test_the_signature_date_is_empty_until_filed():
    leaver = next(p for p in fx.files("ND2A") if "Cease Individual Director" in p.name)
    xml = _xml(leaver)
    assert "02/10/2026" not in _text(render("Nd2a", xml, company_name=COMPANY))[2]
    assert "02/10/2026" in _text(render("Nd2a", xml, company_name=COMPANY,
                                        submitted_on="2026-10-02"))[2]


def test_the_presenter_reference_names_the_form_year_and_company():
    leaver = next(p for p in fx.files("ND2A") if "Cease Individual Director" in p.name)
    page1 = _text(render("Nd2a", _xml(leaver), company_name=COMPANY))[0]
    assert "ND2A/2022/KANENAS HOLDING LIMITED" in page1


def test_the_signature_line_strikes_the_office_the_signer_does_not_hold():
    leaver = next(p for p in fx.files("ND2A") if "Cease Individual Director" in p.name)
    filled = PdfReader(io.BytesIO(render_fields("Nd2a", _xml(leaver), company_name=COMPANY)))
    values = {str(a.get_object().get("/T")).split("__p")[0]:
              str(a.get_object().get("/V") or "").strip()
              for a in filled.pages[2].get("/Annots") or []}
    assert values["Dropdown_7_P.3"] and not values["Dropdown_6_P.3"]


def test_a_corrupt_model_is_a_form_fill_error_not_a_partial_pdf():
    with pytest.raises(FormFillError):
        render("Nd2a", "<cr:nothing/>")
    with pytest.raises(FormFillError):
        render("Nar1", "<cr:brNo>1</cr:brNo>")
