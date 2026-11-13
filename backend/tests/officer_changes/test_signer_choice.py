"""Who signs an e-Signed ND2A: GSHK, or a director with their own e-Registry
account (Levi 2026-11-13)."""
import asyncio
import re

import pytest

from services.officer_changes import prepare, signer_choice as sc
from tests.officer_changes import cr_fixtures as fx
from tests.officer_changes.fakes import FakeSupabase

CASE = {"id": "K1", "entity_id": "E1", "form_code": "Nd2a"}
CEASE_SEC = {"id": "X1", "kind": "cessation", "capacity": "company_secretary",
             "corporate_entity_id": "C-OLD"}
APPOINT_SEC = {"id": "X2", "kind": "appointment", "capacity": "company_secretary",
               "corporate_entity_id": "C-GSHK"}
APPOINT_DIR = {"id": "X3", "kind": "appointment", "capacity": "director", "person_id": "P9"}


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase({
        "entity_officers": [
            {"id": "O1", "entity_id": "E1", "role": "director", "is_current": True,
             "person_id": "P1"},
            {"id": "O2", "entity_id": "E1", "role": "director", "is_current": True,
             "person_id": "P2"},
            {"id": "O3", "entity_id": "E1", "role": "director", "is_current": False,
             "person_id": "P3"},
            {"id": "O4", "entity_id": "E1", "role": "alternate_director", "is_current": True,
             "person_id": "P4"},
            {"id": "O5", "entity_id": "E1", "role": "director", "is_current": True,
             "corporate_entity_id": "C7"},
        ],
        "persons": [{"id": "P1", "full_name": "Ada CHAN"},
                    {"id": "P2", "full_name": "Ben LAU"}],
        "person_identity_documents": [],
        "person_eservice_credentials": [
            {"person_id": "P2", "eservice_user_id": "ER-BEN",
             "eservice_person_name": "LAU, BEN", "eservice_password_enc": "enc"}],
    })
    monkeypatch.setattr(sc, "get_supabase", lambda: fake)
    monkeypatch.setattr(sc.eservice, "get_supabase", lambda: fake)
    return fake


def test_candidates_are_current_natural_person_directors_ready_first(db):
    out = sc.candidates(CASE, [])
    assert [(c["person_id"], c["ready"]) for c in out] == [("P2", True), ("P1", False)]
    assert out[1]["reason"] == "e-Registry not set up"
    assert out[1]["profile_path"] == "/persons/P1"
    assert "enc" not in str(out)


def test_a_director_the_form_ceases_cannot_sign(db):
    leaving = {"id": "X9", "kind": "cessation", "capacity": "director", "officer_id": "O2",
               "person_id": "P2"}
    assert [c["person_id"] for c in sc.candidates(CASE, [leaving])] == ["P1"]


def test_a_secretary_change_defaults_to_the_ready_director(db):
    choice = sc.resolve(CASE, [CEASE_SEC, APPOINT_SEC])
    assert choice["party"] == "director" and choice["default"] == "director"
    assert choice["director"]["person_id"] == "P2" and not choice["stored"]


def test_without_a_secretary_change_gshk_signs_and_nothing_is_read(monkeypatch):
    monkeypatch.setattr(sc, "get_supabase", lambda: pytest.fail("read the database"))
    choice = sc.resolve(CASE, [APPOINT_DIR])
    assert choice["party"] == "gshk" and choice["candidates"] is None


def test_a_secretary_change_with_no_ready_director_stays_with_gshk(db):
    db.tables["person_eservice_credentials"].clear()
    assert sc.resolve(CASE, [CEASE_SEC])["party"] == "gshk"


def test_a_stored_choice_beats_the_default(db):
    assert sc.resolve({**CASE, "signing_party": "gshk"}, [CEASE_SEC])["party"] == "gshk"
    choice = sc.resolve({**CASE, "signing_party": "director",
                         "signing_director_person_id": "P2"}, [APPOINT_DIR])
    assert choice["party"] == "director" and choice["director"]["person_id"] == "P2"


def test_a_stored_director_who_can_no_longer_sign_is_not_swapped_for_another(db):
    choice = sc.resolve({**CASE, "signing_party": "director",
                         "signing_director_person_id": "P1"}, [])
    assert choice["party"] == "director" and choice["director"] is None


def test_nd2b_never_offers_the_choice(monkeypatch):
    monkeypatch.setattr(sc, "get_supabase", lambda: pytest.fail("read the database"))
    case = {**CASE, "form_code": "Nd2b", "signing_party": "director"}
    assert sc.resolve(case, [CEASE_SEC])["party"] == "gshk"
    assert sc.for_sign(case) is None
    assert sc.view(case, [], staff_account=None, gshk_signatory={}) == {"offered": False}


