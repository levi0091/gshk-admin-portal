"""services/tpsi/forms/nar1_mapper.py — G-FlowDesk entity graph -> CR dict.

Pure in, pure out: no Supabase, no CR. The round-trip test at the bottom is the
one that matters -- it diffs against CR's OWN shipped example, which is the
source of truth for shape (spec §5 BE-1).
"""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from services.tpsi.forms import nar1, nar1_mapper

#: HKT is a fixed UTC+8 offset with no DST. Computed here, not imported from the
#: module under test, so the test pins the offset rather than echoing it.
HKT = timezone(timedelta(hours=8))

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
        # Every GSHK-managed company has GSHK as its company secretary, and the
        # secretary is who signs the return (Q-030). Without one there is no
        # signatory and map_entity() rightly refuses to build an unsigned
        # statutory declaration -- see test_a_return_with_nobody_to_sign_it_*.
        "secretaries": [{"is_gshk": True,
                         "secretary_name": "Get Started HK Limited",
                         "tcsp_number": "TC000807", "is_current": True}],
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

#: A corporate party's OWN registered office — deliberately different from both
#: the filing entity's registered address and any individual's residence, so a
#: test can tell which one was filed.
CORP_ADDR = {
    "line1": "Suite 1", "line2": "Corp Tower", "line3": "3 Corp Street",
    "city": "WAN CHAI", "state_region": None, "postal_code": None,
    "country": "Hong Kong", "is_hk_address": True,
}


# ---- scalars ---------------------------------------------------------------

def test_maps_the_core_scalars():
    data = nar1_mapper.map_entity(graph(), year=2026)
    assert data["brNo"] == "00000001"
    assert data["yearAnnualReturn"] == 2026
    assert data["language"] == "E"


def test_omits_only_the_two_non_private_company_fields():
    """The ONLY fields where CR's shipped example beats the worksheet. Both
    worksheet remarks end "(Non Private Company)" and this is a private
    company, so the two sources never actually disagreed."""
    data = nar1_mapper.map_entity(graph(), year=2026)
    for absent in ("dateReturnFrom", "dateReturnTo"):
        assert absent not in data


# ---- the statutory signatory block -----------------------------------------

def test_the_signatory_block_is_emitted():
    """CR's own example carries all four (lines 236-239) and the worksheet marks
    them mandatory -- the two sources agree. nar1.validate() never checks
    `mandatory`, so an unsigned return passes every local gate and fails no
    earlier than CR's server, after the fee is taken."""
    data = nar1_mapper.map_entity(graph(), year=2026)
    assert data["selectCapacityDesc"] == "Company Secretary"
    assert data["selectPersonName"] == "Get Started HK Limited"
    # Today in Hong Kong, not naive date.today(): the DB server runs UTC, which
    # is the wrong calendar day for eight hours out of every twenty-four.
    assert data["signatoryDate"] == datetime.now(HKT).strftime("%d/%m/%Y")


def test_a_body_corporate_signatory_leaves_selectpersonid_empty():
    """Worksheet remark: "Signatory User ID (Empty if sign by Body Corporate)"."""
    assert "selectPersonId" not in nar1_mapper.map_entity(graph(), year=2026)


def test_an_individual_secretary_signs_with_their_identity_number():
    g = graph(
        secretaries=[{"person_id": "p1", "is_gshk": False, "is_current": True}],
        persons={"p1": person()},
        addresses={"a1": ADDR, "a2": ADDR},
        identity_documents={"p1": [{"id_type": "hkid", "id_number": "A123456(7)",
                                    "is_primary": True}]},
    )
    data = nar1_mapper.map_entity(g, year=2026)
    assert data["selectPersonName"] == "CHAN TAI MAN"
    assert data["selectPersonId"] == "A1234567"


def test_the_gshk_secretary_signs_in_preference_to_any_other():
    """Q-030 -- GSHK signs on the client's behalf."""
    g = graph(
        secretaries=[
            {"person_id": "p1", "is_gshk": False, "is_current": True},
            {"is_gshk": True, "secretary_name": "Get Started HK Limited",
             "tcsp_number": "TC000807", "is_current": True},
        ],
        persons={"p1": person()},
        addresses={"a1": ADDR, "a2": ADDR},
    )
    assert nar1_mapper.map_entity(g, year=2026)["selectPersonName"] == \
        "Get Started HK Limited"


