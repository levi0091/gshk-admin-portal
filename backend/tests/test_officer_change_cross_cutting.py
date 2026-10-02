"""The edits ND2A/ND2B make to shared NAR1 code (migration 050):

  * the client's Confirm page for an officer change, and the two pages refusing
    each other's tokens;
  * every NAR1 write route refusing an officer-change case (`wrong_form`);
  * the auto-approval job never approving an officer change on silence;
  * a case-owned document taking its case's permission module.
"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from jobs import auto_approve_nar1
from main import app
from routers import public_approval
from services import document_permissions
from tests.test_public_approval import ENTITY, TOKEN, _Stack, _world, row

client = TestClient(app)
ND2A = {"id": "c1", "case_no": "ND2A-2026-0001", "entity_id": "e1", "form_code": "Nd2a",
        "client_approved": None}
ND2_PATH = f"/public/officer-change-approval/{TOKEN}"
NAR1_PATH = f"/public/nar1-approval/{TOKEN}"


@pytest.fixture(autouse=True)
def _clean_rate_limiter():
    public_approval._HITS.clear()
    yield
    public_approval._HITS.clear()


def test_the_officer_change_page_asks_in_its_own_words_and_writes_nothing():
    with _Stack(*_world(approval=row(), case=ND2A)) as patches:
        resp = client.get(ND2_PATH)
    assert resp.status_code == 200
    assert "Form ND2A" in resp.text and "Confirm &amp; File" in resp.text
    assert "Annual Return" not in resp.text
    assert "proceed with filing" not in resp.text      # no approval on silence
    assert "<script" not in resp.text.lower() and TOKEN not in resp.text
    update = patches[3]
    update.assert_not_called()


def test_a_post_records_the_officer_change_approval():
    with _Stack(*_world(approval=row(), case=ND2A)) as patches:
        resp = client.post(ND2_PATH)
    assert resp.status_code == 200 and "Form ND2A" in resp.text
    assert patches[3].call_args.args[1]["client_approved"] is True


@pytest.mark.parametrize("path, case", [(NAR1_PATH, ND2A),
                                        (ND2_PATH, {**ND2A, "form_code": "Nar1"})])
def test_each_page_refuses_the_other_forms_token(path, case):
    with _Stack(*_world(approval=row(), case=case)) as patches:
        get = client.get(path)
        post = client.post(path)
    assert "no longer available" in get.text.lower() or "not available" in get.text.lower()
    assert "Confirm &amp; File" not in get.text
    patches[3].assert_not_called()
    assert post.status_code == 200


def test_nar1_write_routes_refuse_an_officer_change_case():
    admin = {"id": "U1", "display_name": "A", "role_name": "super_admin", "role_id": "r"}
    with patch("middleware.auth._resolve_user", return_value=admin), \
         patch("routers.cases.nar1_cases.get_case", return_value=dict(ND2A)):
        resp = client.post("/cases/c1/verification/response",
                           headers={"Authorization": "Bearer t"}, json={"approved": True})
        close = client.post("/cases/c1/close", headers={"Authorization": "Bearer t"},
                            json={"reason": "x"})
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "wrong_form"
    assert close.status_code == 409 and close.json()["detail"]["reason"] == "wrong_form"


def test_auto_approval_never_approves_an_officer_change():
    case = {**ND2A, "verification_sent_at": "2026-09-01T00:00:00Z"}
    assert auto_approve_nar1.skip_reason(case) == \
        "an officer change is never approved on silence"
    assert auto_approve_nar1.skip_reason({**case, "form_code": "Nar1"}) != \
        "an officer change is never approved on silence"


def test_a_case_owned_document_takes_its_cases_module(monkeypatch):
    class Q:
        def __init__(self, rows):
            self.rows = rows

        def select(self, *a):
            return self

        def eq(self, *a):
            return self

        def limit(self, *a):
            return self

        def execute(self):
            from types import SimpleNamespace
            return SimpleNamespace(data=self.rows)

    tables = {"documents": [{"entity_id": None, "person_id": None, "nar1_case_id": "c1"}],
              "nar1_cases": [{"form_code": "Nd2a"}]}

    class SB:
        def table(self, name):
            return Q(tables[name])

    monkeypatch.setattr(document_permissions, "get_supabase", lambda: SB())
    assert document_permissions.module_for_document("d1") == "officer_changes"
    tables["nar1_cases"] = [{"form_code": "Nar1"}]
    assert document_permissions.module_for_document("d1") == "nar1"
