"""Company routes added for ND2B: a body corporate OFFICER's particulars alert,
and the baseline capture in front of the edits that change what CR holds."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from tests.officer_changes.fakes import FakeSupabase

client = TestClient(app)
SUPER_ADMIN = {"id": "admin-1", "display_name": "Levi Z.", "role_name": "super_admin",
               "role_id": "role-sa"}
REGULAR = {"id": "u-2", "display_name": "Staff", "role_name": "staff", "role_id": "role-x"}
H = {"Authorization": "Bearer tok"}

PENDING = [{"entity_id": "E1", "company_name": "Client Limited", "capacity": "director",
            "officer_id": "O2", "open_case": None,
            "items": [{"key": "email", "cr_item": "c", "label": "Email address",
                       "old": "a@example.com", "new": "b@example.com",
                       "old_text": "a@example.com", "new_text": "b@example.com",
                       "effective_date": None, "omitted": False}]}]


@pytest.fixture
def db():
    fake = FakeSupabase({"entities": [
        {"id": "C1", "company_name": "Corp Director Limited", "email": "a@example.com",
         "br_number": "12345678", "deleted_at": None}]})
    with patch("routers.companies.get_supabase", return_value=fake):
        yield fake


@pytest.fixture
def admin():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN):
        yield


def test_particulars_changes_for_a_body_corporate_officer(db, admin):
    with patch("services.officer_changes.particulars.pending_for_corporate",
               return_value=PENDING):
        resp = client.get("/companies/C1/particulars-changes", headers=H)
    assert resp.status_code == 200
    item = resp.json()["changes"][0]["items"][0]
    assert item["cr_item"] == "c" and "effective_date" not in item


def test_dismiss_for_a_body_corporate_audits_and_returns_count(db, admin):
    with patch("services.officer_changes.particulars.pending_for_corporate",
               return_value=PENDING), \
         patch("services.officer_changes.particulars.dismiss", return_value=1) as dismiss, \
         patch("routers.companies.log_event", new_callable=AsyncMock) as audit:
        resp = client.post("/companies/C1/particulars-changes/dismiss", headers=H)
    assert resp.json() == {"dismissed": 1}
    dismiss.assert_called_once_with(corporate_entity_id="C1", user_id="admin-1")
    assert audit.await_args.kwargs["action_type"] == "OFFICER_PARTICULARS_DISMISSED"


def test_dismiss_with_nothing_pending_is_quiet(db, admin):
    with patch("services.officer_changes.particulars.pending_for_corporate", return_value=[]), \
         patch("services.officer_changes.particulars.dismiss", return_value=0), \
         patch("routers.companies.log_event", new_callable=AsyncMock) as audit:
        assert client.post("/companies/C1/particulars-changes/dismiss",
                           headers=H).json() == {"dismissed": 0}
    audit.assert_not_awaited()


@pytest.mark.parametrize("method, path", [
    ("get", "/companies/C1/particulars-changes"),
    ("post", "/companies/C1/particulars-changes/dismiss"),
])
def test_needs_companies_permission(db, method, path):
    with patch("middleware.auth._resolve_user", return_value=REGULAR), \
         patch("middleware.auth.get_supabase") as msb:
        chain = msb.return_value.table.return_value.select.return_value
        chain.eq.return_value.eq.return_value.execute.return_value.data = []
        chain.eq.return_value.execute.return_value.data = []
        assert getattr(client, method)(path, headers=H).status_code == 403


def test_editing_a_body_corporates_email_captures_its_appointments_first(db, admin):
    seen = {}

    def capture(**kwargs):
        seen["email"] = db.rows("entities")[0]["email"]
        seen["kwargs"] = kwargs
        return 3

    with patch("services.officer_changes.particulars.capture_before_edit",
               side_effect=capture), \
         patch("routers.companies.log_events", new_callable=AsyncMock):
        resp = client.patch("/companies/C1", headers=H, json={"email": "b@example.com"})
    assert resp.status_code == 200, resp.text
    assert seen == {"email": "a@example.com",
                    "kwargs": {"corporate_entity_id": "C1", "user_id": "admin-1"}}
