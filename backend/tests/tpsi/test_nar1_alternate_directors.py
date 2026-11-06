"""NAR1 lists an alternate director beside the directors (PBI-70 revived).

CR's example carries `dirInd`, `altDirInd` and `altTo` on every indDir / corpDir
row (empty for a director); an alternate is dirInd N, altDirInd Y, with `altTo`
naming the director (String 72 on NAR1). The printed return already has the
"Alternate Director" tick and the "Alternate to" box and reads those same
values, which the last test pins end to end.
"""
import pytest

from services.tpsi.forms import nar1_mapper
from tests.tpsi.test_nar1_mapper import ADDR, CORP_ADDR, graph, mapped, person


def _world(*, alternate_to="OD", corporate_alternate=False, director_name="WONG KA WAI"):
    officers = [
        {"id": "OD", "person_id": "pd", "party_type": "individual", "role": "director",
         "is_current": True},
        {"id": "OA", "party_type": "individual", "role": "alternate_director",
         "is_current": True, "alternate_to_officer_id": alternate_to,
         **({"person_id": "pa"} if not corporate_alternate else {})},
    ]
    persons = {"pd": person("pd", surname="WONG", given_names=director_name[5:],
                            full_name=director_name),
               "pa": person("pa", full_name="LAU MEI", surname="LAU", given_names="MEI")}
    addresses = {"a1": ADDR, "a2": ADDR}
    entities = {}
    if corporate_alternate:
        officers[1].update(party_type="corporate", corporate_name="ALT HOLDINGS",
                           corporate_address=CORP_ADDR, corporate_br_no="12345678")
        entities = {}
    return graph(officers=officers, persons=persons, addresses=addresses,
                 entities=entities)


def test_an_alternate_is_listed_with_dirind_n_altdirind_y_and_the_directors_name():
    data = mapped(_world())
    rows = data["indDirList"]
    assert [r["indvEngSname"] for r in rows] == ["WONG", "LAU"]
    director, alternate = rows
    assert director["dirInd"] == "Y" and "altDirInd" not in director
    assert (alternate["dirInd"], alternate["altDirInd"], alternate["altTo"]) == (
        "N", "Y", "WONG KA WAI")


def test_a_corporate_alternate_goes_in_corpdirlist():
    data = mapped(_world(corporate_alternate=True))
    row = data["corpDirList"][0]
    assert (row["dirInd"], row["altDirInd"], row["altTo"]) == ("N", "Y", "WONG KA WAI")
    assert row["corpEngName"] == "ALT HOLDINGS"


def test_the_alternate_is_not_among_the_cards_directors():
    from services import nar1_return_data

    summary = nar1_return_data.summarise(_world())
    assert summary["directors"] == ["WONG KA WAI"]


def test_an_alternate_with_no_director_recorded_is_a_problem_not_an_empty_altto():
    with pytest.raises(nar1_mapper.MappingError) as caught:
        mapped(_world(alternate_to=None))
    assert any("they act for is not recorded" in p for p in caught.value.problems)


def test_a_director_name_over_crs_72_is_a_problem():
    with pytest.raises(nar1_mapper.MappingError) as caught:
        mapped(_world(director_name="WONG " + "X" * 80))
    assert any("longer than CR's 72" in p for p in caught.value.problems)


def test_the_printed_return_ticks_alternate_and_prints_alternate_to():
    from services.nar1_form import field_map as fm
    from services.nar1_form import fill
    from services.tpsi.forms.nar1 import build_nar1_xml
    from tests.test_nar1_form_fill import values_of

    g = _world()
    g["officers"].reverse()  # the alternate first, so it lands in the main block
    values = values_of(fill.render_fields(build_nar1_xml(mapped(g))))
    block = fm.DIRECTOR_INDIVIDUAL
    assert block["capacity_alternate"] in values
    assert block["capacity_director"] not in values
    assert values[block["alternate_to"]] == ["WONG KA WAI"]
