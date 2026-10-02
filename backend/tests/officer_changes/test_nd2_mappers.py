"""ND2A / ND2B XML against CR's own fourteen worked examples (spec §8), plus the
edge cases the examples do not exercise (Review Focus 1, 5)."""
import copy

import pytest

from services.officer_changes import form_xml, nd2a_mapper, nd2b_mapper
from services.tpsi.forms.nar1 import FormValidationError
from services.tpsi.forms.nar1_mapper import MappingError
from tests.officer_changes import cr_fixtures as fx

#: CR's examples identify a CR-registered body corporate by BR number alone and
#: a BR-only one by name alone. The build always sends both when it has them
#: (assumption B-17, not yet verified against CR TEST), so these may be EXTRA.
_CORPORATE_EXTRAS = {"corpChiName", "corpEngName", "corpBrNo"}


def _build(form, path, **kwargs):
    graph, entries = fx.build_world(path)
    mapper = nd2a_mapper if form == "ND2A" else nd2b_mapper
    data = mapper.map_case(graph, entries, **kwargs)
    return form_xml.build("Nd2a" if form == "ND2A" else "Nd2b", data)


@pytest.mark.parametrize("path", fx.files("ND2A") + fx.files("ND2B"),
                         ids=lambda p: p.name)
def test_matches_crs_example_element_for_element(path):
    form = "ND2A" if "ND2A" in path.name else "ND2B"
    ours = fx.pairs(fx.parse_inner(_build(form, path, for_esign=True)))
    theirs = fx.pairs(fx.form_model(path))
    if "Corporate" in path.name and "Appoint" in path.name:
        extra = [p for p in ours if p not in theirs]
        assert all(p[0].split("/")[-1] in _CORPORATE_EXTRAS for p in extra), extra
        ours = [p for p in ours if p not in extra]
    assert ours == theirs


def test_fourteen_examples_are_covered():
    assert len(fx.files("ND2A")) == 10 and len(fx.files("ND2B")) == 4


def _director_world():
    path = next(p for p in fx.files("ND2A") if "Appoint Individual Director" in p.name)
    return fx.build_world(path)


def test_a_director_without_an_eregistry_account_blocks_esign_only():
    graph, entries = _director_world()
    graph["eservice"] = {}
    with pytest.raises(MappingError) as caught:
        nd2a_mapper.map_case(graph, entries, for_esign=True)
    assert any("e-Registry" in p for p in caught.value.problems)
    data = nd2a_mapper.map_case(graph, entries, for_esign=False)
    bean = data["appOfNpBeans"][0]
    assert "selectPersonId" not in bean and bean["@id"] == "S1"


def test_no_identity_document_files_nil_in_both_and_no_chinese_name_is_omitted():
    graph, entries = _director_world()
    pid = entries[0]["person_id"]
    graph["identity_documents"][pid] = []
    graph["persons"][pid]["full_name_zh"] = None
    bean = nd2a_mapper.map_case(graph, entries)["appOfNpBeans"][0]
    assert bean["indvHkidNo"] == "NIL" and bean["indvPptNo"] == "NIL"
    assert "indvHkidChkDgt" not in bean and "indvPptIssCtry" not in bean
    xml = form_xml.build("Nd2a", nd2a_mapper.map_case(graph, entries))
    assert "indvChiName" not in xml.split("appOfNpBean")[1] and "None" not in xml


def test_a_malformed_hkid_is_reported_not_filed():
    graph, entries = _director_world()
    pid = entries[0]["person_id"]
    graph["identity_documents"][pid][0]["id_number"] = "A12"
    with pytest.raises(MappingError) as caught:
        nd2a_mapper.map_case(graph, entries)
    assert any("check digit" in p for p in caught.value.problems)


def test_consent_ids_number_new_directors_in_entry_order_across_both_bean_kinds():
    graph, entries = _director_world()
    corp_path = next(p for p in fx.files("ND2A") if "Corporate Director - BR" in p.name)
    cgraph, centries = fx.build_world(corp_path)
    for key in ("persons", "entities", "addresses", "identity_documents", "eservice"):
        graph[key].update(cgraph[key])
    secretary = copy.deepcopy(entries[0])
    secretary.update(id="NS", capacity="company_secretary")
    graph["persons"][secretary["person_id"]]["tcsp_licence_no"] = "TC1"
    data = nd2a_mapper.map_case(graph, [entries[0], secretary, centries[0]])
    assert [b.get("@id") for b in data["appOfNpBeans"]] == ["S1", None]
    assert data["appOfBcBeans"][0]["@id"] == "S2"


