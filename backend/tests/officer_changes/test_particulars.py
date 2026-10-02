"""The ND2B baseline: what CR holds for each appointment, and what moved since.

Spec §4. Every test runs on an in-memory Supabase; nothing reaches the network.
"""
import copy

import pytest

from services.officer_changes import particulars as pt
from tests.officer_changes.fakes import FakeSupabase

HOME = {"line1": "Flat A, 10/F", "line2": "Harbour View", "line3": "1 Queen's Road",
        "city": "CENTRAL", "state_region": None, "postal_code": None, "country": "HK"}
OFFICE = {"line1": "Room 1201", "line2": "Tower 2", "line3": "8 Connaught Place",
          "city": "CENTRAL", "state_region": "", "postal_code": "", "country": "HK"}


def _world(**overrides):
    tables = {
        "entities": [
            {"id": "E1", "company_name": "Kanenas Holding Limited"},
            {"id": "E2", "company_name": "Second Limited"},
            {"id": "C1", "company_name": "Corp Director Limited",
             "company_name_zh": "公司董事有限公司", "registered_address_id": "A2",
             "email": "corp@example.com", "tcsp_licence_no": None,
             "tcsp_exemption_reason": None},
        ],
        "persons": [
            {"id": "P1", "full_name": "CHAN Tai Man", "surname": "CHAN",
             "given_names": "Tai Man", "full_name_zh": "陳大文",
             "alias_en": None, "alias_zh": None, "email": "tm@example.com",
             "residential_address_id": "A1", "tcsp_licence_no": None,
             "tcsp_exemption_reason": None},
        ],
        "addresses": [
            {"id": "A1", **HOME},
            {"id": "A2", **OFFICE},
        ],
        "person_identity_documents": [
            {"id": "D1", "person_id": "P1", "id_type": "hkid",
             "id_number": "A1234563", "is_primary": True},
        ],
        "entity_officers": [
            {"id": "O1", "entity_id": "E1", "person_id": "P1", "role": "director",
             "is_current": True},
            {"id": "O2", "entity_id": "E1", "corporate_entity_id": "C1",
             "person_id": None, "role": "director", "is_current": True},
            {"id": "O3", "entity_id": "E2", "person_id": "P1", "role": "director",
             "is_current": False},
        ],
        "company_secretaries": [
            {"id": "S1", "entity_id": "E2", "person_id": "P1", "is_current": True},
        ],
        "officer_cr_particulars": [],
        "officer_change_entries": [],
        "nar1_cases": [],
    }
    tables.update(overrides)
    return FakeSupabase(tables)


@pytest.fixture
def db(monkeypatch):
    fake = _world()
    monkeypatch.setattr(pt, "get_supabase", lambda: fake)
    return fake


def _person(db, **changes):
    db.tables["persons"][0].update(changes)


def _keys(items):
    return [i["key"] for i in items]


# -- snapshots ------------------------------------------------------------------

def test_snapshot_person_reads_every_tracked_particular(db):
    snap = pt.snapshot_person("P1")
    assert snap["party_type"] == "individual"
    assert snap["name_en"] == {"surname": "CHAN", "given_names": "Tai Man"}
    assert snap["name_zh"] == "陳大文"
    assert snap["alias"] == {"alias_en": "", "alias_zh": ""}
    assert snap["residential_address"]["line1"] == "Flat A, 10/F"
    assert snap["correspondence_address"] is None
    assert snap["email"] == "tm@example.com"
    assert snap["hkid"] == "A1234563"
    assert snap["passport"] is None
    assert snap["tcsp"] == {"licence_no": "", "exemption_reason": ""}


def test_snapshot_corporate_reads_name_address_email_tcsp(db):
    snap = pt.snapshot_corporate("C1")
    assert snap["party_type"] == "corporate"
    assert snap["name"] == {"name": "Corp Director Limited", "name_zh": "公司董事有限公司"}
    assert snap["address"]["line3"] == "8 Connaught Place"
    assert snap["email"] == "corp@example.com"


# -- diff: one test per CR item --------------------------------------------------

def _base_person():
    return {
        "party_type": "individual",
        "name_en": {"surname": "CHAN", "given_names": "Tai Man"},
        "name_zh": "陳大文",
        "alias": {"alias_en": "", "alias_zh": ""},
        "residential_address": dict(HOME),
        "correspondence_address": None,
        "email": "tm@example.com",
        "hkid": "A1234563",
        "passport": None,
        "tcsp": {"licence_no": "", "exemption_reason": ""},
    }


@pytest.mark.parametrize("key, change, cr_item", [
    ("name_zh", "陳小文", "a"),
    ("name_en", {"surname": "WONG", "given_names": "Tai Man"}, "b"),
    ("alias", {"alias_en": "Tommy", "alias_zh": ""}, "c"),
    ("email", "new@example.com", "f"),
    ("hkid", "B1234564", "g"),
    ("passport", {"number": "K1234567", "issuing_country": "GB"}, "h"),
])
def test_each_person_item_is_reported_with_its_cr_letter(key, change, cr_item):
    base = _base_person()
    now = copy.deepcopy(base)
    now[key] = change
    items = pt.diff(base, now, capacity="director")
    assert _keys(items) == [key]
    item = items[0]
    assert item["cr_item"] == cr_item
    assert item["old"] == base[key] and item["new"] == change
    assert item["effective_date"] is None and item["omitted"] is False
    assert item["old_text"] != item["new_text"]
    assert item["label"]


