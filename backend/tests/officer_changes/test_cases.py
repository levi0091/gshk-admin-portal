"""ND2A / ND2B cases: opening, the change list, and the composite the page reads."""
import asyncio

import pytest

from services import nar1_cases
from services.officer_changes import cases, particulars
from tests.officer_changes.fakes import FakeSupabase

USER = {"id": "U1", "display_name": "Staff"}


def _tables():
    return {
        "entities": [
            {"id": "E1", "company_name": "Kanenas Holding Limited", "company_type": "P",
             "br_number": "69123456", "deleted_at": None},
            {"id": "GSHK", "company_name": "Get Started HK Limited",
             "registered_address_id": "A2", "email": "cosec@getstarted.hk"},
            {"id": "C9", "company_name": "Corp Director Limited",
             "registered_address_id": "A2", "email": "c9@example.com"},
        ],
        "persons": [
            {"id": "P1", "full_name": "CHAN Tai Man", "surname": "CHAN",
             "given_names": "Tai Man", "email": "p1@example.com",
             "residential_address_id": "A1", "date_of_birth": "1970-01-01"},
            {"id": "P2", "full_name": "LEE Siu Ming", "surname": "LEE",
             "given_names": "Siu Ming", "email": "p2@example.com",
             "residential_address_id": "A1", "date_of_death": "2026-09-20"},
            {"id": "P9", "full_name": "HO New", "surname": "HO", "given_names": "New",
             "email": None, "residential_address_id": None},
        ],
        "addresses": [
            {"id": "A1", "line1": "Flat A", "city": "CENTRAL", "country": "HK"},
            {"id": "A2", "line1": "Suite C", "city": "CENTRAL", "country": "HK"},
        ],
        "person_identity_documents": [
            {"id": "D1", "person_id": "P1", "id_type": "hkid", "id_number": "A1234563",
             "is_primary": True}],
        "entity_officers": [
            {"id": "O1", "entity_id": "E1", "person_id": "P1", "party_type": "individual",
             "role": "director", "is_current": True, "appointed_date": "2020-01-01"},
            {"id": "O2", "entity_id": "E1", "person_id": "P2", "party_type": "individual",
             "role": "director", "is_current": True, "appointed_date": "2021-01-01"},
            {"id": "O3", "entity_id": "E1", "corporate_entity_id": "GSHK",
             "person_id": None, "party_type": "corporate", "role": "company_secretary",
             "is_current": True, "appointed_date": "2020-01-01"},
        ],
        "company_secretaries": [],
        "nar1_cases": [],
        "officer_change_entries": [],
        "officer_change_documents": [],
        "officer_cr_particulars": [],
        "person_eservice_credentials": [],
        "tpsi_filings": [],
        "contacts": [],
    }


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase(_tables())
    for module in (cases, particulars, nar1_cases):
        monkeypatch.setattr(module, "get_supabase", lambda: fake)
    monkeypatch.setattr(cases.soft_delete, "is_deleted", lambda sb, t, i: False)
    return fake


@pytest.fixture
def nd2a(db):
    case, _ = cases.create_case(entity_id="E1", form_code="Nd2a", user_id="U1")
    return case


# -- opening --------------------------------------------------------------------

def test_create_numbers_the_case_and_marks_its_form(db):
    case, reused = cases.create_case(entity_id="E1", form_code="Nd2a", user_id="U1")
    assert reused is False
    assert case["case_no"].startswith("ND2A-")
    assert case["form_code"] == "Nd2a"
    assert case["nar1_type"] == "appointment_and_resignation"
    b, _ = cases.create_case(entity_id="E1", form_code="Nd2b", user_id="U1")
    assert b["case_no"].startswith("ND2B-") and b["nar1_type"] == "change_of_particulars"


def test_create_reuses_the_open_unsent_case_of_that_form(db, nd2a):
    again, reused = cases.create_case(entity_id="E1", form_code="Nd2a", user_id="U1")
    assert reused is True and again["id"] == nd2a["id"]


def test_a_sent_case_is_not_reused(db, nd2a):
    db.tables["nar1_cases"][0]["verification_sent_at"] = "2026-09-30T00:00:00Z"
    again, reused = cases.create_case(entity_id="E1", form_code="Nd2a", user_id="U1")
    assert reused is False and again["id"] != nd2a["id"]


def test_create_refuses_an_unknown_form_and_a_deleted_company(db, monkeypatch):
    with pytest.raises(ValueError):
        cases.create_case(entity_id="E1", form_code="Nar1", user_id="U1")
    monkeypatch.setattr(cases.soft_delete, "is_deleted", lambda sb, t, i: True)
    with pytest.raises(ValueError, match="deleted"):
        cases.create_case(entity_id="E1", form_code="Nd2a", user_id="U1")


def test_get_case_refuses_a_nar1_case(db):
    db.tables["nar1_cases"].append({"id": "N1", "form_code": "Nar1"})
    with pytest.raises(LookupError):
        cases.get_case("N1")
    with pytest.raises(LookupError):
        cases.get_case("nope")


