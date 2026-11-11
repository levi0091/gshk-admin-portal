"""Who signs an ND2A that changes the company secretary (PROD feedback, 2026-11-12).

Jacqueline: Corpagent Online (HK) Limited ceases and Get Started HK Limited is
appointed, and page 3 printed "Corpagent Online (HK) Limited, Company
Secretary". The signer is now the secretary AFTER the form's changes, on the
form (`nd2a_mapper.after_changes`) and on the case screen (`cases._signatory_row`)
alike.
"""
from services.officer_changes import cases, nd2a_mapper, prepare
from services.officer_changes import secretaries_after as sa
from services.tpsi.forms import nar1_mapper as nm
from tests.officer_changes import cr_fixtures as fx
from tests.officer_changes.fakes import FakeSupabase

CORPAGENT = "Corpagent Online (HK) Limited"
GSHK = "Get Started HK Limited"


def _secretary_change():
    """The PROD case: one corporate secretary out, GSHK in."""
    graph, entries = fx.combined_world(
        "ND2A", ["Cease Corporate Secretary", "Appoint Corporate Secretary - BR"])
    leaving, joining = entries
    graph["entities"][leaving["corporate_entity_id"]].update(
        company_name=CORPAGENT, br_number="11111111")
    graph["entities"][joining["corporate_entity_id"]].update(
        company_name=GSHK, br_number=sa.GSHK_BR)
    leaving["officer_id"] = "O-CORP"
    graph["secretaries"] = [{"id": "S-CORP", "person_id": None, "secretary_name": CORPAGENT,
                             "is_current": True, "is_gshk": False,
                             "corporate_entity_id": leaving["corporate_entity_id"],
                             "corporate_br_no": "11111111"}]
    graph["officers"] = [{"id": "O-CORP", "role": "company_secretary",
                          "party_type": "corporate", "is_current": True,
                          "corporate_entity_id": leaving["corporate_entity_id"],
                          "corporate_name": CORPAGENT, "corporate_br_no": "11111111"}]
    return graph, entries


# -- the form ---------------------------------------------------------------------

def test_the_incoming_secretary_signs_the_form_not_the_one_it_ceases():
    graph, entries = _secretary_change()
    data = nd2a_mapper.map_case(graph, entries)
    assert data["selectPersonName"] == GSHK
    # The ceasing secretary is still on the form, as the officer who leaves.
    assert data["resCesBeans"][0]["corpEngName"] == CORPAGENT


def test_the_signers_br_is_the_incoming_secretarys():
    graph, entries = _secretary_change()
    after = nd2a_mapper.after_changes(graph, entries)
    assert nm._corporate_secretary_br(after) == sa.GSHK_BR
    assert nm._corporate_secretary_br(graph) == "11111111"  # the graph itself is untouched


def test_the_default_capacity_follows_the_incoming_signer():
    graph, entries = _secretary_change()
    after = nd2a_mapper.after_changes(graph, entries)
    assert prepare._capacity(after, {}) == prepare.default_capacity(is_corporate=True)


def test_a_form_that_does_not_touch_the_secretary_keeps_todays_signer():
    path = next(p for p in fx.files("ND2A") if "Cease Individual Director" in p.name)
    graph, entries = fx.build_world(path)
    assert nd2a_mapper.after_changes(graph, entries) is graph


def test_ceasing_the_only_secretary_with_no_successor_keeps_todays_signer():
    graph, entries = _secretary_change()
    after = nd2a_mapper.after_changes(graph, entries[:1])
    assert after is graph  # nobody left: today's signer, not an unsigned form
    assert nd2a_mapper.map_case(graph, entries[:1])["selectPersonName"] == CORPAGENT


def test_a_remaining_secretary_still_signs_when_another_is_ceased():
    graph, entries = _secretary_change()
    graph["secretaries"].insert(0, {"id": "S-GS", "person_id": None, "secretary_name": GSHK,
                                    "is_current": True, "is_gshk": True})
    after = nd2a_mapper.after_changes(graph, entries[:1])
    assert nm._derive_signatory(after)["name"] == GSHK