def test_a_directors_residential_move_is_two_items_when_correspondence_follows_it():
    base = _base_person()
    now = copy.deepcopy(base)
    now["residential_address"] = dict(OFFICE)
    items = pt.diff(base, now, capacity="director")
    assert _keys(items) == ["residential_address", "correspondence_address"]
    assert [i["cr_item"] for i in items] == ["d", "e"]
    assert items[1]["old"]["line1"] == HOME["line1"]
    assert items[1]["new"]["line1"] == OFFICE["line1"]


def test_a_secretary_has_no_registered_residential_address_only_correspondence():
    base = _base_person()
    now = copy.deepcopy(base)
    now["residential_address"] = dict(OFFICE)
    assert _keys(pt.diff(base, now, capacity="company_secretary")) == [
        "correspondence_address"]


def test_an_explicit_correspondence_address_is_never_reported_as_moved():
    base = _base_person()
    base["correspondence_address"] = dict(OFFICE)
    now = copy.deepcopy(base)
    now["residential_address"] = {**HOME, "line1": "Flat B, 20/F"}
    now["correspondence_address"] = None
    assert _keys(pt.diff(base, now, capacity="director")) == ["residential_address"]


def test_tcsp_is_a_secretary_item_only():
    base = _base_person()
    now = copy.deepcopy(base)
    now["tcsp"] = {"licence_no": "TC001234", "exemption_reason": ""}
    assert pt.diff(base, now, capacity="director") == []
    items = pt.diff(base, now, capacity="company_secretary")
    assert _keys(items) == ["tcsp"] and items[0]["cr_item"] == "i"


def test_corporate_items_name_address_email_tcsp():
    base = {"party_type": "corporate",
            "name": {"name": "Old Name Limited", "name_zh": ""},
            "address": dict(OFFICE), "email": "a@example.com",
            "tcsp": {"licence_no": "", "exemption_reason": ""}}
    now = copy.deepcopy(base)
    now["name"]["name"] = "New Name Limited"
    now["address"]["line1"] = "Room 99"
    now["email"] = "b@example.com"
    now["tcsp"]["licence_no"] = "TC009999"
    items = pt.diff(base, now, capacity="company_secretary")
    assert _keys(items) == ["name", "address", "email", "tcsp"]
    assert [i["cr_item"] for i in items] == ["a", "b", "c", "i"]
    assert _keys(pt.diff(base, now, capacity="director")) == ["name", "address", "email"]


def test_spelling_and_formatting_noise_is_not_a_change():
    base = _base_person()
    now = copy.deepcopy(base)
    now["name_en"] = {"surname": " chan ", "given_names": "tai  man"}
    now["email"] = "TM@Example.com "
    now["hkid"] = "A123456(3)"
    now["residential_address"] = {**HOME, "state_region": "", "postal_code": ""}
    assert pt.diff(base, now, capacity="director") == []


def test_a_missing_passport_equals_an_empty_one():
    base = _base_person()
    now = copy.deepcopy(base)
    now["passport"] = {"number": "", "issuing_country": ""}
    assert pt.diff(base, now, capacity="director") == []


def test_describe_never_prints_none():
    assert pt.describe("passport", None) == "—"
    assert pt.describe("residential_address", None) == "—"
    assert pt.describe("name_en", {"surname": "CHAN", "given_names": "Tai Man"}) == "CHAN Tai Man"
    assert pt.describe("passport", {"number": "K1", "issuing_country": "GB"}) == "K1 (GB)"


# -- the baseline lifecycle -----------------------------------------------------

def test_no_baseline_means_no_pending_change(db):
    _person(db, email="changed@example.com")
    assert pt.pending_for_person("P1") == []


def test_capture_records_every_current_appointment_once(db):
    assert pt.capture_before_edit(person_id="P1", user_id="U1") == 2
    rows = db.rows("officer_cr_particulars")
    assert sorted(r["entity_id"] for r in rows) == ["E1", "E2"]
    assert all(r["source"] == "first_edit" and r["person_id"] == "P1" for r in rows)
    assert pt.capture_before_edit(person_id="P1", user_id="U1") == 0


def test_capture_never_raises(monkeypatch):
    def boom():
        raise RuntimeError("database down")
    monkeypatch.setattr(pt, "get_supabase", boom)
    assert pt.capture_before_edit(person_id="P1", user_id="U1") == 0


