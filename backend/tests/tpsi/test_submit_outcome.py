"""A NAR1 submit whose outcome is unknown can never be submitted again.

THE PROD INCIDENT, 2026-10-26. CR wrote to GSHK about ~10 companies whose 2026
annual return had arrived two or three times. From `audit_log`, matched copy
for copy against CR's letters: `submitFormNar1` normally answers in 25-56 s,
the portal read with a 60 s timeout, and 16 of 160 submits timed out — while
CR, as often as not, went on to lodge the return and charge for it. The portal
stored those as `submission_failed`, the screen said "The Companies Registry
refused the submission", and `submission_failed` let validate -> sign -> submit
run again on the same row. Fashion Hamburg (NAR-2026-0319), 23 October: three
submits, two timeouts, three copies at CR.

These tests drive that sequence through the real routes against a fake CR
(`cr_harness`). The first one IS the incident: on the code that shipped, the
second submit reaches CR.
"""
import httpx
import pytest

from tests.tpsi.cr_harness import FAULT_BEANS, H, Harness, seed

#: Every way a submit can end WITHOUT CR telling us what happened. In each of
#: them the request may already have been received, lodged and charged.
NO_ANSWER = {
    "read timeout": httpx.ReadTimeout("The read operation timed out"),
    "dropped connection": httpx.RemoteProtocolError("Server disconnected"),
    "5xx without fault beans": httpx.Response(502, content=b"<html>Bad gateway</html>"),
    "a 200 that is not a receipt": httpx.Response(
        200, content=b'<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/'
                     b'soap/envelope/"><soap:Body><nothing/></soap:Body>'
                     b"</soap:Envelope>"),
    "a 200 that is not XML": httpx.Response(200, content=b"\x00garbage"),
}


def _operator_retries(h: Harness) -> None:
    """What the PROD operators did after the screen said CR refused it."""
    h.validate()
    h.sign()
    h.submit()


@pytest.mark.parametrize("failure", list(NO_ANSWER), ids=list(NO_ANSWER))
def test_a_submit_with_no_answer_from_cr_is_never_sent_to_cr_again(failure):
    """AC1 + AC2. The incident, replayed: no answer, then the ordinary retry."""
    with Harness() as h:
        h.cr.answers["/tpsi/submitFormNar1"] = NO_ANSWER[failure]
        h.submit()
        _operator_retries(h)

        assert h.cr.count("submitFormNar1") == 1, (
            "the same annual return was sent to CR a second time")
        assert h.stage() == "submission_unknown"
        assert "TPSI_SUBMISSION_UNKNOWN" in h.actions()
        assert "TPSI_SUBMISSION_FAILED" not in [
            e["action_type"] for e in h.events
            if (e.get("metadata") or {}).get("gate") is not True]


def test_an_unknown_outcome_refuses_validate_sign_and_submit_by_name():
    with Harness(seed(filing={"stage": "submission_unknown"})) as h:
        responses = [h.validate(), h.sign(), h.submit()]

        assert [r.status_code for r in responses] == [409, 409, 409]
        assert h.cr.calls == [], "nothing may reach CR from an unknown outcome"
        assert h.stage() == "submission_unknown"


@pytest.mark.parametrize("stage", ["submitting", "submission_unknown"])
def test_a_new_filing_cannot_be_prepared_on_the_case(stage):
    """`prepare` would open a fresh draft beside a return CR may hold."""
    with Harness(seed(filing={"stage": stage,
                              "submit_started_at": "2099-01-01T00:00:00+00:00"})) as h:
        response = h.http.post("/tpsi/filings/prepare", headers=H,
                               json={"entity_id": "e1", "nar1_case_id": "c1"})

        assert response.status_code == 409
        assert len(h.store.rows("tpsi_filings")) == 1


@pytest.mark.parametrize("stage", ["submitting", "submission_unknown"])
def test_restart_verification_refuses_and_leaves_the_filing_alone(stage):
    with Harness(seed(filing={"stage": stage,
                              "submit_started_at": "2099-01-01T00:00:00+00:00"})) as h:
        response = h.http.patch("/cases/c1", headers=H,
                                json={"restart_verification": True})

        assert response.status_code == 409
        assert h.stage() == stage
        assert h.store.get("nar1_cases", "c1")["client_approved"] is True


@pytest.mark.parametrize("stage", ["submitting", "submission_unknown"])
def test_closing_the_case_refuses_and_leaves_the_filing_alone(stage):
    """Closing supersedes every live filing. Superseding one CR may hold would
    hide a lodged, charged return behind a case marked 'not proceeding'."""
    with Harness(seed(filing={"stage": stage,
                              "submit_started_at": "2099-01-01T00:00:00+00:00"})) as h:
        response = h.http.post("/cases/c1/close", headers=H,
                               json={"reason": "client changed their mind"})

        assert response.status_code == 409
        assert h.stage() == stage
        assert h.store.get("nar1_cases", "c1")["closed_at"] is None


def test_a_timed_out_submit_then_refuses_every_other_door_on_the_case():
    """AC1's second half, end to end from the timeout itself."""
    with Harness() as h:
        h.cr.answers["/tpsi/submitFormNar1"] = httpx.ReadTimeout("timed out")
        h.submit()

        prepare = h.http.post("/tpsi/filings/prepare", headers=H,
                              json={"entity_id": "e1", "nar1_case_id": "c1"})
        restart = h.http.patch("/cases/c1", headers=H,
                               json={"restart_verification": True})
        close = h.http.post("/cases/c1/close", headers=H, json={"reason": "x"})

        assert [prepare.status_code, restart.status_code, close.status_code] == [
            409, 409, 409]
        assert h.stage() == "submission_unknown"


def test_a_refusal_with_fault_beans_is_still_a_failure_and_can_be_retried():
    """AC3. CR answered and said no: nothing was charged, and the ordinary
    validate -> sign -> submit path must keep working exactly as before."""
    with Harness() as h:
        h.cr.answers["/tpsi/submitFormNar1"] = httpx.Response(500, content=FAULT_BEANS)
        h.submit()

        assert h.stage() == "submission_failed"
        faults = h.store.get("tpsi_filings", "f1")["cr_error"]["faults"]
        assert [list(f) for f in faults] == [["ERR_MSG_X", "Deposit account suspended"]]

        from tests.tpsi.cr_harness import RECEIPT
        h.cr.answers["/tpsi/submitFormNar1"] = RECEIPT
        assert h.validate().status_code == 200
        assert h.sign().status_code == 200
        h.submit()

        assert h.cr.count("submitFormNar1") == 2
        assert h.stage() == "submitted"
        assert h.store.get("tpsi_filings", "f1")["receipt"]["caseNo"] == "180256934"


def test_a_token_refused_twice_is_a_failure_not_an_unknown():
    """CR refused the token: it never looked at the form, so nothing was
    lodged and the retry stays open."""
    with Harness() as h:
        h.cr.answers["/tpsi/submitFormNar1"] = httpx.Response(401, content=b"")
        h.submit()

        assert h.stage() == "submission_failed"
