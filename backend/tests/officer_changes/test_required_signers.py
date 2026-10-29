"""`signatures.required_signers`: the list form of `must_sign` (nd2-multi-signer,
spec 2.2 and test group 2).

`must_sign` answers "is THIS person asked to sign?"; the multi-signer mode needs
the whole list at once, to build one panel per director and to freeze the set a
round converges on. The two are separate code that must give one answer, so the
parity test below runs both over the same fixtures and fails if they ever
disagree about anybody.
"""
import pytest

from services import nar1_approvals
from services.officer_changes import cases, signatures
from tests.officer_changes.fakes import FakeSupabase

PEOPLE = ("P1", "P2", "P3", "P9", "PS", "NOBODY")


def _tables():
    return {
        "persons": [{"id": pid, "full_name": f"Name {pid}"}
                    for pid in ("P1", "P2", "P3", "P9", "PS")],
        "entities": [{"id": "GSHK", "company_name": "Get Started HK Limited"},
                     {"id": "E1", "company_name": "Kanenas Holding Limited"}],
        "entity_officers": [
            {"id": "O1", "entity_id": "E1", "person_id": "P1", "role": "director",
             "party_type": "individual", "is_current": True},
            {"id": "O2", "entity_id": "E1", "person_id": "P2", "role": "director",
             "party_type": "individual", "is_current": True},
            {"id": "OX", "entity_id": "E1", "person_id": "P9", "role": "director",
             "party_type": "individual", "is_current": False},
            {"id": "O3", "entity_id": "E1", "corporate_entity_id": "GSHK",
             "role": "company_secretary", "party_type": "corporate", "is_current": True},
        ],
        "company_secretaries": [],
        "officer_change_entries": [],
        "officer_change_signatures": [],
        "nar1_client_approvals": [],
    }


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase(_tables())
    for module in (cases, signatures, nar1_approvals):
        monkeypatch.setattr(module, "get_supabase", lambda: fake)
    return fake


def _case(form="Nd2a", **over):
    return {"id": "C1", "entity_id": "E1", "form_code": form, **over}


def _entry(db, kind, **cols):
    db.tables["officer_change_entries"].append(
        {"id": f"N{len(db.tables['officer_change_entries'])}", "case_id": "C1",
         "kind": kind, **cols})


def _by_person(case):
    return {s["person_id"]: s for s in signatures.required_signers(case)}


def _assert_parity(case):
    """`must_sign` and `required_signers` are the same rule, asked two ways."""
    listed = {s["person_id"] for s in signatures.required_signers(case)}
    for person in PEOPLE:
        assert signatures.must_sign(case, person) == (person in listed), person


# -- the rules ---------------------------------------------------------------------

def test_an_incoming_director_and_a_continuing_director_are_two_signers(db):
    _entry(db, "appointment", capacity="director", person_id="P3",
           party_type="individual")
    signers = _by_person(_case())
    assert set(signers) == {"P1", "P2", "P3"}
    assert signers["P3"]["roles"] == ["consent", "resolution"]
    assert signers["P1"]["roles"] == ["resolution"]
    assert signers["P3"]["name"] == "Name P3"
    _assert_parity(_case())


def test_incoming_one_stays_one_leaves_gives_the_consent_and_the_resolution_line(db):
    _entry(db, "appointment", capacity="director", person_id="P3",
           party_type="individual")
    _entry(db, "cessation", officer_id="O2", person_id="P2", party_type="individual")
    signers = _by_person(_case())
    assert set(signers) == {"P1", "P3"}
    assert "P2" not in signers
    _assert_parity(_case())


def test_a_person_under_more_than_one_rule_is_listed_once_with_every_role(db):
    db.tables["company_secretaries"].append(
        {"id": "S1", "entity_id": "E1", "is_gshk": False, "is_current": True,
         "person_id": "P1", "secretary_name": None})
    listed = signatures.required_signers(_case())
    assert [s["person_id"] for s in listed].count("P1") == 1
    assert _by_person(_case())["P1"]["roles"] == ["form", "resolution"]
    _assert_parity(_case())


def test_the_forms_signatory_comes_first(db):
    db.tables["company_secretaries"].append(
        {"id": "S1", "entity_id": "E1", "is_gshk": False, "is_current": True,
         "person_id": "P2", "secretary_name": None})
    assert signatures.required_signers(_case())[0]["person_id"] == "P2"


def test_a_body_corporate_director_never_appears(db):
    db.tables["entity_officers"].append(
        {"id": "O7", "entity_id": "E1", "corporate_entity_id": "GSHK",
         "role": "director", "party_type": "corporate", "is_current": True})
    ids = [s["person_id"] for s in signatures.required_signers(_case())]
    assert None not in ids
    assert set(ids) == {"P1", "P2"}
    _assert_parity(_case())


def test_an_incoming_secretary_is_not_a_signer(db):
    _entry(db, "appointment", capacity="company_secretary", person_id="P3",
           party_type="individual")
    assert "P3" not in _by_person(_case())
    _assert_parity(_case())


def test_a_director_who_leaves_and_a_former_director_are_not_signers(db):
    _entry(db, "cessation", officer_id="O2", person_id="P2", party_type="individual")
    ids = set(_by_person(_case()))
    assert "P2" not in ids and "P9" not in ids


def test_when_every_director_leaves_the_directors_before_sign(db):
    _entry(db, "cessation", officer_id="O1", person_id="P1", party_type="individual")
    _entry(db, "cessation", officer_id="O2", person_id="P2", party_type="individual")
    assert set(_by_person(_case())) == {"P1", "P2"}
    _assert_parity(_case())


def test_an_nd2b_with_a_corporate_signatory_has_nobody(db):
    _entry(db, "change", officer_id="O1", person_id="P1", party_type="individual")
    assert signatures.required_signers(_case("Nd2b")) == []
    _assert_parity(_case("Nd2b"))


def test_an_nd2b_with_a_director_as_signatory_has_that_one_person(db):
    db.tables["company_secretaries"].append(
        {"id": "S1", "entity_id": "E1", "is_gshk": False, "is_current": True,
         "person_id": "P1", "secretary_name": None})
    _entry(db, "appointment", capacity="director", person_id="P3")   # not an ND2B rule
    signers = signatures.required_signers(_case("Nd2b"))
    assert [(s["person_id"], s["roles"]) for s in signers] == [("P1", ["form"])]
    _assert_parity(_case("Nd2b"))


def test_a_signatory_who_is_not_a_director_is_not_a_signer(db):
    db.tables["company_secretaries"].append(
        {"id": "S1", "entity_id": "E1", "is_gshk": False, "is_current": True,
         "person_id": "PS", "secretary_name": None})
    assert "PS" not in _by_person(_case())
    _assert_parity(_case())


def test_each_signer_carries_exactly_the_three_keys(db):
    for signer in signatures.required_signers(_case()):
        assert set(signer) == {"person_id", "name", "roles"}


# -- never raises ------------------------------------------------------------------

def test_a_database_fault_gives_an_empty_list_and_a_stderr_line(monkeypatch, capsys):
    def boom():
        raise RuntimeError("database is down")
    monkeypatch.setattr(cases, "get_supabase", boom)
    monkeypatch.setattr(signatures, "get_supabase", boom)
    assert signatures.required_signers(_case()) == []
    assert "required_signers failed" in capsys.readouterr().err


def test_a_case_with_no_entity_gives_an_empty_list(db, capsys):
    assert signatures.required_signers({"id": "C1", "form_code": "Nd2a"}) == []
    assert "required_signers failed" in capsys.readouterr().err
