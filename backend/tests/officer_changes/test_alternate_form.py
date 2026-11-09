"""CR's ND2A / ND2B as printed for an alternate director (PBI-70 revived).

The template already has the boxes -- "Alternate Director" tick, "Alternate to",
and the consent line "I consent to act as director / alternate director" with a
deletion dropdown on each word. These pin which are filled for which office.
"""
import io

from pypdf import PdfReader

from services.officer_change_form import render, render_fields
from services.officer_change_form import nd2a_map as m2a
from services.officer_changes import form_xml, nd2a_mapper, nd2b_mapper
from tests.officer_changes.test_alternate_mappers import _alternate, _with_director, _world

COMPANY = "KANENAS HOLDING LIMITED"


def _values(pdf: bytes, page_index: int) -> dict:
    reader = PdfReader(io.BytesIO(pdf))
    return {str(a.get_object().get("/T")).split("__p")[0]: str(a.get_object().get("/V") or "")
            for a in reader.pages[page_index].get("/Annots") or []}


def _nd2a(name_part, *, alternate: bool):
    graph, entries = _world(name_part)
    _with_director(graph)
    if alternate:
        entries = [_alternate(entries[0])]
    return form_xml.build("Nd2a", nd2a_mapper.map_case(graph, entries))


def test_an_alternate_appointment_ticks_the_box_prints_alt_to_and_strikes_director():
    xml = _nd2a("Appoint Individual Director", alternate=True)
    values = _values(render_fields("Nd2a", xml, company_name=COMPANY), 1)
    assert values[m2a.MAIN_2["cap_alternate"]] not in ("", "None", "/Off")
    assert values[m2a.MAIN_2["cap_director"]] in ("", "None", "/Off")
    assert values[m2a.MAIN_2["alternate_to"]] == "WONG Ka Wai"
    # "director / alternate director": the alternate keeps the second, so the
    # word struck is "director" (the other dropdown stays untouched).
    assert values[m2a.MAIN_2["consent_strike_director"]] not in ("", "None")
    assert values[m2a.MAIN_2["consent_strike_alternate"]] in ("", "None")


def test_a_director_still_strikes_alternate_director_and_prints_a_dash_for_alt_to():
    xml = _nd2a("Appoint Individual Director", alternate=False)
    values = _values(render_fields("Nd2a", xml, company_name=COMPANY), 1)
    assert values[m2a.MAIN_2["consent_strike_alternate"]] not in ("", "None")
    assert values[m2a.MAIN_2["consent_strike_director"]] in ("", "None")
    assert values[m2a.MAIN_2["alternate_to"]] == "-"


def test_an_alternate_cessation_ticks_alternate_and_prints_alt_to():
    xml = _nd2a("Cease Individual Director", alternate=True)
    values = _values(render_fields("Nd2a", xml, company_name=COMPANY), 0)
    assert values[m2a.MAIN_1["cap_alternate"]] not in ("", "None", "/Off")
    assert values[m2a.MAIN_1["alternate_to"]] == "WONG Ka Wai"


def test_an_alternate_appointment_gets_a_pi_sheet_with_its_alternate_box_ticked():
    xml = _nd2a("Appoint Individual Director", alternate=True)
    pdf = render_fields("Nd2a", xml, company_name=COMPANY)
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 4  # pages 1-3 + the PI sheet
    pi = _values(pdf, 3)
    assert pi[m2a.PI["cap_alternate"]] not in ("", "None", "/Off")


def test_the_flat_alternate_form_renders_with_the_director_named():
    xml = _nd2a("Appoint Individual Director", alternate=True)
    reader = PdfReader(io.BytesIO(render("Nd2a", xml, company_name=COMPANY)))
    assert "WONG Ka Wai" in reader.pages[1].extract_text()


def test_an_nd2b_for_an_alternate_ticks_the_alternate_box():
    from services.officer_change_form import nd2b_map as m2b

    graph, entries = _world("Individual Director", "ND2B")
    entries[0]["capacity"] = "alternate_director"
    xml = form_xml.build("Nd2b", nd2b_mapper.map_case(graph, entries))
    values = _values(render_fields("Nd2b", xml, company_name=COMPANY), 0)
    assert values[m2b.MAIN_1["cap_alternate"]] not in ("", "None", "/Off")
    assert values[m2b.MAIN_1["cap_director"]] in ("", "None", "/Off")



def test_a_body_corporate_cessation_ticks_resignation_others_on_the_form():
    """CR's XML has no reason for a body corporate, but the printed form must
    not leave its Reason box empty: a company can only resign (UAT 2026-11-08)."""
    for kind in ("Cease Corporate Secretary", "Cease Corporate Director"):
        graph, entries = _world(kind)
        xml = form_xml.build("Nd2a", nd2a_mapper.map_case(graph, entries))
        assert "rsnCes" not in xml  # the XML still follows CR's example
        values = _values(render_fields("Nd2a", xml, company_name=COMPANY), 0)
        assert values[m2a.MAIN_1["reason_resign"]] not in ("", "None", "/Off"), kind
        assert values[m2a.MAIN_1["reason_deceased"]] in ("", "None", "/Off"), kind