# -- the change list --------------------------------------------------------------

def test_a_cessation_takes_its_party_from_the_officer_row(db, nd2a):
    entry = cases.add_entry(nd2a, {"kind": "cessation", "officer_id": "O1",
                                   "effective_date": "2026-09-28",
                                   "cessation_reason": "R"}, user_id="U1")
    assert entry["person_id"] == "P1" and entry["capacity"] == "director"
    assert entry["party_type"] == "individual"
    assert db.rows("nar1_cases")[0]["filing_deadline"] == "2026-10-13"


@pytest.mark.parametrize("payload, message", [
    ({"kind": "cessation", "effective_date": "2026-09-28", "cessation_reason": "R"},
     "officer"),
    ({"kind": "cessation", "officer_id": "O1", "effective_date": "2026-09-28"},
     "reason"),
    ({"kind": "cessation", "officer_id": "OX", "effective_date": "2026-09-28",
      "cessation_reason": "R"}, "current officer"),
    ({"kind": "appointment", "party_type": "individual", "person_id": "P1",
      "capacity": "director", "effective_date": "2026-09-28"}, "already"),
    ({"kind": "appointment", "party_type": "corporate", "corporate_entity_id": "C9",
      "capacity": "director", "effective_date": "2026-09-28"}, "consent"),
    ({"kind": "appointment", "party_type": "individual", "person_id": "P9",
      "capacity": "director", "effective_date": "2026-09-28",
      "correspondence_same_as_residential": False}, "correspondence"),
    ({"kind": "appointment", "party_type": "individual", "person_id": "P9",
      "capacity": "alternate_director", "effective_date": "2026-09-28"}, "capacity"),
    ({"kind": "change", "officer_id": "O1"}, "ND2B"),
])
def test_nd2a_entry_validation(db, nd2a, payload, message):
    with pytest.raises(ValueError, match=message):
        cases.add_entry(nd2a, payload, user_id="U1")


def test_a_corporate_cessation_needs_no_reason(db, nd2a):
    entry = cases.add_entry(nd2a, {"kind": "cessation", "officer_id": "O3",
                                   "effective_date": "2026-09-28"}, user_id="U1")
    assert entry["cessation_reason"] is None and entry["capacity"] == "company_secretary"


def test_an_officer_cannot_cease_twice_on_one_case(db, nd2a):
    body = {"kind": "cessation", "officer_id": "O1", "effective_date": "2026-09-28",
            "cessation_reason": "R"}
    cases.add_entry(nd2a, body, user_id="U1")
    with pytest.raises(ValueError, match="already"):
        cases.add_entry(nd2a, body, user_id="U1")


def test_a_body_corporate_director_with_its_consent_signer(db, nd2a):
    entry = cases.add_entry(nd2a, {
        "kind": "appointment", "party_type": "corporate", "corporate_entity_id": "C9",
        "capacity": "director", "effective_date": "2026-09-28",
        "consent_person_id": "P1", "consent_capacity": "Director"}, user_id="U1")
    assert entry["corporate_entity_id"] == "C9" and entry["consent_person_id"] == "P1"


def test_nothing_changes_once_the_client_has_been_sent_the_form(db, nd2a):
    entry = cases.add_entry(nd2a, {"kind": "cessation", "officer_id": "O1",
                                   "effective_date": "2026-09-28",
                                   "cessation_reason": "R"}, user_id="U1")
    sent = {**nd2a, "verification_sent_at": "2026-09-30T00:00:00Z"}
    assert cases.editable(sent) is False
    with pytest.raises(cases.CaseRefused) as refused:
        cases.update_entry(sent, entry["id"], {"effective_date": "2026-09-27"},
                           user_id="U1")
    assert refused.value.reason == "not_editable"
    with pytest.raises(cases.CaseRefused):
        cases.remove_entry(sent, entry["id"])
    # KYC is a Data Verification act, after the send.
    assert cases.set_kyc(sent, entry["id"], True, user_id="U1")["kyc_cleared"] is True


def test_update_returns_before_and_after_and_moves_the_deadline(db, nd2a):
    entry = cases.add_entry(nd2a, {"kind": "cessation", "officer_id": "O1",
                                   "effective_date": "2026-09-28",
                                   "cessation_reason": "R"}, user_id="U1")
    before, after = cases.update_entry(nd2a, entry["id"],
                                       {"effective_date": "2026-09-20"}, user_id="U1")
    assert before["effective_date"] == "2026-09-28"
    assert after["effective_date"] == "2026-09-20"
    assert db.rows("nar1_cases")[0]["filing_deadline"] == "2026-10-05"
    cases.remove_entry(nd2a, entry["id"])
    assert db.rows("nar1_cases")[0]["filing_deadline"] is None


# -- ND2B ----------------------------------------------------------------------------

@pytest.fixture
def nd2b(db):
    particulars.capture_before_edit(person_id="P1", user_id="U1")
    db.tables["persons"][0]["email"] = "new@example.com"
    case, _ = cases.create_case(entity_id="E1", form_code="Nd2b", user_id="U1")
    return case