def test_an_explicit_signatory_overrides_the_derived_one():
    data = nar1_mapper.map_entity(
        graph(), year=2026,
        signatory={"name": "WONG SIU MING", "capacity": "Director",
                   "person_id": "B7654321", "date": "2026-06-01"},
    )
    assert data["selectPersonName"] == "WONG SIU MING"
    assert data["selectCapacityDesc"] == "Director"
    assert data["selectPersonId"] == "B7654321"
    assert data["signatoryDate"] == "01/06/2026"


def test_a_return_with_nobody_to_sign_it_is_a_mapping_error():
    """Never emit the return with the declaration silently absent -- that is an
    unsigned statutory filing CR's schema gate happily accepts."""
    with pytest.raises(nar1_mapper.MappingError) as exc:
        nar1_mapper.map_entity(graph(secretaries=[]), year=2026)
    assert any("signatory" in p for p in exc.value.problems)


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


def test_a_blank_country_defaults_to_hong_kong_only_on_the_registered_office():
    """roAddr is a HK company's registered office, so a blank there is HK. The
    same helper also builds residential addresses, and there a blank is not."""
    g = graph(
        registered_address={**ADDR, "country": None},
        secretaries=[{"is_gshk": True, "secretary_name": "Get Started HK Limited",
                      "tcsp_number": "TC000807", "is_current": True,
                      "corporate_address": ADDR}],
    )
    assert nar1_mapper.map_entity(g, year=2026)["roAddr"]["ctryRegion"] == "HKG"


def test_a_blank_country_on_a_residential_address_is_a_problem_not_hong_kong():
    """A UK-resident director with a null country was silently filed as
    resident in Hong Kong -- wrong, and accepted by CR."""
    g = graph(
        officers=[{"person_id": "p1", "party_type": "individual",
                   "role": "director", "is_current": True}],
        persons={"p1": person()},
        addresses={"a1": ADDR, "a2": {**ADDR, "country": None}},
    )
    with pytest.raises(nar1_mapper.MappingError) as exc:
        nar1_mapper.map_entity(g, year=2026)
    assert any("country" in p and "CHAN TAI MAN" in p for p in exc.value.problems)


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
                   "role": "director", "is_current": True,
                   "corporate_address": CORP_ADDR}],
        addresses={"a1": ADDR},
    )
    data = nar1_mapper.map_entity(g, year=2026)
    assert data["corpDirList"][0]["corpEngName"] == "HOLDCO LIMITED"
    assert "indDirList" not in data


def test_a_corporate_officer_files_its_own_address_not_the_filers():
    """Migration 007 gave entity_officers a corporate_entity_id FK, so the real
    address is reachable. Substituting the filing company's registered office
    files a WRONG address on a statutory return -- and CR accepts it."""
    g = graph(
        officers=[{"corporate_name": "HOLDCO LIMITED", "party_type": "corporate",
                   "role": "director", "is_current": True,
                   "corporate_address": CORP_ADDR}],
        addresses={"a1": ADDR},
    )
    addr = nar1_mapper.map_entity(g, year=2026)["corpDirList"][0]["stdAddress"]
    assert addr["bldg"] == "Corp Tower"
    assert addr["dstCtyStatePostal"] == "WAN CHAI"


def test_a_corporate_officers_br_number_and_chinese_name_are_filed():
    """_corporate's br_no / name_zh parameters were dead -- no caller passed
    them -- while the worksheet defines corpBrNo and corpChiName and CR's own
    example sends both."""
    g = graph(
        officers=[{"corporate_name": "HOLDCO LIMITED", "party_type": "corporate",
                   "role": "director", "is_current": True,
                   "corporate_address": CORP_ADDR,
                   "corporate_br_no": "00000002",
                   "corporate_name_zh": "控股有限公司"}],
        addresses={"a1": ADDR},
    )
    corp = nar1_mapper.map_entity(g, year=2026)["corpDirList"][0]
    assert corp["corpBrNo"] == "00000002"
    assert corp["corpChiName"] == "控股有限公司"


