"""The signer routes of a multi-director ND2A / ND2B (nd2-multi-signer, spec 2.3,
3.1 and 8 item 8): list the signers, and send to one of them.

Services are patched at the names the routers call, so nothing reaches Supabase,
Resend, DNS or CR. The per-signer state machine itself (`signers.state`,
`record_signing`) has its own tests; here it is a stub that returns the contract.
"""
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app
from routers import officer_change_signers as ocs
from routers import officer_changes as oc

client = TestClient(app)
ADMIN = {"id": "U1", "display_name": "Levi Z.", "role_name": "super_admin", "role_id": "r"}
STAFF = {"id": "U2", "display_name": "Staff", "role_name": "staff", "role_id": "x"}
H = {"Authorization": "Bearer tok"}

P1 = {"person_id": "P1", "name": "Jacqueline Koh", "roles": ["resolution"]}
P2 = {"person_id": "P2", "name": "Testing Brian", "roles": ["consent"]}
CASE = {"id": "K1", "case_no": "ND2A-2026-0001", "entity_id": "E1", "form_code": "Nd2a",
        "closed_at": None, "multi_signer": True, "verification_sent_at": None,
        "verification_xml": None, "verification_revision": 0, "required_signers": None,
        "client_approved": None, "client_response_at": None}
#: A round that is open: P1 was sent first, the set was frozen then.
OPEN = {**CASE, "verification_sent_at": "2026-10-29T07:00:00+00:00",
        "verification_xml": "<frozen/>", "verification_revision": 1,
        "required_signers": [P1, P2]}
COMPOSITE = {"id": "K1", "form_code": "Nd2a", "entries": [], "officers": [],
             "rules": {"blocking": False, "checks": [], "summary": ""}}
BODY = {"email": "brian@example.com", "respond_by": "2099-01-01"}
URL = "/officer-changes/K1/verification/signers"


def _state(*signers, **top):
    base = {"multi_signer": True, "revision": 1, "frozen": True, "set_changed": False,
            "required": len(signers), "signed": 0, "converged": False}
    return {**base, **top, "signers": [
        {"person_id": s["person_id"], "name": s["name"], "roles": s["roles"],
         "role_label": "director", "suggested_email": None, "status": s.get("status", "sent"),
         "email": f"{s['person_id'].lower()}@example.com", "sent_at": "2026-10-29T07:00:00+00:00",
         "expires_at": "2099-01-01T15:59:59+00:00", "signed_at": None,
         "signature_captured": False, "delivery": None} for s in signers]}


@pytest.fixture
def env():
    """An admin, a case and everything the routers call, patched."""
    m = MagicMock()
    m.sent = []
    m.issued = []

    def fake_send(**kwargs):
        m.sent.append(kwargs)
        return {"id": f"m{len(m.sent)}", "to": kwargs["to"], "intended_to": kwargs["to"]}

    def fake_issue(**kwargs):
        m.issued.append(kwargs)
        return {**kwargs["recipient"], "token": f"tok-{kwargs['recipient']['person_id']}",
                "expires_at": kwargs["expires_at"], "revision": kwargs["revision"]}

    with ExitStack() as stack:
        def p(target, attr, **kw):
            return stack.enter_context(patch.object(target, attr, **kw))

        stack.enter_context(patch("middleware.auth._resolve_user", return_value=ADMIN))
        p(oc.svc, "get_case", side_effect=lambda cid: dict(m.case))
        m.composite = p(oc.svc, "composite", new_callable=AsyncMock, return_value=dict(COMPOSITE))
        p(oc.svc, "list_entries", return_value=[])
        m.deferred = p(oc.svc, "mark_deferred", return_value=0)
        m.current_filing = p(oc.nar1_cases, "current_filing", return_value=None)
        m.update = p(oc.nar1_cases, "update_case")
        p(oc.nar1_cases, "entity_for", return_value={"company_name": "Kanenas"})
        m.build = p(oc.prepare, "build_form_xml", new_callable=AsyncMock,
                    return_value="<built/>")
        p(oc.prepare, "consent_plan", new_callable=AsyncMock, return_value=[])
        m.create_filing = p(oc.tpsi_filings, "create_filing", return_value={"id": "F1"})
        m.render = p(oc, "_render", new_callable=AsyncMock, return_value=b"%PDF")
        p(oc.resolution, "render", return_value=b"%PDF-res")
        p(oc.documents, "email_attachments", return_value=[])
        p(oc.nar1_router, "_undeliverable", new_callable=AsyncMock, return_value={})
        p(oc.nar1_router, "_approval_link_base", return_value="https://api.test")
        m.supersede_all = p(oc.nar1_approvals, "supersede_outstanding", return_value=0)
        m.issue = p(oc.nar1_approvals, "issue_for_signer", side_effect=fake_issue)
        m.send = p(oc.email_service, "send", side_effect=fake_send)
        m.letter = p(oc.emails, "officer_change_email", return_value=("s", "<html/>"))
        m.required = p(oc.signatures, "required_signers", return_value=[P1, P2])
        m.rows = p(ocs.signers, "round_approvals", return_value=[])
        m.state = p(ocs.signers, "state", side_effect=lambda case: _state(
            {**P1, "status": "sent"}, {**P2, "status": "sent"}))
        m.audit = p(oc, "log_event", new_callable=AsyncMock)
        m.case = dict(CASE)
        yield m


