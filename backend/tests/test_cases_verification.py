"""BE-3 — client verification send / response.

R1 has no inbound mail handling and no client-facing endpoint: the client
replies to a human, and an admin records the answer through
POST /cases/{id}/verification/response. Both routes are staff-only
(`nar1:write`) — there is no token, no magic link and nothing an unauthenticated
caller can reach, which is the whole reason this flow has no security surface to
get wrong.
"""
import datetime as _dt
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from services import email_service

#: The fixed copy on every client-facing message. Read from the module rather
#: than retyped, so a test cannot keep passing against an address the code no
#: longer uses.
CLIENT_CC = email_service.CLIENT_CC

SUPER = {"id": "u1", "display_name": "Levi", "role_name": "super_admin",
         "role_id": "role-sa"}
REGULAR = {"id": "u2", "display_name": "Staff", "role_name": "staff",
           "role_id": "role-x"}
H = {"Authorization": "Bearer tok"}

#: The response deadline is MANDATORY on every send (Levi 2026-09-07), so it is
#: part of the minimum body rather than something individual tests remember.
#:
#: RELATIVE TO TODAY, not a literal date. The route refuses a deadline in the
#: past, so a hardcoded 2026 date would turn this whole file red on a calendar
#: boundary rather than on a code change — the same trap `_TODAY` avoids in
#: tests/tpsi/test_submit_gate.py.
_RESPOND_BY = (_dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8))).date()
               + _dt.timedelta(days=21))
SEND = {"respond_by": _RESPOND_BY.isoformat()}


def _super():
    return patch("middleware.auth._resolve_user", return_value=SUPER)


@pytest.fixture(autouse=True)
def _approval_tokens():
    """Spec §5 issues one approval token per recipient inside the send.

    Stubbed for the WHOLE file, because the real one writes to Supabase: left
    unpatched it reached the live DEV database from a unit test — which is the
    exact "green locally, red in CI, and meanwhile mutating a real environment"
    failure this repo has already been bitten by twice.

    The stub returns a deterministic token per recipient so the link that lands
    in the email body is assertable, and keeps the shape `issue` returns.
    """
    def issue(*, case_id, recipients, sent_at=None, expires_at=None):
        # ECHOES `expires_at` BACK. The route now passes the operator's chosen
        # deadline down, and a stub that ignored it would let the email print a
        # date nobody picked while every test still passed.
        return [{**r, "token": f"tok-{i}",
                 "expires_at": expires_at or "2026-09-15T00:00:00+00:00"}
                for i, r in enumerate(recipients)]

    with patch("routers.cases.nar1_approvals.issue", side_effect=issue),          patch("routers.cases.nar1_approvals.supersede_outstanding",
               return_value=0):
        yield


def _addresses_sent(send):
    """Every address the transport was handed, across all its calls.

    Spec §5 made this ONE MESSAGE PER RECIPIENT, so `call_args` (the last call)
    now sees only the last director. A test reading it would report a three-
    director send as a one-director send and pass while doing so.
    """
    return [address
            for call in send.call_args_list
            for address in call.kwargs["to"]]


@pytest.fixture
def client():
    return TestClient(app)


CASE = {"id": "c1", "case_no": "NAR-2026-0041", "entity_id": "e1",
        "verification_sent_at": None, "client_approved": None,
        "client_response_at": None}

VALIDATED = {"id": "f1", "form_code": "Nar1", "stage": "validated",
             "validated_xml": "<x/>", "validated_at": "2026-08-16T00:00:00Z"}

ENTITY = {"id": "e1", "company_name": "ACME LIMITED", "br_number": "00000001"}


#: A board, as `nar1_cases.default_recipients` returns one. Two directors who
#: can be written to and one who cannot — the shape the send route has to get
#: right, and the shape the picker renders.
BOARD = [
    {"person_id": "p1", "name": "AH CHAN", "email": "chan@example.com",
     "role": "director", "party_type": "individual", "reason": None},
    {"person_id": "p2", "name": "BO LEE", "email": "lee@example.com",
     "role": "director", "party_type": "individual", "reason": None},
    {"person_id": None, "name": "HOLDCO LIMITED", "email": None,
     "role": "director", "party_type": "corporate",
     "reason": "a corporate director has no address on record"},
]


def _sendable(case=None, filing=None, recipient="client@example.com",
              directors=()):
    """Every collaborator of a successful send, patched at the module boundary.

    `directors` defaults to EMPTY, not to BOARD: most of these tests are about
    the company-contact fallback, and a default board would silently take that
    path away from every one of them.
    """
    return [
        patch("routers.cases.nar1_cases.get_case", return_value=case or CASE),
        patch("routers.cases.nar1_cases.current_filing",
              return_value=filing if filing is not None else VALIDATED),
        patch("routers.cases.nar1_cases.default_recipients",
              return_value=list(directors)),
        patch("routers.cases.nar1_cases.recipient_email", return_value=recipient),
        patch("routers.cases.nar1_cases.entity_for", return_value=ENTITY),
        patch("routers.cases.nar1_form_fill.render", return_value=b"%PDF-1.4"),
    ]


class _Stack:
    """with _Stack(a, b, c): — the patch lists above get long."""

    def __init__(self, *managers):
        self._managers = managers

    def __enter__(self):
        self._entered = [m.__enter__() for m in self._managers]
        return self._entered

    def __exit__(self, *exc):
        for m in reversed(self._managers):
            m.__exit__(*exc)
        return False


# ---------------------------------------------------------------------------
# send
# ---------------------------------------------------------------------------


def test_send_attaches_the_pdf_rendered_from_the_validated_xml(client):
    """The client approves what CR is holding, not what the profile says today."""
    with _super(), _Stack(*_sendable()), \
         patch("routers.cases.email_service.send",
               return_value={"id": "m1", "to": ["client@example.com"],
                             "intended_to": ["client@example.com"],
                             "redirected": False}) as send, \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.post("/cases/c1/verification/send", headers=H, json=SEND)
    assert response.status_code == 200
    assert send.call_args.kwargs["attachments"][0][1] == b"%PDF-1.4"
    assert send.call_args.kwargs["to"] == ["client@example.com"]


