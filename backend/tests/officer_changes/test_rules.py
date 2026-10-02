"""Company rules an officer change must not breach (PRD §4, E-2 … E-14)."""
from datetime import date

from services.officer_changes import rules

TODAY = date(2026, 9, 30)
PRIVATE = {"company_type": "P"}
HK_HOME = {"line1": "Flat A", "city": "CENTRAL", "country": "HK"}
UK_HOME = {"line1": "1 High St", "city": "London", "country": "GB"}


def officer(oid, role, person=None, corp=None):
    return {"officer_id": oid, "role": role,
            "party_type": "individual" if person else "corporate",
            "person_id": person, "corporate_entity_id": corp, "name": oid}


BOARD = [officer("O1", "director", person="P1"),
         officer("O2", "director", person="P2"),
         officer("O3", "company_secretary", corp="GSHK")]


def cease(oid, person=None, corp=None, capacity="director", when="2026-09-28"):
    return {"kind": "cessation", "officer_id": oid, "capacity": capacity,
            "party_type": "individual" if person else "corporate",
            "person_id": person, "corporate_entity_id": corp,
            "effective_date": when, "cessation_reason": "R" if person else None}


def appoint(person=None, corp=None, capacity="director", when="2026-09-28", **party):
    entry = {"kind": "appointment", "capacity": capacity,
             "party_type": "individual" if person else "corporate",
             "person_id": person, "corporate_entity_id": corp, "effective_date": when,
             "correspondence_same_as_residential": True,
             "correspondence_address": None, "section5_confirmed": False,
             "party": {"date_of_birth": "1980-01-01", "residential_address": HK_HOME,
                       "address": HK_HOME, "hkid": "A1234563", "passport": None,
                       **party}}
    return entry


def run(entries, officers=BOARD, company=PRIVATE, deadline=None):
    return rules.evaluate(officers, entries, company=company, today=TODAY,
                          deadline=deadline)


def check(result, code):
    return next(c for c in result["checks"] if c["code"] == code)


def test_a_clean_change_passes_and_summarises_the_board():
    result = run([appoint(person="P9")])
    assert result["blocking"] is False
    assert result["summary"] == ("After these changes the company will have 3 directors "
                                 "(3 natural persons) and 1 secretary.")
    assert all(c["ok"] for c in result["checks"] if c["level"] == "rule")


def test_an_empty_case_cannot_be_sent():
    result = run([])
    assert result["blocking"] is True and check(result, "has_changes")["ok"] is False


def test_losing_the_last_natural_person_director_blocks():
    result = run([cease("O1", person="P1"), cease("O2", person="P2"),
                  appoint(corp="C9", consent_person_id="P5")])
    assert check(result, "natural_director")["ok"] is False
    assert result["blocking"] is True


def test_a_public_company_needs_two_directors():
    result = run([cease("O1", person="P1")], company={"company_type": "N"})
    assert check(result, "two_directors")["ok"] is False


def test_losing_the_only_secretary_blocks():
    result = run([cease("O3", corp="GSHK", capacity="company_secretary")])
    assert check(result, "has_secretary")["ok"] is False


def test_a_sole_director_may_not_also_be_the_secretary():
    board = [officer("O1", "director", person="P1"),
             officer("O3", "company_secretary", corp="GSHK")]
    result = run([cease("O3", corp="GSHK", capacity="company_secretary"),
                  appoint(person="P1", capacity="company_secretary",
                          section5_confirmed=True)], officers=board)
    assert check(result, "sole_director_not_secretary")["ok"] is False


def test_a_new_director_under_eighteen_blocks():
    result = run([appoint(person="P9", date_of_birth="2010-01-01")])
    assert check(result, "director_age")["ok"] is False and result["blocking"] is True


def test_a_new_director_with_no_date_of_birth_is_a_warning_only():
    result = run([appoint(person="P9", date_of_birth=None)])
    c = check(result, "director_age")
    assert c["ok"] is False and c["level"] == "notice"
    assert result["blocking"] is False


def test_a_natural_secretary_needs_a_hong_kong_address_and_section_5():
    entry = appoint(person="P9", capacity="company_secretary",
                    residential_address=UK_HOME)
    result = run([entry])
    assert check(result, "secretary_hong_kong")["ok"] is False
    entry["correspondence_same_as_residential"] = False
    entry["correspondence_address"] = HK_HOME
    assert check(run([entry]), "secretary_hong_kong")["ok"] is False  # no section 5 yet
    entry["section5_confirmed"] = True
    assert check(run([entry]), "secretary_hong_kong")["ok"] is True


def test_a_body_corporate_secretary_needs_a_hong_kong_office():
    result = run([appoint(corp="C9", capacity="company_secretary", address=UK_HOME)])
    assert check(result, "secretary_hong_kong")["ok"] is False


def test_future_dates_block():
    result = run([appoint(person="P9", when="2026-10-05")])
    assert check(result, "no_future_dates")["ok"] is False and result["blocking"]


def test_a_missing_date_blocks():
    result = run([appoint(person="P9", when=None)])
    assert check(result, "dates_present")["ok"] is False


def test_an_officer_with_no_identity_document_is_a_warning():
    result = run([appoint(person="P9", hkid="", passport=None)])
    c = check(result, "identity_document")
    assert c["ok"] is False and c["level"] == "notice" and result["blocking"] is False


def test_an_overdue_case_is_a_notice_not_a_block():
    result = run([appoint(person="P9")], deadline=date(2026, 9, 29))
    c = check(result, "deadline")
    assert c["ok"] is False and c["level"] == "notice" and result["blocking"] is False


def test_nd2b_needs_a_date_on_every_line_it_files():
    entry = {"kind": "change", "capacity": "director", "party_type": "individual",
             "person_id": "P1", "items": [
                 {"key": "email", "effective_date": None, "omitted": False},
                 {"key": "alias", "effective_date": None, "omitted": True}]}
    result = run([entry])
    assert check(result, "dates_present")["ok"] is False
    entry["items"][0]["effective_date"] = "2026-09-20"
    assert run([entry])["blocking"] is False


def test_nd2b_is_not_held_up_by_a_board_that_already_breaches_a_rule():
    entry = {"kind": "change", "capacity": "director", "party_type": "individual",
             "person_id": "P1",
             "items": [{"key": "email", "effective_date": "2026-09-20", "omitted": False}]}
    no_secretary = [officer("O1", "director", person="P1")]
    result = run([entry], officers=no_secretary)
    assert result["blocking"] is False
    assert not any(c["code"] == "has_secretary" for c in result["checks"])


def test_nd2b_with_every_line_omitted_has_nothing_to_file():
    entry = {"kind": "change", "capacity": "director", "party_type": "individual",
             "person_id": "P1",
             "items": [{"key": "email", "effective_date": "2026-09-20", "omitted": True}]}
    assert check(run([entry]), "has_changes")["ok"] is False