def test_a_corporate_officer_with_no_address_is_a_mapping_error():
    g = graph(
        officers=[{"corporate_name": "HOLDCO LIMITED", "party_type": "corporate",
                   "role": "director", "is_current": True}],
        addresses={"a1": ADDR},
    )
    with pytest.raises(nar1_mapper.MappingError) as exc:
        nar1_mapper.map_entity(g, year=2026)
    assert any("HOLDCO LIMITED" in p for p in exc.value.problems)


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


def test_a_secretary_recorded_in_both_tables_is_emitted_once():
    """officer_role includes 'company_secretary', so the same individual can be
    an entity_officers row AND a company_secretaries row. Two indSec entries
    for one secretary is a false statutory return."""
    g = graph(
        officers=[{"person_id": "p1", "party_type": "individual",
                   "role": "company_secretary", "is_current": True}],
        secretaries=[{"person_id": "p1", "is_gshk": False, "is_current": True}],
        persons={"p1": person()},
        addresses={"a1": ADDR, "a2": ADDR},
        # This secretary is also the signatory, and a natural person who signs
        # must carry an identity number (selectPersonId).
        identity_documents={"p1": [{"id_type": "hkid", "id_number": "A123456(7)",
                                    "is_primary": True}]},
    )
    assert len(nar1_mapper.map_entity(g, year=2026)["indSecList"]) == 1


def test_a_corporate_secretary_in_both_tables_is_emitted_once_with_its_tcsp():
    """Dedup falls back to a normalised name for rows with no person_id, and
    the company_secretaries row -- the one carrying the TCSP number -- wins."""
    g = graph(
        officers=[{"corporate_name": "Get Started HK  Limited",
                   "party_type": "corporate", "role": "company_secretary",
                   "is_current": True, "corporate_address": CORP_ADDR}],
        secretaries=[{"is_gshk": True, "secretary_name": "GET STARTED HK LIMITED",
                      "tcsp_number": "TC000807", "is_current": True}],
        addresses={"a1": ADDR},
    )
    secs = nar1_mapper.map_entity(g, year=2026)["corpSecList"]
    assert len(secs) == 1
    assert secs[0]["corpTcspNo"] == "TC000807"


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


def test_a_china_id_is_a_problem_not_a_director_filed_without_any_id():
    """id_document_type is ENUM('hkid','passport','china_id','other') and the
    NAR1 carries only indvHkidNo / indvPptNo — no node in nar1_schema.json
    mentions a PRC identity card. A PRC director was being filed with NO
    identity number at all and nothing appended to problems."""
    g = graph(
        officers=[{"person_id": "p1", "party_type": "individual",
                   "role": "director", "is_current": True}],
        persons={"p1": person()},
        addresses={"a1": ADDR, "a2": ADDR},
        identity_documents={"p1": [{"id_type": "china_id",
                                    "id_number": "440101199001011234",
                                    "is_primary": True}]},
    )
    with pytest.raises(nar1_mapper.MappingError) as exc:
        nar1_mapper.map_entity(g, year=2026)
    assert any("china_id" in p and "CHAN TAI MAN" in p for p in exc.value.problems)


def test_a_china_id_alongside_a_passport_files_the_passport_quietly():
    g = graph(
        officers=[{"person_id": "p1", "party_type": "individual",
                   "role": "director", "is_current": True}],
        persons={"p1": person()},
        addresses={"a1": ADDR, "a2": ADDR},
        identity_documents={"p1": [
            {"id_type": "china_id", "id_number": "440101199001011234",
             "is_primary": True},
            {"id_type": "passport", "id_number": "E12345678",
             "issuing_country": "China"},
        ]},
    )
    assert nar1_mapper.map_entity(g, year=2026)["indDirList"][0]["indvPptNo"] == "E12345678"