def test_send_renders_the_CR_validated_snapshot_on_CRs_own_form(client):
    """Levi 2026-08-30: the client is emailed Form NAR1 itself, not a summary.

    THIS DROPPED A PROVENANCE FOOTER. The old renderer stamped `validated_at`
    and `stage` on the page so a snapshot CR had since rejected could be told
    from a fresh one. CR's printed form has nowhere to put that, and an
    internal workflow stage is not something to print on a client's statutory
    return anyway. The facts did not disappear — the Submission stage shows
    them on screen, where the admin who needs them is looking.
    """
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value=CASE), \
         patch("routers.cases.nar1_cases.current_filing", return_value=VALIDATED), \
         patch("routers.cases.nar1_cases.default_recipients", return_value=[]), \
         patch("routers.cases.nar1_cases.recipient_email",
               return_value="client@example.com"), \
         patch("routers.cases.nar1_cases.entity_for", return_value=ENTITY), \
         patch("routers.cases.nar1_form_fill.render", return_value=b"%PDF") as render, \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}), \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        client.post("/cases/c1/verification/send", headers=H, json=SEND)
    # The CR-validated snapshot, never the live profile: showing a client one
    # document and filing another is the failure this guards.
    assert render.call_args.args[0] == "<x/>"
    assert "validated_at" not in render.call_args.kwargs
    assert "stage" not in render.call_args.kwargs


def test_send_is_refused_before_cr_validation(client):
    """Sending a client a form CR has not validated asks them to approve
    something that may be rejected minutes later."""
    draft = {"id": "f1", "form_code": "Nar1", "stage": "draft",
             "validated_xml": None}
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value=CASE), \
         patch("routers.cases.nar1_cases.current_filing", return_value=draft):
        response = client.post("/cases/c1/verification/send", headers=H, json=SEND)
    assert response.status_code == 409


def test_send_is_refused_when_no_filing_exists_at_all(client):
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value=CASE), \
         patch("routers.cases.nar1_cases.current_filing", return_value=None):
        response = client.post("/cases/c1/verification/send", headers=H, json=SEND)
    assert response.status_code == 409


def test_send_is_refused_when_the_latest_validation_failed(client):
    """THE STALE-SNAPSHOT HOLE. filings.validate() only sets stage on failure —
    it leaves the PREVIOUS validated_xml in place. So a filing CR has just
    rejected still satisfies "has validated_xml", and a gate that checks only
    that would mail the client a form CR is no longer holding."""
    stale = {"id": "f1", "form_code": "Nar1", "stage": "validation_failed",
             "validated_xml": "<x/>", "validated_at": "2026-08-01T00:00:00Z"}
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value=CASE), \
         patch("routers.cases.nar1_cases.current_filing", return_value=stale):
        response = client.post("/cases/c1/verification/send", headers=H, json=SEND)
    assert response.status_code == 409
    assert "validation" in response.json()["detail"].lower()


def test_send_is_refused_for_a_form_that_is_not_nar1(client):
    """There is one renderer and it is a NAR1 renderer. Fed an Nd2a it would not
    fail — it would emit a document headed Form NAR1."""
    other = {"id": "f1", "form_code": "Nd2a", "stage": "validated",
             "validated_xml": "<x/>"}
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value=CASE), \
         patch("routers.cases.nar1_cases.current_filing", return_value=other):
        response = client.post("/cases/c1/verification/send", headers=H, json=SEND)
    assert response.status_code == 409


def test_send_is_refused_once_the_return_is_already_filed(client):
    """Asking a client to approve a return CR already holds is a false request:
    their answer can change nothing."""
    filed = {"id": "f1", "form_code": "Nar1", "stage": "submitted",
             "validated_xml": "<x/>"}
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value=CASE), \
         patch("routers.cases.nar1_cases.current_filing", return_value=filed):
        response = client.post("/cases/c1/verification/send", headers=H, json=SEND)
    assert response.status_code == 409


def test_send_is_refused_when_the_case_was_completed_off_portal(client):
    done = {**CASE, "manual_receipt": {"caseNo": "X"}}
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value=done), \
         patch("routers.cases.nar1_cases.current_filing", return_value=VALIDATED):
        response = client.post("/cases/c1/verification/send", headers=H, json=SEND)
    assert response.status_code == 409


def test_send_is_refused_when_no_recipient_is_on_record(client):
    with _super(), _Stack(*_sendable(recipient=None)):
        response = client.post("/cases/c1/verification/send", headers=H, json=SEND)
    assert response.status_code == 409


def test_an_explicit_recipient_overrides_the_address_on_record(client):
    """A bare string is still accepted — it is what this route shipped with."""
    with _super(), _Stack(*_sendable()), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}) as send, \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.post("/cases/c1/verification/send", headers=H,
                               json={**SEND, "to": "other@example.com"})
    assert response.status_code == 200
    assert send.call_args.kwargs["to"] == ["other@example.com"]


def test_a_recipient_override_that_is_not_an_address_is_refused(client):
    """The override directs a document carrying directors' residential addresses
    and identity numbers. Free text is not an address."""
    with _super(), _Stack(*_sendable()):
        response = client.post("/cases/c1/verification/send", headers=H,
                               json={**SEND, "to": "not-an-address"})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Multiple recipients — a board is one message with three addresses on it
# ---------------------------------------------------------------------------


def _ok_send(**extra):
    return patch("routers.cases.email_service.send",
                 return_value={"id": "m1", "redirected": False, **extra})


def test_every_director_with_an_address_is_mailed_by_default(client):
    """Three directors, two reachable — BOTH are written to.

    A send that reached only the first director would look identical on screen
    to one that reached all of them, which is why this is asserted on the list
    the transport was handed rather than on the response.
    """
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         patch("routers.cases.email_service.send",
               return_value={"id": "m1"}) as send, \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.post("/cases/c1/verification/send", headers=H, json=SEND)
    assert response.status_code == 200
    assert _addresses_sent(send) == ["chan@example.com", "lee@example.com"]


def test_the_company_address_is_used_only_when_no_director_has_one(client):
    """The fallback must not FIRE alongside the directors — the company contact
    is a substitute for a board with no addresses, not an extra copy."""
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}) as send, \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        client.post("/cases/c1/verification/send", headers=H, json=SEND)
    assert "client@example.com" not in _addresses_sent(send)


def test_an_explicit_list_is_sent_verbatim(client):
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}) as send, \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.post(
            "/cases/c1/verification/send", headers=H,
            json={**SEND, "to": ["a@example.com", "b@example.com", "c@example.com"]})
    assert response.status_code == 200
    assert _addresses_sent(send) == [
        "a@example.com", "b@example.com", "c@example.com"]


def test_an_explicit_list_is_not_topped_up_with_the_directors(client):
    """THE REASON THE FRONTEND ALWAYS POSTS A LIST. An operator who removed a
    director from the chips must not have them added back by the server."""
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}) as send, \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        client.post("/cases/c1/verification/send", headers=H,
                    json={**SEND, "to": ["chan@example.com"]})
    assert _addresses_sent(send) == ["chan@example.com"]


