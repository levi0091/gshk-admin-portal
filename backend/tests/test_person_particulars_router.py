"""A person's identification and addresses, per company (Levi 2026-10-05).

"maybe the residential address field can be a list of addresses now and
clicking on new button allows adding a new residential address. and in each
residential address in the list it shows which companies is using those
addresses. same design applied to correspondence address.. same for
identification".

Happy path, 401/403 and edge cases per route; an in-memory Supabase, nothing
reaches the network.
"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app
from tests.officer_changes.fakes import FakeSupabase

client = TestClient(app)
ADMIN = {"id": "admin-1", "display_name": "Levi Z.", "role_name": "super_admin",
         "role_id": "role-sa"}
REGULAR = {"id": "u-2", "display_name": "Staff", "role_name": "staff", "role_id": "role-x"}
H = {"Authorization": "Bearer tok"}
HOME = {"line1": "Flat A, 10/F", "line2": "Harbour View", "line3": "1 Queen's Road",
        "city": "CENTRAL", "country": "HK"}
NEW = {"line1": "Flat 20A", "line2": "Harbour Vista", "line3": "9 Model Road",
       "city": "WANCHAI", "country": "HK"}
PARIS = {"line1": "12 Rue de Rivoli", "city": "PARIS", "postal_code": "75001", "country": "FR"}


@pytest.fixture
def db():
    fake = FakeSupabase({
        "persons": [{"id": "P1", "full_name": "CHAN Tai Man", "residential_address_id": "A1",
                     "deleted_at": None, "email": "a@example.com"},
                    {"id": "P2", "full_name": "CHAN Siu Ming", "residential_address_id": "A1",
                     "deleted_at": None}],
        "addresses": [{"id": "A1", **HOME}, {"id": "A2", **PARIS},
                      {"id": "A3", "line1": "Room 1201", "line2": "Tower 2",
                       "line3": "8 Connaught Place", "city": "CENTRAL", "country": "HK"}],
        "person_addresses": [
            {"id": "PA1", "person_id": "P1", "address_id": "A1", "kind": "residential"},
            {"id": "PA2", "person_id": "P1", "address_id": "A2", "kind": "residential"},
            {"id": "PA3", "person_id": "P1", "address_id": "A3", "kind": "correspondence"},
            {"id": "PA9", "person_id": "P2", "address_id": "A1", "kind": "residential"}],
        "entities": [{"id": "E1", "company_name": "Kanenas Holding Limited"},
                     {"id": "E2", "company_name": "Second Limited"},
                     {"id": "E3", "company_name": "Not Hers Limited"}],
        "entity_officers": [
            {"id": "O1", "entity_id": "E1", "person_id": "P1", "role": "director",
             "is_current": True, "correspondence_address_id": "A3"},
            {"id": "O2", "entity_id": "E2", "person_id": "P1", "role": "director",
             "is_current": True, "residential_address_id": "A2",
             "identity_document_id": "D2"},
            {"id": "O9", "entity_id": "E3", "person_id": "P2", "role": "director",
             "is_current": True}],
        "person_identity_documents": [
            {"id": "D1", "person_id": "P1", "id_type": "passport", "id_number": "F1111111",
             "issuing_country": "FR", "is_primary": True},
            {"id": "D2", "person_id": "P1", "id_type": "passport", "id_number": "K7654321",
             "issuing_country": "US", "is_primary": False},
            {"id": "D9", "person_id": "P2", "id_type": "hkid", "id_number": "A1234563",
             "is_primary": True}],
        "officer_cr_particulars": [],
        "company_secretaries": [],
        "officer_change_entries": [],
        "nar1_cases": [],
    })
    with patch("routers.persons.get_supabase", return_value=fake), \
         patch("services.person_particulars.get_supabase", return_value=fake), \
         patch("services.officer_changes.particulars.get_supabase", return_value=fake):
        yield fake


@pytest.fixture
def admin():
    with patch("middleware.auth._resolve_user", return_value=ADMIN):
        yield


@pytest.fixture
def audit():
    with patch("routers.persons.log_event", new_callable=AsyncMock) as log:
        yield log


def _officer(db, oid):
    return next(o for o in db.tables["entity_officers"] if o["id"] == oid)


def _rows(audit):
    return [c.kwargs for c in audit.await_args_list]


# -- reading ------------------------------------------------------------------------

def test_the_book_lists_each_entry_with_the_companies_using_it(db, admin):
    resp = client.get("/persons/P1/particulars-by-company", headers=H)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert [(c["entity_id"], c["company_name"]) for c in data["companies"]] == [
        ("E1", "Kanenas Holding Limited"), ("E2", "Second Limited")]
    res = {r["address_id"]: r for r in data["residential"]}
    assert res["A1"]["is_default"] is True and res["A1"]["used_by"] == ["E1"]
    assert res["A2"]["is_default"] is False and res["A2"]["used_by"] == ["E2"]
    assert res["A2"]["address"]["city"] == "PARIS"
    assert [r["address_id"] for r in data["residential"]][0] == "A1"  # default first
    corr = {r["address_id"]: r for r in data["correspondence"]}
    assert corr["A3"]["used_by"] == ["E1"]
    assert data["correspondence_same_as_residential"] == ["E2"]
    ids = {d["document_id"]: d for d in data["identity"]}
    assert ids["D1"]["used_by"] == ["E1"] and ids["D2"]["used_by"] == ["E2"]
    assert ids["D1"]["is_primary"] is True


def test_an_address_set_by_an_older_route_still_appears(db, admin):
    """The book is the union of what is recorded and what is in use: an address
    written by `PUT /residential-address` before the book existed is listed."""
    db.tables["person_addresses"] = []
    data = client.get("/persons/P1/particulars-by-company", headers=H).json()
    assert {r["address_id"] for r in data["residential"]} == {"A1", "A2"}
    assert {r["address_id"] for r in data["correspondence"]} == {"A3"}


# -- adding -------------------------------------------------------------------------

def test_a_new_residential_address_links_the_chosen_companies_and_captures_first(db, admin, audit):
    order = []
    real = __import__("services.officer_changes.particulars", fromlist=["x"]).capture_before_edit
    with patch("services.person_particulars.particulars.capture_before_edit",
               side_effect=lambda **k: order.append("capture") or real(**k)):
        resp = client.post("/persons/P1/addresses", headers=H,
                           json={"kind": "residential", **NEW, "entity_ids": ["E1"]})
    assert resp.status_code == 201, resp.text
    new_id = _officer(db, "O1")["residential_address_id"]
    assert new_id and new_id not in ("A1", "A2", "A3")
    assert order == ["capture"]
    assert any(r["address_id"] == new_id and r["kind"] == "residential"
               for r in db.tables["person_addresses"])
    assert db.tables["persons"][0]["residential_address_id"] == "A1"  # default unchanged
    row = _rows(audit)[-1]
    assert row["action_type"] == "CASE_FIELD_UPDATED"
    assert row["metadata"]["field"] == "residential_address"
    assert row["metadata"]["entity_id"] == "E1"
    # The baseline was captured BEFORE the link: E1 now has a pending (d)/(e).
    pending = client.get("/persons/P1/particulars-changes", headers=H).json()["changes"]
    assert [c["entity_id"] for c in pending] == ["E1"]


def test_a_new_address_can_become_the_default(db, admin, audit):
    resp = client.post("/persons/P1/addresses", headers=H,
                       json={"kind": "residential", **NEW, "entity_ids": [],
                             "make_default": True})
    assert resp.status_code == 201, resp.text
    new_id = db.tables["persons"][0]["residential_address_id"]
    assert new_id not in ("A1", "A2")
    assert any(r["metadata"]["field"] == "default_residential_address" for r in _rows(audit))


def test_a_new_correspondence_address_for_a_company(db, admin, audit):
    resp = client.post("/persons/P1/addresses", headers=H,
                       json={"kind": "correspondence", **NEW, "entity_ids": ["E2"]})
    assert resp.status_code == 201, resp.text
    assert _officer(db, "O2")["correspondence_address_id"] not in (None, "A3")


def test_a_company_the_person_does_not_serve_is_refused(db, admin, audit):
    resp = client.post("/persons/P1/addresses", headers=H,
                       json={"kind": "residential", **NEW, "entity_ids": ["E3"]})
    assert resp.status_code == 422
    assert "Not Hers Limited" in resp.json()["detail"]["message"] or \
        "not a company" in resp.json()["detail"]["message"]
    assert audit.await_count == 0


def test_a_bad_kind_or_a_correspondence_default_is_refused(db, admin):
    assert client.post("/persons/P1/addresses", headers=H,
                       json={"kind": "holiday", **NEW}).status_code == 422
    assert client.post("/persons/P1/addresses", headers=H,
                       json={"kind": "correspondence", **NEW,
                             "make_default": True}).status_code == 422


def test_an_invalid_address_is_a_422(db, admin):
    resp = client.post("/persons/P1/addresses", headers=H,
                       json={"kind": "residential", "line1": "x" * 80, "country": "HK"})
    assert resp.status_code == 422


# -- correcting -----------------------------------------------------------------------

def test_correcting_an_address_moves_this_person_only(db, admin, audit):
    resp = client.put("/persons/P1/addresses/A1", headers=H, json={**HOME, "line1": "Flat B, 10/F"})
    assert resp.status_code == 200, resp.text
    p1, p2 = db.tables["persons"]
    assert p1["residential_address_id"] not in ("A1",) and p2["residential_address_id"] == "A1"
    assert any(r["person_id"] == "P1" and r["address_id"] == p1["residential_address_id"]
               for r in db.tables["person_addresses"])
    assert not any(r["person_id"] == "P1" and r["address_id"] == "A1"
                   for r in db.tables["person_addresses"])
    assert _rows(audit)[-1]["metadata"]["field"] == "address_corrected"


def test_correcting_an_address_not_in_the_book_is_404(db, admin):
    assert client.put("/persons/P1/addresses/NOPE", headers=H, json=HOME).status_code == 404


# -- which companies ---------------------------------------------------------------------

def test_choosing_companies_moves_one_and_releases_the_unlisted(db, admin, audit):
    resp = client.put("/persons/P1/addresses/A2/companies", headers=H,
                      json={"kind": "residential", "entity_ids": ["E1"]})
    assert resp.status_code == 200, resp.text
    assert _officer(db, "O1")["residential_address_id"] == "A2"
    assert _officer(db, "O2")["residential_address_id"] is None  # back to the default
    assert {r["metadata"]["entity_id"] for r in _rows(audit)} == {"E1", "E2"}


def test_choosing_correspondence_companies(db, admin, audit):
    resp = client.put("/persons/P1/addresses/A3/companies", headers=H,
                      json={"kind": "correspondence", "entity_ids": ["E2"]})
    assert resp.status_code == 200
    assert _officer(db, "O2")["correspondence_address_id"] == "A3"
    assert _officer(db, "O1")["correspondence_address_id"] is None  # same as residential


def test_nothing_changed_writes_no_audit_row(db, admin, audit):
    resp = client.put("/persons/P1/addresses/A2/companies", headers=H,
                      json={"kind": "residential", "entity_ids": ["E2"]})
    assert resp.status_code == 200 and audit.await_count == 0


# -- default and removal ---------------------------------------------------------------

def test_make_default(db, admin, audit):
    resp = client.post("/persons/P1/addresses/A2/default", headers=H)
    assert resp.status_code == 200
    assert db.tables["persons"][0]["residential_address_id"] == "A2"


def test_the_default_cannot_be_removed(db, admin):
    resp = client.delete("/persons/P1/addresses/A1?kind=residential", headers=H)
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "default"


def test_an_address_in_use_cannot_be_removed(db, admin):
    resp = client.delete("/persons/P1/addresses/A2?kind=residential", headers=H)
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "in_use"


def test_an_unused_address_is_removed_from_the_book(db, admin, audit):
    _officer(db, "O2")["residential_address_id"] = None
    resp = client.delete("/persons/P1/addresses/A2?kind=residential", headers=H)
    assert resp.status_code == 200, resp.text
    assert not any(r["address_id"] == "A2" for r in db.tables["person_addresses"])
    assert _rows(audit)[-1]["metadata"]["field"] == "address_removed"


# -- identification ------------------------------------------------------------------------

def test_a_document_is_linked_to_the_chosen_companies(db, admin, audit):
    resp = client.put("/persons/P1/identity-documents/D2/companies", headers=H,
                      json={"entity_ids": ["E1", "E2"]})
    assert resp.status_code == 200, resp.text
    assert _officer(db, "O1")["identity_document_id"] == "D2"
    assert [r["metadata"]["entity_id"] for r in _rows(audit)] == ["E1"]
    resp = client.put("/persons/P1/identity-documents/D2/companies", headers=H,
                      json={"entity_ids": []})
    assert _officer(db, "O1")["identity_document_id"] is None
    assert _officer(db, "O2")["identity_document_id"] is None


def test_another_persons_document_is_404(db, admin):
    resp = client.put("/persons/P1/identity-documents/D9/companies", headers=H,
                      json={"entity_ids": ["E1"]})
    assert resp.status_code == 404


# -- permissions -------------------------------------------------------------------------------

ROUTES = [
    ("get", "/persons/P1/particulars-by-company", None),
    ("post", "/persons/P1/addresses", {"kind": "residential", **NEW}),
    ("put", "/persons/P1/addresses/A1", HOME),
    ("put", "/persons/P1/addresses/A1/companies", {"kind": "residential", "entity_ids": []}),
    ("post", "/persons/P1/addresses/A1/default", None),
    ("delete", "/persons/P1/addresses/A1?kind=residential", None),
    ("put", "/persons/P1/identity-documents/D1/companies", {"entity_ids": []}),
]


@pytest.mark.parametrize("method, path, body", ROUTES)
def test_every_route_needs_a_persons_permission(db, method, path, body):
    with patch("middleware.auth._resolve_user", return_value=REGULAR), \
         patch("middleware.auth.get_supabase") as msb:
        chain = msb.return_value.table.return_value.select.return_value
        chain.eq.return_value.eq.return_value.execute.return_value.data = []
        chain.eq.return_value.execute.return_value.data = []
        kwargs = {"json": body} if body is not None else {}
        assert getattr(client, method)(path, headers=H, **kwargs).status_code == 403


def test_an_invalid_token_is_401(db):
    with patch("middleware.auth._resolve_user",
               side_effect=HTTPException(status_code=401, detail="x")):
        assert client.get("/persons/P1/particulars-by-company", headers=H).status_code == 401
