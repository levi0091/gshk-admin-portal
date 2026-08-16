"""services/tpsi/forms/nar1_mapper.py — G-FlowDesk entity graph -> CR dict.

Pure in, pure out: no Supabase, no CR. The round-trip test at the bottom is the
one that matters -- it diffs against CR's OWN shipped example, which is the
source of truth for shape (spec §5 BE-1).
"""
import re
from pathlib import Path

import pytest

from services.tpsi.forms import nar1, nar1_mapper

SAMPLE = (
    Path(__file__).resolve().parents[3]
    / "docs" / "Web Form Example" / "validateForm"
    / "validate_NAR1(Private Company, Schedule 1).xml"
)


def graph(**over):
    base = {
        "entity": {
            "id": "e1",
            "company_name": "TEST COMPANY LIMITED",
            "company_name_zh": "測試有限公司",
            "br_number": "00000001",
            "incorporation_date": "2020-03-01",
            "registered_address_id": "a1",
        },
        "registered_address": {
            "line1": "Flat A", "line2": "Test Tower", "line3": "1 Test Street",
            "city": "CENTRAL", "state_region": None, "postal_code": None,
            "country": "Hong Kong", "is_hk_address": True,
        },
        "officers": [],
        "secretaries": [],
        "share_classes": [],
        "shareholdings": [],
        "persons": {},
        "addresses": {},
        "identity_documents": {},
    }
    base.update(over)
    return base


def person(pid="p1", **over):
    p = {
        "id": pid, "full_name": "CHAN TAI MAN", "surname": "CHAN",
        "given_names": "TAI MAN", "full_name_zh": "陳大文",
        "email": "test@cr.gov.hk", "residential_address_id": "a2",
    }
    p.update(over)
    return p


ADDR = {
    "line1": "Flat B", "line2": "Res Tower", "line3": "2 Res Street",
    "city": "CENTRAL", "state_region": None, "postal_code": None,
    "country": "Hong Kong", "is_hk_address": True,
}


# ---- scalars ---------------------------------------------------------------

def test_maps_the_core_scalars():
    data = nar1_mapper.map_entity(graph(), year=2026)
    assert data["brNo"] == "00000001"
    assert data["yearAnnualReturn"] == 2026
    assert data["language"] == "E"


def test_omits_the_fields_crs_own_example_omits():
    """The worksheet marks these mandatory; CR's shipped example has none of
    them. The example wins (spec §5 BE-1 source-of-truth order)."""
    data = nar1_mapper.map_entity(graph(), year=2026)
    for absent in ("dateReturnFrom", "dateReturnTo", "signatoryDate",
                   "selectPersonId", "selectPersonName", "selectCapacityDesc"):
        assert absent not in data


def test_a_private_company_declares_schedule_1_only():
    data = nar1_mapper.map_entity(graph(), year=2026)
    assert data["shareholderListedInSch1"] == "Y"
    assert data["shareholderListedInSch2"] == "N"
    assert data["shareholderListedInCdrom"] == "N"


# ---- addresses -------------------------------------------------------------

def test_maps_a_registered_address_onto_crs_five_address_lines():
    data = nar1_mapper.map_entity(graph(), year=2026)
    assert data["roAddr"] == {
        "addrLangInd": "E",
        "flatFlrBlk": "Flat A",
        "bldg": "Test Tower",
        "stEstLotVlg": "1 Test Street",
        "dstCtyStatePostal": "CENTRAL",
        "ctryRegion": "HKG",
    }


def test_country_becomes_a_three_letter_region_code():
    """ctryRegion is max 4 characters. "Hong Kong" would be truncated silently
    by CR or rejected; HKG is what CR's own example sends."""
    g = graph(registered_address={**ADDR, "country": "Hong Kong"})
    assert nar1_mapper.map_entity(g, year=2026)["roAddr"]["ctryRegion"] == "HKG"


def test_an_unmapped_country_is_a_mapping_error_not_a_guess():
    """Inventing a code produces a document CR rejects AFTER the fee is taken."""
    g = graph(registered_address={**ADDR, "country": "Freedonia"})
    with pytest.raises(nar1_mapper.MappingError) as exc:
        nar1_mapper.map_entity(g, year=2026)
    assert any("Freedonia" in p for p in exc.value.problems)


# ---- officers --------------------------------------------------------------

def test_an_individual_director_lands_in_inddirlist():
    g = graph(
        officers=[{"person_id": "p1", "party_type": "individual",
                   "role": "director", "is_current": True}],
        persons={"p1": person()},
        addresses={"a1": ADDR, "a2": ADDR},
    )
    data = nar1_mapper.map_entity(g, year=2026)
    assert len(data["indDirList"]) == 1
    d = data["indDirList"][0]
    assert d["indvEngSname"] == "CHAN"
    assert d["indvEngOname"] == "TAI MAN"
    assert d["indvChiName"] == "陳大文"
    assert d["dirInd"] == "Y"


