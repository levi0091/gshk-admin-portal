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