# ---------------------------------------------------------------------------
# The SHARED RENEWALS MAILBOX is copied, and the client's reply is aimed at
# the case worker
#
# Levi 2026-09-08: "right now the person that triggers sending the email in
# gflowdesk is also in cc to the email that is sent to client. this is the
# wrong behavior... for all emails to client we should cc a fixed email
# address: renewal@getstarted.hk".
#
# This REVERSES Levi 2026-08-30 ("whoever is logged in should be in the cc as
# well.. so that the person who is working on the case can get an email"). The
# reply path is unchanged and still reaches that person — what moved is the
# COPY, from an individual's mailbox to the team's.
# ---------------------------------------------------------------------------

#: The same super admin, but resolved with the address they signed in with.
#: `middleware.auth._resolve_user` grew that key on 2026-08-30.
SUPER_MAILED = {**SUPER, "email": "levi@zenexflow.com"}


def _super_mailed():
    return patch("middleware.auth._resolve_user", return_value=SUPER_MAILED)


def _send_as_operator(client, json=None, user=None):
    """POST the send as a signed-in operator; return the mocked transport."""
    with patch("middleware.auth._resolve_user", return_value=user or SUPER_MAILED), \
         _Stack(*_sendable(directors=BOARD)), \
         patch("routers.cases.email_service.send",
               return_value={"id": "m1", "cc": [CLIENT_CC],
                             "intended_cc": [CLIENT_CC]}) as send, \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.post("/cases/c1/verification/send", headers=H,
                               json={**SEND, **(json or {})})
    return send, response


def test_the_shared_renewals_mailbox_is_copied_not_the_logged_in_user(client):
    """The whole point of Levi's 2026-09-08 change. The client must not see an
    individual staff member's address on a letter about their statutory
    return, and GSHK's record of what it told that client must not live in one
    person's mailbox."""
    send, response = _send_as_operator(client)
    assert response.status_code == 200
    copies = [c.kwargs["cc"] for c in send.call_args_list]
    assert copies == [[CLIENT_CC], [CLIENT_CC]]
    # The operator signed in as levi@zenexflow.com. That address must appear on
    # no CC line anywhere — asserted explicitly rather than inferred from the
    # equality above, because THIS is the behaviour that was reported wrong.
    assert not any("levi@zenexflow.com" in (c or []) for c in copies)


def test_the_copy_is_on_EVERY_message_not_just_the_first(client):
    """The case worker's copy went on the first message only, so three
    directors did not mean three identical mails in one inbox. That reasoning
    does not carry over: these messages are not identical (each carries its own
    approval link), and a shared mailbox holding the first of three would
    misrepresent a partial send as a complete one."""
    send, _ = _send_as_operator(client)
    assert len(send.call_args_list) == 2
    assert all(c.kwargs["cc"] == [CLIENT_CC] for c in send.call_args_list)


def test_the_reply_address_is_the_case_worker_on_every_message(client):
    """`reply_to` is the load-bearing half and is DELIBERATELY UNCHANGED by the
    CC move. The message asks the client to reply and is sent from
    no-reply@getstarted.hk, so the reply must reach a human who knows the case
    — the copy going to the team while the answer goes to a person is the
    intended split."""
    send, _ = _send_as_operator(client)
    assert {c.kwargs["reply_to"] for c in send.call_args_list} == {
        "levi@zenexflow.com"}


def test_each_director_gets_their_OWN_approval_link(client):
    """The whole reason this became one message per recipient: a shared link in
    a shared message would let any director approve in another's name, which is
    a misattribution in a statutory record."""
    send, _ = _send_as_operator(client)
    links = [c.kwargs["html"] for c in send.call_args_list]
    assert len(links) == 2
    assert "nar1-approval/tok-0" in links[0]
    assert "nar1-approval/tok-1" in links[1]
    # And neither carries the other's.
    assert "tok-1" not in links[0]
    assert "tok-0" not in links[1]


def test_the_clients_reply_is_aimed_at_the_person_who_sent_it(client):
    """The message ASKS for a reply and is sent from no-reply@getstarted.hk.
    Without reply_to, the one action it requests goes nowhere."""
    send, _ = _send_as_operator(client)
    assert send.call_args.kwargs["reply_to"] == "levi@zenexflow.com"


def test_a_send_still_works_for_an_identity_carrying_no_address(client):
    """`email` is new on the auth dict, and identities are CACHED for 30s. A
    send must not start failing because it resolved from a cache written
    before the key existed."""
    send, response = _send_as_operator(client, user=SUPER)
    assert response.status_code == 200
    # The COPY no longer depends on the identity at all, which is the point:
    # an identity with no address used to mean the message went out with
    # nobody copied. The renewals mailbox is copied either way.
    assert send.call_args.kwargs["cc"] == [CLIENT_CC]
    # Only the reply address is still the operator's, and it is legitimately
    # absent here — there is no address to aim the reply at.
    assert send.call_args.kwargs["reply_to"] is None


def test_the_copy_is_recorded_in_the_audit_row(client):
    """Both `cc` and `intended_cc`: on a test deployment the copy is DROPPED,
    and a trail recording only the intention would claim the renewals mailbox
    was copied when nothing reached it."""
    with _super_mailed(), _Stack(*_sendable(directors=BOARD)), \
         patch("routers.cases.email_service.send",
               return_value={"id": "m1", "cc": [],
                             "intended_cc": [CLIENT_CC],
                             "redirected": True}), \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()) as log:
        client.post("/cases/c1/verification/send", headers=H, json=SEND)
    meta = log.await_args_list[0].kwargs["metadata"]
    assert meta["cc"] == []
    assert meta["intended_cc"] == [CLIENT_CC]


def test_the_attachment_name_is_the_one_the_email_announces(client):
    """The body names the attached file. If the two were built separately they
    would drift, and the message would point at a filename that is not there."""
    with _super_mailed(), _Stack(*_sendable(directors=BOARD)), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}) as send, \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        client.post("/cases/c1/verification/send", headers=H, json=SEND)
    name = send.call_args.kwargs["attachments"][0][0]
    assert name == "NAR1-NAR-2026-0041.pdf"
    assert name in send.call_args.kwargs["html"]


def test_an_empty_list_is_refused_rather_than_treated_as_absent(client):
    """`[]` says the operator cleared every chip. Falling back to the directors
    would mail the people they had just removed."""
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         patch("routers.cases.email_service.send") as send, \
         patch("routers.cases.nar1_cases.update_case") as update:
        response = client.post("/cases/c1/verification/send", headers=H,
                               json={**SEND, "to": []})
    assert response.status_code == 422
    send.assert_not_called()
    update.assert_not_called()