def test_validation_pins_the_party_or_refuses(db):
    assert sc.pinned_for_validation(CASE, [CEASE_SEC]) == {
        "signing_party": "director", "signing_director_person_id": "P2"}
    assert sc.pinned_for_validation(CASE, [APPOINT_DIR]) == {
        "signing_party": "gshk", "signing_director_person_id": None}
    with pytest.raises(sc.SignerUnavailable):
        sc.pinned_for_validation({**CASE, "signing_party": "director",
                                  "signing_director_person_id": "P1"}, [])


def test_signing_reads_only_the_stored_party():
    # Never the default: the validated XML names whoever was pinned.
    assert sc.for_sign(CASE) is None
    assert sc.for_sign({**CASE, "signing_party": "director",
                        "signing_director_person_id": "P2"}) == "P2"


def test_the_view_carries_both_options(db):
    out = sc.view(CASE, [CEASE_SEC], staff_account="STAFF-1",
                  gshk_signatory={"name": "Get Started HK Limited",
                                  "default_capacity": "Director of the Company Secretary "
                                                      "(Body Corporate)"})
    assert out["offered"] and out["party"] == "director" and out["changes_secretary"]
    assert out["director_person_id"] == "P2" and out["director_ready"]
    assert out["gshk"] == {"signs_for": "Get Started HK Limited",
                           "capacity": "Director of the Company Secretary (Body Corporate)",
                           "eservice_user_id": "STAFF-1"}


def test_the_form_names_the_director_as_their_account_does():
    signer = sc.form_signatory({"name": "Ben LAU", "eservice_person_name": "LAU, BEN",
                                "eservice_user_id": "ER-BEN"})
    assert signer == {"name": "LAU, BEN", "capacity": "Director", "person_id": "ER-BEN",
                      "is_corporate": False, "date": None}


# -- the XML ---------------------------------------------------------------------------

def _world(monkeypatch, ready: bool):
    path = next(p for p in fx.files("ND2A") if "Cease Corporate Secretary" in p.name)
    graph, entries = fx.build_world(path)

    async def load(entity_id, entries_):
        return graph

    monkeypatch.setattr(prepare.source, "load_graph", load)
    monkeypatch.setattr(prepare.signer_choice, "candidates", lambda case, entries_: [
        {"person_id": "P2", "name": "Ben LAU", "eservice_user_id": "ER-BEN",
         "eservice_person_name": "LAU, BEN", "ready": ready,
         "reason": None if ready else "e-Registry not set up"}])
    return entries


def _form_level(xml: str, tag: str) -> list[str]:
    # The form-level block follows the beans; consents carry their own ids.
    tail = xml.rsplit("</cr:resCesBeans>", 1)[-1]
    return re.findall(rf"<cr:{tag}>([^<]*)</cr:{tag}>", tail)


def test_a_director_signed_form_names_the_directors_account(monkeypatch):
    entries = _world(monkeypatch, ready=True)
    xml = asyncio.run(prepare.build_form_xml(CASE, entries, for_esign=True,
                                             signing_identity={"eservice_user_id": "STAFF-1",
                                                               "person_name": "STAFF ONE"}))
    assert _form_level(xml, "selectPersonId") == ["ER-BEN"]
    assert _form_level(xml, "selectPersonName") == ["LAU, BEN"]
    assert _form_level(xml, "selectCapacityDesc") == ["Director"]
    # Not the body-corporate scheme: no staff member signs for GSHK Ltd.
    assert "selectAssoBrNo" not in xml and "STAFF-1" not in xml


def test_a_gshk_choice_keeps_the_secretarys_block(monkeypatch):
    entries = _world(monkeypatch, ready=True)
    xml = asyncio.run(prepare.build_form_xml({**CASE, "signing_party": "gshk"}, entries,
                                             signing_identity={"eservice_user_id": "STAFF-1",
                                                               "person_name": "STAFF ONE"}))
    assert "ER-BEN" not in xml


def test_the_manual_route_never_uses_the_director(monkeypatch):
    entries = _world(monkeypatch, ready=True)
    xml = asyncio.run(prepare.build_form_xml({**CASE, "signing_method": "manual"}, entries))
    assert "ER-BEN" not in xml


def test_a_chosen_director_who_cannot_sign_stops_esign_but_not_the_preview(monkeypatch):
    entries = _world(monkeypatch, ready=False)
    case = {**CASE, "signing_party": "director", "signing_director_person_id": "P2"}
    with pytest.raises(prepare.MappingError) as exc:
        asyncio.run(prepare.build_form_xml(case, entries, for_esign=True))
    assert "choose GSHK e-Service at Signing" in str(exc.value.problems)
    assert "ER-BEN" not in asyncio.run(prepare.build_form_xml(case, entries))
