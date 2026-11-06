"""Alternate directors on an ND2A case: entries, validation, the composite and
what filing writes (PBI-70 revived, Jacqueline 2026-11-04)."""
import asyncio

import pytest

from services.officer_changes import apply, cases, particulars
from tests.officer_changes.test_apply import CASE, USER
from tests.officer_changes.test_apply import db as apply_db  # noqa: F401
from tests.officer_changes.test_cases import db, nd2a  # noqa: F401 (fixtures)

APPOINT_ALT = {"kind": "appointment", "party_type": "individual", "person_id": "P9",
               "capacity": "alternate_director", "effective_date": "2026-09-28",
               "alternate_to_officer_id": "O1"}


# -- _check_appointment ----------------------------------------------------------------

def test_an_alternate_appointment_keeps_the_director_it_acts_for(db, nd2a):
    entry = cases.add_entry(nd2a, APPOINT_ALT, user_id="U1")
    assert entry["capacity"] == "alternate_director"
    assert entry["alternate_to_officer_id"] == "O1"


@pytest.mark.parametrize("director, message", [
    (None, "Choose the director"),
    ("OX", "current director of this company"),
    ("O3", "current director of this company"),   # the secretary is not a director
])
def test_the_director_must_be_chosen_and_must_be_a_current_director(
        db, nd2a, director, message):
    with pytest.raises(ValueError, match=message):
        cases.add_entry(nd2a, {**APPOINT_ALT, "alternate_to_officer_id": director},
                        user_id="U1")


def test_a_director_who_has_left_cannot_be_acted_for(db, nd2a):
    db.tables["entity_officers"][0]["is_current"] = False
    with pytest.raises(ValueError, match="current director"):
        cases.add_entry(nd2a, APPOINT_ALT, user_id="U1")


def test_a_director_of_another_company_cannot_be_acted_for(db, nd2a):
    db.tables["entity_officers"].append(
        {"id": "OZ", "entity_id": "OTHER", "person_id": "P2", "party_type": "individual",
         "role": "director", "is_current": True})
    with pytest.raises(ValueError, match="current director of this company"):
        cases.add_entry(nd2a, {**APPOINT_ALT, "alternate_to_officer_id": "OZ"},
                        user_id="U1")


def test_a_director_cannot_be_their_own_alternate(db, nd2a):
    with pytest.raises(ValueError, match="own alternate"):
        cases.add_entry(nd2a, {**APPOINT_ALT, "person_id": "P1"}, user_id="U1")


def test_a_body_corporate_alternate_needs_the_consent_signer_like_a_director(db, nd2a):
    body = {**APPOINT_ALT, "party_type": "corporate", "corporate_entity_id": "C9"}
    del body["person_id"]
    with pytest.raises(ValueError, match="consent"):
        cases.add_entry(nd2a, body, user_id="U1")
    entry = cases.add_entry(nd2a, {**body, "consent_person_id": "P9",
                                   "consent_capacity": "Alternate Director"},
                            user_id="U1")
    assert entry["consent_capacity"] == "Alternate Director"


def test_a_secretary_or_director_entry_drops_a_stray_alternate_link(db, nd2a):
    entry = cases.add_entry(nd2a, {**APPOINT_ALT, "capacity": "director"}, user_id="U1")
    assert entry.get("alternate_to_officer_id") is None


def test_editing_an_alternate_to_a_director_clears_the_link(db, nd2a):
    entry = cases.add_entry(nd2a, APPOINT_ALT, user_id="U1")
    _before, after = cases.update_entry(nd2a, entry["id"], {"capacity": "director"},
                                        user_id="U1")
    assert after["capacity"] == "director" and after["alternate_to_officer_id"] is None


def test_the_director_can_be_changed_on_an_alternate_entry(db, nd2a):
    entry = cases.add_entry(nd2a, APPOINT_ALT, user_id="U1")
    _b, after = cases.update_entry(nd2a, entry["id"], {"alternate_to_officer_id": "O2"},
                                   user_id="U1")
    assert after["alternate_to_officer_id"] == "O2"


# -- ceasing an alternate --------------------------------------------------------------

def _alternate_officer(db):
    db.tables["entity_officers"].append(
        {"id": "OA", "entity_id": "E1", "person_id": "P9", "party_type": "individual",
         "role": "alternate_director", "is_current": True, "alternate_to_officer_id": "O1",
         "appointed_date": "2022-01-01"})


def test_ceasing_an_alternate_takes_capacity_and_director_from_the_officer_row(db, nd2a):
    _alternate_officer(db)
    entry = cases.add_entry(nd2a, {"kind": "cessation", "officer_id": "OA",
                                   "effective_date": "2026-09-28",
                                   "cessation_reason": "R"}, user_id="U1")
    assert entry["capacity"] == "alternate_director"
    assert entry["alternate_to_officer_id"] == "O1"


def test_ceasing_a_director_does_not_carry_an_alternate_link(db, nd2a):
    entry = cases.add_entry(nd2a, {"kind": "cessation", "officer_id": "O1",
                                   "effective_date": "2026-09-28",
                                   "cessation_reason": "R"}, user_id="U1")
    assert "alternate_to_officer_id" not in entry