def test_one_bad_address_no_longer_refuses_the_whole_send(client):
    """REVERSES "the operator asked for a set" (Levi 2026-09-07).

    That reasoning held while this route sent ONE message to several addresses,
    where a partial send really was indistinguishable from a complete one. Spec
    §5 made it one message per director, so the other two directors can be told
    and there is never a reason not to — what was actually happening was that a
    typo in the third chip left a whole board unmailed.

    The bad address is named, with its reason, in the same report as anything
    Resend rejects: the operator's question is "who did not get it".
    """
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}) as send, \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.post("/cases/c1/verification/send", headers=H,
                               json={**SEND, "to": ["good@example.com", "nope"]})

    assert response.status_code == 200
    body = response.json()
    # The good one went, and is reported as delivered.
    assert _addresses_sent(send) == ["good@example.com"]
    assert body["to"] == ["good@example.com"]
    # The bad one did not, is named, and says WHY — "not a valid email address"
    # is fixed by editing the chip; a provider rejection is fixed by pressing
    # Send again, and the operator must be able to tell those apart.
    assert body["failed_to"] == ["nope"]
    assert body["failed"] == [
        {"email": "nope", "reason": "not a valid email address"}]


def test_a_malformed_address_is_never_handed_to_the_transport(client):
    """The check is exactly as strict as it was. What changed is what happens
    to the REST of the board — not whether free text can reach Resend."""
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}) as send, \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        client.post("/cases/c1/verification/send", headers=H,
                    json={**SEND, "to": ["good@example.com", "please send to Mary"]})

    assert "please send to Mary" not in _addresses_sent(send)


def test_a_list_of_nothing_but_bad_addresses_is_still_refused(client):
    """There is no partial success to report, so this stays a refusal — and it
    names the addresses, so the operator knows which chips to fix."""
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         patch("routers.cases.email_service.send") as send, \
         patch("routers.cases.nar1_cases.update_case") as update:
        response = client.post("/cases/c1/verification/send", headers=H,
                               json={**SEND, "to": ["nope", "also-bad"]})

    assert response.status_code == 422
    assert "nope" in response.json()["detail"]
    assert "also-bad" in response.json()["detail"]
    send.assert_not_called()
    # NOTHING is marked sent: a case that says it went out while waiting on a
    # reply to nothing sits in Awaiting Client forever.
    update.assert_not_called()


def test_the_failed_addresses_and_their_reasons_are_audited(client):
    """`failed_to` alone made a reader guess whether an address was rejected by
    Resend or was never an address at all."""
    logged = AsyncMock()
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}), \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=logged):
        client.post("/cases/c1/verification/send", headers=H,
                    json={**SEND, "to": ["good@example.com", "nope"]})

    email_rows = [c for c in logged.await_args_list
                  if c.kwargs.get("action_type") == "EMAIL_SENT"]
    assert email_rows
    meta = email_rows[0].kwargs["metadata"]
    assert meta["failed_to"] == ["nope"]
    assert meta["failed"] == [
        {"email": "nope", "reason": "not a valid email address"}]


# ---------------------------------------------------------------------------
# An address whose DOMAIN cannot receive mail (Levi 2026-09-08)
#
# "I sent an email to an address that clearly does not exist... but I am still
# not getting an error on the client verification page to say that the email to
# this address failed to send."
#
# Resend answers 200 for anything syntactically valid and bounces it out of
# band, minutes later, so `EmailError` never fired and the screen reported
# total success. What IS knowable before sending is whether the domain accepts
# mail at all, and that is what these cover.
# ---------------------------------------------------------------------------

def _dns_rejects(*domains, reason=None):
    """Patch the DNS probe so addresses at `domains` come back undeliverable.

    Keyed by DOMAIN, because that is the question the probe actually asks —
    one lookup per domain, never one per address. The autouse `_no_dns_in_tests`
    fixture patches the same name to return None; this overrides it for the
    tests that want a specific answer, and neither touches the network.
    """
    def probe(address):
        domain = address.rsplit("@", 1)[-1].lower()
        if domain in domains:
            return reason or f"The domain name {domain} does not exist."
        return None
    return patch("services.email_service.undeliverable_reason",
                 side_effect=probe)


def test_an_address_whose_domain_does_not_exist_is_reported_as_failed(client):
    """THE REPORTED FAULT. This used to return a clean 200 naming nothing: the
    address was well-formed, so the syntax gate passed it, and Resend accepted
    it, so there was no EmailError to catch."""
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         _dns_rejects("nosuchdomain.invalid"), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}) as send, \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.post(
            "/cases/c1/verification/send", headers=H,
            json={**SEND, "to": ["good@example.com",
                                 "ghost@nosuchdomain.invalid"]})

    assert response.status_code == 200
    body = response.json()
    # It was never handed to the transport — there is no point paying for a
    # send that can only bounce.
    assert _addresses_sent(send) == ["good@example.com"]
    assert body["failed_to"] == ["ghost@nosuchdomain.invalid"]
    assert body["failed"] == [{
        "email": "ghost@nosuchdomain.invalid",
        "reason": "The domain name nosuchdomain.invalid does not exist."}]


def test_the_report_also_names_who_DID_receive_it(client):
    """Levi asked for this in the same breath as the failure: "The message
    should also indicate what other emails were successful, so that there is no
    doubt that there were other successful emails." A report naming only the
    failure makes re-sending to the whole board look like the safe move, which
    puts a second request in front of a director who already has one."""
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         _dns_rejects("nosuchdomain.invalid"), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}), \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.post(
            "/cases/c1/verification/send", headers=H,
            json={**SEND, "to": ["chan@example.com", "lee@example.com",
                                 "ghost@nosuchdomain.invalid"]})

    body = response.json()
    assert body["to"] == ["chan@example.com", "lee@example.com"]
    assert body["failed_to"] == ["ghost@nosuchdomain.invalid"]
    # And the case IS marked sent, because two directors really were told.
    assert body["sent_at"]


def test_a_DIRECTOR_address_on_a_dead_domain_is_checked_too(client):
    """The gap this closed. The syntax gate only ever ran on addresses an
    OPERATOR typed, so a director address that came out of Viewpoint years ago
    on a since-lapsed domain went to Resend completely unexamined. "Who did not
    get it" must not depend on which branch supplied the address."""
    board = [{"person_id": "p1", "name": "CHAN", "given_names": "Tai Man",
              "email": "chan@deadco.invalid"},
             {"person_id": "p2", "name": "LEE", "given_names": "Siu Ming",
              "email": "lee@example.com"}]
    with _super(), _Stack(*_sendable(directors=board)), \
         _dns_rejects("deadco.invalid"), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}) as send, \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        # NO "to" in the body — the default-recipients branch.
        response = client.post("/cases/c1/verification/send", headers=H,
                               json=SEND)

    assert response.status_code == 200
    assert _addresses_sent(send) == ["lee@example.com"]
    assert response.json()["failed_to"] == ["chan@deadco.invalid"]


