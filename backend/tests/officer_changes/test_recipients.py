"""Who the officer-change verification email goes to (spec B-6)."""
import pytest

from services import nar1_cases
from services.officer_changes import recipients
from tests.officer_changes.fakes import FakeSupabase


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase({
        "entity_officers": [
            {"id": "O1", "entity_id": "E1", "person_id": "P1", "party_type": "individual",
             "role": "director", "is_current": True},
            {"id": "O2", "entity_id": "E1", "person_id": "P2", "party_type": "individual",
             "role": "director", "is_current": True},
            {"id": "O3", "entity_id": "E1", "person_id": "P3", "party_type": "individual",
             "role": "company_secretary", "is_current": True},
        ],
        "persons": [
            {"id": "P1", "full_name": "CHAN Tai Man", "given_names": "Tai Man",
             "email": "p1@example.com"},
            {"id": "P2", "full_name": "LEE Siu Ming", "given_names": "Siu Ming",
             "email": None},
            {"id": "P3", "full_name": "WONG Ka Yan", "email": "p3@example.com"},
            {"id": "P9", "full_name": "HO New Director", "given_names": "New Director",
             "email": "p9@example.com"},
        ],
        "contacts": [],
        "entities": [{"id": "C9", "company_name": "Corp Director Limited",
                      "email": "corp@example.com"}],
    })
    monkeypatch.setattr(recipients, "get_supabase", lambda: fake)
    monkeypatch.setattr(nar1_cases, "get_supabase", lambda: fake)
    return fake


ND2A = {"id": "K1", "entity_id": "E1", "form_code": "Nd2a"}
ND2B = {"id": "K2", "entity_id": "E1", "form_code": "Nd2b"}


def test_nd2a_writes_to_every_current_and_every_incoming_director(db):
    entries = [{"kind": "appointment", "capacity": "director",
                "party_type": "individual", "person_id": "P9"},
               {"kind": "appointment", "capacity": "company_secretary",
                "party_type": "individual", "person_id": "P3"}]
    out = recipients.default_recipients(ND2A, entries)
    by_id = {r["person_id"]: r for r in out}
    assert set(by_id) == {"P1", "P2", "P9"}
    assert by_id["P9"]["role"] == "incoming director"
    assert by_id["P9"]["email"] == "p9@example.com" and by_id["P9"]["reason"] is None


def test_a_director_with_no_address_is_listed_with_the_reason(db):
    out = recipients.default_recipients(ND2A, [])
    p2 = next(r for r in out if r["person_id"] == "P2")
    assert p2["email"] is None and "no email" in p2["reason"]


def test_an_incoming_corporate_director_is_listed_but_not_mailed(db):
    entries = [{"kind": "appointment", "capacity": "director",
                "party_type": "corporate", "corporate_entity_id": "C9"}]
    corp = next(r for r in recipients.default_recipients(ND2A, entries)
                if r.get("corporate_entity_id") == "C9")
    assert corp["email"] is None and corp["reason"]
    assert corp["name"] == "Corp Director Limited"


def test_nd2b_writes_to_the_officer_concerned_only(db):
    entries = [{"kind": "change", "capacity": "company_secretary",
                "party_type": "individual", "person_id": "P3"}]
    out = recipients.default_recipients(ND2B, entries)
    assert [r["person_id"] for r in out] == ["P3"]
    assert out[0]["email"] == "p3@example.com" and out[0]["role"] == "officer"


def test_one_person_on_two_entries_is_written_to_once(db):
    entries = [{"kind": "change", "capacity": "director", "party_type": "individual",
                "person_id": "P1"},
               {"kind": "change", "capacity": "company_secretary",
                "party_type": "individual", "person_id": "P1"}]
    assert len(recipients.default_recipients(ND2B, entries)) == 1
