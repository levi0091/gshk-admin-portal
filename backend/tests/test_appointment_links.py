"""What ONE appointment files: its own identity document and addresses.

Levi 2026-10-05 (Jacqueline's ND2B question 2): "different identifications can
be linked to different companies too" — a client holding a French and a US
passport may have given one to each company, and an address likewise. A link
on the officer row says which; no link means the person's default, which is
exactly the behaviour before links existed.
"""
import copy

from services import appointment_links as links
from services.tpsi.forms import nar1
from tests.tpsi.test_nar1_mapper import ADDR, graph, mapped, person

DOCS = [{"id": "H", "person_id": "p1", "id_type": "hkid", "id_number": "A123456(7)",
         "is_primary": True},
        {"id": "FR", "person_id": "p1", "id_type": "passport", "id_number": "FR111",
         "issuing_country": "FR", "is_primary": True},
        {"id": "US", "person_id": "p1", "id_type": "passport", "id_number": "US222",
         "issuing_country": "US", "is_primary": False}]


def test_unlinked_follows_the_person():
    assert links.documents_for(DOCS, None) is DOCS
    p = {"id": "p1", "residential_address_id": "A1"}
    assert links.person_for(p, {}) is p and links.person_for(p, None) is p


def test_a_linked_passport_replaces_the_primary_passport_only():
    out = links.documents_for(DOCS, "US")
    passports = [d for d in out if d["id_type"] == "passport"]
    assert [d["id"] for d in passports] == ["US", "FR"]
    assert passports[0]["is_primary"] is True and passports[1]["is_primary"] is False
    assert next(d for d in out if d["id"] == "H")["is_primary"] is True
    assert DOCS[2]["is_primary"] is False  # the input is not mutated


def test_a_linked_document_that_no_longer_exists_falls_back():
    assert links.documents_for(DOCS, "GONE") is DOCS


def test_a_linked_residential_address_replaces_the_default():
    p = {"id": "p1", "residential_address_id": "A1"}
    assert links.person_for(p, {"residential_address_id": "A9"})["residential_address_id"] == "A9"
    assert p["residential_address_id"] == "A1"


def test_apply_to_graph_rewrites_only_linked_people():
    persons = {"p1": {"id": "p1", "residential_address_id": "A1"},
               "p2": {"id": "p2", "residential_address_id": "A2"}}
    docs = {"p1": list(DOCS)}
    officers = [{"person_id": "p1", "is_current": True, "identity_document_id": "US",
                 "residential_address_id": "A9"},
                {"person_id": "p2", "is_current": True}]
    p2 = persons["p2"]
    links.apply_to_graph(persons, docs, officers)
    assert persons["p1"]["residential_address_id"] == "A9"
    assert persons["p2"] is p2
    assert [d["id"] for d in docs["p1"] if d["id_type"] == "passport"] == ["US", "FR"]


def test_the_first_linked_appointment_wins_for_two_roles_in_one_company():
    persons = {"p1": {"id": "p1", "residential_address_id": "A1"}}
    officers = [{"person_id": "p1", "is_current": True, "residential_address_id": "A8",
                 "role": "director"},
                {"person_id": "p1", "is_current": True, "residential_address_id": "A9",
                 "role": "company_secretary"}]
    links.apply_to_graph(persons, {}, officers)
    assert persons["p1"]["residential_address_id"] == "A8"


def test_extra_address_ids_names_the_linked_rows():
    officers = [{"person_id": "p1", "residential_address_id": "A9"},
                {"person_id": "p2"}, {"corporate_entity_id": "c1", "residential_address_id": "AX"}]
    assert links.extra_address_ids(officers) == {"A9"}


# -- the NAR1 a company files ----------------------------------------------------------

def _passport_graph(officer_link=None):
    officer = {"person_id": "p1", "party_type": "individual", "role": "director",
               "is_current": True, **(officer_link or {})}
    return graph(officers=[officer], persons={"p1": person()},
                 addresses={"a2": ADDR, "a9": {**ADDR, "line1": "Flat 9"}},
                 identity_documents={"p1": [d for d in copy.deepcopy(DOCS)
                                            if d["id_type"] == "passport"]})


def _linked(g):
    links.apply_to_graph(g["persons"], g["identity_documents"], g["officers"])
    return g


