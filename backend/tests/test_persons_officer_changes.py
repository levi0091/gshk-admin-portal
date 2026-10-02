"""Person routes added for ND2A/ND2B: the e-Registry credential, the ND2B
"changed on the profile" alert, and the baseline capture in front of edits.

Happy path, 401/403 and an edge case per route (repo CLAUDE.md, Unit testing).
"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app
from tests.officer_changes.fakes import FakeSupabase

client = TestClient(app)
SUPER_ADMIN = {"id": "admin-1", "display_name": "Levi Z.", "role_name": "super_admin",
               "role_id": "role-sa"}
REGULAR = {"id": "u-2", "display_name": "Staff", "role_name": "staff", "role_id": "role-x"}
H = {"Authorization": "Bearer tok"}
SECRET = "Correct-Horse-9"


@pytest.fixture
def db():
    fake = FakeSupabase({
        "persons": [{"id": "P1", "full_name": "CHAN Tai Man", "email": "a@example.com",
                     "residential_address_id": None, "deleted_at": None}],
        "person_identity_documents": [],
        "person_eservice_credentials": [],
        "officer_cr_particulars": [],
    })
    with patch("routers.persons.get_supabase", return_value=fake), \
         patch("services.officer_changes.eservice.get_supabase", return_value=fake), \
         patch("services.officer_changes.eservice.encrypt", side_effect=lambda p: "enc:" + p[::-1]), \
         patch("services.officer_changes.eservice.decrypt", side_effect=lambda c: c[4:][::-1]):
        yield fake


@pytest.fixture
def admin():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN):
        yield


@pytest.fixture
def audit():
    with patch("routers.persons.log_event", new_callable=AsyncMock) as log:
        yield log


def _no_permissions():
    p = patch("middleware.auth.get_supabase")
    msb = p.start()
    chain = msb.return_value.table.return_value.select.return_value
    chain.eq.return_value.eq.return_value.execute.return_value.data = []
    chain.eq.return_value.execute.return_value.data = []
    return p


# -- e-Registry credential ----------------------------------------------------------

def test_get_credential_reports_metadata_only(db, admin):
    resp = client.get("/persons/P1/eservice-credential", headers=H)
    assert resp.status_code == 200
    assert resp.json()["configured"] is False


def test_put_credential_stores_it_and_audits_the_account_only(db, admin, audit):
    resp = client.put("/persons/P1/eservice-credential", headers=H, json={
        "eservice_user_id": "ER123456", "eservice_person_name": "CHAN Tai Man",
        "password": SECRET})
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_password"] is True and body["eservice_user_id"] == "ER123456"
    assert SECRET not in resp.text
    kwargs = audit.await_args.kwargs
    assert kwargs["action_type"] == "PERSON_ESERVICE_CRED_SET"
    assert kwargs["metadata"]["eservice_user_id"] == "ER123456"
    assert SECRET not in str(audit.await_args) and SECRET[-4:] not in str(audit.await_args)
    assert SECRET not in str(db.rows("person_eservice_credentials"))


def test_put_credential_stores_registered_id_and_never_audits_the_number(db, admin, audit):
    resp = client.put("/persons/P1/eservice-credential", headers=H, json={
        "eservice_user_id": "ER1", "eservice_person_name": "CHAN Tai Man",
        "password": SECRET, "registered_id_type": "passport",
        "registered_id_number": "X1234567"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["registered_id_number"] == "X1234567"
    assert "X1234567" not in str(audit.await_args)
    assert audit.await_args.kwargs["metadata"]["registered_id_type"] == "passport"


def test_get_credential_reports_an_identity_mismatch(db, admin, audit):
    db.tables["person_identity_documents"].append(
        {"person_id": "P1", "id_type": "passport", "id_number": "Y7654321"})
    client.put("/persons/P1/eservice-credential", headers=H, json={
        "eservice_user_id": "ER1", "eservice_person_name": "CHAN Tai Man",
        "password": SECRET, "registered_id_type": "passport",
        "registered_id_number": "X1234567"})
    body = client.get("/persons/P1/eservice-credential", headers=H).json()
    assert "Y765" in body["registered_id_mismatch"]


def test_put_credential_refuses_a_bad_registered_id_type(db, admin, audit):
    resp = client.put("/persons/P1/eservice-credential", headers=H, json={
        "eservice_user_id": "ER1", "eservice_person_name": "A", "password": SECRET,
        "registered_id_type": "licence", "registered_id_number": "1"})
    assert resp.status_code == 400 and "registered_id_type" in resp.json()["detail"]
    assert SECRET not in resp.text


def test_put_credential_first_time_without_password_is_400(db, admin, audit):
    resp = client.put("/persons/P1/eservice-credential", headers=H, json={
        "eservice_user_id": "ER1", "eservice_person_name": "A"})
    assert resp.status_code == 400
    assert "password" in resp.json()["detail"].lower()
    audit.assert_not_awaited()


def test_put_credential_refuses_unknown_fields_naming_the_key_not_the_value(db, admin):
    resp = client.put("/persons/P1/eservice-credential", headers=H, json={
        "eservice_user_id": "ER1", "eservice_person_name": "A", "pin": "1234"})
    assert resp.status_code == 400
    assert "pin" in resp.json()["detail"] and "1234" not in resp.text


@pytest.mark.parametrize("payload", [
    # A missing name: pydantic's 422 used to echo the whole input, password included.
    {"eservice_user_id": "ER1", "password": SECRET},
    # A stale key: extra="forbid" echoed the value under `input`.
    {"eservice_user_id": "ER1", "eservice_person_name": "A", "eservice_password": SECRET},
    # Not an object at all.
    [SECRET],
    SECRET,
    {"eservice_user_id": "ER1", "eservice_person_name": "A", "password": [SECRET]},
])
def test_no_refusal_ever_repeats_the_password(db, admin, audit, payload):
    resp = client.put("/persons/P1/eservice-credential", headers=H, json=payload)
    assert resp.status_code == 400
    assert SECRET not in resp.text
    audit.assert_not_awaited()


def test_delete_credential_removes_and_audits(db, admin, audit):
    client.put("/persons/P1/eservice-credential", headers=H, json={
        "eservice_user_id": "ER1", "eservice_person_name": "A", "password": SECRET})
    resp = client.delete("/persons/P1/eservice-credential", headers=H)
    assert resp.status_code == 200
    assert resp.json()["removed"] is True and resp.json()["configured"] is False
    assert audit.await_args.kwargs["metadata"]["removed"] is True


@pytest.mark.parametrize("method, path", [
    ("get", "/persons/P1/eservice-credential"),
    ("put", "/persons/P1/eservice-credential"),
    ("delete", "/persons/P1/eservice-credential"),
    ("get", "/persons/P1/particulars-changes"),
    ("post", "/persons/P1/particulars-changes/dismiss"),
])
def test_routes_need_persons_permission(db, method, path):
    with patch("middleware.auth._resolve_user", return_value=REGULAR):
        p = _no_permissions()
        try:
            kwargs = {"json": {"eservice_user_id": "x", "eservice_person_name": "y"}} \
                if method == "put" else {}
            resp = getattr(client, method)(path, headers=H, **kwargs)
        finally:
            p.stop()
    assert resp.status_code == 403


def test_invalid_token_is_401(db):
    with patch("middleware.auth._resolve_user",
               side_effect=HTTPException(status_code=401, detail="x")):
        assert client.get("/persons/P1/eservice-credential", headers=H).status_code == 401


# -- the ND2B alert -------------------------------------------------------------------

PENDING = [{"entity_id": "E1", "company_name": "Kanenas Holding Limited",
            "capacity": "director", "officer_id": "O1", "open_case": None,
            "items": [{"key": "email", "cr_item": "f", "label": "Email address",
                       "old": "a@example.com", "new": "b@example.com",
                       "old_text": "a@example.com", "new_text": "b@example.com",
                       "effective_date": None, "omitted": False}]}]


def test_particulars_changes_lists_items_without_dates(db, admin):
    with patch("services.officer_changes.particulars.pending_for_person",
               return_value=PENDING):
        resp = client.get("/persons/P1/particulars-changes", headers=H)
    assert resp.status_code == 200
    item = resp.json()["changes"][0]["items"][0]
    assert item["key"] == "email" and "effective_date" not in item and "omitted" not in item


def test_particulars_changes_empty_when_nothing_pending(db, admin):
    with patch("services.officer_changes.particulars.pending_for_person", return_value=[]):
        assert client.get("/persons/P1/particulars-changes", headers=H).json() == {"changes": []}


def test_dismiss_moves_the_baseline_and_audits_labels_not_values(db, admin, audit):
    with patch("services.officer_changes.particulars.pending_for_person",
               return_value=PENDING), \
         patch("services.officer_changes.particulars.dismiss", return_value=1) as dismiss:
        resp = client.post("/persons/P1/particulars-changes/dismiss", headers=H)
    assert resp.json() == {"dismissed": 1}
    dismiss.assert_called_once_with(person_id="P1", user_id="admin-1")
    kwargs = audit.await_args.kwargs
    assert kwargs["action_type"] == "OFFICER_PARTICULARS_DISMISSED"
    assert kwargs["metadata"]["dismissed"][0]["items"] == ["Email address"]
    assert "b@example.com" not in str(kwargs["metadata"])


def test_dismiss_with_nothing_to_dismiss_writes_no_audit_row(db, admin, audit):
    with patch("services.officer_changes.particulars.pending_for_person", return_value=[]), \
         patch("services.officer_changes.particulars.dismiss", return_value=0):
        assert client.post("/persons/P1/particulars-changes/dismiss",
                           headers=H).json() == {"dismissed": 0}
    audit.assert_not_awaited()


# -- the baseline is captured BEFORE the write ---------------------------------------

def test_editing_a_tracked_field_captures_the_baseline_first(db, admin):
    seen = {}

    def capture(**kwargs):
        seen["email_at_capture"] = db.rows("persons")[0]["email"]
        seen["kwargs"] = kwargs
        return 1

    with patch("services.officer_changes.particulars.capture_before_edit",
               side_effect=capture), \
         patch("routers.persons.log_events", new_callable=AsyncMock):
        resp = client.patch("/persons/P1", headers=H, json={"email": "b@example.com"})
    assert resp.status_code == 200
    assert seen["email_at_capture"] == "a@example.com"
    assert seen["kwargs"] == {"person_id": "P1", "user_id": "admin-1"}
    assert db.rows("persons")[0]["email"] == "b@example.com"


def test_editing_an_untracked_field_captures_nothing(db, admin):
    with patch("services.officer_changes.particulars.capture_before_edit") as capture, \
         patch("routers.persons.log_events", new_callable=AsyncMock):
        resp = client.patch("/persons/P1", headers=H, json={"phone": "+852 1234 5678"})
    assert resp.status_code == 200
    capture.assert_not_called()


def test_a_residential_address_change_captures_first(db, admin):
    order = []
    with patch("services.officer_changes.particulars.capture_before_edit",
               side_effect=lambda **k: order.append("capture") or 1), \
         patch("routers.persons.address_service.save",
               side_effect=lambda *a, **k: order.append("save") or
               {"address": {"id": "A9"}, "action": "created"}), \
         patch("routers.persons.address_service.count_references", return_value=1), \
         patch("routers.persons.log_events", new_callable=AsyncMock), \
         patch("routers.persons._address_audit_entries", return_value=[]):
        resp = client.put("/persons/P1/residential-address", headers=H, json={
            "line1": "Flat A", "city": "CENTRAL", "country": "HK"})
    assert resp.status_code == 200, resp.text
    assert order == ["capture", "save"]