def test_a_change_entry_takes_its_items_from_the_profile_not_the_payload(db, nd2b):
    entry = cases.add_entry(nd2b, {"kind": "change", "officer_id": "O1",
                                   "items": [{"key": "hkid", "new": "X"}]}, user_id="U1")
    assert [i["key"] for i in entry["items"]] == ["email"]
    assert entry["registered"]["email"] == "p1@example.com"


def test_only_the_date_and_omission_of_an_item_are_writable(db, nd2b):
    entry = cases.add_entry(nd2b, {"kind": "change", "officer_id": "O1"}, user_id="U1")
    _, after = cases.update_entry(nd2b, entry["id"], {"items": [
        {"key": "email", "effective_date": "2026-09-25", "omitted": False,
         "new": "hacked@example.com"}]}, user_id="U1")
    item = after["items"][0]
    assert item["effective_date"] == "2026-09-25"
    assert item["new"] == "new@example.com"
    assert db.rows("nar1_cases")[0]["filing_deadline"] == "2026-10-10"


def test_refresh_keeps_dates_drops_vanished_items_and_adds_new_ones(db, nd2b):
    entry = cases.add_entry(nd2b, {"kind": "change", "officer_id": "O1"}, user_id="U1")
    cases.update_entry(nd2b, entry["id"], {"items": [
        {"key": "email", "effective_date": "2026-09-25"}]}, user_id="U1")
    db.tables["persons"][0]["surname"] = "WONG"
    entries = cases.refresh_items(nd2b, cases.list_entries(nd2b["id"]))
    items = {i["key"]: i for i in entries[0]["items"]}
    assert set(items) == {"name_en", "email"}
    assert items["email"]["effective_date"] == "2026-09-25"
    # Put the email back: that line disappears, the name change stays.
    db.tables["persons"][0]["email"] = "p1@example.com"
    entries = cases.refresh_items(nd2b, cases.list_entries(nd2b["id"]))
    assert [i["key"] for i in entries[0]["items"]] == ["name_en"]


def test_an_nd2b_case_refuses_appointments(db, nd2b):
    with pytest.raises(ValueError, match="ND2A"):
        cases.add_entry(nd2b, {"kind": "appointment", "party_type": "individual",
                               "person_id": "P9", "capacity": "director",
                               "effective_date": "2026-09-28"}, user_id="U1")


# -- composite and pending ---------------------------------------------------------

def test_composite_survives_unbuilt_parts_and_reports_them(db, nd2a, monkeypatch):
    cases.add_entry(nd2a, {"kind": "cessation", "officer_id": "O2",
                           "effective_date": "2026-09-28", "cessation_reason": "D"},
                    user_id="U1")
    monkeypatch.setattr(nar1_cases, "composite", lambda cid: {"id": cid})

    async def boom(*a, **k):
        raise NotImplementedError("Task 3")
    monkeypatch.setattr(cases.prepare, "mapping_problems", boom)
    monkeypatch.setattr(cases.prepare, "consent_plan", boom)
    data = asyncio.run(cases.composite(nd2a["id"], user=USER))
    assert data["form_code"] == "Nd2a" and data["case_type"] == "ND2A"
    assert data["editable"] is True
    assert data["deadline"]["date"] == "2026-10-13"
    assert data["entries"][0]["party"]["name"] == "LEE Siu Ming"
    assert "ceases" in data["entries"][0]["summary"]
    officer = next(o for o in data["officers"] if o["officer_id"] == "O2")
    assert officer["pending"] is True and officer["date_of_death"] == "2026-09-20"
    assert data["rules"]["checks"]
    assert any("Task 3" in p or "not available" in p for p in data["problems"])
    assert data["signatory"]["is_corporate"] is True
    assert data["signatory"]["name"] == "Get Started HK Limited"
    assert data["route"]["default"] == "esign"


def test_composite_names_new_directors_missing_an_eregistry_credential(db, nd2a, monkeypatch):
    cases.add_entry(nd2a, {"kind": "appointment", "party_type": "individual",
                           "person_id": "P9", "capacity": "director",
                           "effective_date": "2026-09-28"}, user_id="U1")
    monkeypatch.setattr(nar1_cases, "composite", lambda cid: {"id": cid})

    async def no_problems(*a, **k):
        return []

    async def plan(case, entries):
        return [{"entry_id": entries[0]["id"], "bean_id": "S1", "signer_person_id": "P9",
                 "signer_name": "HO New", "eservice_user_id": None, "ready": False,
                 "reason": "HO New has no e-Registry account stored", "signed_at": None}]
    monkeypatch.setattr(cases.prepare, "mapping_problems", no_problems)
    monkeypatch.setattr(cases.prepare, "consent_plan", plan)
    data = asyncio.run(cases.composite(nd2a["id"], user=USER))
    assert data["route"]["esign_available"] is False
    assert data["route"]["default"] == "manual"
    assert data["route"]["reasons"] == ["HO New has no e-Registry account stored"]
    assert data["entries"][0]["eservice"]["configured"] is False
    assert "email address" in data["entries"][0]["party"]["missing"]