def test_nd2b_an_undated_line_names_the_officer_and_the_item():
    path = next(p for p in fx.files("ND2B") if "Individual Director" in p.name)
    graph, entries = fx.build_world(path)
    entries[0]["items"][0]["effective_date"] = None
    with pytest.raises(MappingError) as caught:
        nd2b_mapper.map_case(graph, entries)
    assert any("CHAN TAI MAN" in p and "effective date" in p for p in caught.value.problems)


def test_nd2b_omitted_lines_are_not_filed_and_an_all_omitted_officer_is_dropped():
    path = next(p for p in fx.files("ND2B") if "Individual Director" in p.name)
    graph, entries = fx.build_world(path)
    for item in entries[0]["items"]:
        item["omitted"] = item["key"] != "email"
    bean = nd2b_mapper.map_case(graph, entries)["npBeans"][0]
    assert "indvNewEmailAddr" in bean and "indvNewChiName" not in bean
    for item in entries[0]["items"]:
        item["omitted"] = True
    with pytest.raises(MappingError, match="no change"):
        nd2b_mapper.map_case(graph, entries)


def test_nd2b_part_a_is_the_registered_name_not_the_profile():
    path = next(p for p in fx.files("ND2B") if "Individual Director" in p.name)
    graph, entries = fx.build_world(path)
    entries[0]["registered"]["name_en"] = {"surname": "OLD", "given_names": "NAME"}
    bean = nd2b_mapper.map_case(graph, entries)["npBeans"][0]
    assert bean["indvEngSname"] == "OLD"


def test_a_cessation_names_the_officer_as_cr_holds_them():
    # Renamed and re-documented on the profile, no ND2B filed: CR's register
    # still has the old name and HKID, so that is how the leaver is identified.
    path = next(p for p in fx.files("ND2A") if "Cease Individual Director" in p.name)
    graph, entries = fx.build_world(path)
    pid = entries[0]["person_id"]
    graph["baselines"] = {pid: {
        "party_type": "individual", "name_en": {"surname": "OLD", "given_names": "NAME"},
        "name_zh": "舊名", "hkid": "A1234563", "passport": None}}
    data = nd2a_mapper.map_case(graph, entries)
    beans = next(v for k, v in data.items() if isinstance(v, list) and v
                 and "rsnCes" in v[0])
    bean = beans[0]
    assert bean["indvEngSname"] == "OLD" and bean["indvEngOname"] == "NAME"
    assert bean["indvChiName"] == "舊名" and bean["indvHkidPartial"] == "A123"
    # With no baseline the profile is CR's view, unchanged.
    graph["baselines"] = {}
    beans = next(v for k, v in nd2a_mapper.map_case(graph, entries).items()
                 if isinstance(v, list) and v and "rsnCes" in v[0])
    assert beans[0]["indvEngSname"] != "OLD"


def test_form_xml_refuses_overlong_values_and_unknown_fields():
    with pytest.raises(FormValidationError) as caught:
        form_xml.build("Nd2a", {"language": "E", "brNo": "1" * 21, "bogus": "x"})
    assert any("brNo" in e and "21 characters" in e for e in caught.value.errors)
    assert any("bogus" in e for e in caught.value.errors)


def test_form_xml_emits_schema_order_and_the_bean_id():
    xml = form_xml.build("Nd2a", {
        "signatoryDate": "01/06/2022", "brNo": "00000001", "language": "E",
        "appOfNpBeans": [{"@id": "S1", "indvDtAppt": "01/06/2022", "cpty": "D"}]})
    assert xml.index("<cr:language>") < xml.index("<cr:brNo>") < xml.index("<cr:appOfNpBeans>")
    assert '<cr:appOfNpBean id="S1"><cr:cpty>D</cr:cpty>' in xml
    assert xml.endswith("<cr:signatoryDate>01/06/2022</cr:signatoryDate>")
