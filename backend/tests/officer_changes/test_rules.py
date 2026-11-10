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


def test_a_future_date_reminds_but_does_not_stop_the_send():
    """Levi 2026-10-30: the form and resolution go to the client early on
    purpose. The reminder names the day it can be filed."""
    result = run([appoint(person="P9", when="2026-10-05")])
    c = check(result, "no_future_dates")
    assert c["ok"] is False and c["level"] == "reminder" and result["blocking"] is False
    assert "05 Oct 2026" in c["text"]


def test_filing_opens_on_the_latest_future_date():
    entries = [{"kind": "cessation", "effective_date": "2026-10-05"},
               {"kind": "appointment", "effective_date": "2026-11-01"}]
    assert rules.filing_opens_on(entries, TODAY) == date(2026, 11, 1)


def test_filing_is_open_when_nothing_is_ahead():
    entries = [{"kind": "cessation", "effective_date": TODAY.isoformat()},
               {"kind": "appointment", "effective_date": None}]
    assert rules.filing_opens_on(entries, TODAY) is None


def test_an_omitted_nd2b_line_does_not_hold_up_the_filing():
    items = [{"key": "a", "effective_date": "2030-01-01", "omitted": True},
             {"key": "b", "effective_date": "2026-11-01"}]
    assert rules.filing_opens_on([{"kind": "change", "items": items}], TODAY) == date(2026, 11, 1)


def test_a_missing_date_no_longer_blocks_sending():
    """Jacqueline A1: clients let GSHK fill in the most recent date, so the
    draft may go out undated; the date is required at Signing instead."""
    result = run([appoint(person="P9", when=None)])
    c = check(result, "dates_present")
    assert c["ok"] is False and c["level"] == "notice" and result["blocking"] is False


def _named(o, name):
    return {**o, "name": name}


def test_three_lines_name_the_board():
    """Jacqueline A6: three lines are enough for the team."""
    board = [_named(officer("O1", "director", person="P1"), "CHAN Tai Man"),
             _named(officer("O3", "company_secretary", corp="GSHK"), "Get Started HK Limited")]
    r = rules.evaluate(board, [appoint(person="P9", name="LEE Ka Ho")], company=PRIVATE,
                       today=TODAY)
    assert r["lines"] == [
        "After these changes the company will have 2 directors (2 natural persons) "
        "and 1 secretary.",
        "Directors: CHAN Tai Man and LEE Ka Ho.",
        "A company secretary remains — Get Started HK Limited."]


def test_three_or_more_directors_are_listed_with_commas():
    board = [_named(officer("O1", "director", person="P1"), "A"),
             _named(officer("O2", "director", person="P2"), "B"),
             _named(officer("O3", "company_secretary", corp="GSHK"), "G")]
    r = rules.evaluate(board, [appoint(person="P9", name="C")], company=PRIVATE, today=TODAY)
    assert r["lines"][1] == "Directors: A, B and C."


def test_no_director_left_is_visible_in_the_board():
    board = [_named(o, o["officer_id"]) for o in BOARD]
    r = rules.evaluate(board, [cease("O1", person="P1"), cease("O2", person="P2")],
                       company=PRIVATE, today=TODAY)
    assert r["board"]["directors"] == []
    assert r["lines"][1] == "No director would remain."


def test_secretary_line_when_appointed_on_this_form():
    board = [_named(officer("O1", "director", person="P1"), "CHAN Tai Man"),
             _named(officer("O3", "company_secretary", corp="GSHK"), "Old Sec Ltd")]
    r = rules.evaluate(board, [cease("O3", corp="GSHK", capacity="company_secretary"),
                               appoint(corp="NEW", capacity="company_secretary",
                                       name="New Sec Ltd")],
                       company=PRIVATE, today=TODAY)
    assert r["lines"][2] == "Company secretary: New Sec Ltd (appointed on this form)."
    assert r["board"]["secretaries"] == [{"name": "New Sec Ltd", "new": True}]


def test_secretary_line_when_none_remains():
    board = [_named(officer("O1", "director", person="P1"), "CHAN Tai Man"),
             _named(officer("O3", "company_secretary", corp="GSHK"), "G")]
    r = rules.evaluate(board, [cease("O3", corp="GSHK", capacity="company_secretary")],
                       company=PRIVATE, today=TODAY)
    assert r["lines"][2] == "No company secretary would remain."


def test_dates_missing_lists_undated_changes():
    entries = [appoint(person="P9", when=None, name="LEE Ka Ho"),
               cease("O1", person="P1"),
               {"kind": "change", "party": {"name": "CHAN Tai Man"}, "items": [
                   {"key": "email", "label": "Email address", "effective_date": None},
                   {"key": "alias", "label": "Alias", "effective_date": None,
                    "omitted": True}]}]
    assert rules.dates_missing(entries) == ["LEE Ka Ho", "CHAN Tai Man — Email address"]


def test_an_officer_with_no_identity_document_blocks_the_send():
    # Jacqueline 2026-11-04: "Address and ID number must be included in the
    # form before it is sent out ... 'not all met'".
    result = run([appoint(person="P9", name="JACJAC Test", hkid="", passport=None)])
    c = check(result, "identity_document")
    assert c["ok"] is False and c["level"] == "rule" and result["blocking"] is True
    assert "JACJAC Test" in c["text"] and "NIL" in c["text"]


def test_a_passport_alone_is_an_identity_document():
    result = run([appoint(person="P9", hkid="", passport={"number": "P123", "issuing_country": "AU"})])
    assert check(result, "identity_document")["ok"] is True
    assert result["blocking"] is False