def test_nar1_files_the_passport_and_address_linked_to_this_company():
    xml = nar1.build_nar1_xml(mapped(_linked(_passport_graph(
        {"identity_document_id": "US", "residential_address_id": "a9"}))))
    assert "US2" in xml and "FR1" not in xml
    assert "Flat 9" in xml


def test_nar1_is_byte_identical_without_links():
    plain = nar1.build_nar1_xml(mapped(_passport_graph()))
    assert nar1.build_nar1_xml(mapped(_linked(_passport_graph()))) == plain


# -- the correspondence address (PROD, ABMOS LIMITED, 2026-11-26) ----------------------
#
# CR's NAR1 labels indDir/resDir stdAddress "Correspondence Address" and indSec's
# "Hong Kong Correspondence Address". The mapper filed the residential address
# there regardless, so an ND2B changing only a director's correspondence address
# never reached the next NAR1, and a protected residential address went into a
# public field.

CORR = {**ADDR, "line1": "Suite C, Level 7", "line2": "Corr Plaza 77",
        "line3": "50 Stanley Street"}


def _corr_graph(role="director", link=None, **graph_over):
    officer = {"person_id": "p1", "party_type": "individual", "role": role,
               "is_current": True, **(link or {})}
    return graph(officers=[officer], persons={"p1": person()},
                 addresses={"a2": ADDR, "a9": {**ADDR, "line1": "Flat 9"}, "c1": CORR},
                 **graph_over)


def test_a_linked_correspondence_address_rides_on_the_person():
    p = {"id": "p1", "residential_address_id": "A1"}
    out = links.correspondence_for(p, {"correspondence_address_id": "C1"})
    assert out[links.CORRESPONDENCE] == "C1"
    assert out["residential_address_id"] == "A1"
    assert links.CORRESPONDENCE not in p  # the input is not mutated
    assert links.correspondence_for(p, {}) is p


def test_apply_to_graph_carries_a_correspondence_only_link():
    persons = {"p1": {"id": "p1", "residential_address_id": "A1"}}
    links.apply_to_graph(persons, {}, [{"person_id": "p1", "is_current": True,
                                        "correspondence_address_id": "C1"}])
    assert persons["p1"][links.CORRESPONDENCE] == "C1"
    assert persons["p1"]["residential_address_id"] == "A1"


def test_apply_to_graph_keeps_both_links_of_one_appointment():
    persons = {"p1": {"id": "p1", "residential_address_id": "A1"}}
    links.apply_to_graph(persons, {}, [{"person_id": "p1", "is_current": True,
                                        "residential_address_id": "A9",
                                        "correspondence_address_id": "C1"}])
    assert persons["p1"]["residential_address_id"] == "A9"
    assert persons["p1"][links.CORRESPONDENCE] == "C1"


def test_extra_address_ids_names_correspondence_links_too():
    officers = [{"person_id": "p1", "residential_address_id": "A9",
                 "correspondence_address_id": "C1"},
                {"person_id": "p2", "correspondence_address_id": "C2"},
                {"corporate_entity_id": "c1", "correspondence_address_id": "CX"}]
    assert links.extra_address_ids(officers) == {"A9", "C1", "C2"}


def test_nar1_files_a_directors_correspondence_address():
    xml = nar1.build_nar1_xml(mapped(_linked(_corr_graph(
        link={"correspondence_address_id": "c1"}))))
    assert "Corr Plaza 77" in xml
    assert "Res Tower" not in xml


def test_nar1_files_correspondence_over_a_linked_residential_address():
    xml = nar1.build_nar1_xml(mapped(_linked(_corr_graph(
        link={"residential_address_id": "a9", "correspondence_address_id": "c1"}))))
    assert "Corr Plaza 77" in xml
    assert "Flat 9" not in xml


def test_nar1_files_a_reserve_directors_correspondence_address():
    xml = nar1.build_nar1_xml(mapped(_linked(_corr_graph(
        role="reserve_director", link={"correspondence_address_id": "c1"}))))
    assert "Corr Plaza 77" in xml


def test_nar1_without_a_correspondence_link_files_the_residential_address():
    xml = nar1.build_nar1_xml(mapped(_linked(_corr_graph(
        link={"residential_address_id": "a9"}))))
    assert "Flat 9" in xml and "Corr Plaza 77" not in xml


def test_a_correspondence_link_to_a_missing_address_falls_back():
    xml = nar1.build_nar1_xml(mapped(_linked(_corr_graph(
        link={"correspondence_address_id": "GONE"}))))
    assert "Res Tower" in xml