def _actions(audit):
    return [c.kwargs["action_type"] for c in audit.await_args_list]


def _post(person="P2", body=None, **extra):
    return client.post(f"{URL}/{person}/send", headers=H, json=BODY if body is None else body,
                       **extra)


def _nothing_went_out(env):
    env.send.assert_not_called()
    env.issue.assert_not_called()
    env.update.assert_not_called()
    env.audit.assert_not_awaited()


# -- permissions -------------------------------------------------------------------------

@pytest.mark.parametrize("method, path, body", [
    ("get", URL, None),
    ("post", f"{URL}/P1/send", BODY),
])
def test_both_routes_need_a_permission(method, path, body):
    with patch("middleware.auth._resolve_user", return_value=STAFF), \
         patch("middleware.auth.get_supabase") as msb:
        chain = msb.return_value.table.return_value.select.return_value
        chain.eq.return_value.eq.return_value.execute.return_value.data = []
        chain.eq.return_value.execute.return_value.data = []
        kwargs = {"json": body} if body is not None else {}
        assert getattr(client, method)(path, headers=H, **kwargs).status_code == 403


@pytest.mark.parametrize("method, path, body", [
    ("get", URL, None),
    ("post", f"{URL}/P1/send", BODY),
])
def test_both_routes_need_a_valid_token(method, path, body):
    with patch("middleware.auth._resolve_user",
               side_effect=HTTPException(status_code=401, detail="x")):
        kwargs = {"json": body} if body is not None else {}
        assert getattr(client, method)(path, headers=H, **kwargs).status_code == 401


def test_a_read_only_role_may_list_the_signers_but_not_send(env):
    """`officer_changes:read` lists; `officer_changes:write` sends."""
    with patch("middleware.auth._resolve_user", return_value=STAFF), \
         patch("middleware.auth._permissions_for", return_value={"read"}), \
         patch.object(ocs.signers, "latest_sends", return_value={}):
        listed = client.get(URL, headers=H)
        sent = client.post(f"{URL}/P2/send", headers=H, json=BODY)
    assert listed.status_code == 200
    assert sent.status_code == 403
    env.send.assert_not_called()


# -- GET: the report ---------------------------------------------------------------------------

def test_the_report_is_the_state_with_no_delivery_check_for_nobody_sent(env):
    env.state.side_effect = lambda case: _state({**P1, "status": "not_sent"},
                                                {**P2, "status": "signed"})
    with patch.object(ocs.email_service, "delivery_status") as ask, \
         patch.object(ocs.signers, "latest_sends", return_value={}) as sends:
        resp = client.get(URL, headers=H)
    assert resp.status_code == 200, resp.text
    assert [s["status"] for s in resp.json()["signers"]] == ["not_sent", "signed"]
    ask.assert_not_called()
    sends.assert_not_called()


def test_a_redirected_signer_is_never_asked_about(env):
    entry = {"email": "p1@example.com", "message_id": "m9", "redirected": True,
             "delivered_to": ["levi@zenexflow.com"]}
    with patch.object(ocs.email_service, "delivery_status") as ask, \
         patch.object(ocs.signers, "latest_sends", return_value={"P1": entry, "P2": entry}):
        resp = client.get(URL, headers=H)
    assert resp.status_code == 200
    first = resp.json()["signers"][0]
    assert first["status"] == "redirected"
    assert first["delivery"]["status"] == "redirected"
    assert "levi@zenexflow.com" in first["delivery"]["detail"]
    assert "test environment" in first["delivery"]["detail"]
    ask.assert_not_called()


