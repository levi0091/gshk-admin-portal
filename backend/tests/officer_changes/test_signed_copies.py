"""`signed_copies.for_form` — turning "who drew what" into the renderer's argument
(e-signature-nd2, ticket 02). The renderers find boxes by the names a page prints,
so this is where a person id becomes a name exactly as `nd2a_mapper` prints it."""
import base64

import pytest

from services import nar1_approvals
from services.officer_change_form import stamp
from services.officer_changes import cases, signatures, signed_copies
from tests.officer_changes.fakes import FakeSupabase

PNG = b"\x89PNG\r\n\x1a\nfake-but-opaque-to-this-module"


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase({
        "persons": [
            {"id": "P1", "full_name": "CHAN, TAI MAN", "surname": "CHAN",
             "given_names": "TAI MAN"},
            {"id": "P2", "full_name": "WONG SIU MING", "surname": "WONG",
             "given_names": "SIU MING"},
            {"id": "P3", "full_name": "HO KA YAN", "surname": "HO", "given_names": "KA YAN"},
            {"id": "P4", "full_name": "WONG SIU MING", "surname": "WONG",
             "given_names": "SIU MING"},
        ],
        "entities": [{"id": "GSHK", "company_name": "Get Started HK Limited"}],
        "entity_officers": [
            {"id": "O9", "entity_id": "E1", "corporate_entity_id": "GSHK",
             "role": "company_secretary", "party_type": "corporate", "is_current": True}],
        "company_secretaries": [],
        "officer_change_entries": [],
        "officer_change_signatures": [],
        "nar1_client_approvals": [],
    })
    for module in (cases, signatures, nar1_approvals):
        monkeypatch.setattr(module, "get_supabase", lambda: fake)
    return fake


def _case(form="Nd2a", **over):
    return {"id": "C1", "entity_id": "E1", "form_code": form, "client_approved": True,
            "verification_revision": 1, **over}


def _signed(db, *people):
    for n, person in enumerate(people):
        db.tables["officer_change_signatures"].append(
            {"id": f"S{n}", "case_id": "C1", "approval_id": f"A{n}", "person_id": person,
             "revision": 1, "image_b64": base64.b64encode(PNG).decode()})


def _entry(db, capacity, person, kind="appointment"):
    db.tables["officer_change_entries"].append(
        {"id": f"N{len(db.tables['officer_change_entries'])}", "case_id": "C1", "kind": kind,
         "capacity": capacity, "person_id": person})


def test_nothing_signed_means_nothing_to_print(db):
    _entry(db, "director", "P1")
    assert signed_copies.for_form(_case()) is None


def test_an_unapproved_case_prints_nothing_even_if_a_picture_exists(db):
    _entry(db, "director", "P1")
    _signed(db, "P1")
    assert signed_copies.for_form(_case(client_approved=False)) is None


def test_an_incoming_directors_picture_is_keyed_by_the_names_the_form_prints(db):
    _entry(db, "director", "P1")
    _signed(db, "P1")
    result = signed_copies.for_form(_case())
    assert result.consents == {("chan", "tai man"): PNG}
    assert result.signatory is None


def test_only_directors_who_signed_are_included(db):
    _entry(db, "director", "P1")
    _entry(db, "director", "P2")           # appointed but did not sign
    _entry(db, "company_secretary", "P3")  # a secretary's picture has no consent box
    _signed(db, "P1", "P3")
    assert set(signed_copies.for_form(_case()).consents) == {("chan", "tai man")}


def test_two_directors_who_print_as_the_same_name_are_not_told_apart(db):
    _entry(db, "director", "P2")
    _entry(db, "director", "P4")
    _signed(db, "P2", "P4")
    assert signed_copies.for_form(_case()) is None


def test_a_same_named_director_who_did_not_sign_still_blocks_the_name(db):
    """P2 signed, P4 did not, and both print as WONG SIU MING. Keyed by name,
    P2's picture would match P4's consent box as well — one director's
    signature on another's consent in a statutory copy. Neither is printed."""
    _entry(db, "director", "P2")
    _entry(db, "director", "P4")
    _signed(db, "P2")
    assert signed_copies.for_form(_case()) is None


def test_a_natural_person_signatory_who_signed_gets_the_page_3_box(db):
    db.tables["company_secretaries"].append(
        {"id": "S1", "entity_id": "E1", "is_gshk": False, "is_current": True,
         "person_id": "P1", "secretary_name": None})
    _signed(db, "P1")
    for form in ("Nd2a", "Nd2b"):
        result = signed_copies.for_form(_case(form))
        assert result.signatory == ("CHAN, TAI MAN", PNG), form


def test_a_body_corporate_secretary_leaves_page_3_blank(db):
    """GSHK Ltd signs for nearly every client: no natural person, no stamp."""
    _entry(db, "director", "P1")
    _signed(db, "P1")
    assert signed_copies.for_form(_case()).signatory is None


def test_an_nd2b_has_no_consent_boxes(db):
    _entry(db, "director", "P1")
    _signed(db, "P1")
    assert signed_copies.for_form(_case("Nd2b")) is None


def test_for_form_never_raises(monkeypatch):
    def boom():
        raise RuntimeError("database is down")
    monkeypatch.setattr(signatures, "get_supabase", boom)
    monkeypatch.setattr(cases, "get_supabase", boom)
    assert signed_copies.for_form(_case()) is None


def test_the_result_is_what_the_renderer_takes(db):
    _entry(db, "director", "P1")
    _signed(db, "P1")
    assert isinstance(signed_copies.for_form(_case()), stamp.Signatures)