def test_a_corporate_party_with_too_many_appointments_is_not_captured(monkeypatch):
    many = [{"id": f"O{i}", "entity_id": f"X{i}", "corporate_entity_id": "C1",
             "person_id": None, "role": "company_secretary", "is_current": True}
            for i in range(pt.MAX_APPOINTMENTS_CAPTURED + 1)]
    fake = _world(entity_officers=many)
    monkeypatch.setattr(pt, "get_supabase", lambda: fake)
    assert pt.capture_before_edit(corporate_entity_id="C1", user_id="U1") == 0
    assert fake.rows("officer_cr_particulars") == []


def test_edit_then_restore_leaves_nothing_pending(db):
    pt.capture_before_edit(person_id="P1", user_id="U1")
    _person(db, email="changed@example.com")
    pending = pt.pending_for_person("P1")
    assert sorted(r["entity_id"] for r in pending) == ["E1", "E2"]
    e1 = next(r for r in pending if r["entity_id"] == "E1")
    assert e1["company_name"] == "Kanenas Holding Limited"
    assert e1["capacity"] == "director" and e1["officer_id"] == "O1"
    assert _keys(e1["items"]) == ["email"]
    assert e1["open_case"] is None
    # E2's secretaryship is on the register only: no officer row, so the alert
    # starts its ND2B by register id.
    e2 = next(r for r in pending if r["entity_id"] == "E2")
    assert e2["officer_id"] is None and e2["secretary_id"] == "S1"
    _person(db, email="tm@example.com")
    assert pt.pending_for_person("P1") == []


def test_pending_names_an_open_nd2b_case_already_carrying_the_officer(db):
    pt.capture_before_edit(person_id="P1", user_id="U1")
    _person(db, email="changed@example.com")
    db.tables["nar1_cases"].append(
        {"id": "K1", "case_no": "ND2B-2026-0001", "entity_id": "E1",
         "form_code": "Nd2b", "closed_at": None, "changes_applied_at": None})
    db.tables["officer_change_entries"].append(
        {"id": "N1", "case_id": "K1", "kind": "change", "person_id": "P1"})
    e1 = next(r for r in pt.pending_for_person("P1") if r["entity_id"] == "E1")
    assert e1["open_case"] == {"id": "K1", "case_no": "ND2B-2026-0001"}


def test_dismiss_moves_every_baseline_to_now(db):
    pt.capture_before_edit(person_id="P1", user_id="U1")
    _person(db, email="changed@example.com")
    assert pt.dismiss(person_id="P1", user_id="U2") == 2
    assert pt.pending_for_person("P1") == []
    assert all(r["source"] == "dismissed" for r in db.rows("officer_cr_particulars"))


def test_dismiss_keeps_an_explicit_correspondence_address(db):
    pt.set_baseline("E1", person_id="P1",
                    particulars={**pt.snapshot_person("P1"),
                                 "correspondence_address": dict(OFFICE)},
                    source="nd2a_filed", user_id="U1")
    pt.dismiss(person_id="P1", user_id="U1")
    assert pt.baseline("E1", person_id="P1")["correspondence_address"]["line1"] == "Room 1201"


def test_advance_moves_only_the_filed_items(db):
    pt.capture_before_edit(person_id="P1", user_id="U1")
    _person(db, email="changed@example.com", full_name_zh="陳小文")
    items = pt.pending_for_officer("E1", person_id="P1", capacity="director")
    filed = [i for i in items if i["key"] == "email"]
    pt.advance("E1", person_id="P1", items=filed, user_id="U1")
    left = pt.pending_for_officer("E1", person_id="P1", capacity="director")
    assert _keys(left) == ["name_zh"]
    assert pt.baseline("E1", person_id="P1")["email"] == "changed@example.com"


def test_advance_of_a_secretarys_correspondence_keeps_it_following_residential(db):
    pt.capture_before_edit(person_id="P1", user_id="U1")
    db.tables["addresses"][0].update(line1="Flat Z, 1/F")
    items = pt.pending_for_officer("E2", person_id="P1", capacity="company_secretary")
    assert _keys(items) == ["correspondence_address"]
    pt.advance("E2", person_id="P1", items=items, user_id="U1",
               capacity="company_secretary")
    base = pt.baseline("E2", person_id="P1")
    assert base["correspondence_address"] is None
    assert base["residential_address"]["line1"] == "Flat Z, 1/F"
    assert pt.pending_for_officer("E2", person_id="P1", capacity="company_secretary") == []


def test_registered_view_falls_back_to_the_profile(db):
    assert pt.registered_view("E1", person_id="P1")["email"] == "tm@example.com"
    pt.capture_before_edit(person_id="P1", user_id="U1")
    _person(db, email="changed@example.com")
    assert pt.registered_view("E1", person_id="P1")["email"] == "tm@example.com"


def test_corporate_pending_and_dismiss(db):
    pt.capture_before_edit(corporate_entity_id="C1", user_id="U1")
    db.tables["entities"][2]["email"] = "new-corp@example.com"
    pending = pt.pending_for_corporate("C1")
    assert [r["entity_id"] for r in pending] == ["E1"]
    assert _keys(pending[0]["items"]) == ["email"]
    assert pt.dismiss(corporate_entity_id="C1", user_id="U1") == 1
    assert pt.pending_for_corporate("C1") == []
