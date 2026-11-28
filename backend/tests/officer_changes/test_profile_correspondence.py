"""ND2A's correspondence address follows the Natural Person profile (Levi 2026-11-28).

The "Add appointment" drawer used to ask "Correspondence address is the same as the
residential address"; unticked, it made staff re-type an address already on the
profile and filing inserted a duplicate `addresses` row. ND2A now reads the profile
exactly as NAR1 and ND2B do: `services.officer_changes.profile_correspondence` is
the one rule, a pure function over the person's choices plus a loader.
"""
import pytest

from services.officer_changes import profile_correspondence as pc
from tests.officer_changes.fakes import FakeSupabase

HOME = {"line1": "Flat A", "city": "CENTRAL", "country": "HK"}
CORR1 = {"line1": "Room 1201", "line2": "Tower 2", "city": "CENTRAL", "country": "HK"}
CORR2 = {"line1": "12 Rue de Rivoli", "city": "PARIS", "postal_code": "75001", "country": "FR"}
PERSON = {"id": "P1", "residential_address_id": "A1"}


def _choice(address_id, address, used_by=(), also=()):
    return {"address_id": address_id, "address": pc.normalised(address),
            "address_ids": [address_id, *also], "used_by": list(used_by)}


# -- content, not id ------------------------------------------------------------------

def test_content_key_ignores_case_whitespace_and_empty_versus_none():
    a = {"line1": "  Room 1201 ", "line2": "", "city": "central", "country": "hk"}
    b = {"line1": "ROOM 1201", "line2": None, "line3": None, "city": "CENTRAL",
         "country": "HK", "state_region": " "}
    assert pc.content_key(a) == pc.content_key(b)
    assert pc.content_key(a) != pc.content_key({**b, "line1": "Room 1202"})


def test_normalised_carries_exactly_the_seven_keys():
    assert set(pc.normalised({"line1": "x", "id": "A1", "junk": 1})) == set(pc.ADDRESS_KEYS)


# -- the rule table -------------------------------------------------------------------

def test_no_choices_files_the_residential_address():
    r = pc.resolve(PERSON, [], home=HOME)
    assert r["status"] == "none"
    assert r["address_id"] is None and r["choices"] == []
    assert r["printed_kind"] == "residential"
    assert r["printed_address"] == pc.normalised(HOME)


def test_one_in_use_address_is_taken():
    c = _choice("A3", CORR1, used_by=["E1"])
    r = pc.resolve(PERSON, [c], home=HOME)
    assert (r["status"], r["address_id"]) == ("in_use", "A3")
    assert r["printed_kind"] == "correspondence"
    assert r["printed_address"] == pc.normalised(CORR1)


def test_two_in_use_addresses_are_ambiguous_and_print_nothing():
    cs = [_choice("A3", CORR1, used_by=["E1"]), _choice("A4", CORR2, used_by=["E2"])]
    r = pc.resolve(PERSON, cs, home=HOME)
    assert r["status"] == "ambiguous"
    assert r["address_id"] is None and r["printed_kind"] is None
    assert r["printed_address"] is None
    assert len(r["choices"]) == 2


def test_an_unused_recorded_address_is_ignored_when_one_is_in_use():
    cs = [_choice("A3", CORR1, used_by=["E1"]), _choice("A4", CORR2)]
    r = pc.resolve(PERSON, cs, home=HOME)
    assert (r["status"], r["address_id"]) == ("in_use", "A3")


def test_a_single_recorded_address_is_taken_when_none_is_in_use():
    r = pc.resolve(PERSON, [_choice("A4", CORR2)], home=HOME)
    assert (r["status"], r["address_id"]) == ("recorded", "A4")
    assert r["printed_kind"] == "correspondence"


def test_two_recorded_addresses_and_none_in_use_is_ambiguous():
    r = pc.resolve(PERSON, [_choice("A3", CORR1), _choice("A4", CORR2)], home=HOME)
    assert r["status"] == "ambiguous"


def test_the_entry_chooses_among_several_and_overrides_in_use():
    cs = [_choice("A3", CORR1, used_by=["E1"]), _choice("A4", CORR2, used_by=["E2"])]
    r = pc.resolve(PERSON, cs, chosen_id="A4", home=HOME)
    assert (r["status"], r["address_id"]) == ("chosen", "A4")
    assert r["printed_address"] == pc.normalised(CORR2)
    # ...even over a single in-use address.
    r = pc.resolve(PERSON, [_choice("A3", CORR1, used_by=["E1"]), _choice("A4", CORR2)],
                   chosen_id="A4", home=HOME)
    assert (r["status"], r["address_id"]) == ("chosen", "A4")


def test_a_chosen_id_matches_a_duplicate_row_of_the_same_content():
    cs = [_choice("A3", CORR1, used_by=["E1"], also=["A7"]),
          _choice("A4", CORR2, used_by=["E2"])]
    r = pc.resolve(PERSON, cs, chosen_id="A7", home=HOME)
    assert (r["status"], r["address_id"]) == ("chosen", "A3")


def test_a_chosen_id_that_is_not_a_choice_falls_through_to_the_rule():
    one = [_choice("A3", CORR1, used_by=["E1"])]
    assert pc.resolve(PERSON, one, chosen_id="A99", home=HOME)["status"] == "in_use"
    two = [_choice("A3", CORR1, used_by=["E1"]), _choice("A4", CORR2, used_by=["E2"])]
    assert pc.resolve(PERSON, two, chosen_id="A99", home=HOME)["status"] == "ambiguous"
    assert pc.resolve(PERSON, [], chosen_id="A99", home=HOME)["status"] == "none"


