"""Writing a filed officer change to the profiles, and Undo (spec B-5, §5 stage 6;
Review Focus 4)."""
import asyncio

import pytest

from services.officer_changes import apply, particulars
from tests.officer_changes.fakes import FakeSupabase

USER = {"id": "U1", "display_name": "Staff"}
CASE = {"id": "K1", "entity_id": "E1", "company_name": "Kanenas Holding Limited"}
HOME = {"line1": "Flat A", "city": "CENTRAL", "country": "HK"}
OFFICE = {"line1": "Room 1", "city": "CENTRAL", "country": "HK"}


def _db():
    return FakeSupabase({
        "nar1_cases": [dict(CASE)],
        "entities": [{"id": "E1", "company_name": "Kanenas Holding Limited"},
                     {"id": "GSHK", "company_name": "Get Started HK Limited",
                      "registered_address_id": "A2"}],
        "persons": [{"id": "P1", "full_name": "CHAN Tai Man", "surname": "CHAN",
                     "given_names": "Tai Man", "email": "p1@example.com",
                     "residential_address_id": "A1"},
                    {"id": "P9", "full_name": "HO New", "surname": "HO",
                     "given_names": "New", "email": "p9@example.com",
                     "residential_address_id": "A1"}],
        "addresses": [{"id": "A1", **HOME}, {"id": "A2", **OFFICE}],
        "person_identity_documents": [],
        "entity_officers": [
            {"id": "O1", "entity_id": "E1", "person_id": "P1", "party_type": "individual",
             "role": "director", "is_current": True, "resigned_date": None,
             "resignation_reason": None},
            {"id": "O3", "entity_id": "E1", "corporate_entity_id": "GSHK",
             "person_id": None, "party_type": "corporate", "role": "company_secretary",
             "is_current": True},
        ],
        "company_secretaries": [
            {"id": "S1", "entity_id": "E1", "person_id": None,
             "secretary_name": "Get Started HK Limited", "is_current": True}],
        "officer_cr_particulars": [],
        "officer_change_entries": [],
    })


@pytest.fixture
def db(monkeypatch):
    fake = _db()
    monkeypatch.setattr(apply, "get_supabase", lambda: fake)
    monkeypatch.setattr(particulars, "get_supabase", lambda: fake)
    return fake


def _entries(db, *rows):
    db.tables["officer_change_entries"] = [dict(r) for r in rows]
    return db.tables["officer_change_entries"]


CEASE_DIRECTOR = {"id": "N1", "case_id": "K1", "kind": "cessation", "capacity": "director",
                  "party_type": "individual", "person_id": "P1", "officer_id": "O1",
                  "effective_date": "2026-09-28", "cessation_reason": "D",
                  "party": {"name": "CHAN Tai Man"}}
CEASE_SECRETARY = {"id": "N2", "case_id": "K1", "kind": "cessation",
                   "capacity": "company_secretary", "party_type": "corporate",
                   "person_id": None, "corporate_entity_id": "GSHK", "officer_id": "O3",
                   "effective_date": "2026-09-28", "cessation_reason": None,
                   "party": {"name": "Get Started HK Limited"}}
APPOINT = {"id": "N3", "case_id": "K1", "kind": "appointment", "capacity": "director",
           "party_type": "individual", "person_id": "P9", "officer_id": None,
           "effective_date": "2026-09-29", "correspondence_same_as_residential": False,
           "correspondence_address": OFFICE, "party": {"name": "HO New"}}


def _run(fn, case, entries):
    return asyncio.run(fn(case, [dict(e) for e in entries], user=USER))


def test_plan_says_what_filing_will_write(db):
    rows = apply.plan(CASE, [CEASE_DIRECTOR, APPOINT])
    assert rows[0]["text"] == ("Mark CHAN Tai Man as a former director "
                               "(ceased 28 Sep 2026, Deceased)")
    assert rows[1]["text"] == "Add HO New as a director from 29 Sep 2026"
    assert rows[0]["target"] == {"kind": "company", "id": "E1",
                                 "name": "Kanenas Holding Limited"}


def test_a_cessation_marks_the_officer_former_and_the_register_too(db):
    entries = _entries(db, CEASE_DIRECTOR, CEASE_SECRETARY)
    out = _run(apply.apply_changes, CASE, entries)
    assert out["errors"] == [] and len(out["applied"]) == 2
    o1 = next(o for o in db.rows("entity_officers") if o["id"] == "O1")
    assert o1["is_current"] is False and o1["resigned_date"] == "2026-09-28"
    assert o1["resignation_reason"] == "Deceased"
    assert db.rows("company_secretaries")[0]["is_current"] is False
    assert db.rows("nar1_cases")[0]["changes_applied_at"]


def test_an_appointment_adds_the_officer_and_its_baseline(db):
    entries = _entries(db, APPOINT)
    _run(apply.apply_changes, CASE, entries)
    new = next(o for o in db.rows("entity_officers") if o.get("person_id") == "P9")
    assert new["role"] == "director" and new["is_current"] is True
    assert new["appointed_date"] == "2026-09-29"
    entry = db.rows("officer_change_entries")[0]
    assert entry["officer_id"] == new["id"] and entry["applied"]["officer_id"] == new["id"]
    base = particulars.baseline("E1", person_id="P9")
    assert base["correspondence_address"]["line1"] == "Room 1"


