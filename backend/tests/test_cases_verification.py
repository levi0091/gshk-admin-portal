"""BE-3 — client verification send / response.

R1 has no inbound mail handling and no client-facing endpoint: the client
replies to a human, and an admin records the answer through
POST /cases/{id}/verification/response. Both routes are staff-only
(`nar1:write`) — there is no token, no magic link and nothing an unauthenticated
caller can reach, which is the whole reason this flow has no security surface to
get wrong.
"""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from services import email_service

SUPER = {"id": "u1", "display_name": "Levi", "role_name": "super_admin",
         "role_id": "role-sa"}
REGULAR = {"id": "u2", "display_name": "Staff", "role_name": "staff",
           "role_id": "role-x"}
H = {"Authorization": "Bearer tok"}


def _super():
    return patch("middleware.auth._resolve_user", return_value=SUPER)


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
        response = client.post("/cases/c1/verification/send", headers=H, json={})
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
        client.post("/cases/c1/verification/send", headers=H, json={})
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
        response = client.post("/cases/c1/verification/send", headers=H, json={})
    assert response.status_code == 409


def test_send_is_refused_when_no_filing_exists_at_all(client):
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value=CASE), \
         patch("routers.cases.nar1_cases.current_filing", return_value=None):
        response = client.post("/cases/c1/verification/send", headers=H, json={})
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
        response = client.post("/cases/c1/verification/send", headers=H, json={})
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
        response = client.post("/cases/c1/verification/send", headers=H, json={})
    assert response.status_code == 409


def test_send_is_refused_once_the_return_is_already_filed(client):
    """Asking a client to approve a return CR already holds is a false request:
    their answer can change nothing."""
    filed = {"id": "f1", "form_code": "Nar1", "stage": "submitted",
             "validated_xml": "<x/>"}
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value=CASE), \
         patch("routers.cases.nar1_cases.current_filing", return_value=filed):
        response = client.post("/cases/c1/verification/send", headers=H, json={})
    assert response.status_code == 409


def test_send_is_refused_when_the_case_was_completed_off_portal(client):
    done = {**CASE, "manual_receipt": {"caseNo": "X"}}
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", return_value=done), \
         patch("routers.cases.nar1_cases.current_filing", return_value=VALIDATED):
        response = client.post("/cases/c1/verification/send", headers=H, json={})
    assert response.status_code == 409


def test_send_is_refused_when_no_recipient_is_on_record(client):
    with _super(), _Stack(*_sendable(recipient=None)):
        response = client.post("/cases/c1/verification/send", headers=H, json={})
    assert response.status_code == 409


def test_an_explicit_recipient_overrides_the_address_on_record(client):
    """A bare string is still accepted — it is what this route shipped with."""
    with _super(), _Stack(*_sendable()), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}) as send, \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.post("/cases/c1/verification/send", headers=H,
                               json={"to": "other@example.com"})
    assert response.status_code == 200
    assert send.call_args.kwargs["to"] == ["other@example.com"]


def test_a_recipient_override_that_is_not_an_address_is_refused(client):
    """The override directs a document carrying directors' residential addresses
    and identity numbers. Free text is not an address."""
    with _super(), _Stack(*_sendable()):
        response = client.post("/cases/c1/verification/send", headers=H,
                               json={"to": "not-an-address"})
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
        response = client.post("/cases/c1/verification/send", headers=H, json={})
    assert response.status_code == 200
    assert send.call_args.kwargs["to"] == ["chan@example.com", "lee@example.com"]


def test_the_company_address_is_used_only_when_no_director_has_one(client):
    """The fallback must not FIRE alongside the directors — the company contact
    is a substitute for a board with no addresses, not an extra copy."""
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}) as send, \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        client.post("/cases/c1/verification/send", headers=H, json={})
    assert "client@example.com" not in send.call_args.kwargs["to"]


def test_an_explicit_list_is_sent_verbatim(client):
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}) as send, \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        response = client.post(
            "/cases/c1/verification/send", headers=H,
            json={"to": ["a@example.com", "b@example.com", "c@example.com"]})
    assert response.status_code == 200
    assert send.call_args.kwargs["to"] == [
        "a@example.com", "b@example.com", "c@example.com"]