def test_a_failed_delivery_reads_not_delivered(env):
    answers = {"m1": {"status": "failed", "event": "bounced", "detail": "the address bounced"},
               "m2": {"status": "delivered", "event": "delivered", "detail": "arrived"}}
    sends = {"P1": {"email": "p1@example.com", "message_id": "m1", "redirected": False},
             "P2": {"email": "p2@example.com", "message_id": "m2", "redirected": False}}
    with patch.object(ocs.email_service, "delivery_status",
                      side_effect=lambda mid: answers[mid]), \
         patch.object(ocs.signers, "latest_sends", return_value=sends):
        body = client.get(URL, headers=H).json()
    first, second = body["signers"]
    assert first["status"] == "not_delivered"
    assert first["delivery"] == {"status": "failed", "detail": "the address bounced"}
    assert second["status"] == "sent" and second["delivery"]["status"] == "delivered"


@pytest.mark.parametrize("answer", [
    {"status": "pending", "event": None, "detail": "could not reach Resend"},
    {"status": "mystery", "event": "new_event", "detail": "x"},
    RuntimeError("the library broke"),
])
def test_uncertainty_stays_sent_and_pending(env, answer):
    """A timeout, a fault, an event name we do not know: never `failed`."""
    sends = {"P1": {"email": "p1@example.com", "message_id": "m1", "redirected": False},
             "P2": {"email": "p2@example.com", "message_id": "m2", "redirected": False}}
    with patch.object(ocs.email_service, "delivery_status",
                      side_effect=[answer, answer]), \
         patch.object(ocs.signers, "latest_sends", return_value=sends):
        body = client.get(URL, headers=H).json()
    assert [s["status"] for s in body["signers"]] == ["sent", "sent"]
    assert [s["delivery"]["status"] for s in body["signers"]] == ["pending", "pending"]


def test_a_send_with_no_record_of_its_message_reads_unknown(env):
    with patch.object(ocs.email_service, "delivery_status") as ask, \
         patch.object(ocs.signers, "latest_sends", return_value={}):
        body = client.get(URL, headers=H).json()
    assert [s["status"] for s in body["signers"]] == ["sent", "sent"]
    assert [s["delivery"]["status"] for s in body["signers"]] == ["unknown", "unknown"]
    ask.assert_not_called()


def test_a_signed_signer_is_not_asked_about(env):
    env.state.side_effect = lambda case: _state({**P1, "status": "signed"},
                                                {**P2, "status": "sent"})
    sends = {"P2": {"email": "p2@example.com", "message_id": "m2", "redirected": False}}
    with patch.object(ocs.email_service, "delivery_status",
                      return_value={"status": "delivered", "detail": "arrived"}) as ask, \
         patch.object(ocs.signers, "latest_sends", return_value=sends):
        body = client.get(URL, headers=H).json()
    ask.assert_called_once_with("m2")
    assert body["signers"][0]["delivery"] is None


def test_the_report_writes_nothing(env):
    with patch.object(ocs.signers, "latest_sends", return_value={}):
        client.get(URL, headers=H)
    env.update.assert_not_called()
    env.audit.assert_not_awaited()


def test_an_unknown_case_is_404(env):
    with patch.object(oc.svc, "get_case", side_effect=LookupError("nar1")):
        assert client.get(URL, headers=H).status_code == 404


# -- POST: refusals, in order -----------------------------------------------------------------------

def test_the_option_must_be_on(env):
    env.case = {**CASE, "multi_signer": False}
    resp = _post("P1")
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "multi_signer_off"
    _nothing_went_out(env)


def test_a_closed_case_is_refused(env):
    env.case = {**CASE, "closed_at": "2026-10-01T00:00:00Z"}
    resp = _post("P1")
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "case_closed"
    _nothing_went_out(env)


def test_a_filed_form_is_refused(env):
    with patch.object(ocs, "filed", return_value=True):
        resp = _post("P1")
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "already_filed"
    _nothing_went_out(env)


def test_someone_outside_the_set_is_refused_before_a_round_opens(env):
    resp = _post("P9")
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "not_a_signer"
    _nothing_went_out(env)


def test_someone_outside_the_frozen_set_is_refused_once_it_is_open(env):
    """The live board may have changed since; the frozen set governs the round."""
    env.case = dict(OPEN)
    env.required.return_value = [P1, P2, {"person_id": "P9", "name": "New", "roles": []}]
    resp = _post("P9")
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "not_a_signer"
    _nothing_went_out(env)