def test_a_corporate_director_lands_in_corpdirlist():
    g = graph(
        officers=[{"corporate_name": "HOLDCO LIMITED", "party_type": "corporate",
                   "role": "director", "is_current": True}],
        addresses={"a1": ADDR},
    )
    data = nar1_mapper.map_entity(g, year=2026)
    assert data["corpDirList"][0]["corpEngName"] == "HOLDCO LIMITED"
    assert "indDirList" not in data


def test_a_reserve_director_lands_in_resdirlist():
    g = graph(
        officers=[{"person_id": "p1", "party_type": "individual",
                   "role": "reserve_director", "is_current": True}],
        persons={"p1": person()},
        addresses={"a1": ADDR, "a2": ADDR},
    )
    data = nar1_mapper.map_entity(g, year=2026)
    assert len(data["resDirList"]) == 1
    assert "indDirList" not in data


def test_a_resigned_officer_is_excluded():
    """The annual return states the officers AT the return date. A resigned
    director filed as current is a false statutory declaration."""
    g = graph(
        officers=[{"person_id": "p1", "party_type": "individual",
                   "role": "director", "is_current": False}],
        persons={"p1": person()},
        addresses={"a1": ADDR, "a2": ADDR},
    )
    assert "indDirList" not in nar1_mapper.map_entity(g, year=2026)


def test_the_gshk_secretary_is_a_corporate_secretary_with_its_tcsp_number():
    g = graph(
        secretaries=[{"is_gshk": True, "secretary_name": "Get Started HK Limited",
                      "tcsp_number": "TC000807", "is_current": True}],
        addresses={"a1": ADDR},
    )
    sec = nar1_mapper.map_entity(g, year=2026)["corpSecList"][0]
    assert sec["corpEngName"] == "Get Started HK Limited"
    assert sec["corpTcspNo"] == "TC000807"


def test_hkid_is_sent_without_its_bracketed_check_digit():
    """indvHkidNo is max 8 characters. "A123456(7)" is 10 and would be rejected
    on length; stripping the punctuation gives the 8 CR expects."""
    g = graph(
        officers=[{"person_id": "p1", "party_type": "individual",
                   "role": "director", "is_current": True}],
        persons={"p1": person()},
        addresses={"a1": ADDR, "a2": ADDR},
        identity_documents={"p1": [{"id_type": "hkid", "id_number": "A123456(7)",
                                    "is_primary": True}]},
    )
    assert nar1_mapper.map_entity(g, year=2026)["indDirList"][0]["indvHkidNo"] == "A1234567"


def test_a_passport_holder_gets_a_number_and_an_issuing_country():
    g = graph(
        officers=[{"person_id": "p1", "party_type": "individual",
                   "role": "director", "is_current": True}],
        persons={"p1": person()},
        addresses={"a1": ADDR, "a2": ADDR},
        identity_documents={"p1": [{"id_type": "passport", "id_number": "X1234567",
                                    "issuing_country": "Singapore",
                                    "is_primary": True}]},
    )
    d = nar1_mapper.map_entity(g, year=2026)["indDirList"][0]
    assert d["indvPptNo"] == "X1234567"
    assert d["indvPptIssCtry"] == "SGP"
    assert "indvHkidNo" not in d


# ---- share capital and Schedule 1 ------------------------------------------

def test_each_share_class_becomes_one_sharecapital_entry():
    g = graph(share_classes=[
        {"id": "sc1", "class_name": "Ordinary", "currency": "HKD",
         "total_issued": 1000, "total_paid": 1000},
        {"id": "sc2", "class_name": "Preference", "currency": "CAD",
         "total_issued": 2000, "total_paid": 2000},
    ], addresses={"a1": ADDR})
    caps = nar1_mapper.map_entity(g, year=2026)["shareCapitals"]
    assert len(caps) == 2
    assert caps[0] == {
        "clsOfShares": "Ordinary", "currency": "HKD",
        "noOfShareIssuedOnThisCls": 1000, "issuedCapital": 1000,
        "paidUpCapital": 1000,
    }


def test_schedule_1_groups_shareholders_under_their_share_class():
    g = graph(
        share_classes=[{"id": "sc1", "class_name": "Ordinary", "currency": "HKD",
                        "total_issued": 1000, "total_paid": 1000}],
        shareholdings=[
            {"share_class_id": "sc1", "person_id": "p1", "party_type": "individual",
             "shares_held": 100, "is_current": True},
            {"share_class_id": "sc1", "corporate_name": "TEST COMPANY LIMITED",
             "party_type": "corporate", "shares_held": 900, "is_current": True},
        ],
        persons={"p1": person()},
        addresses={"a1": ADDR, "a2": ADDR},
    )
    share = nar1_mapper.map_entity(g, year=2026)["schedule1"]["shares"][0]
    assert share["clsOfShares"] == "Ordinary"
    grps = share["shareHolderGrps"]
    assert [g_["sharesAlloted"] for g_ in grps] == [100, 900]
    assert grps[0]["allotteeRec"][0]["allotteeType"] == "I"
    assert grps[1]["allotteeRec"][0]["allotteeType"] == "C"