def test_an_over_length_hkid_is_caught_in_the_mapper():
    """indvHkidNo is 8 characters. nar1.validate() catches this downstream, but
    the mapper is where the intent to strip to 8 lives."""
    g = graph(
        officers=[{"person_id": "p1", "party_type": "individual",
                   "role": "director", "is_current": True}],
        persons={"p1": person()},
        addresses={"a1": ADDR, "a2": ADDR},
        identity_documents={"p1": [{"id_type": "hkid", "id_number": "AB123456(7)",
                                    "is_primary": True}]},
    )
    with pytest.raises(nar1_mapper.MappingError) as exc:
        nar1_mapper.map_entity(g, year=2026)
    assert any("HKID" in p for p in exc.value.problems)


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
             "party_type": "corporate", "shares_held": 900, "is_current": True,
             "corporate_address": CORP_ADDR},
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


def test_shtype_is_1_for_a_sole_individual_shareholder():
    """shType is SHAREHOLDER TYPE -- "1" sole, "2" joint. Nothing to do with
    whether the shares are paid up."""
    g = graph(
        share_classes=[{"id": "sc1", "class_name": "Ordinary", "currency": "HKD",
                        "total_issued": 100, "total_paid": 100}],
        shareholdings=[{"share_class_id": "sc1", "person_id": "p1",
                        "party_type": "individual", "shares_held": 100,
                        "is_current": True}],
        persons={"p1": person()},
        addresses={"a1": ADDR, "a2": ADDR},
    )
    grp = nar1_mapper.map_entity(g, year=2026)["schedule1"]["shares"][0]["shareHolderGrps"][0]
    assert grp["shType"] == "1"


def test_shtype_is_1_for_a_sole_corporate_shareholder():
    """CR's example lines 172-191: a shType=1 group whose only allottee is
    `C`. So "1" means ONE holder, not "natural person" -- filing a corporate
    sole shareholder as "2" (or as "Individual Shareholder") is a
    self-contradicting return CR's schema happily accepts."""
    g = graph(
        share_classes=[{"id": "sc1", "class_name": "Ordinary", "currency": "HKD",
                        "total_issued": 900, "total_paid": 900}],
        shareholdings=[{"share_class_id": "sc1", "corporate_name": "HOLDCO LIMITED",
                        "party_type": "corporate", "shares_held": 900,
                        "is_current": True, "corporate_address": ADDR}],
        addresses={"a1": ADDR},
    )
    grp = nar1_mapper.map_entity(g, year=2026)["schedule1"]["shares"][0]["shareHolderGrps"][0]
    assert grp["shType"] == "1"
    assert grp["allotteeRec"][0]["allotteeType"] == "C"


def test_a_corporate_shareholder_files_its_own_address_not_the_filers():
    g = graph(
        share_classes=[{"id": "sc1", "class_name": "Ordinary", "currency": "HKD",
                        "total_issued": 900, "total_paid": 900}],
        shareholdings=[{"share_class_id": "sc1", "corporate_name": "HOLDCO LIMITED",
                        "party_type": "corporate", "shares_held": 900,
                        "is_current": True, "corporate_address": CORP_ADDR}],
        addresses={"a1": ADDR},
    )
    grp = nar1_mapper.map_entity(g, year=2026)["schedule1"]["shares"][0]["shareHolderGrps"][0]
    assert grp["allotteeRec"][0]["allotteeAddr"]["bldg"] == "Corp Tower"


def test_a_corporate_shareholder_with_no_address_is_a_mapping_error():
    g = graph(
        share_classes=[{"id": "sc1", "class_name": "Ordinary", "currency": "HKD",
                        "total_issued": 900, "total_paid": 900}],
        shareholdings=[{"share_class_id": "sc1", "corporate_name": "HOLDCO LIMITED",
                        "party_type": "corporate", "shares_held": 900,
                        "is_current": True}],
        addresses={"a1": ADDR},
    )
    with pytest.raises(nar1_mapper.MappingError) as exc:
        nar1_mapper.map_entity(g, year=2026)
    assert any("HOLDCO LIMITED" in p for p in exc.value.problems)