def test_a_natural_person_secretary_replaced_by_another():
    graph, entries = fx.combined_world(
        "ND2A", ["Cease Individual Secretary", "Appoint Individual Secretary"],
        renames={1: {"surname": "LEE", "given_names": "SIU MING", "full_name": "LEE SIU MING"}})
    leaving, joining = entries
    graph["persons"][leaving["person_id"]]["full_name"] = "CHAN TAI MAN"
    graph["secretaries"] = [{"id": "S-OLD", "person_id": leaving["person_id"],
                             "is_current": True, "is_gshk": False}]
    data = nd2a_mapper.map_case(graph, entries)
    assert data["selectPersonName"] == "LEE SIU MING"


# -- the case screen, and the signature pad ------------------------------------------

def _db(monkeypatch):
    fake = FakeSupabase({
        "company_secretaries": [{"id": "S-CORP", "entity_id": "E1", "person_id": None,
                                 "secretary_name": CORPAGENT, "is_current": True,
                                 "is_gshk": False}],
        "entity_officers": [{"id": "O-CORP", "entity_id": "E1", "role": "company_secretary",
                             "party_type": "corporate", "corporate_entity_id": "C-CORP",
                             "corporate_name": "CORPAG", "is_current": True}],
        "entities": [{"id": "C-CORP", "company_name": CORPAGENT, "br_number": "11111111"},
                     {"id": "C-GSHK", "company_name": GSHK, "br_number": sa.GSHK_BR},
                     {"id": "C-OTHER", "company_name": "Other Secretaries Limited",
                      "br_number": "22222222"}],
        "persons": [{"id": "P-NEW", "full_name": "LEE SIU MING"}],
    })
    monkeypatch.setattr(cases, "get_supabase", lambda: fake)
    return fake


CEASE_CORPAGENT = {"kind": "cessation", "capacity": "company_secretary",
                   "party_type": "corporate", "corporate_entity_id": "C-CORP",
                   "officer_id": "O-CORP"}
APPOINT_GSHK = {"kind": "appointment", "capacity": "company_secretary",
                "party_type": "corporate", "corporate_entity_id": "C-GSHK"}


def test_the_screen_names_the_incoming_secretary(monkeypatch):
    _db(monkeypatch)
    entries = [CEASE_CORPAGENT, APPOINT_GSHK]
    assert cases._signatory_row("E1", entries) == (GSHK, True, None)
    assert cases._signatory("E1", {}, entries)["name"] == GSHK
    assert cases._signatory_row("E1") == (CORPAGENT, True, None)  # no entries: today's


def test_the_screen_keeps_todays_signer_when_nobody_would_be_left(monkeypatch):
    _db(monkeypatch)
    assert cases._signatory_row("E1", [CEASE_CORPAGENT]) == (CORPAGENT, True, None)


def test_the_screen_puts_an_incoming_gshk_ahead_of_another_incoming_firm(monkeypatch):
    _db(monkeypatch)
    other = {**APPOINT_GSHK, "corporate_entity_id": "C-OTHER"}
    assert cases._signatory_row("E1", [CEASE_CORPAGENT, other, APPOINT_GSHK])[0] == GSHK


def test_an_incoming_natural_person_secretary_is_asked_to_sign(monkeypatch):
    _db(monkeypatch)
    entries = [CEASE_CORPAGENT, {"kind": "appointment", "capacity": "company_secretary",
                                 "party_type": "individual", "person_id": "P-NEW"}]
    assert cases.signatory_person_id("E1", entries) == "P-NEW"
    assert cases.signatory_person_id("E1") is None


def test_a_director_change_leaves_the_screens_signer_alone(monkeypatch):
    _db(monkeypatch)
    entries = [{"kind": "appointment", "capacity": "director", "person_id": "P-NEW"}]
    assert cases._signatory_row("E1", entries) == (CORPAGENT, True, None)