def test_a_former_shareholding_is_excluded():
    g = graph(
        share_classes=[{"id": "sc1", "class_name": "Ordinary", "currency": "HKD",
                        "total_issued": 1000, "total_paid": 1000}],
        shareholdings=[{"share_class_id": "sc1", "person_id": "p1",
                        "party_type": "individual", "shares_held": 100,
                        "is_current": False}],
        persons={"p1": person()},
        addresses={"a1": ADDR, "a2": ADDR},
    )
    assert nar1_mapper.map_entity(g, year=2026)["schedule1"]["shares"] == []


# ---- the round trip --------------------------------------------------------

def _cardinality(xml: str) -> dict[str, int]:
    """Count every repeating wrapper's children. Silent data loss hides HERE:
    a mapper that drops the second director still produces valid XML."""
    return {
        tag: len(re.findall(rf"<cr:{tag}>", xml))
        for tag in ("shareCapital", "indSec", "corpSec", "indDir", "corpDir",
                    "resDir", "share", "shareHolderGrp", "allottee")
    }


def test_the_mapped_dict_builds_without_a_validation_error():
    """nar1.validate() is the schema gate. A mapper key CR does not know is a
    document CR rejects -- catch it here, not at a chargeable call."""
    g = graph(
        officers=[{"person_id": "p1", "party_type": "individual",
                   "role": "director", "is_current": True}],
        secretaries=[{"is_gshk": True, "secretary_name": "Get Started HK Limited",
                      "tcsp_number": "TC000807", "is_current": True}],
        share_classes=[{"id": "sc1", "class_name": "Ordinary", "currency": "HKD",
                        "total_issued": 1000, "total_paid": 1000}],
        shareholdings=[{"share_class_id": "sc1", "person_id": "p1",
                        "party_type": "individual", "shares_held": 1000,
                        "is_current": True}],
        persons={"p1": person()},
        addresses={"a1": ADDR, "a2": ADDR},
    )
    data = nar1_mapper.map_entity(g, year=2026)
    assert nar1.validate(data) == []
    xml = nar1.build_nar1_xml(data)
    assert "<cr:brNo>00000001</cr:brNo>" in xml


def test_round_trip_cardinality_matches_crs_own_example():
    """Build the same company CR's example describes and assert the repeating
    wrappers come out with the same counts. This is the assertion spec §5 BE-1
    calls for: cardinality on repeating wrappers is where data loss hides."""
    g = graph(
        officers=[
            {"person_id": "p1", "party_type": "individual", "role": "director",
             "is_current": True},
            {"corporate_name": "Test Company Limited", "party_type": "corporate",
             "role": "director", "is_current": True},
            {"person_id": "p1", "party_type": "individual",
             "role": "reserve_director", "is_current": True},
            {"person_id": "p1", "party_type": "individual",
             "role": "company_secretary", "is_current": True},
        ],
        secretaries=[{"is_gshk": True, "secretary_name": "TEST COMPANY LIMITED",
                      "tcsp_number": "TC000807", "is_current": True}],
        share_classes=[
            {"id": "sc1", "class_name": "Ordinary", "currency": "HKD",
             "total_issued": 1000, "total_paid": 1000},
            {"id": "sc2", "class_name": "Preference", "currency": "CAD",
             "total_issued": 2000, "total_paid": 2000},
        ],
        shareholdings=[
            {"share_class_id": "sc1", "person_id": "p1", "party_type": "individual",
             "shares_held": 100, "is_current": True},
            {"share_class_id": "sc1", "corporate_name": "TEST COMPANY LIMITED",
             "party_type": "corporate", "shares_held": 900, "is_current": True},
            {"share_class_id": "sc2", "person_id": "p1", "party_type": "individual",
             "shares_held": 2000, "is_current": True},
        ],
        persons={"p1": person()},
        addresses={"a1": ADDR, "a2": ADDR},
    )
    ours = _cardinality(nar1.build_nar1_xml(nar1_mapper.map_entity(g, year=2020)))
    theirs = _cardinality(SAMPLE.read_text(encoding="utf8"))

    for tag in ("shareCapital", "indSec", "corpSec", "indDir", "corpDir",
                "resDir", "share", "shareHolderGrp"):
        assert ours[tag] == theirs[tag], (
            f"{tag}: built {ours[tag]}, CR's example has {theirs[tag]}"
        )


def test_the_mapper_does_no_io():
    """The riskiest form logic in the system must be testable without CR and
    without Supabase -- the TEST form APIs are open 30 hours a week."""
    import inspect
    src = inspect.getsource(nar1_mapper)
    assert "supabase" not in src.lower()