def test_a_director_who_has_signed_is_refused(env):
    env.case = dict(OPEN)
    env.rows.return_value = [{"person_id": "P2", "outcome": "approved",
                              "recipient_email": "brian@example.com"}]
    resp = _post("P2")
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "signed"
    _nothing_went_out(env)


def test_a_converged_case_is_refused(env):
    env.case = {**OPEN, "client_approved": True, "client_approval_source": "self_service"}
    resp = _post("P2")
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "converged"
    _nothing_went_out(env)


def test_an_nd2b_waiver_does_not_count_as_converged(env):
    """Signing continues after "proceed without confirmation"; the real thing
    replaces the waiver when the last director signs."""
    env.case = {**OPEN, "form_code": "Nd2b", "client_approved": True,
                "client_approval_source": "staff_waiver"}
    assert _post("P2").status_code == 200


def test_a_declined_case_is_refused(env):
    env.case = {**OPEN, "client_approved": False}
    resp = _post("P2")
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "declined"
    _nothing_went_out(env)


def test_a_round_with_no_frozen_set_is_refused(env):
    env.case = {**OPEN, "required_signers": None}
    resp = _post("P2")
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "round_not_fixed"
    _nothing_went_out(env)


def test_a_breached_company_rule_blocks_the_send(env):
    env.composite.return_value = {**COMPOSITE, "rules": {"blocking": True, "checks": [
        {"code": "has_secretary", "ok": False, "level": "rule",
         "text": "The company would be left without a company secretary."}]}}
    resp = _post("P2")
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "rules_blocking"
    assert "secretary" in resp.json()["detail"]["message"]
    _nothing_went_out(env)


def test_another_directors_address_is_refused(env):
    env.case = dict(OPEN)
    env.rows.return_value = [{"person_id": "P1", "outcome": None,
                              "recipient_email": "Brian@Example.com",
                              "expires_at": "2099-01-01T00:00:00+00:00"}]
    resp = _post("P2")
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "address_in_use"
    _nothing_went_out(env)


def test_a_signed_directors_address_is_refused_too(env):
    env.case = dict(OPEN)
    env.rows.return_value = [{"person_id": "P1", "outcome": "approved",
                              "recipient_email": "brian@example.com"}]
    assert _post("P2").json()["detail"]["reason"] == "address_in_use"


def test_the_same_directors_own_address_is_fine_on_a_resend(env):
    env.case = dict(OPEN)
    env.rows.return_value = [{"person_id": "P2", "outcome": None,
                              "recipient_email": "brian@example.com",
                              "expires_at": "2099-01-01T00:00:00+00:00"}]
    assert _post("P2").status_code == 200


def test_a_dead_or_expired_link_does_not_hold_its_address(env):
    env.case = dict(OPEN)
    env.rows.return_value = [
        {"person_id": "P1", "outcome": "superseded", "recipient_email": "brian@example.com"},
        {"person_id": "P1", "outcome": None, "recipient_email": "brian@example.com",
         "expires_at": "2000-01-01T00:00:00+00:00"}]
    assert _post("P2").status_code == 200


# -- POST: the address and the link ------------------------------------------------------------------

def test_a_deadline_is_required(env):
    resp = _post("P2", body={"email": "brian@example.com"})
    assert resp.status_code == 422
    _nothing_went_out(env)


def test_a_malformed_address_is_refused_and_named(env):
    resp = _post("P2", body={"email": "not an address", "respond_by": "2099-01-01"})
    assert resp.status_code == 422 and "not an address" in resp.json()["detail"]
    _nothing_went_out(env)


def test_an_address_that_cannot_receive_mail_is_refused(env):
    with patch.object(oc.nar1_router, "_undeliverable", new_callable=AsyncMock,
                      return_value={"brian@example.com": "the domain does not exist"}):
        resp = _post("P2")
    assert resp.status_code == 422 and "does not exist" in resp.json()["detail"]
    _nothing_went_out(env)


def test_without_a_link_base_nothing_is_mailed(env):
    with patch.object(oc.nar1_router, "_approval_link_base", return_value=None):
        resp = _post("P2")
    assert resp.status_code == 503 and resp.json()["detail"]["reason"] == "links_unavailable"
    env.send.assert_not_called()
    env.update.assert_not_called()