# -- the officers and entries the API returns ------------------------------------------

def test_officers_and_entries_carry_alternate_to_name(db, nd2a):
    _alternate_officer(db)
    entry = cases.add_entry(nd2a, {"kind": "cessation", "officer_id": "OA",
                                   "effective_date": "2026-09-28",
                                   "cessation_reason": "R"}, user_id="U1")
    officers = cases._current_officers("E1", [entry])
    alternate = next(o for o in officers if o["officer_id"] == "OA")
    assert alternate["role"] == "alternate_director"
    assert alternate["alternate_to_officer_id"] == "O1"
    assert alternate["alternate_to_name"] == "CHAN Tai Man"
    assert next(o for o in officers if o["officer_id"] == "O1")["alternate_to_name"] is None
    assert cases._alternate_names([entry], officers) == {"O1": "CHAN Tai Man"}


def test_a_director_who_is_no_longer_current_is_still_named(db, nd2a):
    db.tables["entity_officers"][1]["is_current"] = False  # LEE, O2
    entry = {"alternate_to_officer_id": "O2"}
    current = cases._current_officers("E1", [])
    assert cases._alternate_names([entry], current) == {"O2": "LEE Siu Ming"}


def test_composite_names_the_director_on_an_alternate_entry(db, nd2a, monkeypatch):
    monkeypatch.setattr(cases.nar1_cases, "composite", lambda case_id: {})
    entry = cases.add_entry(nd2a, APPOINT_ALT, user_id="U1")
    result = asyncio.run(cases.composite(nd2a["id"], user=USER))
    row = next(e for e in result["entries"] if e["id"] == entry["id"])
    assert row["alternate_to_name"] == "CHAN Tai Man"
    # And an alternate is asked to consent, as a director is.
    assert row["eservice"] is not None
    assert row["consent_mode"] in ("esign", "manual")
    assert "Alternate directors: HO New (alternate to CHAN Tai Man)." in result["rules"]["lines"]


# -- filing writes the role and the link ----------------------------------------------

def test_filing_an_alternate_appointment_writes_role_and_link(apply_db):
    entry = {"id": "N4", "case_id": "K1", "kind": "appointment",
             "capacity": "alternate_director", "party_type": "individual",
             "person_id": "P9", "officer_id": None, "effective_date": "2026-09-29",
             "correspondence_same_as_residential": True,
             "alternate_to_officer_id": "O1", "party": {"name": "HO New"}}
    apply_db.tables["officer_change_entries"] = [dict(entry)]
    out = asyncio.run(apply.apply_changes(CASE, [dict(entry)], user=USER))
    assert out["errors"] == []
    row = next(o for o in apply_db.rows("entity_officers")
               if o["role"] == "alternate_director")
    assert row["alternate_to_officer_id"] == "O1" and row["is_current"] is True
    assert out["applied"][0]["text"] == "Add HO New as an alternate director from 29 Sep 2026"


def test_a_director_row_is_written_without_the_link_column(apply_db):
    entry = {"id": "N5", "case_id": "K1", "kind": "appointment", "capacity": "director",
             "party_type": "individual", "person_id": "P9", "officer_id": None,
             "effective_date": "2026-09-29", "correspondence_same_as_residential": True,
             "party": {"name": "HO New"}}
    apply_db.tables["officer_change_entries"] = [dict(entry)]
    asyncio.run(apply.apply_changes(CASE, [dict(entry)], user=USER))
    row = next(o for o in apply_db.rows("entity_officers") if o["person_id"] == "P9")
    assert "alternate_to_officer_id" not in row


def test_filing_an_alternate_cessation_marks_the_row_former(apply_db):
    apply_db.tables["entity_officers"].append(
        {"id": "OA", "entity_id": "E1", "person_id": "P9", "party_type": "individual",
         "role": "alternate_director", "is_current": True, "alternate_to_officer_id": "O1"})
    entry = {"id": "N6", "case_id": "K1", "kind": "cessation",
             "capacity": "alternate_director", "party_type": "individual",
             "person_id": "P9", "officer_id": "OA", "effective_date": "2026-09-28",
             "cessation_reason": "R", "party": {"name": "HO New"}}
    apply_db.tables["officer_change_entries"] = [dict(entry)]
    out = asyncio.run(apply.apply_changes(CASE, [dict(entry)], user=USER))
    assert out["errors"] == []
    row = next(o for o in apply_db.rows("entity_officers") if o["id"] == "OA")
    assert row["is_current"] is False
    assert out["applied"][0]["text"].startswith("Mark HO New as a former alternate director")


# -- ND2B: an alternate's particulars change as a director's -------------------------

def test_the_residential_address_is_a_change_item_for_an_alternate():
    baseline = {"party_type": "individual", "residential_address": {"line1": "Old"}}
    current = {"residential_address": {"line1": "New"}}
    keys = [i["key"] for i in particulars.diff(baseline, current,
                                               capacity="alternate_director")]
    assert "residential_address" in keys
    secretary = [i["key"] for i in particulars.diff(baseline, current,
                                                    capacity="company_secretary")]
    assert "residential_address" not in secretary


def test_the_pending_detection_includes_the_alternate_role():
    assert "alternate_director" in particulars._ROLES