def test_a_board_whose_every_domain_is_dead_is_refused_with_the_reasons(client):
    """No partial success to report, so it stays a refusal — and it names the
    addresses AND why, because this refusal is the only thing the operator
    sees and "nothing was sent" alone is not actionable."""
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         _dns_rejects("nosuchdomain.invalid", "alsogone.invalid"), \
         patch("routers.cases.email_service.send") as send, \
         patch("routers.cases.nar1_cases.update_case") as update:
        response = client.post(
            "/cases/c1/verification/send", headers=H,
            json={**SEND, "to": ["a@nosuchdomain.invalid",
                                 "b@alsogone.invalid"]})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "a@nosuchdomain.invalid" in detail
    assert "b@alsogone.invalid" in detail
    assert "does not exist" in detail
    send.assert_not_called()
    # Nothing is marked sent: a case that says it went out while waiting on a
    # reply to nothing sits in Awaiting Client forever.
    update.assert_not_called()


def test_a_malformed_chip_and_a_dead_domain_land_in_ONE_report(client):
    """Two different ways to be unreachable, one question: "who did not get
    it". The operator must not have to read two lists."""
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         _dns_rejects("nosuchdomain.invalid"), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}), \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.post(
            "/cases/c1/verification/send", headers=H,
            json={**SEND, "to": ["good@example.com", "nope",
                                 "ghost@nosuchdomain.invalid"]})

    body = response.json()
    assert sorted(body["failed_to"]) == ["ghost@nosuchdomain.invalid", "nope"]
    reasons = {f["email"]: f["reason"] for f in body["failed"]}
    assert reasons["nope"] == "not a valid email address"
    assert "does not exist" in reasons["ghost@nosuchdomain.invalid"]


def test_the_dead_domain_and_its_reason_are_audited(client):
    """The trail answers "who was told" and must not imply a bounce-to-be was
    a delivery."""
    logged = AsyncMock()
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         _dns_rejects("nosuchdomain.invalid"), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}), \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=logged):
        client.post("/cases/c1/verification/send", headers=H,
                    json={**SEND, "to": ["good@example.com",
                                         "ghost@nosuchdomain.invalid"]})

    meta = [c for c in logged.await_args_list
            if c.kwargs.get("action_type") == "EMAIL_SENT"][0].kwargs["metadata"]
    assert meta["failed_to"] == ["ghost@nosuchdomain.invalid"]
    assert "does not exist" in meta["failed"][0]["reason"]
    # And the delivered address is still the one recorded as told.
    assert meta["intended_to"] == ["good@example.com"]


def test_one_dns_lookup_per_DOMAIN_not_per_address(client):
    """A board of five directors at the same company asks one question. Asking
    it five times puts four needless round-trips in front of an operator who is
    watching a spinner."""
    probe = MagicMock(return_value=None)
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         patch("services.email_service.undeliverable_reason", new=probe), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}), \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        client.post("/cases/c1/verification/send", headers=H,
                    json={**SEND, "to": ["a@example.com", "b@example.com",
                                         "c@example.com", "d@other.test"]})

    domains = sorted(c.args[0].rsplit("@", 1)[-1] for c in probe.call_args_list)
    assert domains == ["example.com", "other.test"]


def test_an_uncertain_dns_answer_lets_the_message_through(client):
    """SILENCE IS PERMISSION. A timeout, a resolver that will not answer, no
    network at all — every one of those returns None from the probe and the
    send proceeds. A wrongly withheld verification email stalls a statutory
    filing on a director who was never written to, which is far worse than a
    bounce."""
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         patch("services.email_service.undeliverable_reason", return_value=None), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}) as send, \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.post(
            "/cases/c1/verification/send", headers=H,
            json={**SEND, "to": ["unknown@whoknows.invalid"]})

    assert response.status_code == 200
    assert _addresses_sent(send) == ["unknown@whoknows.invalid"]
    assert response.json()["failed"] == []


# ---------------------------------------------------------------------------
# The response deadline — mandatory, and the operator's own (Levi 2026-09-07)
# ---------------------------------------------------------------------------


def test_a_send_without_a_deadline_is_refused(client):
    """It used to default to `sent + 14 days`, chosen by nobody. Some clients
    are chased inside a week; a return prepared months before its filing window
    should not have its link die long before anyone intends to file."""
    with _super(), _Stack(*_sendable()), \
         patch("routers.cases.email_service.send") as send, \
         patch("routers.cases.nar1_cases.update_case") as update:
        response = client.post("/cases/c1/verification/send", headers=H, json={})

    assert response.status_code == 422
    assert "deadline" in response.json()["detail"]
    # Refused BEFORE the 15-page AcroForm is filled and before anything is
    # marked sent.
    send.assert_not_called()
    update.assert_not_called()


def test_a_deadline_in_the_past_is_refused(client):
    """The link would be dead on arrival, and `jobs.auto_approve_nar1` would
    approve the return on the client's "silence" the same night — recording
    consent from somebody who never had time to answer."""
    yesterday = (_RESPOND_BY - _dt.timedelta(days=22)).isoformat()
    with _super(), _Stack(*_sendable()), \
         patch("routers.cases.email_service.send") as send:
        response = client.post("/cases/c1/verification/send", headers=H,
                               json={"respond_by": yesterday})

    assert response.status_code == 422
    assert "past" in response.json()["detail"]
    send.assert_not_called()


def test_a_deadline_that_is_not_a_date_is_refused(client):
    with _super(), _Stack(*_sendable()), \
         patch("routers.cases.email_service.send") as send:
        response = client.post("/cases/c1/verification/send", headers=H,
                               json={"respond_by": "next Tuesday"})
    assert response.status_code == 422
    send.assert_not_called()


def test_the_chosen_deadline_is_what_the_tokens_expire_on(client):
    """ONE VALUE, THREE JOBS: the date the email prints, the moment the link
    dies, and the moment the auto-approval job reads silence as consent. They
    are one argument precisely so the message cannot promise a date the job
    does not honour."""
    issued = {}

    def issue(*, case_id, recipients, sent_at=None, expires_at=None):
        issued["expires_at"] = expires_at
        return [{**r, "token": "tok", "expires_at": expires_at}
                for r in recipients]

    with _super(), _Stack(*_sendable()), \
         patch("routers.cases.nar1_approvals.issue", side_effect=issue), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}), \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.post("/cases/c1/verification/send", headers=H, json=SEND)

    assert response.status_code == 200
    # The END of the chosen day in Hong Kong. A client told "by 20 September"
    # has until that day is over — expiring at midnight UTC would kill the link
    # at 08:00 on the morning of the day they were given.
    assert issued["expires_at"].date().isoformat() >= _RESPOND_BY.isoformat()
    assert issued["expires_at"].astimezone(
        _dt.timezone(_dt.timedelta(hours=8))).date() == _RESPOND_BY
    assert response.json()["respond_by"] == issued["expires_at"].isoformat()