def test_shtype_ignores_amount_paid_entirely():
    """amount_paid is numeric(20,4) MONEY and shares_held is a share COUNT, so
    comparing them is a unit mismatch that coincides only for HKD-1-par shares
    -- and payment state is not what shType means in the first place."""
    g = graph(
        share_classes=[{"id": "sc1", "class_name": "Ordinary", "currency": "HKD",
                        "total_issued": 1000, "total_paid": 1}],
        shareholdings=[{"share_class_id": "sc1", "person_id": "p1",
                        "party_type": "individual", "shares_held": 1000,
                        "amount_paid": 1, "is_current": True}],
        persons={"p1": person()},
        addresses={"a1": ADDR, "a2": ADDR},
    )
    grp = nar1_mapper.map_entity(g, year=2026)["schedule1"]["shares"][0]["shareHolderGrps"][0]
    assert grp["shType"] == "1"


def test_a_holding_whose_share_class_was_not_loaded_is_a_mapping_error():
    """The emit loop iterates share_classes and picks matching holdings, so a
    holding pointing at a class that is not loaded was dropped in silence -- a
    shareholder disappearing from the statutory register of members."""
    g = graph(
        share_classes=[{"id": "sc1", "class_name": "Ordinary", "currency": "HKD",
                        "total_issued": 100, "total_paid": 100}],
        shareholdings=[
            {"share_class_id": "sc1", "person_id": "p1", "party_type": "individual",
             "shares_held": 100, "is_current": True},
            {"share_class_id": "sc9", "person_id": "p1", "party_type": "individual",
             "shares_held": 500, "is_current": True},
        ],
        persons={"p1": person()},
        addresses={"a1": ADDR, "a2": ADDR},
    )
    with pytest.raises(nar1_mapper.MappingError) as exc:
        nar1_mapper.map_entity(g, year=2026)
    assert any("sc9" in p for p in exc.value.problems)


def test_shares_allotted_short_of_shares_issued_is_a_mapping_error():
    """A class with 1000 issued and 900 allotted filed silently."""
    g = graph(
        share_classes=[{"id": "sc1", "class_name": "Ordinary", "currency": "HKD",
                        "total_issued": 1000, "total_paid": 1000}],
        shareholdings=[{"share_class_id": "sc1", "person_id": "p1",
                        "party_type": "individual", "shares_held": 900,
                        "is_current": True}],
        persons={"p1": person()},
        addresses={"a1": ADDR, "a2": ADDR},
    )
    with pytest.raises(nar1_mapper.MappingError) as exc:
        nar1_mapper.map_entity(g, year=2026)
    assert any("900" in p and "1000" in p for p in exc.value.problems)


def test_a_joint_block_counts_once_against_shares_issued():
    """Two rows holding one block jointly is 2000 allotted, not 4000."""
    g = graph(
        share_classes=[{"id": "sc1", "class_name": "Ordinary", "currency": "HKD",
                        "total_issued": 2000, "total_paid": 2000}],
        shareholdings=[
            {"share_class_id": "sc1", "person_id": "p1", "party_type": "individual",
             "shares_held": 2000, "is_current": True, "joint_group_id": "j1"},
            {"share_class_id": "sc1", "corporate_name": "HOLDCO LIMITED",
             "party_type": "corporate", "shares_held": 2000, "is_current": True,
             "joint_group_id": "j1", "corporate_address": CORP_ADDR},
        ],
        persons={"p1": person()},
        addresses={"a1": ADDR, "a2": ADDR},
    )
    assert nar1_mapper.map_entity(g, year=2026)["schedule1"]["shares"][0][
        "shareHolderGrps"][0]["sharesAlloted"] == 2000