def test_open_cases_for_a_company_and_for_a_person(db, nd2a):
    cases.add_entry(nd2a, {"kind": "cessation", "officer_id": "O1",
                           "effective_date": "2026-09-28", "cessation_reason": "R"},
                    user_id="U1")
    by_company = cases.open_cases_for(entity_id="E1")
    assert [c["id"] for c in by_company] == [nd2a["id"]]
    assert by_company[0]["case_type"] == "ND2A"
    assert by_company[0]["company_name"] == "Kanenas Holding Limited"
    assert by_company[0]["entries"][0]["party_name"] == "CHAN Tai Man"
    assert [c["id"] for c in cases.open_cases_for(person_id="P1")] == [nd2a["id"]]
    assert cases.open_cases_for(person_id="P2") == []
    db.tables["nar1_cases"][0]["closed_at"] = "2026-09-30T00:00:00Z"
    assert cases.open_cases_for(entity_id="E1") == []


# -- a secretary held only in the secretary register ------------------------------
#
# `company_secretaries` is the register the NAR1 mapper reads first, and on DEV
# hundreds of companies hold their secretary only there. The ND2A board read
# `entity_officers` alone, so such a company looked secretary-less: the
# "keeps a company secretary" rule failed and Send was blocked on every ND2A,
# and the secretary could not be ceased at all.

def _register_only(db, **row):
    db.tables["entity_officers"] = [o for o in db.tables["entity_officers"] if o["id"] != "O3"]
    db.tables["company_secretaries"].append({
        "id": "S1", "entity_id": "E1", "is_gshk": True, "is_current": True,
        "secretary_name": "Get Started HK Limited", "person_id": None,
        "appointed_date": "2019-05-01", **row})


def test_a_register_only_secretary_is_on_the_board(db, nd2a):
    _register_only(db)
    officers = cases._current_officers("E1", [])
    sec = [o for o in officers if o["role"] == "company_secretary"]
    assert len(sec) == 1
    assert sec[0]["officer_id"] is None and sec[0]["secretary_id"] == "S1"
    assert sec[0]["register_only"] is True
    assert sec[0]["name"] == "Get Started HK Limited"
    # Resolved to the one live company of that name, as the NAR1 source does.
    assert sec[0]["corporate_entity_id"] == "GSHK"
    assert sec[0]["party_type"] == "corporate"


def test_a_register_row_twinned_by_an_officer_row_is_not_listed_twice(db, nd2a):
    db.tables["company_secretaries"].append({
        "id": "S1", "entity_id": "E1", "is_current": True, "person_id": None,
        "secretary_name": "get started hk  limited"})
    officers = cases._current_officers("E1", [])
    secs = [o for o in officers if o["role"] == "company_secretary"]
    assert [o["officer_id"] for o in secs] == ["O3"]
    # So a Cease pressed on the profile's Secretary tile (register id) finds O3.
    assert secs[0]["secretary_ids"] == ["S1"]


def test_a_twinned_register_id_resolves_to_its_officer_row_without_promoting(db, nd2a):
    db.tables["company_secretaries"].append({
        "id": "S1", "entity_id": "E1", "is_current": True, "person_id": None,
        "secretary_name": "Get Started HK Limited"})
    before = len(db.tables["entity_officers"])
    entry = cases.add_entry(nd2a, {"kind": "cessation", "secretary_id": "S1",
                                   "effective_date": "2026-09-28"}, user_id="U1")
    assert entry["officer_id"] == "O3"
    assert "promoted_from_register" not in entry
    assert len(db.tables["entity_officers"]) == before


def test_an_nd2b_for_a_register_only_secretary_promotes_it_too(db):
    case, _ = cases.create_case(entity_id="E1", form_code="Nd2b", user_id="U1")
    _register_only(db, person_id="P1", secretary_name=None, is_gshk=False)
    entry = cases.add_entry(case, {"kind": "change", "secretary_id": "S1"}, user_id="U1")
    assert entry["capacity"] == "company_secretary" and entry["person_id"] == "P1"
    assert entry["promoted_from_register"]["secretary_id"] == "S1"


def test_the_rules_see_a_register_only_secretary(db, nd2a):
    _register_only(db)
    view = asyncio.run(cases.composite(nd2a["id"], user=USER))
    check = next(c for c in view["rules"]["checks"] if c["code"] == "has_secretary")
    assert check["ok"] is True


def test_ceasing_a_register_only_secretary_promotes_it_to_an_officer_row(db, nd2a):
    _register_only(db)
    entry = cases.add_entry(nd2a, {"kind": "cessation", "secretary_id": "S1",
                                   "effective_date": "2026-09-28"}, user_id="U1")
    promoted = [o for o in db.tables["entity_officers"]
                if o["role"] == "company_secretary" and o["entity_id"] == "E1"]
    assert len(promoted) == 1
    assert promoted[0]["corporate_entity_id"] == "GSHK"
    assert promoted[0]["party_type"] == "corporate"
    assert promoted[0]["is_current"] is True
    assert promoted[0]["appointed_date"] == "2019-05-01"
    assert entry["officer_id"] == promoted[0]["id"]
    assert entry["party_type"] == "corporate" and entry["cessation_reason"] is None
    assert entry["promoted_from_register"] == {"secretary_id": "S1",
                                               "officer_id": promoted[0]["id"]}
    # The register row is untouched until the form is filed.
    assert db.tables["company_secretaries"][0]["is_current"] is True