def test_a_body_corporate_needs_no_identity_document():
    result = run([appoint(corp="C9", capacity="company_secretary", hkid="")])
    assert check(result, "identity_document")["ok"] is True


def test_an_officer_with_no_residential_address_blocks_the_send():
    result = run([appoint(person="P9", name="LEE Ka Ho", residential_address=None)])
    c = check(result, "address_present")
    assert c["ok"] is False and c["level"] == "rule" and result["blocking"] is True
    assert "LEE Ka Ho" in c["text"]


def test_an_address_needs_a_line_and_a_country():
    result = run([appoint(person="P9", residential_address={"line1": "", "country": "HK"})])
    assert check(result, "address_present")["ok"] is False
    result = run([appoint(person="P9", residential_address={"line1": "Flat A", "country": ""})])
    assert check(result, "address_present")["ok"] is False


def test_a_separate_correspondence_address_must_be_given():
    entry = appoint(person="P9")
    entry["correspondence_same_as_residential"] = False
    entry["correspondence_address"] = None
    assert check(run([entry]), "address_present")["ok"] is False
    entry["correspondence_address"] = HK_HOME
    assert check(run([entry]), "address_present")["ok"] is True


def test_a_body_corporate_with_no_address_blocks_the_send():
    result = run([appoint(corp="C9", capacity="director", address=None)])
    assert check(result, "address_present")["ok"] is False
    assert result["blocking"] is True


def _nd2b(*items, registered=None):
    return {"kind": "change", "capacity": "director", "party_type": "individual",
            "person_id": "P1", "party": {"name": "Jacqueline Koh"},
            "registered": registered or {"hkid": "", "passport": None},
            "items": [{"effective_date": "2026-09-20", "omitted": False, **i}
                      for i in items]}


def test_nd2b_passport_changed_to_nothing_blocks_the_send():
    # ND2B-2026-0013 on DEV: (h) Passport 12345678 (BD) -> nothing, no HKID,
    # and CR's form printed "-" in both boxes.
    result = run([_nd2b({"key": "passport", "label": "Passport", "new": None,
                         "old": {"number": "12345678", "issuing_country": "BD"}},
                        registered={"hkid": "",
                                    "passport": {"number": "12345678", "issuing_country": "BD"}})])
    c = check(result, "change_values_present")
    assert c["ok"] is False and c["level"] == "rule" and result["blocking"] is True
    assert "Jacqueline Koh" in c["text"] and "no HKID or passport" in c["text"]


def test_nd2b_hkid_given_up_for_a_passport_is_fileable():
    # Review B1: the mapper files the cleared HKID as NIL, which CR accepts.
    result = run([_nd2b({"key": "hkid", "label": "HKID", "new": ""},
                        {"key": "passport", "label": "Passport",
                         "new": {"number": "X123", "issuing_country": "GB"}},
                        registered={"hkid": "A1234563", "passport": None})])
    assert check(result, "change_values_present")["ok"] is True
    assert result["blocking"] is False


def test_nd2b_clearing_one_number_while_cr_holds_the_other_is_fileable():
    result = run([_nd2b({"key": "passport", "label": "Passport", "new": None},
                        registered={"hkid": "A1234563",
                                    "passport": {"number": "P1", "issuing_country": "AU"}})])
    assert check(result, "change_values_present")["ok"] is True


def test_nd2b_empty_hkid_or_address_blocks_but_an_omitted_line_does_not():
    assert run([_nd2b({"key": "hkid", "label": "HKID", "new": ""},
                      registered={"hkid": "A1234563", "passport": None})])["blocking"] is True
    assert run([_nd2b({"key": "residential_address", "label": "Residential address",
                       "new": None})])["blocking"] is True
    omitted = _nd2b({"key": "passport", "label": "Passport", "new": None},
                    registered={"hkid": "", "passport": {"number": "P1"}})
    omitted["items"][0]["omitted"] = True
    omitted["items"].append({"key": "email", "effective_date": "2026-09-20",
                             "omitted": False, "new": "a@b.com"})
    assert check(run([omitted]), "change_values_present")["ok"] is True


def test_an_address_of_building_and_street_with_a_country_is_enough():
    # Review S1: CR makes only the country mandatory in its address blocks.
    result = run([appoint(person="P9", residential_address={
        "line1": "", "line2": "World Trust Tower", "line3": "50 Stanley Street",
        "country": "HK"})])
    assert check(result, "address_present")["ok"] is True


def test_a_secretary_with_a_separate_correspondence_address_needs_no_residential():
    entry = appoint(person="P9", capacity="company_secretary", residential_address=None)
    entry["correspondence_same_as_residential"] = False
    entry["correspondence_address"] = HK_HOME
    assert check(run([entry]), "address_present")["ok"] is True


def test_nd2b_with_a_real_new_passport_passes():
    result = run([_nd2b({"key": "passport", "label": "Passport",
                         "new": {"number": "P7751249A", "issuing_country": "AU"}})])
    assert check(result, "change_values_present")["ok"] is True
    assert result["blocking"] is False


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


def test_an_alternate_to_name_longer_than_cr_allows_blocks_the_send():
    # Review S2: CR's ND2A `altTo` is String(15); the mapper refuses a longer
    # name, so the rules panel must say so before the client is asked.
    entry = appoint(person="P9", capacity="alternate_director")
    entry["alternate_to_officer_id"] = "O1"
    entry["alternate_to_name"] = "LEE Chi Wai David"
    result = run([entry])
    c = check(result, "alternate_to_length")
    assert c["ok"] is False and c["level"] == "rule" and result["blocking"] is True
    entry["alternate_to_name"] = "CHAN Tai Man"
    assert not any(c["code"] == "alternate_to_length" for c in run([entry])["checks"])