def test_a_link_that_cannot_be_issued_mails_nothing(env):
    env.issue.side_effect = RuntimeError("insert failed")
    resp = _post("P2")
    assert resp.status_code == 503 and resp.json()["detail"]["reason"] == "links_unavailable"
    env.send.assert_not_called()
    env.update.assert_not_called()
    env.audit.assert_not_awaited()


def test_a_message_resend_refuses_is_a_502_and_opens_no_round(env):
    env.send.side_effect = oc.email_service.EmailError("resend refused it")
    resp = _post("P2")
    assert resp.status_code == 502 and "resend refused it" in resp.json()["detail"]
    env.update.assert_not_called()
    env.audit.assert_not_awaited()


# -- POST: the first send of a round ----------------------------------------------------------------------

def test_the_first_send_opens_the_round(env):
    resp = _post("P2")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["round_opened"] is True and body["revision"] == 1
    assert body["person_id"] == "P2" and body["to"] == ["brian@example.com"]
    # The form is built, the filing created, earlier links cleared.
    env.build.assert_awaited_once()
    env.create_filing.assert_called_once()
    env.supersede_all.assert_called_once_with("K1")
    # One link, for this director, stamped with the revision.
    [issued] = env.issued
    assert issued["recipient"]["person_id"] == "P2" and issued["revision"] == 1
    # Stored: the round's facts and the frozen set.
    written = env.update.call_args.args[1]
    assert written["verification_xml"] == "<built/>"
    assert written["verification_revision"] == 1
    assert written["verification_sent_at"]
    assert written["required_signers"] == [
        {"person_id": "P1", "name": "Jacqueline Koh", "roles": ["resolution"]},
        {"person_id": "P2", "name": "Testing Brian", "roles": ["consent"]}]
    env.deferred.assert_called_once_with("K1")
    # The letter carries this director's own link.
    html_url = env.letter.call_args.kwargs["approval_url"]
    assert html_url == "https://api.test/public/officer-change-approval/tok-P2"


def test_the_first_send_freezes_the_list_it_checked_and_reads_it_once(env):
    """Review A, S5: a second read that faulted would freeze [] and strand the
    round. The send reads the set once and freezes what it checked."""
    env.required.side_effect = [[P1, P2], []]
    resp = _post("P2")
    assert resp.status_code == 200, resp.text
    assert env.required.call_count == 1
    assert [s["person_id"] for s in env.update.call_args.args[1]["required_signers"]] == [
        "P1", "P2"]


def test_the_first_send_never_freezes_an_empty_set(env):
    env.required.return_value = []
    resp = _post("P2")
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "not_a_signer"
    _nothing_went_out(env)


def test_a_restart_leaves_old_approvals_out_of_the_new_round(env):
    """After a restart the revision is unchanged and the old approved rows are
    still in the table. They belong to a round that is over."""
    env.case = {**CASE, "verification_revision": 1}
    env.rows.return_value = [{"person_id": "P2", "outcome": "approved",
                              "recipient_email": "brian@example.com"}]
    resp = _post("P2")
    assert resp.status_code == 200, resp.text
    assert resp.json()["revision"] == 2
    env.rows.assert_not_called()


def test_the_first_send_clears_an_earlier_answer_and_says_so(env):
    env.case = {**CASE, "client_approved": None, "client_response_at": "2026-10-01T00:00:00Z"}
    _post("P2")
    written = env.update.call_args.args[1]
    assert written["client_approved"] is None and written["client_response_at"] is None
    assert "CASE_STATUS_CHANGED" in _actions(env.audit)


def test_the_first_send_audits_the_signer_and_the_round(env):
    _post("P2")
    assert _actions(env.audit) == ["EMAIL_SENT", "CLIENT_APPROVAL_LINK_SENT"]
    email = next(c.kwargs for c in env.audit.await_args_list
                 if c.kwargs["action_type"] == "EMAIL_SENT")
    meta = email["metadata"]
    assert meta["signer_person_id"] == "P2"
    assert meta["multi_signer"] is True and meta["round_opened"] is True
    assert meta["revision"] == 1
    assert meta["deliveries"][0]["person_id"] == "P2"
    assert meta["deliveries"][0]["email"] == "brian@example.com"
    assert "template" not in meta     # the newest-send readers skip templated rows
    link = next(c.kwargs for c in env.audit.await_args_list
                if c.kwargs["action_type"] == "CLIENT_APPROVAL_LINK_SENT")
    assert link["metadata"]["person_id"] == "P2"