def test_a_register_only_individual_secretary_is_ceased_with_a_reason(db, nd2a):
    _register_only(db, person_id="P1", secretary_name=None, is_gshk=False)
    with pytest.raises(ValueError, match="reason for cessation"):
        cases.add_entry(nd2a, {"kind": "cessation", "secretary_id": "S1",
                               "effective_date": "2026-09-28"}, user_id="U1")
    entry = cases.add_entry(nd2a, {"kind": "cessation", "secretary_id": "S1",
                                   "effective_date": "2026-09-28",
                                   "cessation_reason": "R"}, user_id="U1")
    assert entry["person_id"] == "P1" and entry["party_type"] == "individual"


def test_a_register_name_no_company_answers_to_is_refused_by_name(db, nd2a):
    _register_only(db, secretary_name="Nobody Secretarial Limited")
    with pytest.raises(ValueError, match="Nobody Secretarial Limited"):
        cases.add_entry(nd2a, {"kind": "cessation", "secretary_id": "S1",
                               "effective_date": "2026-09-28"}, user_id="U1")
    assert not [o for o in db.tables["entity_officers"] if o["role"] == "company_secretary"]


def test_the_signatory_is_read_in_the_xmls_order_register_first(db, nd2a):
    # The officer list names GSHK; the register names a natural person. The
    # XML (nar1_mapper._signatory_candidates) takes the register first, so the
    # card must too — and offer that person the Individual capacities.
    db.tables["company_secretaries"].append({
        "id": "S1", "entity_id": "E1", "is_gshk": False, "is_current": True,
        "person_id": "P1", "secretary_name": None})
    view = cases._signatory("E1", nd2a)
    assert view["name"] == "CHAN Tai Man" and view["is_corporate"] is False
    assert "Company Secretary" in view["capacities"]


def test_a_register_only_corporate_secretary_is_named_as_the_signatory(db, nd2a):
    _register_only(db)
    view = cases._signatory("E1", nd2a)
    assert view["name"] == "Get Started HK Limited" and view["is_corporate"] is True


def test_a_corporate_row_with_only_a_name_is_not_a_natural_person():
    # A Viewpoint corporate director with no corporate_entity_id must not count
    # towards "a natural-person director remains".
    row = {"id": "O9", "role": "director", "party_type": "corporate",
           "person_id": None, "corporate_entity_id": None, "corporate_name": "OLD CO"}
    assert cases._party_of(row)["party_type"] == "corporate"
    assert cases._party_of({**row, "party_type": "individual", "person_id": "P1"})[
        "party_type"] == "individual"


def test_a_register_row_of_another_company_is_refused(db, nd2a):
    _register_only(db, entity_id="E-OTHER")
    with pytest.raises(ValueError, match="not a current secretary of this company"):
        cases.add_entry(nd2a, {"kind": "cessation", "secretary_id": "S1",
                               "effective_date": "2026-09-28"}, user_id="U1")


# -- deferred effective dates (Jacqueline A1, B1) -------------------------------------

from datetime import date as _date  # noqa: E402


def _send(db, case):
    row = next(r for r in db.tables["nar1_cases"] if r["id"] == case["id"])
    row["verification_sent_at"] = "2026-10-01T00:00:00Z"
    cases.mark_deferred(case["id"])
    return dict(row)


def test_appointment_and_cessation_accept_no_date(db, nd2a):
    gone = cases.add_entry(nd2a, {"kind": "cessation", "officer_id": "O1",
                                  "cessation_reason": "R"}, user_id="U1")
    new = cases.add_entry(nd2a, {"kind": "appointment", "party_type": "individual",
                                 "person_id": "P9", "capacity": "director",
                                 "effective_date": ""}, user_id="U1")
    assert gone["effective_date"] is None and new["effective_date"] is None
    assert db.rows("nar1_cases")[0]["filing_deadline"] is None


def test_new_nd2b_item_is_dated_the_anniversary(db, monkeypatch):
    db.tables["entities"][0]["incorporation_date"] = "2019-09-01"
    monkeypatch.setattr(cases.deadlines, "hk_today", lambda: _date(2026, 10, 2))
    particulars.capture_before_edit(person_id="P1", user_id="U1")
    db.tables["persons"][0]["email"] = "new@example.com"
    case, _ = cases.create_case(entity_id="E1", form_code="Nd2b", user_id="U1")
    entry = cases.add_entry(case, {"kind": "change", "officer_id": "O1"}, user_id="U1")
    assert [i["effective_date"] for i in entry["items"]] == ["2026-09-01"]