def test_the_residential_flag_prints_the_home_address_but_still_resolves_the_link():
    person = {**PERSON, "address_on_forms": "residential"}
    r = pc.resolve(person, [_choice("A3", CORR1, used_by=["E1"])], home=HOME)
    assert (r["status"], r["address_id"]) == ("in_use", "A3")
    assert r["printed_kind"] == "residential"
    assert r["printed_address"] == pc.normalised(HOME)


def test_the_residential_flag_still_prints_home_when_the_choices_are_ambiguous():
    person = {**PERSON, "address_on_forms": "residential"}
    cs = [_choice("A3", CORR1, used_by=["E1"]), _choice("A4", CORR2, used_by=["E2"])]
    r = pc.resolve(person, cs, home=HOME)
    assert r["status"] == "ambiguous" and r["printed_kind"] == "residential"
    assert r["printed_address"] == pc.normalised(HOME)


def test_no_home_address_prints_nothing_for_a_residential_person():
    person = {**PERSON, "address_on_forms": "residential"}
    r = pc.resolve(person, [], home=None)
    assert r["printed_kind"] == "residential" and r["printed_address"] is None


# -- the loader -----------------------------------------------------------------------

def _db():
    return FakeSupabase({
        "addresses": [
            {"id": "A1", **HOME},
            {"id": "A3", **CORR1},
            # the same content typed twice, as the old drawer used to leave it
            {"id": "A7", **{**CORR1, "line1": "ROOM 1201 "}},
            {"id": "A4", **CORR2},
            {"id": "A5", "line1": "Unused", "city": "KOWLOON", "country": "HK"}],
        "person_addresses": [
            {"id": "PA1", "person_id": "P1", "address_id": "A3", "kind": "correspondence"},
            {"id": "PA2", "person_id": "P1", "address_id": "A5", "kind": "correspondence"},
            {"id": "PA3", "person_id": "P1", "address_id": "A1", "kind": "residential"},
            {"id": "PA4", "person_id": "P2", "address_id": "A4", "kind": "correspondence"}],
        "entity_officers": [
            {"id": "O1", "entity_id": "E1", "person_id": "P1", "role": "director",
             "is_current": True, "correspondence_address_id": "A3"},
            {"id": "O2", "entity_id": "E2", "person_id": "P1", "role": "company_secretary",
             "is_current": True, "correspondence_address_id": "A7"},
            {"id": "O3", "entity_id": "E3", "person_id": "P1", "role": "alternate_director",
             "is_current": True, "correspondence_address_id": "A7"},
            # not counted: resigned, a shareholder, no link
            {"id": "O4", "entity_id": "E4", "person_id": "P1", "role": "director",
             "is_current": False, "correspondence_address_id": "A4"},
            {"id": "O5", "entity_id": "E5", "person_id": "P1", "role": "shareholder",
             "is_current": True, "correspondence_address_id": "A4"},
            {"id": "O6", "entity_id": "E6", "person_id": "P1", "role": "director",
             "is_current": True, "correspondence_address_id": None}],
    })


def test_the_loader_dedups_by_content_and_names_the_companies(monkeypatch):
    monkeypatch.setattr(pc, "get_supabase", lambda: _db())
    got = pc.for_persons(["P1", "P2", "P3"])
    p1 = got["P1"]
    # A3 + A7 are one choice, represented by A7 (two officer rows to A3's one);
    # A5 is recorded only; A4 is not P1's (resigned / shareholder rows).
    assert [c["address_id"] for c in p1] == ["A7", "A5"]
    assert p1[0]["used_by"] == ["E1", "E2", "E3"]
    assert sorted(p1[0]["address_ids"]) == ["A3", "A7"]
    assert p1[1]["used_by"] == [] and p1[1]["address"]["line1"] == "Unused"
    assert got["P2"][0]["address_id"] == "A4" and got["P2"][0]["used_by"] == []
    assert got["P3"] == []


def test_a_tie_between_representatives_takes_the_smallest_id(monkeypatch):
    db = _db()
    db.tables["entity_officers"] = [
        {"id": "O1", "entity_id": "E1", "person_id": "P1", "role": "director",
         "is_current": True, "correspondence_address_id": "A7"},
        {"id": "O2", "entity_id": "E2", "person_id": "P1", "role": "director",
         "is_current": True, "correspondence_address_id": "A3"}]
    monkeypatch.setattr(pc, "get_supabase", lambda: db)
    assert pc.for_persons(["P1"])["P1"][0]["address_id"] == "A3"


def test_the_loader_asks_nothing_for_no_people(monkeypatch):
    db = _db()
    monkeypatch.setattr(pc, "get_supabase", lambda: db)
    assert pc.for_persons([]) == {}
    assert db.calls == []


@pytest.mark.parametrize("flag,kind", [(None, "correspondence"), ("residential", "residential")])
def test_loaded_choices_resolve_end_to_end(monkeypatch, flag, kind):
    db = _db()
    db.tables["entity_officers"] = [db.tables["entity_officers"][0]]  # only O1 -> A3
    monkeypatch.setattr(pc, "get_supabase", lambda: db)
    person = {**PERSON, **({"address_on_forms": flag} if flag else {})}
    choices = pc.for_persons(["P1"])["P1"]
    # A3 in use, A5 recorded-only -> in_use A3
    r = pc.resolve(person, choices, home=HOME)
    assert r["status"] == "in_use" and r["address_id"] == "A3"
    assert r["printed_kind"] == kind