def test_the_chosen_deadline_is_the_date_the_client_is_given(client):
    """The letter's "if we do not hear from you by ..." sentence — the whole
    reason the field exists."""
    with _super(), _Stack(*_sendable()), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}) as send, \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        client.post("/cases/c1/verification/send", headers=H, json=SEND)

    html = send.call_args.kwargs["html"]
    assert _RESPOND_BY.strftime("%d %B %Y") in html


def test_addresses_differing_only_in_case_are_one_recipient(client):
    """Resend would otherwise deliver the statutory return to one mailbox
    twice."""
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}) as send, \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        client.post("/cases/c1/verification/send", headers=H,
                    json={**SEND, "to": ["Chan@Example.com", "chan@example.com"]})
    assert _addresses_sent(send) == ["Chan@Example.com"]


def test_too_many_recipients_is_refused(client):
    from routers.cases import MAX_RECIPIENTS
    many = [f"d{i}@example.com" for i in range(MAX_RECIPIENTS + 1)]
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         patch("routers.cases.email_service.send") as send:
        response = client.post("/cases/c1/verification/send", headers=H,
                               json={**SEND, "to": many})
    assert response.status_code == 422
    send.assert_not_called()


def test_the_refusal_names_directors_as_well_as_the_company(client):
    """The operator's next move is to find an address. A message that mentions
    only the company sends them to the wrong screen."""
    with _super(), _Stack(*_sendable(recipient=None, directors=[BOARD[2]])):
        response = client.post("/cases/c1/verification/send", headers=H, json=SEND)
    assert response.status_code == 409
    assert "director" in response.json()["detail"].lower()


def test_the_trail_names_every_recipient_not_just_the_first(client):
    """`new_value` is what the audit screen renders. A row naming one of three
    directors is worse than one naming none — it looks complete."""
    logged = []

    async def fake_log(**kwargs):
        logged.append(kwargs)

    with _super(), _Stack(*_sendable(directors=BOARD)), \
         patch("routers.cases.email_service.send",
               return_value={"id": "m1",
                             "to": ["chan@example.com", "lee@example.com"],
                             "intended_to": ["chan@example.com", "lee@example.com"],
                             "redirected": False}), \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", side_effect=fake_log):
        client.post("/cases/c1/verification/send", headers=H, json=SEND)
    assert logged[0]["new_value"] == "chan@example.com, lee@example.com"
    assert logged[0]["metadata"]["recipient_count"] == 2


def test_a_stubbed_send_is_audited_as_one(client):
    """The console transport is gone (2026-08-30), but rows written while it
    existed still say transport='console', meaning NOTHING WAS DELIVERED. The
    router must keep passing that through rather than normalising it away —
    an EMAIL_SENT row that lost the flag becomes a record of a client being
    told when nobody was. The service is stubbed here precisely because it can
    no longer produce this value on its own."""
    logged = []

    async def fake_log(**kwargs):
        logged.append(kwargs)

    with _super(), _Stack(*_sendable(directors=BOARD)), \
         _ok_send(transport="console", id=None), \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", side_effect=fake_log):
        response = client.post("/cases/c1/verification/send", headers=H, json=SEND)
    assert response.json()["transport"] == "console"
    assert logged[0]["metadata"]["transport"] == "console"


def test_a_real_send_is_not_labelled_as_stubbed(client):
    """The mutation that would make the flag useless: defaulting it to
    'console'. Every real send has to come back saying 'resend'."""
    logged = []

    async def fake_log(**kwargs):
        logged.append(kwargs)

    with _super(), _Stack(*_sendable(directors=BOARD)), _ok_send(), \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", side_effect=fake_log):
        response = client.post("/cases/c1/verification/send", headers=H, json=SEND)
    assert response.json()["transport"] == "resend"
    assert logged[0]["metadata"]["transport"] == "resend"


# ---------------------------------------------------------------------------
# GET /verification/recipients — who the screen offers
# ---------------------------------------------------------------------------


def test_recipients_lists_the_whole_board_including_the_unreachable(client):
    """A three-director board that renders two chips looks like a two-director
    board, and nothing on screen would say otherwise."""
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value=CASE), \
         patch("routers.cases.nar1_cases.default_recipients", return_value=BOARD), \
         patch("routers.cases.nar1_cases.recipient_email", return_value=None):
        response = client.get("/cases/c1/verification/recipients", headers=H)
    body = response.json()
    assert response.status_code == 200
    assert [r["name"] for r in body["recipients"]] == [
        "AH CHAN", "BO LEE", "HOLDCO LIMITED"]
    assert body["default_to"] == ["chan@example.com", "lee@example.com"]


def test_recipients_falls_back_to_the_company_exactly_as_the_send_does(client):
    """Two implementations of "who by default" would let the screen promise one
    set of addresses and the send use another."""
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value=CASE), \
         patch("routers.cases.nar1_cases.default_recipients", return_value=[]), \
         patch("routers.cases.nar1_cases.recipient_email",
               return_value="office@example.com"):
        response = client.get("/cases/c1/verification/recipients", headers=H)
    assert response.json()["default_to"] == ["office@example.com"]


def test_recipients_needs_only_read_permission(client):
    """It says who WOULD be mailed. Gating it on `write` would blank the screen
    for a reviewer who is allowed to look at the case."""
    with patch("middleware.auth._resolve_user", return_value=REGULAR), \
         patch("middleware.auth._permissions_for", return_value={"read"}), \
         patch("routers.cases.nar1_cases.get_case", return_value=CASE), \
         patch("routers.cases.nar1_cases.default_recipients", return_value=BOARD), \
         patch("routers.cases.nar1_cases.recipient_email", return_value=None):
        response = client.get("/cases/c1/verification/recipients", headers=H)
    assert response.status_code == 200


def test_recipients_404s_for_a_case_that_does_not_exist(client):
    with _super(), \
         patch("routers.cases.nar1_cases.get_case",
               side_effect=LookupError("no NAR1 case c9")):
        response = client.get("/cases/c9/verification/recipients", headers=H)
    assert response.status_code == 404