def test_an_explicit_list_is_not_topped_up_with_the_directors(client):
    """THE REASON THE FRONTEND ALWAYS POSTS A LIST. An operator who removed a
    director from the chips must not have them added back by the server."""
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}) as send, \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        client.post("/cases/c1/verification/send", headers=H,
                    json={"to": ["chan@example.com"]})
    assert send.call_args.kwargs["to"] == ["chan@example.com"]


def test_an_empty_list_is_refused_rather_than_treated_as_absent(client):
    """`[]` says the operator cleared every chip. Falling back to the directors
    would mail the people they had just removed."""
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         patch("routers.cases.email_service.send") as send, \
         patch("routers.cases.nar1_cases.update_case") as update:
        response = client.post("/cases/c1/verification/send", headers=H,
                               json={"to": []})
    assert response.status_code == 422
    send.assert_not_called()
    update.assert_not_called()


def test_one_bad_address_in_a_list_refuses_the_whole_send(client):
    """Not "send to the good ones": the operator asked for a set, and a partial
    send that reports success is indistinguishable from a complete one."""
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         patch("routers.cases.email_service.send") as send:
        response = client.post("/cases/c1/verification/send", headers=H,
                               json={"to": ["good@example.com", "nope"]})
    assert response.status_code == 422
    assert "nope" in response.json()["detail"]
    send.assert_not_called()


def test_addresses_differing_only_in_case_are_one_recipient(client):
    """Resend would otherwise deliver the statutory return to one mailbox
    twice."""
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         patch("routers.cases.email_service.send", return_value={"id": "m1"}) as send, \
         patch("routers.cases.nar1_cases.update_case", return_value=CASE), \
         patch("routers.cases.log_event", new=AsyncMock()):
        client.post("/cases/c1/verification/send", headers=H,
                    json={"to": ["Chan@Example.com", "chan@example.com"]})
    assert send.call_args.kwargs["to"] == ["Chan@Example.com"]


def test_too_many_recipients_is_refused(client):
    from routers.cases import MAX_RECIPIENTS
    many = [f"d{i}@example.com" for i in range(MAX_RECIPIENTS + 1)]
    with _super(), _Stack(*_sendable(directors=BOARD)), \
         patch("routers.cases.email_service.send") as send:
        response = client.post("/cases/c1/verification/send", headers=H,
                               json={"to": many})
    assert response.status_code == 422
    send.assert_not_called()


def test_the_refusal_names_directors_as_well_as_the_company(client):
    """The operator's next move is to find an address. A message that mentions
    only the company sends them to the wrong screen."""
    with _super(), _Stack(*_sendable(recipient=None, directors=[BOARD[2]])):
        response = client.post("/cases/c1/verification/send", headers=H, json={})
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
        client.post("/cases/c1/verification/send", headers=H, json={})
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
        response = client.post("/cases/c1/verification/send", headers=H, json={})
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
        response = client.post("/cases/c1/verification/send", headers=H, json={})
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
        response = client.post("/cases/c1/verification/send", headers=H, json={})
    assert response.status_code == 200
    assert spy.call_args.args[1]["verification_sent_at"] is not None
    assert response.json()["sent_at"] == spy.call_args.args[1]["verification_sent_at"]
    assert [e["action_type"] for e in logged] == ["EMAIL_SENT"]
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
        client.post("/cases/c1/verification/send", headers=H, json={})
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
        response = client.post("/cases/c1/verification/send", headers=H, json={})
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
        response = client.post("/cases/c1/verification/send", headers=H, json={})
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
        response = client.post("/cases/c1/verification/send", headers=H, json={})
    assert response.status_code == 422
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
        client.post("/cases/c1/verification/send", headers=H, json={})
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
        client.post("/cases/c1/verification/send", headers=H, json={})
    assert [e["action_type"] for e in logged] == ["EMAIL_SENT"]


def test_send_404s_on_an_unknown_case(client):
    with _super(), \
         patch("routers.cases.nar1_cases.get_case", side_effect=LookupError("no case")):
        response = client.post("/cases/nope/verification/send", headers=H, json={})
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
        response = client.post("/cases/c1/verification/send", headers=H, json={})

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