def test_nd2b_default_follows_the_open_nar1_return_date(db, monkeypatch):
    db.tables["entities"][0]["incorporation_date"] = "2019-03-12"
    db.tables["nar1_cases"].append({"id": "N1", "entity_id": "E1", "form_code": "Nar1",
                                    "ar_period_year": 2026, "closed_at": None})
    monkeypatch.setattr(cases.deadlines, "hk_today", lambda: _date(2026, 10, 2))
    particulars.capture_before_edit(person_id="P1", user_id="U1")
    db.tables["persons"][0]["email"] = "new@example.com"
    case, _ = cases.create_case(entity_id="E1", form_code="Nd2b", user_id="U1")
    entry = cases.add_entry(case, {"kind": "change", "officer_id": "O1"}, user_id="U1")
    assert entry["items"][0]["effective_date"] == "2026-03-12"


def test_mark_deferred_flags_only_undated(db, nd2a):
    dated = cases.add_entry(nd2a, {"kind": "cessation", "officer_id": "O1",
                                   "cessation_reason": "R",
                                   "effective_date": "2026-09-28"}, user_id="U1")
    undated = cases.add_entry(nd2a, {"kind": "appointment", "party_type": "individual",
                                     "person_id": "P9", "capacity": "director"},
                              user_id="U1")
    _send(db, nd2a)
    rows = {r["id"]: r for r in db.rows("officer_change_entries")}
    assert not rows[dated["id"]].get("date_deferred")  # column default false
    assert rows[undated["id"]]["date_deferred"] is True


def test_mark_deferred_marks_nd2b_items(db, nd2b):
    entry = cases.add_entry(nd2b, {"kind": "change", "officer_id": "O1"}, user_id="U1")
    _send(db, nd2b)
    item = cases.list_entries(nd2b["id"])[0]["items"][0]
    assert entry["items"][0]["effective_date"] is None and item["deferred"] is True


def _deferred_appointment(db, nd2a):
    entry = cases.add_entry(nd2a, {"kind": "appointment", "party_type": "individual",
                                   "person_id": "P9", "capacity": "director"}, user_id="U1")
    return _send(db, nd2a), entry


def test_set_effective_date_fills_a_deferred_date(db, nd2a, monkeypatch):
    monkeypatch.setattr(cases.deadlines, "hk_today", lambda: _date(2026, 10, 2))
    sent, entry = _deferred_appointment(db, nd2a)
    before, after = cases.set_effective_date(sent, entry["id"], "2026-10-01", user_id="U1")
    assert before["effective_date"] is None and after["effective_date"] == "2026-10-01"
    assert db.rows("nar1_cases")[0]["filing_deadline"] == "2026-10-16"


def test_set_effective_date_refuses_a_date_the_client_saw(db, nd2a):
    entry = cases.add_entry(nd2a, {"kind": "cessation", "officer_id": "O1",
                                   "cessation_reason": "R",
                                   "effective_date": "2026-09-28"}, user_id="U1")
    sent = _send(db, nd2a)
    with pytest.raises(cases.CaseRefused) as exc:
        cases.set_effective_date(sent, entry["id"], "2026-09-29", user_id="U1")
    assert exc.value.reason == "not_deferred"


def test_set_effective_date_refuses_the_future(db, nd2a, monkeypatch):
    monkeypatch.setattr(cases.deadlines, "hk_today", lambda: _date(2026, 10, 2))
    sent, entry = _deferred_appointment(db, nd2a)
    with pytest.raises(ValueError, match="after today"):
        cases.set_effective_date(sent, entry["id"], "2026-10-03", user_id="U1")


def test_set_effective_date_before_sending_is_refused(db, nd2a):
    entry = cases.add_entry(nd2a, {"kind": "appointment", "party_type": "individual",
                                   "person_id": "P9", "capacity": "director"}, user_id="U1")
    with pytest.raises(cases.CaseRefused) as exc:
        cases.set_effective_date(nd2a, entry["id"], "2026-09-29", user_id="U1")
    assert exc.value.reason == "not_sent"


def test_set_effective_date_after_signing_is_refused(db, nd2a, monkeypatch):
    sent, entry = _deferred_appointment(db, nd2a)
    with pytest.raises(cases.CaseRefused) as exc:
        cases.set_effective_date({**sent, "manual_signed_document_id": "D9"}, entry["id"],
                                 "2026-09-29", user_id="U1")
    assert exc.value.reason == "signed"
    monkeypatch.setattr(cases.nar1_cases, "current_filing",
                        lambda cid: {"id": "F1", "stage": "signed"})
    with pytest.raises(cases.CaseRefused) as exc:
        cases.set_effective_date(sent, entry["id"], "2026-09-29", user_id="U1")
    assert exc.value.reason == "signed"