def test_send_records_the_timestamp_and_audits(client):
    logged = []

    async def fake_log(**kwargs):
        logged.append(kwargs)

    with _super(), _Stack(*_sendable()), \
         patch("routers.cases.email_service.send",
               return_value={"id": "m1", "redirected": False}), \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE) as spy, \
         patch("routers.cases.log_event", side_effect=fake_log):
        response = client.post("/cases/c1/verification/send", headers=H, json=SEND)
    assert response.status_code == 200
    assert spy.call_args.args[1]["verification_sent_at"] is not None
    assert response.json()["sent_at"] == spy.call_args.args[1]["verification_sent_at"]
    # CLIENT_APPROVAL_LINK_SENT follows it, one per director whose link went
    # out (spec §5). Filtered here rather than added to the expectation: this
    # test is about which STATUS events a first send does or does not write.
    assert [e["action_type"] for e in logged
            if e["action_type"] != "CLIENT_APPROVAL_LINK_SENT"] == ["EMAIL_SENT"]
    assert logged[0]["new_value"] == "client@example.com"
    assert logged[0]["metadata"]["message_id"] == "m1"


def test_the_audit_entry_carries_no_document_content(client):
    """The PDF is the whole statutory return. Its bytes belong on the filing
    row, not in the trail — and after_state is not scrubbed."""
    logged = []

    async def fake_log(**kwargs):
        logged.append(kwargs)

    with _super(), _Stack(*_sendable()), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}), \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", side_effect=fake_log):
        client.post("/cases/c1/verification/send", headers=H, json=SEND)
    blob = str(logged[0])
    assert "%PDF" not in blob
    assert logged[0].get("after_state") is None


def test_a_failed_send_does_not_mark_the_case_as_sent(client):
    """Otherwise the case sits in Awaiting Client forever waiting on a reply to
    an email that never left."""
    with _super(), _Stack(*_sendable()), \
         patch("routers.cases.email_service.send",
               side_effect=email_service.EmailError("domain not verified")), \
         patch("routers.cases.nar1_cases.update_case") as spy, \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.post("/cases/c1/verification/send", headers=H, json=SEND)
    assert response.status_code == 502
    spy.assert_not_called()


def test_an_unconfigured_deployment_answers_503_not_500(client):
    """RESEND_API_KEY unset, or a DEV service with no EMAIL_REDIRECT_TO, is a
    deployment fault. A 500 tells the admin the portal crashed."""
    with _super(), _Stack(*_sendable()), \
         patch("routers.cases.email_service.send",
               side_effect=RuntimeError("RESEND_API_KEY must be set to send email")), \
         patch("routers.cases.nar1_cases.update_case") as spy, \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.post("/cases/c1/verification/send", headers=H, json=SEND)
    assert response.status_code == 503
    assert "RESEND_API_KEY" in response.json()["detail"]
    spy.assert_not_called()


def test_an_unrenderable_snapshot_is_422_not_500(client):
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value=CASE), \
         patch("routers.cases.nar1_cases.current_filing", return_value=VALIDATED), \
         patch("routers.cases.nar1_cases.default_recipients", return_value=[]), \
         patch("routers.cases.nar1_cases.recipient_email",
               return_value="client@example.com"), \
         patch("routers.cases.nar1_cases.entity_for", return_value=ENTITY), \
         patch("routers.cases.nar1_form_fill.render",
               side_effect=ValueError("no <formModel> in the payload")), \
         patch("routers.cases.email_service.send") as send:
        response = client.post("/cases/c1/verification/send", headers=H, json=SEND)
    assert response.status_code == 422
    send.assert_not_called()


def test_an_uncoverable_character_is_422_not_500(client):
    """M5 (final review): `AppearanceError` -- raised when a character has
    no glyph in either embedded face (see `appearance.draw_value`) -- was not
    in this handler's except tuple, so a real missing-glyph failure on
    Railway would have surfaced as an opaque 500 instead of this route's own
    'the validated snapshot could not be rendered' message. `fill.render`
    already translates `AppearanceError` into `FormFillError` internally, so
    this also stands as a belt-and-braces check on the route itself."""
    from services.nar1_form.appearance import AppearanceError
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value=CASE), \
         patch("routers.cases.nar1_cases.current_filing", return_value=VALIDATED), \
         patch("routers.cases.nar1_cases.default_recipients", return_value=[]), \
         patch("routers.cases.nar1_cases.recipient_email",
               return_value="client@example.com"), \
         patch("routers.cases.nar1_cases.entity_for", return_value=ENTITY), \
         patch("routers.cases.nar1_form_fill.render",
               side_effect=AppearanceError(
                   "cannot draw '杨' (U+6768): no glyph in NAR1-CJK")), \
         patch("routers.cases.email_service.send") as send:
        response = client.post("/cases/c1/verification/send", headers=H, json=SEND)
    assert response.status_code == 422
    assert "U+6768" in response.json()["detail"]
    send.assert_not_called()


def test_resending_supersedes_the_previous_client_answer(client):
    """A rejection answers the PREVIOUS request. Left in place it pins the badge
    at Client Rejected forever, while the client is looking at a fresh PDF."""
    logged = []

    async def fake_log(**kwargs):
        logged.append(kwargs)

    rejected = {**CASE, "verification_sent_at": "2026-08-01T00:00:00Z",
                "client_approved": False, "client_response_at": "2026-08-02T00:00:00Z"}
    with _super(), _Stack(*_sendable(case=rejected)), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}), \
         patch("routers.cases.nar1_cases.update_case", return_value=rejected) as spy, \
         patch("routers.cases.log_event", side_effect=fake_log):
        client.post("/cases/c1/verification/send", headers=H, json=SEND)
    patch_sent = spy.call_args.args[1]
    assert patch_sent["client_approved"] is None
    assert patch_sent["client_response_at"] is None
    # The discarded answer is a workflow change and has to be visible as one —
    # otherwise the trail shows a rejection that silently stopped counting.
    assert "CASE_STATUS_CHANGED" in [e["action_type"] for e in logged]


def test_a_first_send_does_not_log_a_superseded_response(client):
    logged = []

    async def fake_log(**kwargs):
        logged.append(kwargs)

    with _super(), _Stack(*_sendable()), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}), \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", side_effect=fake_log):
        client.post("/cases/c1/verification/send", headers=H, json=SEND)
    # CLIENT_APPROVAL_LINK_SENT follows it, one per director whose link went
    # out (spec §5). Filtered here rather than added to the expectation: this
    # test is about which STATUS events a first send does or does not write.
    assert [e["action_type"] for e in logged
            if e["action_type"] != "CLIENT_APPROVAL_LINK_SENT"] == ["EMAIL_SENT"]


def test_send_404s_on_an_unknown_case(client):
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", side_effect=LookupError("no case")):
        response = client.post("/cases/nope/verification/send", headers=H, json=SEND)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# response
