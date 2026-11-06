"""Alternate directors in the ND2A / ND2B form models (PBI-70 revived).

Jacqueline, 2026-11-04: "Alternate directors are not out of scope." CR's own
examples carry only an EMPTY `altTo`, so these assert the shape from the
worksheet's schema (cpty `AD`, `altTo` right after it) on top of the existing
director examples.
"""
import copy

import pytest

from services.officer_changes import form_xml, nd2a_mapper, nd2b_mapper
from services.tpsi.forms.nar1_mapper import MappingError
from tests.officer_changes import cr_fixtures as fx

DIRECTOR_ID = "OFF-DIR"


def _world(name_part: str, form: str = "ND2A"):
    path = next(p for p in fx.files(form) if name_part in p.name)
    return fx.build_world(path)


def _with_director(graph, *, surname="WONG", given="Ka Wai"):
    """The director the alternate acts for, on the officer list NAR1 loads."""
    graph.setdefault("persons", {})["P-DIR"] = {
        "id": "P-DIR", "full_name": f"{surname} {given}", "surname": surname,
        "given_names": given}
    graph["officers"] = [{"id": DIRECTOR_ID, "person_id": "P-DIR", "role": "director",
                          "is_current": True}]
    return graph


def _alternate(entry):
    entry = copy.deepcopy(entry)
    entry.update(capacity="alternate_director", alternate_to_officer_id=DIRECTOR_ID)
    return entry


def test_an_alternate_appointment_is_cpty_ad_with_alt_to_right_after_it():
    graph, entries = _world("Appoint Individual Director")
    _with_director(graph)
    data = nd2a_mapper.map_case(graph, [_alternate(entries[0])], for_esign=True)
    bean = data["appOfNpBeans"][0]
    assert bean["cpty"] == "AD" and bean["altTo"] == "WONG Ka Wai"
    # An alternate consents like a director: id for the PinSign, existing-director flag.
    assert bean["@id"] == "S1" and bean["dirBeforeApptInd"] == "N"
    xml = form_xml.build("Nd2a", data)
    assert "<cr:cpty>AD</cr:cpty><cr:altTo>WONG Ka Wai</cr:altTo><cr:indvChiName>" in xml
    assert 'id="S1"' in xml


def test_a_director_and_a_secretary_carry_no_alt_to():
    graph, entries = _world("Appoint Individual Director")
    _with_director(graph)
    bean = nd2a_mapper.map_case(graph, entries)["appOfNpBeans"][0]
    assert bean["cpty"] == "D" and "altTo" not in bean


def test_an_alternate_cessation_is_ad_with_alt_to_and_leaves_no_directorship():
    graph, entries = _world("Cease Individual Director")
    _with_director(graph)
    data = nd2a_mapper.map_case(graph, [_alternate(entries[0])])
    bean = data["resCesBeans"][0]
    assert (bean["cpty"], bean["altTo"], bean["dirAfterCesInd"]) == ("AD", "WONG Ka Wai", "N")
    xml = form_xml.build("Nd2a", data)
    assert "<cr:cpty>AD</cr:cpty><cr:altTo>WONG Ka Wai</cr:altTo>" in xml


def test_an_alternate_to_a_body_corporate_director_is_named_by_its_company_name():
    graph, entries = _world("Appoint Individual Director")
    graph.setdefault("entities", {})["C-DIR"] = {"id": "C-DIR", "company_name": "ACME LTD"}
    graph["officers"] = [{"id": DIRECTOR_ID, "corporate_entity_id": "C-DIR",
                          "party_type": "corporate", "role": "director"}]
    bean = nd2a_mapper.map_case(graph, [_alternate(entries[0])])["appOfNpBeans"][0]
    assert bean["altTo"] == "ACME LTD"


def test_a_director_who_is_not_on_the_officer_list_is_a_problem():
    graph, entries = _world("Appoint Individual Director")
    graph["officers"] = []
    with pytest.raises(MappingError) as caught:
        nd2a_mapper.map_case(graph, [_alternate(entries[0])])
    assert any("alternate acts for is not on the company's officer list" in p
               for p in caught.value.problems)


def test_a_name_over_crs_fifteen_characters_is_reported_not_truncated():
    graph, entries = _world("Appoint Individual Director")
    _with_director(graph, surname="WONG", given="Ka Wai Johnny")  # 18 characters
    with pytest.raises(MappingError) as caught:
        nd2a_mapper.map_case(graph, [_alternate(entries[0])])
    message = next(p for p in caught.value.problems if "Alternate to" in p)
    assert "15" in message and "WONG Ka Wai Johnny" in message and "18" in message


def test_consent_ids_number_alternates_with_the_directors():
    graph, entries = _world("Appoint Individual Director")
    _with_director(graph)
    second = _alternate(entries[0])
    second["id"] = "N-ALT"
    second["person_id"] = "P-ALT"
    graph["persons"]["P-ALT"] = {**graph["persons"][entries[0]["person_id"]], "id": "P-ALT"}
    graph["identity_documents"]["P-ALT"] = graph["identity_documents"][entries[0]["person_id"]]
    graph["eservice"]["P-ALT"] = graph["eservice"][entries[0]["person_id"]]
    data = nd2a_mapper.map_case(graph, [entries[0], second])
    assert [b["@id"] for b in data["appOfNpBeans"]] == ["S1", "S2"]


def test_an_nd2b_for_an_alternate_is_cpty_ad_and_has_no_alt_to():
    graph, entries = _world("Individual Director", "ND2B")
    entry = copy.deepcopy(entries[0])
    entry["capacity"] = "alternate_director"
    data = nd2b_mapper.map_case(graph, [entry], for_esign=True)
    bean = data["npBeans"][0]
    assert bean["cpty"] == "AD" and "altTo" not in bean
    assert "<cr:cpty>AD</cr:cpty>" in form_xml.build("Nd2b", data)