def test_a_fractional_share_count_is_a_mapping_error_not_a_truncation():
    """total_issued is numeric(20,4) and every CR field here is an Integer, so
    int() was silently truncating a number CR cannot represent."""
    g = graph(
        share_classes=[{"id": "sc1", "class_name": "Ordinary", "currency": "HKD",
                        "total_issued": "1000.5000", "total_paid": 1000}],
        addresses={"a1": ADDR},
    )
    with pytest.raises(nar1_mapper.MappingError) as exc:
        nar1_mapper.map_entity(g, year=2026)
    assert any("1000.5000" in p for p in exc.value.problems)


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
             "role": "director", "is_current": True,
             "corporate_address": CORP_ADDR},
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
             "party_type": "corporate", "shares_held": 900, "is_current": True,
             "corporate_address": CORP_ADDR},
            # CR's Preference class is ONE group of 2000 shares held JOINTLY by
            # an individual and a body corporate -- shType 2, two allottees.
            {"share_class_id": "sc2", "person_id": "p1", "party_type": "individual",
             "shares_held": 2000, "is_current": True, "joint_group_id": "j1"},
            {"share_class_id": "sc2", "corporate_name": "Test Company Limited",
             "party_type": "corporate", "shares_held": 2000, "is_current": True,
             "joint_group_id": "j1", "corporate_address": CORP_ADDR},
        ],
        persons={"p1": person()},
        addresses={"a1": ADDR, "a2": ADDR},
    )
    ours = _cardinality(nar1.build_nar1_xml(nar1_mapper.map_entity(g, year=2020)))
    theirs = _cardinality(SAMPLE.read_text(encoding="utf8"))

    # `allottee` is in this loop. It was computed and NOT asserted before, and
    # the gap it hid (ours 3, CR's 4) was the joint-shareholder concept.
    for tag in ("shareCapital", "indSec", "corpSec", "indDir", "corpDir",
                "resDir", "share", "shareHolderGrp", "allottee"):
        assert ours[tag] == theirs[tag], (
            f"{tag}: built {ours[tag]}, CR's example has {theirs[tag]}"
        )


def test_joint_holders_are_one_group_of_shtype_2_with_one_allottee_each():
    """CR's Preference class (lines 197-231): one shareHolderGrp, shType 2, two
    allottees. Splitting joint holders into separate sole groups misdeclares
    the register -- and CR's schema accepts it."""
    g = graph(
        share_classes=[{"id": "sc1", "class_name": "Ordinary", "currency": "HKD",
                        "total_issued": 2000, "total_paid": 2000}],
        shareholdings=[
            {"share_class_id": "sc1", "person_id": "p1", "party_type": "individual",
             "shares_held": 2000, "is_current": True, "joint_group_id": "j1"},
            {"share_class_id": "sc1", "corporate_name": "HOLDCO LIMITED",
             "party_type": "corporate", "shares_held": 2000, "is_current": True,
             "joint_group_id": "j1", "corporate_address": CORP_ADDR},
        ],
        persons={"p1": person()},
        addresses={"a1": ADDR, "a2": ADDR},
    )
    grps = nar1_mapper.map_entity(g, year=2026)["schedule1"]["shares"][0]["shareHolderGrps"]
    assert len(grps) == 1
    assert grps[0]["shType"] == "2"
    assert grps[0]["sharesAlloted"] == 2000
    assert [a["allotteeType"] for a in grps[0]["allotteeRec"]] == ["I", "C"]


def test_joint_holders_disagreeing_on_the_block_size_is_a_mapping_error():
    """Joint holders hold ONE block jointly. Two different numbers means the
    register is wrong, and picking either would file a number nobody recorded."""
    g = graph(
        share_classes=[{"id": "sc1", "class_name": "Ordinary", "currency": "HKD",
                        "total_issued": 2000, "total_paid": 2000}],
        shareholdings=[
            {"share_class_id": "sc1", "person_id": "p1", "party_type": "individual",
             "shares_held": 2000, "is_current": True, "joint_group_id": "j1"},
            {"share_class_id": "sc1", "corporate_name": "HOLDCO LIMITED",
             "party_type": "corporate", "shares_held": 1500, "is_current": True,
             "joint_group_id": "j1", "corporate_address": CORP_ADDR},
        ],
        persons={"p1": person()},
        addresses={"a1": ADDR, "a2": ADDR},
    )
    with pytest.raises(nar1_mapper.MappingError) as exc:
        nar1_mapper.map_entity(g, year=2026)
    assert any("joint" in p for p in exc.value.problems)


def test_the_mapper_does_no_io():
    """The riskiest form logic in the system must be testable without CR and
    without Supabase -- the TEST form APIs are open 30 hours a week."""
    import inspect
    src = inspect.getsource(nar1_mapper)
    assert "supabase" not in src.lower()
