"""The "Multiple directors must sign" option on an ND2A / ND2B (nd2-multi-signer,
spec 2.4 and 8 items 6 and 7).

PATCH accepts `multi_signer`; Restart verification clears the frozen signer set
and keeps the option; and while the option is on the single send and a staff
"client approved" both refuse, because either would approve the case without the
signatures the option exists to collect. Services are patched at the names the
router calls, so nothing reaches Supabase, Resend, DNS or CR.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app
from routers import officer_changes as oc

client = TestClient(app)
ADMIN = {"id": "U1", "display_name": "Levi Z.", "role_name": "super_admin", "role_id": "r"}
STAFF = {"id": "U2", "display_name": "Staff", "role_name": "staff", "role_id": "x"}
H = {"Authorization": "Bearer tok"}
CASE = {"id": "K1", "case_no": "ND2A-2026-0001", "entity_id": "E1", "form_code": "Nd2a",
        "closed_at": None, "verification_sent_at": None, "client_approved": None,
        "multi_signer": False, "required_signers": None}
COMPOSITE = {"id": "K1", "form_code": "Nd2a", "entries": [],
             "rules": {"blocking": False, "checks": [], "summary": ""}}
SIGNERS = [{"person_id": "P1", "name": "Jacqueline Koh", "roles": ["resolution"]}]


@pytest.fixture
def env():
    """An admin, a case and the services the router calls, all patched."""
    m = MagicMock()
    with patch("middleware.auth._resolve_user", return_value=ADMIN), \
         patch.object(oc.svc, "get_case", side_effect=lambda cid: dict(m.case)), \
         patch.object(oc.svc, "composite", new_callable=AsyncMock) as composite, \
         patch.object(oc.svc, "list_entries", return_value=[]), \
         patch.object(oc.nar1_cases, "current_filing", return_value=None), \
         patch.object(oc.nar1_cases, "update_case") as update, \
         patch.object(oc.nar1_cases, "entity_for", return_value={"company_name": "Kanenas"}), \
         patch.object(oc.svc, "mark_deferred", return_value=0), \
         patch.object(oc.signatures, "required_signers", return_value=list(SIGNERS)), \
         patch.object(oc, "log_event", new_callable=AsyncMock) as audit:
        m.case = dict(CASE)
        composite.return_value = dict(COMPOSITE)
        m.composite, m.update, m.audit = composite, update, audit
        yield m


def _actions(audit):
    return [c.kwargs["action_type"] for c in audit.await_args_list]


def _patch(body):
    return client.patch("/officer-changes/K1", headers=H, json=body)


# -- permissions -----------------------------------------------------------------------

def test_the_toggle_needs_the_write_permission():
    with patch("middleware.auth._resolve_user", return_value=STAFF), \
         patch("middleware.auth.get_supabase") as msb:
        chain = msb.return_value.table.return_value.select.return_value
        chain.eq.return_value.eq.return_value.execute.return_value.data = []
        chain.eq.return_value.execute.return_value.data = []
        assert _patch({"multi_signer": True}).status_code == 403


def test_the_toggle_needs_a_valid_token():
    with patch("middleware.auth._resolve_user",
               side_effect=HTTPException(status_code=401, detail="x")):
        assert _patch({"multi_signer": True}).status_code == 401


# -- the toggle ------------------------------------------------------------------------

def test_turning_it_on_is_written_and_audited_as_a_field_edit(env):
    resp = _patch({"multi_signer": True})
    assert resp.status_code == 200, resp.text
    assert env.update.call_args.args[1] == {"multi_signer": True}
    [row] = [c.kwargs for c in env.audit.await_args_list]
    assert row["action_type"] == "CASE_FIELD_UPDATED"
    assert row["metadata"]["field"] == "multi_signer"
    assert row["old_value"] is False and row["new_value"] is True


def test_turning_it_off_is_written_and_audited(env):
    env.case = {**CASE, "multi_signer": True}
    resp = _patch({"multi_signer": False})
    assert resp.status_code == 200, resp.text
    assert env.update.call_args.args[1] == {"multi_signer": False}
    row = env.audit.await_args.kwargs
    assert row["metadata"]["field"] == "multi_signer"
    assert row["old_value"] is True and row["new_value"] is False


def test_turning_it_off_needs_no_signers(env):
    """Only turning it ON asks who must sign."""
    env.case = {**CASE, "multi_signer": True}
    with patch.object(oc.signatures, "required_signers", return_value=[]):
        assert _patch({"multi_signer": False}).status_code == 200


def test_it_cannot_change_once_the_form_has_been_sent(env):
    env.case = {**CASE, "verification_sent_at": "2026-10-29T00:00:00Z"}
    resp = _patch({"multi_signer": True})
    assert resp.status_code == 409
    assert resp.json()["detail"]["reason"] == "already_sent"
    env.update.assert_not_called()
    env.audit.assert_not_awaited()


def test_a_restart_in_the_same_request_lets_it_change(env):
    env.case = {**CASE, "verification_sent_at": "2026-10-29T00:00:00Z", "multi_signer": False}
    with patch.object(oc.nar1_approvals, "supersede_outstanding", return_value=0), \
         patch.object(oc.tpsi_filings, "supersede_all_for_case", return_value=0):
        resp = _patch({"multi_signer": True, "restart_verification": True})
    assert resp.status_code == 200, resp.text
    written = env.update.call_args.args[1]
    assert written["multi_signer"] is True
    assert written["verification_sent_at"] is None
    assert _actions(env.audit) == ["CASE_FIELD_UPDATED", "CASE_STATUS_CHANGED"]


def test_it_cannot_be_turned_on_when_nobody_has_a_box_to_sign(env):
    with patch.object(oc.signatures, "required_signers", return_value=[]):
        resp = _patch({"multi_signer": True})
    assert resp.status_code == 409
    assert resp.json()["detail"]["reason"] == "no_signers"
    env.update.assert_not_called()
    env.audit.assert_not_awaited()


def test_a_refused_toggle_writes_nothing_even_beside_other_fields(env):
    """The refusal is decided before any field of the request is written, or a
    409 would leave half a PATCH behind."""
    env.case = {**CASE, "verification_sent_at": "2026-10-29T00:00:00Z"}
    resp = _patch({"multi_signer": True, "signing_method": "manual"})
    assert resp.status_code == 409
    env.update.assert_not_called()
    env.audit.assert_not_awaited()


def test_a_closed_or_filed_case_refuses_the_toggle(env):
    env.case = {**CASE, "closed_at": "2026-10-01T00:00:00Z"}
    closed = _patch({"multi_signer": True})
    assert closed.status_code == 409 and closed.json()["detail"]["reason"] == "case_closed"
    env.case = dict(CASE)
    with patch.object(oc, "filed", return_value=True):
        filed = _patch({"multi_signer": True})
    assert filed.status_code == 409 and filed.json()["detail"]["reason"] == "already_filed"


# -- restart ---------------------------------------------------------------------------

def test_restart_clears_the_frozen_signers_and_keeps_the_option(env):
    env.case = {**CASE, "verification_sent_at": "2026-10-29T00:00:00Z", "multi_signer": True,
                "required_signers": list(SIGNERS), "client_approved": None}
    with patch.object(oc.nar1_approvals, "supersede_outstanding", return_value=1), \
         patch.object(oc.tpsi_filings, "supersede_all_for_case", return_value=0):
        resp = _patch({"restart_verification": True})
    assert resp.status_code == 200, resp.text
    written = env.update.call_args.args[1]
    assert written["required_signers"] is None
    assert written["verification_sent_at"] is None
    assert "multi_signer" not in written


# -- the single send and the staff relay refuse while it is on -----------------------------

def test_the_single_send_refuses_while_it_is_on(env):
    env.case = {**CASE, "multi_signer": True}
    with patch.object(oc.prepare, "build_form_xml", new_callable=AsyncMock) as build, \
         patch.object(oc.nar1_approvals, "issue") as issue, \
         patch.object(oc.email_service, "send") as send:
        resp = client.post("/officer-changes/K1/verification/send", headers=H,
                           json={"emails": ["a@example.com"], "respond_by": "2099-01-01"})
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["reason"] == "multi_signer"
    assert detail["message"] == "Each director is sent their own link below."
    build.assert_not_awaited()
    issue.assert_not_called()
    send.assert_not_called()
    env.update.assert_not_called()


def test_the_single_send_still_works_while_it_is_off(env):
    """The refusal is the option's, not a new rule on every send."""
    with patch.object(oc.prepare, "build_form_xml", new_callable=AsyncMock,
                      return_value="<x/>"), \
         patch.object(oc.tpsi_filings, "create_filing", return_value={"id": "F1"}), \
         patch.object(oc.nar1_router, "_undeliverable", new_callable=AsyncMock,
                      return_value={}), \
         patch.object(oc, "render_form", return_value=b"%PDF"), \
         patch.object(oc.documents, "email_attachments", return_value=[]), \
         patch.object(oc.resolution, "render", return_value=b"%PDF-res"), \
         patch.object(oc.prepare, "consent_plan", new_callable=AsyncMock, return_value=[]), \
         patch.object(oc.recipients_svc, "default_recipients", return_value=[]), \
         patch.object(oc.nar1_router, "_approval_link_base", return_value=None), \
         patch.object(oc.email_service, "send",
                      side_effect=lambda **k: {"id": "m1", "to": k["to"]}), \
         patch.object(oc.emails, "officer_change_email", return_value=("s", "h")):
        resp = client.post("/officer-changes/K1/verification/send", headers=H,
                           json={"emails": ["a@example.com"], "respond_by": "2099-01-01"})
    assert resp.status_code == 200, resp.text