# ---------------------------------------------------------------------------

SENT = {**CASE, "verification_sent_at": "2026-08-16T00:00:00Z"}


def test_response_records_a_yes(client):
    logged = []

    async def fake_log(**kwargs):
        logged.append(kwargs)

    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value=SENT), \
         patch("routers.cases.nar1_cases.update_case", return_value=SENT) as spy, \
         patch("routers.cases.nar1_cases.composite", return_value=SENT), \
         patch("routers.cases.log_event", side_effect=fake_log):
        response = client.post("/cases/c1/verification/response", headers=H,
                               json={"approved": True})
    assert response.status_code == 200
    assert spy.call_args.args[1]["client_approved"] is True
    assert spy.call_args.args[1]["client_response_at"] is not None
    assert logged[0]["action_type"] == "CLIENT_APPROVAL_RECEIVED"
    assert logged[0]["new_value"] == "approved"


def test_response_records_a_no(client):
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value=SENT), \
         patch("routers.cases.nar1_cases.update_case", return_value=SENT) as spy, \
         patch("routers.cases.nar1_cases.composite", return_value=SENT), \
         patch("routers.cases.log_event", new=AsyncMock()):
        client.post("/cases/c1/verification/response", headers=H,
                    json={"approved": False})
    assert spy.call_args.args[1]["client_approved"] is False


def test_a_reversed_answer_is_recorded_with_the_one_it_replaced(client):
    logged = []

    async def fake_log(**kwargs):
        logged.append(kwargs)

    rejected = {**SENT, "client_approved": False}
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value=rejected), \
         patch("routers.cases.nar1_cases.update_case", return_value=rejected), \
         patch("routers.cases.nar1_cases.composite", return_value=rejected), \
         patch("routers.cases.log_event", side_effect=fake_log):
        client.post("/cases/c1/verification/response", headers=H,
                    json={"approved": True})
    assert logged[0]["old_value"] == "rejected"
    assert logged[0]["new_value"] == "approved"


def test_recording_the_same_answer_twice_writes_nothing(client):
    """A no-op must not put a second client decision in an insert-only trail —
    the same rule PATCH /cases and manual-sign already follow."""
    approved = {**SENT, "client_approved": True}
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value=approved), \
         patch("routers.cases.nar1_cases.update_case") as spy, \
         patch("routers.cases.nar1_cases.composite", return_value=approved), \
         patch("routers.cases.log_event", new=AsyncMock()) as log:
        response = client.post("/cases/c1/verification/response", headers=H,
                               json={"approved": True})
    assert response.status_code == 200
    spy.assert_not_called()
    log.assert_not_called()


def test_a_response_cannot_be_recorded_before_anything_was_sent(client):
    """R1 records the reply manually. Recording one for an email never sent puts
    an approval in the trail with no request behind it."""
    with _super(), patch("routers.cases.nar1_cases.get_case", return_value=CASE):
        response = client.post("/cases/c1/verification/response", headers=H,
                               json={"approved": True})
    assert response.status_code == 409


def test_response_404s_on_an_unknown_case(client):
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", side_effect=LookupError("no case")):
        response = client.post("/cases/nope/verification/response", headers=H,
                               json={"approved": True})
    assert response.status_code == 404


def test_response_requires_an_explicit_answer(client):
    with _super(), patch("routers.cases.nar1_cases.get_case", return_value=SENT):
        response = client.post("/cases/c1/verification/response", headers=H, json={})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Permission gate
# ---------------------------------------------------------------------------


def test_verification_endpoints_require_nar1_write(client):
    with patch("middleware.auth._resolve_user", return_value=REGULAR), \
         patch("middleware.auth._permissions_for", return_value={"read"}):
        assert client.post("/cases/c1/verification/send", headers=H,
                           json={}).status_code == 403
        assert client.post("/cases/c1/verification/response", headers=H,
                           json={"approved": True}).status_code == 403


def test_verification_endpoints_reject_an_unauthenticated_caller(client):
    assert client.post("/cases/c1/verification/send", json={}).status_code == 403
    assert client.post("/cases/c1/verification/response",
                       json={"approved": True}).status_code == 403


def test_verification_endpoints_reject_an_invalid_token(client):
    with patch("middleware.auth._resolve_user",
               side_effect=__import__("fastapi").HTTPException(401, "Invalid token")):
        assert client.post("/cases/c1/verification/send", headers=H,
                           json={}).status_code == 401


# ---------------------------------------------------------------------------
# The mocked-boundary trap
#
# Every test above patches email_service.send, so none of them proves the router
# reaches the real transport, or that the real renderer produces something
# mailable. This one patches ONE thing — httpx.post — and lets the NAR1 form renderer
# and email_service.send run for real against CR's own shipped example.
# ---------------------------------------------------------------------------

_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "cr-examples" / "validateForm"
    / "validate_NAR1(Private Company, Schedule 1).xml"
)


def test_send_drives_the_real_renderer_and_the_real_transport(client, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.delenv("EMAIL_REDIRECT_TO", raising=False)
    monkeypatch.delenv("VERIFICATION_FROM", raising=False)
    # Kept after the console transport was removed: EMAIL_TRANSPORT set to
    # anything now RAISES, so a stale value in a developer's .env would fail
    # this test with a config error rather than the assertion it is about.
    monkeypatch.delenv("EMAIL_TRANSPORT", raising=False)
    email_service.get_email_config.cache_clear()

    posted = MagicMock(status_code=200)
    posted.json.return_value = {"id": "msg_real"}

    filing = {**VALIDATED, "validated_xml": _FIXTURE.read_text(encoding="utf8")}

    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value=CASE), \
         patch("routers.cases.nar1_cases.current_filing", return_value=filing), \
         patch("routers.cases.nar1_cases.default_recipients", return_value=[]), \
         patch("routers.cases.nar1_cases.recipient_email",
               return_value="client@example.com"), \
         patch("routers.cases.nar1_cases.entity_for", return_value=ENTITY), \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()), \
         patch("services.email_service.httpx.post", return_value=posted) as post:
        response = client.post("/cases/c1/verification/send", headers=H, json=SEND)

    assert response.status_code == 200
    payload = post.call_args.kwargs["json"]
    assert payload["from"] == "no-reply@getstarted.hk"
    assert payload["to"] == ["client@example.com"]
    assert "ACME LIMITED" in payload["subject"] + payload["html"]

    import base64
    pdf = base64.b64decode(payload["attachments"][0]["content"])
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 2000
    assert payload["attachments"][0]["filename"] == "NAR1-NAR-2026-0041.pdf"

    email_service.get_email_config.cache_clear()