def test_a_change_writes_nothing_to_the_profile_and_moves_the_baseline(db):
    particulars.capture_before_edit(person_id="P1", user_id="U1")
    db.tables["persons"][0]["email"] = "new@example.com"
    items = particulars.pending_for_officer("E1", person_id="P1", capacity="director")
    change = {"id": "N4", "case_id": "K1", "kind": "change", "capacity": "director",
              "party_type": "individual", "person_id": "P1", "officer_id": "O1",
              "items": [{**i, "effective_date": "2026-09-25"} for i in items],
              "party": {"name": "CHAN Tai Man"}}
    entries = _entries(db, change)
    profile_before = [dict(p) for p in db.rows("persons")]
    _run(apply.apply_changes, CASE, entries)
    assert db.rows("persons") == profile_before
    assert particulars.pending_for_officer("E1", person_id="P1", capacity="director") == []


def test_a_partial_failure_is_reported_and_a_rerun_duplicates_nothing(db, monkeypatch):
    entries = _entries(db, CEASE_DIRECTOR, APPOINT)
    real = apply._apply_appointment
    monkeypatch.setattr(apply, "_apply_appointment",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("timeout")))
    out = _run(apply.apply_changes, CASE, entries)
    assert out["errors"] == ["HO New: timeout"] and len(out["applied"]) == 1
    assert not db.rows("nar1_cases")[0].get("changes_applied_at")
    monkeypatch.setattr(apply, "_apply_appointment", real)
    out = _run(apply.apply_changes, CASE, db.rows("officer_change_entries"))
    assert out["errors"] == [] and [a["entry_id"] for a in out["applied"]] == ["N3"]
    assert len([o for o in db.rows("entity_officers") if o.get("person_id") == "P9"]) == 1
    assert db.rows("nar1_cases")[0]["changes_applied_at"]


def test_an_appointment_failing_after_its_insert_is_recorded_and_finished_on_retry(db, monkeypatch):
    # The officer row went in, then the baseline write failed. The row must be
    # findable (Undo deletes it) and a retry must finish it, not insert again.
    entries = _entries(db, APPOINT)
    real = particulars.set_baseline
    monkeypatch.setattr(particulars, "set_baseline",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("timeout")))
    out = _run(apply.apply_changes, CASE, entries)
    assert out["errors"] == ["HO New: timeout"]
    entry = db.rows("officer_change_entries")[0]
    new = next(o for o in db.rows("entity_officers") if o.get("person_id") == "P9")
    assert entry["applied"] == {"officer_id": new["id"], "baseline_before": None, "partial": True}
    monkeypatch.setattr(particulars, "set_baseline", real)
    out = _run(apply.apply_changes, CASE, db.rows("officer_change_entries"))
    assert out["errors"] == [] and [a["entry_id"] for a in out["applied"]] == ["N3"]
    assert len([o for o in db.rows("entity_officers") if o.get("person_id") == "P9"]) == 1
    assert "partial" not in db.rows("officer_change_entries")[0]["applied"]
    assert particulars.baseline("E1", person_id="P9") is not None
    assert db.rows("nar1_cases")[0]["changes_applied_at"]


def test_a_re_appointment_files_todays_particulars_not_a_ceased_ones_baseline(db):
    # P9 was a director once, was edited (baseline captured), then ceased. The
    # baseline of that ended appointment is not what CR holds any more: the
    # ND2A re-appointing them filed their CURRENT particulars.
    db.tables["officer_cr_particulars"].append({
        "id": "B1", "entity_id": "E1", "person_id": "P9", "corporate_entity_id": None,
        "particulars": {"party_type": "individual",
                        "name_en": {"surname": "HO", "given_names": "Old"},
                        "email": "old@example.com", "correspondence_address": None}})
    entries = _entries(db, {**APPOINT, "correspondence_same_as_residential": True,
                            "correspondence_address": None})
    _run(apply.apply_changes, CASE, entries)
    base = particulars.baseline("E1", person_id="P9")
    assert base["name_en"]["given_names"] == "New" and base["email"] == "p9@example.com"
    assert particulars.pending_for_officer("E1", person_id="P9", capacity="director") == []


def test_a_second_appointment_keeps_the_baseline_cr_holds_for_the_first(db):
    # P1 is a sitting director with an unfiled change; appointing them secretary
    # too must not silently mark that change as told to CR.
    particulars.capture_before_edit(person_id="P1", user_id="U1")
    db.tables["persons"][0]["email"] = "new@example.com"
    entries = _entries(db, {**APPOINT, "id": "N5", "capacity": "company_secretary",
                            "person_id": "P1", "correspondence_same_as_residential": True,
                            "correspondence_address": None, "party": {"name": "CHAN Tai Man"}})
    _run(apply.apply_changes, CASE, entries)
    assert particulars.baseline("E1", person_id="P1")["email"] == "p1@example.com"


def test_undo_reverses_exactly_what_was_applied(db):
    entries = _entries(db, CEASE_DIRECTOR, CEASE_SECRETARY, APPOINT)
    _run(apply.apply_changes, CASE, entries)
    out = _run(apply.undo_changes, CASE, db.rows("officer_change_entries"))
    assert out["errors"] == [] and len(out["applied"]) == 3
    o1 = next(o for o in db.rows("entity_officers") if o["id"] == "O1")
    assert o1["is_current"] is True and o1["resigned_date"] is None
    assert db.rows("company_secretaries")[0]["is_current"] is True
    assert not any(o.get("person_id") == "P9" for o in db.rows("entity_officers"))
    assert particulars.baseline("E1", person_id="P9") is None
    assert all(e["applied"] is None for e in db.rows("officer_change_entries"))
    assert db.rows("nar1_cases")[0]["changes_undone_at"]