def test_staff_cannot_record_an_approval_while_it_is_on(env):
    env.case = {**CASE, "multi_signer": True,
                "verification_sent_at": "2026-10-29T00:00:00Z"}
    resp = client.post("/officer-changes/K1/verification/response", headers=H,
                       json={"approved": True, "approved_by": "Someone"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["reason"] == "multi_signer"
    env.update.assert_not_called()
    env.audit.assert_not_awaited()


def test_staff_can_still_record_a_decline_while_it_is_on(env):
    env.case = {**CASE, "multi_signer": True,
                "verification_sent_at": "2026-10-29T00:00:00Z"}
    resp = client.post("/officer-changes/K1/verification/response", headers=H,
                       json={"approved": False})
    assert resp.status_code == 200, resp.text
    written = env.update.call_args.args[1]
    assert written["client_approved"] is False
    assert _actions(env.audit) == ["CLIENT_APPROVAL_RECEIVED"]


def test_staff_can_still_record_an_approval_while_it_is_off(env):
    env.case = {**CASE, "verification_sent_at": "2026-10-29T00:00:00Z"}
    resp = client.post("/officer-changes/K1/verification/response", headers=H,
                       json={"approved": True})
    assert resp.status_code == 200, resp.text
    assert env.update.call_args.args[1]["client_approved"] is True