def test_set_effective_date_supersedes_a_validated_filing(db, nd2a, monkeypatch):
    monkeypatch.setattr(cases.deadlines, "hk_today", lambda: _date(2026, 10, 2))
    sent, entry = _deferred_appointment(db, nd2a)
    monkeypatch.setattr(cases.nar1_cases, "current_filing",
                        lambda cid: {"id": "F1", "stage": "validated"})
    calls = []
    monkeypatch.setattr(cases.tpsi_filings, "supersede_all_for_case",
                        lambda cid: calls.append(cid) or 1)
    cases.set_effective_date(sent, entry["id"], "2026-10-01", user_id="U1")
    assert calls == [nd2a["id"]]


def test_set_effective_date_on_an_nd2b_item(db, nd2b, monkeypatch):
    monkeypatch.setattr(cases.deadlines, "hk_today", lambda: _date(2026, 10, 2))
    entry = cases.add_entry(nd2b, {"kind": "change", "officer_id": "O1"}, user_id="U1")
    sent = _send(db, nd2b)
    _, after = cases.set_effective_date(sent, entry["id"], "2026-09-30", item_key="email",
                                        user_id="U1")
    assert after["items"][0]["effective_date"] == "2026-09-30"


def test_restart_then_resend_makes_a_filled_date_seen(db, nd2a, monkeypatch):
    """Review Focus 1: a date filled in after the first send is one the client
    has SEEN once the form is re-sent, so it can no longer be changed quietly."""
    monkeypatch.setattr(cases.deadlines, "hk_today", lambda: _date(2026, 10, 2))
    sent, entry = _deferred_appointment(db, nd2a)
    cases.set_effective_date(sent, entry["id"], "2026-10-01", user_id="U1")
    resent = _send(db, nd2a)
    with pytest.raises(cases.CaseRefused) as exc:
        cases.set_effective_date(resent, entry["id"], "2026-09-30", user_id="U1")
    assert exc.value.reason == "not_deferred"


def test_composite_lists_missing_dates(db, nd2a, monkeypatch):
    cases.add_entry(nd2a, {"kind": "appointment", "party_type": "individual",
                           "person_id": "P9", "capacity": "director"}, user_id="U1")
    data = asyncio.run(cases.composite(nd2a["id"], user=USER))
    assert data["dates_missing"] == ["HO New"]


def test_composite_carries_the_manual_checks(db, nd2a, monkeypatch):
    monkeypatch.setattr(cases.documents, "list_for_case", lambda cid, entries=None: [])
    cases.add_entry(nd2a, {"kind": "cessation", "officer_id": "O1",
                           "cessation_reason": "R"}, user_id="U1")
    data = asyncio.run(cases.composite(nd2a["id"], user=USER))
    assert [c["code"] for c in data["manual_checks"]] == ["resignation_letter"]
    assert data["manual_checks"][0]["label"] == "Resignation letter on file — CHAN Tai Man"


def test_manual_checks_open_names_the_leaver(db, nd2a, monkeypatch):
    monkeypatch.setattr(cases.documents, "list_for_case", lambda cid, entries=None: [])
    cases.add_entry(nd2a, {"kind": "cessation", "officer_id": "O1",
                           "cessation_reason": "R"}, user_id="U1")
    assert cases.manual_checks_open(nd2a, route="manual") == [
        "Resignation letter on file — CHAN Tai Man"]



def test_composite_says_how_each_new_director_consents(db, nd2a, monkeypatch):
    monkeypatch.setattr(cases.documents, "list_for_case", lambda cid, entries=None: [])

    async def plan(case, entries):
        return [{"entry_id": e["id"], "ready": False, "reason": "no account"}
                for e in entries if e.get("kind") == "appointment"]

    monkeypatch.setattr(cases.prepare, "consent_plan", plan)
    db.tables["persons"][2]["email"] = "ho@example.com"
    entry = cases.add_entry(nd2a, {"kind": "appointment", "party_type": "individual",
                                   "person_id": "P9", "capacity": "director"}, user_id="U1")
    data = asyncio.run(cases.composite(nd2a["id"], user=USER))
    view = next(e for e in data["entries"] if e["id"] == entry["id"])
    # No account: the case goes the manual route (Levi 2026-10-05).
    assert view["consent_mode"] == "manual" and "econsent" not in view


# -- other open cases for the company (Jacqueline AQ3, BQ1) -------------------------

def _seed_open_cases(db):
    db.tables["nar1_cases"] += [
        {"id": "N-OPEN", "entity_id": "E1", "form_code": "Nar1", "case_no": "NAR-2026-0042"},
        {"id": "N-CLOSED", "entity_id": "E1", "form_code": "Nar1", "case_no": "NAR-2025-0001",
         "closed_at": "2026-01-01T00:00:00Z"},
        {"id": "N-FILED", "entity_id": "E1", "form_code": "Nd2b", "case_no": "ND2B-2026-0001",
         "manual_receipt": {"caseNo": "1"}},
        {"id": "N-OTHERCO", "entity_id": "E2", "form_code": "Nar1", "case_no": "NAR-2026-0099"},
    ]