def test_the_response_carries_the_director_read_back(env):
    resp = _post("P2")
    body = resp.json()
    assert set(body) >= {"sent_at", "revision", "round_opened", "person_id", "to",
                         "intended_to", "redirected", "message_ids", "deliveries",
                         "failed", "respond_by", "signer"}
    assert body["signer"]["person_id"] == "P2" and body["signer"]["status"] == "sent"
    assert body["deliveries"][0]["person_id"] == "P2"
    assert body["failed"] == []


def test_a_redirected_send_is_reported_as_not_sent(env):
    env.send.side_effect = lambda **k: {"id": "m1", "to": ["levi@zenexflow.com"],
                                        "intended_to": k["to"], "redirected": True}
    body = _post("P2").json()
    assert body["redirected"] is True
    assert body["signer"]["status"] == "redirected"
    assert body["signer"]["delivery"]["status"] == "redirected"


def test_a_failed_readback_does_not_fail_a_send_that_went_out(env):
    env.state.side_effect = RuntimeError("database hiccup")
    resp = _post("P2")
    assert resp.status_code == 200 and resp.json()["signer"] is None


# -- POST: every later send in the round ----------------------------------------------------------------------

def test_a_second_directors_send_reuses_the_frozen_form_and_revision(env):
    env.case = dict(OPEN)
    resp = _post("P2")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["round_opened"] is False and body["revision"] == 1
    # Not rebuilt, filing untouched, no earlier link cleared, nothing written.
    env.build.assert_not_awaited()
    env.create_filing.assert_not_called()
    env.supersede_all.assert_not_called()
    env.update.assert_not_called()
    env.deferred.assert_not_called()
    # The frozen XML is what gets rendered, under the same revision.
    assert env.render.await_args.args[1] == "<frozen/>"
    [issued] = env.issued
    assert issued["revision"] == 1 and issued["recipient"]["person_id"] == "P2"
    assert env.letter.call_args.kwargs["revision"] == 1


def test_a_resend_to_the_same_director_issues_a_fresh_link_for_them_only(env):
    env.case = dict(OPEN)
    assert _post("P1", body={"email": "jkoh@example.com",
                             "respond_by": "2099-01-01"}).status_code == 200
    [issued] = env.issued
    assert issued["recipient"]["person_id"] == "P1"
    # The only thing that retires links is the per-person function inside
    # issue_for_signer; the whole-case one must stay uncalled.
    env.supersede_all.assert_not_called()


def test_a_later_send_audits_round_opened_false(env):
    env.case = dict(OPEN)
    _post("P2")
    email = next(c.kwargs for c in env.audit.await_args_list
                 if c.kwargs["action_type"] == "EMAIL_SENT")
    assert email["metadata"]["round_opened"] is False
    assert email["metadata"]["signer_person_id"] == "P2"
    assert email["metadata"]["revision"] == 1


# -- the draft is never stamped ----------------------------------------------------------------------------------

@pytest.mark.parametrize("case", [dict(CASE), dict(OPEN)], ids=["first", "later"])
def test_the_form_is_rendered_without_signatures(env, case):
    env.case = case
    with patch.object(oc.signed_copies, "for_form") as for_form, \
         patch.object(oc.signatures, "images_for") as images_for:
        assert _post("P2").status_code == 200
    for_form.assert_not_called()
    images_for.assert_not_called()
    assert "signatures" not in env.render.await_args.kwargs
    assert env.render.await_args.kwargs["public_only"] is False


def test_the_single_mode_deliveries_do_not_gain_a_person_id(env):
    """The shared audit helper adds `person_id` only for the per-director send;
    today's rows are read by the NAR1 delivery check and stay as they were."""
    targets = [{"email": "a@example.com", "person_id": "PX", "name": "A", "token": "t",
                "expires_at": None}]
    sends = [{"target": targets[0], "sent": {"id": "m1", "to": ["a@example.com"]}}]
    import asyncio
    with patch.object(oc, "log_event", new_callable=AsyncMock) as log:
        asyncio.run(oc._audit_send(
            {"id": "K1", "form_code": "Nd2a"}, ADMIN, sends, [], revision=1,
            deadline_at=__import__("datetime").datetime(2099, 1, 1), names=[],
            superseded=0))
    meta = log.await_args_list[0].kwargs["metadata"]
    assert "person_id" not in meta["deliveries"][0]
