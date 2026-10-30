"""Send again on an ND2A / ND2B: the frozen copy under the same revision, as on NAR1
(Levi 2026-10-30). Services are patched at the names the router calls, so nothing
reaches Supabase, Resend, DNS or CR.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from routers import officer_changes as oc

client = TestClient(app)
ADMIN = {"id": "U1", "display_name": "Levi Z.", "role_name": "super_admin", "role_id": "r"}
H = {"Authorization": "Bearer tok"}
CASE = {"id": "K1", "case_no": "ND2A-2026-0001", "entity_id": "E1", "form_code": "Nd2a",
        "closed_at": None, "verification_sent_at": None, "client_approved": None}
COMPOSITE = {"id": "K1", "form_code": "Nd2a", "entries": [],
             "rules": {"blocking": False, "checks": [], "summary": ""}}


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
         patch.object(oc, "log_event", new_callable=AsyncMock) as audit:
        m.case = dict(CASE)
        composite.return_value = dict(COMPOSITE)
        m.composite, m.update, m.audit = composite, update, audit
        yield m


def _send_again(env, case):
    """Post a single send with every collaborator patched; hand back what they saw."""
    env.case = case
    with patch.object(oc.prepare, "build_form_xml", new_callable=AsyncMock,
                      return_value="<rebuilt/>") as build, \
         patch.object(oc.tpsi_filings, "create_filing", return_value={"id": "F1"}) as create, \
         patch.object(oc.tpsi_filings, "supersede_all_for_case") as supersede, \
         patch.object(oc.nar1_router, "_undeliverable", new_callable=AsyncMock,
                      return_value={}), \
         patch.object(oc, "render_form", return_value=b"%PDF") as render, \
         patch.object(oc.documents, "email_attachments", return_value=[]), \
         patch.object(oc.resolution, "render", return_value=b"%PDF-res"), \
         patch.object(oc.prepare, "consent_plan", new_callable=AsyncMock, return_value=[]), \
         patch.object(oc.recipients_svc, "default_recipients", return_value=[]), \
         patch.object(oc.nar1_router, "_approval_link_base", return_value="https://x"), \
         patch.object(oc.nar1_approvals, "issue",
                      side_effect=lambda **k: [{**r, "token": "t"} for r in k["recipients"]]) as issue, \
         patch.object(oc.email_service, "send",
                      side_effect=lambda **k: {"id": "m1", "to": k["to"]}) as send, \
         patch.object(oc.emails, "officer_change_email", return_value=("s", "h")):
        resp = client.post("/officer-changes/K1/verification/send", headers=H,
                           json={"emails": ["a@example.com"], "respond_by": "2099-01-01"})
    return resp, dict(build=build, create=create, supersede=supersede, render=render,
                      issue=issue, send=send)


SENT = {**CASE, "verification_sent_at": "2026-10-29T00:00:00Z", "verification_revision": 2,
        "verification_xml": "<frozen/>"}


def test_send_again_mails_the_frozen_copy_and_builds_nothing(env):
    resp, seen = _send_again(env, dict(SENT))
    assert resp.status_code == 200, resp.text
    seen["build"].assert_not_awaited()
    seen["create"].assert_not_called()
    seen["supersede"].assert_not_called()
    call = seen["render"].call_args
    assert "<frozen/>" in [*call.args, *call.kwargs.values()]
    assert env.update.call_args.args[1]["verification_xml"] == "<frozen/>"


def test_send_again_repeats_the_revision_the_client_holds(env):
    resp, seen = _send_again(env, dict(SENT))
    assert resp.json()["revision"] == 2
    assert env.update.call_args.args[1]["verification_revision"] == 2
    kwargs = seen["issue"].call_args.kwargs
    assert kwargs["revision"] == 2 and kwargs["new_revision"] is False


def test_a_send_after_a_restart_is_the_next_revision_and_built_afresh(env):
    # Restart verification clears the send and the copy but keeps the count.
    resp, seen = _send_again(env, {**CASE, "verification_revision": 2})
    assert resp.json()["revision"] == 3
    seen["build"].assert_awaited_once()
    assert seen["issue"].call_args.kwargs["new_revision"] is True
    assert env.update.call_args.args[1]["verification_xml"] == "<rebuilt/>"


def test_send_again_clears_an_earlier_answer_as_a_first_send_does(env):
    resp, _ = _send_again(env, {**SENT, "client_approved": False,
                                "client_response_at": "2026-10-29T01:00:00Z"})
    assert resp.status_code == 200, resp.text
    assert env.update.call_args.args[1]["client_approved"] is None


def test_send_again_refuses_when_no_copy_was_kept(env):
    resp, seen = _send_again(env, {**SENT, "verification_xml": None})
    assert resp.status_code == 409
    assert resp.json()["detail"]["reason"] == "no_frozen_copy"
    seen["send"].assert_not_called()
    env.update.assert_not_called()


@pytest.mark.parametrize("entries", [
    [{"id": "E1", "kind": "appointment", "date_deferred": True, "effective_date": "2026-10-29"}],
    [{"id": "E1", "kind": "change", "items": [
        {"key": "name", "deferred": True, "effective_date": "2026-10-29"}]}],
])
def test_send_again_refuses_a_date_the_frozen_copy_does_not_carry(env, entries):
    with patch.object(oc.svc, "list_entries", return_value=entries):
        resp, seen = _send_again(env, dict(SENT))
    assert resp.status_code == 409
    assert resp.json()["detail"]["reason"] == "dates_filled_since_send"
    seen["send"].assert_not_called()
    env.update.assert_not_called()


@pytest.mark.parametrize("entries", [
    # Still deferred and still blank: the frozen copy is right about it.
    [{"id": "E1", "kind": "appointment", "date_deferred": True, "effective_date": None}],
    # Dated before the send: the client saw it.
    [{"id": "E1", "kind": "cessation", "date_deferred": False, "effective_date": "2026-10-01"}],
    # A line left off the form has no date to carry.
    [{"id": "E1", "kind": "change", "items": [
        {"key": "name", "deferred": True, "effective_date": "2026-10-29", "omitted": True}]}],
])
def test_send_again_goes_when_the_frozen_copy_is_still_true(env, entries):
    with patch.object(oc.svc, "list_entries", return_value=entries):
        resp, _ = _send_again(env, dict(SENT))
    assert resp.status_code == 200, resp.text


def test_send_again_says_nothing_new_about_what_the_client_has_seen(env):
    resp, _ = _send_again(env, dict(SENT))
    assert resp.status_code == 200, resp.text
    oc.svc.mark_deferred.assert_not_called()


def test_a_first_send_still_marks_the_undated_changes_deferred(env):
    resp, _ = _send_again(env, dict(CASE))
    assert resp.status_code == 200, resp.text
    oc.svc.mark_deferred.assert_called_once_with("K1")