def test_other_open_cases_excludes_self_closed_filed_and_other_companies(db, nd2a):
    _seed_open_cases(db)
    rows = nar1_cases.other_open_cases("E1", exclude=nd2a["id"])
    assert [(r["case_no"], r["case_type"]) for r in rows] == [("NAR-2026-0042", "NAR1")]
    assert rows[0]["workflow_status"]["code"]


def test_other_open_cases_excludes_a_cr_filed_return(db, nd2a):
    _seed_open_cases(db)
    db.tables["tpsi_filings"].append({"id": "F1", "nar1_case_id": "N-OPEN",
                                      "stage": "submitted", "created_at": "2026-10-01"})
    assert nar1_cases.other_open_cases("E1", exclude=nd2a["id"]) == []


def test_nd2_composite_carries_other_open_cases(db, nd2a, monkeypatch):
    monkeypatch.setattr(cases.documents, "list_for_case", lambda cid, entries=None: [])
    _seed_open_cases(db)
    data = asyncio.run(cases.composite(nd2a["id"], user=USER))
    assert [r["case_no"] for r in data["other_open_cases"]] == ["NAR-2026-0042"]


def test_other_open_cases_never_raises(monkeypatch):
    def boom():
        raise RuntimeError("database down")
    monkeypatch.setattr(nar1_cases, "get_supabase", boom)
    assert nar1_cases.other_open_cases("E1", exclude="K1") == []


def test_nd2b_composite_names_the_anniversary_default(db, monkeypatch):
    """Jacqueline B1: the card says which date the lines start on, and why."""
    monkeypatch.setattr(cases.documents, "list_for_case", lambda cid, entries=None: [])
    db.tables["entities"][0]["incorporation_date"] = "2019-09-01"
    monkeypatch.setattr(cases.deadlines, "hk_today", lambda: _date(2026, 10, 2))
    case, _ = cases.create_case(entity_id="E1", form_code="Nd2b", user_id="U1")
    data = asyncio.run(cases.composite(case["id"], user=USER))
    assert data["anniversary_default"] == "2026-09-01"


def test_a_nar1_filed_by_esign_does_not_set_the_nd2b_default(db, monkeypatch):
    """Finding 3: an e-Sign-filed NAR1 (no manual_receipt; its filing is at
    'submitted') is not 'open', so an October ND2B is not dated March."""
    db.tables["entities"][0]["incorporation_date"] = "2019-03-12"
    db.tables["nar1_cases"].append({"id": "N1", "entity_id": "E1", "form_code": "Nar1",
                                    "ar_period_year": 2026, "closed_at": None})
    db.tables["tpsi_filings"].append({"id": "F1", "nar1_case_id": "N1", "stage": "submitted",
                                      "created_at": "2026-03-20T00:00:00Z"})
    monkeypatch.setattr(cases.deadlines, "hk_today", lambda: _date(2026, 10, 2))
    particulars.capture_before_edit(person_id="P1", user_id="U1")
    db.tables["persons"][0]["email"] = "new@example.com"
    case, _ = cases.create_case(entity_id="E1", form_code="Nd2b", user_id="U1")
    entry = cases.add_entry(case, {"kind": "change", "officer_id": "O1"}, user_id="U1")
    assert entry["items"][0]["effective_date"] is None


def test_a_ready_director_on_a_manual_only_case_is_not_shown_as_esign(db, nd2a, monkeypatch):
    """Finding 4, on the change list."""
    monkeypatch.setattr(cases.documents, "list_for_case", lambda cid, entries=None: [])

    async def plan(case, entries):
        rows = [e for e in entries if e.get("kind") == "appointment"]
        return [{"entry_id": rows[0]["id"], "ready": True},
                {"entry_id": rows[1]["id"], "ready": False, "reason": "no account"}]

    monkeypatch.setattr(cases.prepare, "consent_plan", plan)
    db.tables["persons"][2]["email"] = "ho@example.com"
    db.tables["persons"].append({"id": "P7", "full_name": "LEE Ka Ho", "surname": "LEE",
                                 "given_names": "Ka Ho", "email": "lee@example.com"})
    a = cases.add_entry(nd2a, {"kind": "appointment", "party_type": "individual",
                               "person_id": "P7", "capacity": "director"}, user_id="U1")
    cases.add_entry(nd2a, {"kind": "appointment", "party_type": "individual",
                           "person_id": "P9", "capacity": "director"}, user_id="U1")
    data = asyncio.run(cases.composite(nd2a["id"], user=USER))
    view = next(e for e in data["entries"] if e["id"] == a["id"])
    assert view["consent_mode"] == "manual"


def test_composite_officers_carry_the_chinese_name(db, nd2a, monkeypatch):
    """The written resolution signs 'Name: Aldo KRIEL 歐立德' (Levi 2026-10-05)."""
    monkeypatch.setattr(cases.documents, "list_for_case", lambda cid, entries=None: [])
    db.tables["persons"][0]["full_name_zh"] = "陳大文"
    data = asyncio.run(cases.composite(nd2a["id"], user=USER))
    officer = next(o for o in data["officers"] if o["person_id"] == db.tables["persons"][0]["id"])
    assert officer["name_zh"] == "陳大文"
