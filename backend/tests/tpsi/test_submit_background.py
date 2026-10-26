"""The submit claims its filing, answers 202, and calls CR in the background.

Levi 2026-10-26 (Option B). submitFormNar1 takes 25-56 s and missed a 60 s
timeout 16 times in 160 on PROD; the edge in front of the API abandons a
request at 100 s. So the wait CR needs cannot happen inside a request. The
route does every gate and one atomic claim, answers, and finishes after the
response with a 180 s read timeout on submitForm alone.
"""
import asyncio
import threading
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from services.tpsi import filings
from tests.tpsi.cr_harness import (CASE_NOT_FOUND, H, SUPER, Harness, ago,
                                   doc_status_reply, seed)

STAFF = {"id": "u2", "display_name": "Staff", "role_name": "staff",
         "role_id": "role-x"}


# --------------------------------------------------------------------------- #
#  AC4 — two submits on one signed filing: exactly one reaches CR
# --------------------------------------------------------------------------- #

def test_two_concurrent_submits_send_exactly_one_return_to_cr():
    """Both requests pass every gate on a `signed` row — the barrier holds
    them inside the balance read until both have read the row — and only the
    conditional UPDATE can tell them apart."""
    with Harness() as h:
        barrier = threading.Barrier(2, timeout=5)
        h.cr.on_call["/tpsi/enquireDepositAccount"] = barrier.wait
        results = []

        def attempt():
            try:
                claim = filings.begin_submit(h.tpsi, "f1", True, "ACC")
            except filings.SubmitGateError as exc:
                results.append(exc)
                return
            results.append(filings.finish_submit(h.tpsi, claim))

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)

        assert h.cr.count("submitFormNar1") == 1
        refused = [r for r in results if isinstance(r, filings.AlreadyFiling)]
        filed = [r for r in results if isinstance(r, filings.SubmitOutcome)]
        assert len(refused) == 1 and len(filed) == 1
        assert h.stage() == "submitted"


def test_a_second_submit_while_the_first_is_in_flight_is_a_409():
    with Harness(seed(filing={"stage": "submitting",
                              "submit_started_at": ago(5)})) as h:
        response = h.submit()

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "filing_locked"
    assert "being filed with CR right now" in response.json()["detail"]["message"]
    assert h.cr.count("submitFormNar1") == 0


# --------------------------------------------------------------------------- #
#  AC5 — a second filing on a case whose first one CR has, or may have
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("held", ["submitting", "submission_unknown", "submitted"])
def test_a_second_filing_on_the_case_cannot_be_signed_or_submitted(held):
    second = {"id": "f2", "entity_id": "e1", "nar1_case_id": "c1",
              "form_code": "Nar1", "stage": "validated",
              "validated_xml": seed().get("tpsi_filings", "f1")["validated_xml"],
              "request_xml": seed().get("tpsi_filings", "f1")["request_xml"],
              "created_at": "2026-10-25T01:00:00+00:00"}
    store = seed(filing={"stage": held, "submit_started_at": ago(5)},
                 more_filings=[second])
    with Harness(store) as h:
        sign = h.http.post("/tpsi/filings/f2/sign", headers=H, json={})
        h.store.get("tpsi_filings", "f2").update(
            stage="signed", signed_xml=h.store.get("tpsi_filings", "f2")["validated_xml"])
        submit = h.http.post("/tpsi/filings/f2/submit", headers=H,
                             json={"confirm": True})
        validate = h.http.post("/tpsi/filings/f2/validate", headers=H)
        prepare = h.http.post("/tpsi/filings/prepare", headers=H,
                              json={"entity_id": "e1", "nar1_case_id": "c1"})

    assert [sign.status_code, submit.status_code, validate.status_code,
            prepare.status_code] == [409, 409, 409, 409]
    assert "another filing on this case" in sign.json()["detail"]["message"]
    assert h.cr.count("verifyPinSigningNar1") == 0
    assert h.cr.count("submitFormNar1") == 0


def test_the_claim_is_refused_by_the_case_lock_when_the_read_is_beaten():
    """The read half of the case lock can lose a race; the index cannot. A
    sibling claims between our lock check and our claim, and the store — like
    Postgres with migration 056 — refuses the second locked row."""
    second = {**seed().get("tpsi_filings", "f1"), "id": "f2",
              "created_at": "2026-10-25T01:00:00+00:00"}
    with Harness(seed(more_filings=[second])) as h:
        h.cr.on_call["/tpsi/enquireDepositAccount"] = lambda: h.store.get(
            "tpsi_filings", "f2").update(stage="submitting",
                                         submit_started_at=ago(1))
        with pytest.raises(filings.FilingLocked):
            filings.begin_submit(h.tpsi, "f1", True, "ACC")
        assert h.stage("f1") == "signed"
        assert h.cr.count("submitFormNar1") == 0


# --------------------------------------------------------------------------- #
#  AC6 — 202 without waiting for CR; 180 s for submitForm, 60 s for the rest
# --------------------------------------------------------------------------- #

def test_the_route_answers_202_before_cr_is_called():
    """Called directly, so the background tasks are visibly NOT run by the
    time the handler has returned — TestClient would run them first."""
    from fastapi import BackgroundTasks

    from routers.tpsi import SubmitIn, submit_filing

    with Harness() as h:
        tasks = BackgroundTasks()
        answer = asyncio.run(submit_filing("f1", SubmitIn(confirm=True), tasks,
                                           user=SUPER))
        assert answer["stage"] == "submitting"
        assert h.stage() == "submitting"
        assert h.cr.count("submitFormNar1") == 0, "CR was called inside the request"
        assert h.actions() == ["TPSI_SUBMISSION_ATTEMPTED"]

        asyncio.run(tasks())
        assert h.cr.count("submitFormNar1") == 1
        assert h.stage() == "submitted"
        assert "TPSI_SUBMISSION_SUCCESS" in h.actions()


def test_the_http_status_is_202_and_names_the_claim():
    with Harness() as h:
        response = h.submit()

    assert response.status_code == 202
    assert response.json()["stage"] == "submitting"
    assert response.json()["filing_id"] == "f1"


def test_submitform_waits_180_seconds_and_every_other_call_60():
    with Harness() as h:
        h.store.get("tpsi_filings", "f1")["stage"] = "draft"
        assert h.validate().status_code == 200
        assert h.sign().status_code == 200
        h.submit()
        # docStatusEnquiry is reached by the resolve route only (the CR status
        # poll and its GET route were removed, Levi 2026-10-17 / 2026-10-27):
        # put the row in an unknown outcome and verify it is lodged.
        row = h.store.get("tpsi_filings", "f1")
        row["stage"] = "submission_unknown"
        row["submit_started_at"] = "2026-10-23T00:30:00+00:00"
        h.http.post("/tpsi/filings/f1/resolve", headers=H,
                    json={"outcome": "lodged", "receipt": {
                        "caseNo": "180256934", "pymtNo": "5010475972",
                        "pymtRefNo": "733037536", "pymtMtd": "Deduct from Account",
                        "transactionDate": "23/10/2026",
                        "transactionTime": "09:15:30", "totalAmount": "2610.00",
                        "paymentRcptList": [{"rcptNo": "D7700", "revCode": "16",
                                             "docShtFrm": "NAR1L",
                                             "amtChrg": "2610.00"}]}})

    timeouts = h.cr.timeouts
    assert timeouts["/tpsi/submitFormNar1"] == [180.0]
    for path in ("/tpsi/validateFormNar1", "/tpsi/verifyPinSigningNar1",
                 "/tpsi/enquireDepositAccount", "/tpsi/docStatusEnquiry",
                 "/oauth/token.do"):
        assert set(timeouts[path]) == {60.0}, path


def test_the_attempt_is_audited_before_anything_reaches_cr():
    with Harness() as h:
        seen_at_submit = []
        h.cr.on_call["/tpsi/submitFormNar1"] = lambda: seen_at_submit.extend(
            h.actions())
        h.submit()

    assert seen_at_submit[0] == "TPSI_SUBMISSION_ATTEMPTED"
    assert h.stage() == "submitted"


# --------------------------------------------------------------------------- #
#  AC7 — a claim nobody can answer becomes an unknown outcome
# --------------------------------------------------------------------------- #

def test_a_claim_older_than_the_cut_off_reads_and_becomes_unknown():
    with Harness(seed(filing={"stage": "submitting",
                              "submit_started_at": ago(400)})) as h:
        response = h.http.get("/tpsi/filings/f1", headers=H)

        assert response.json()["form_status"]["code"] == "submission_unknown"
        assert h.stage() == "submission_unknown"
        unknown = [e for e in h.events
                   if e["action_type"] == "TPSI_SUBMISSION_UNKNOWN"]
        assert len(unknown) == 1
        assert unknown[0]["metadata"]["reason"] == "no answer recorded"
        assert unknown[0]["metadata"]["waited_seconds"] >= 330


def test_a_live_claim_is_left_alone():
    with Harness(seed(filing={"stage": "submitting",
                              "submit_started_at": ago(30)})) as h:
        response = h.http.get("/tpsi/filings/f1", headers=H)

    assert response.json()["form_status"]["code"] == "submitting"
    assert h.stage() == "submitting"
    assert h.events == []


def test_the_case_screen_reads_a_stale_claim_as_unknown_too():
    with Harness(seed(filing={"stage": "submitting",
                              "submit_started_at": ago(600)})) as h:
        response = h.http.get("/cases/c1", headers=H)

        assert response.status_code == 200
        assert response.json()["form_status"]["code"] == "submission_unknown"
        assert response.json()["workflow_status"]["code"] == "submission"
        assert h.stage() == "submission_unknown"
        assert "TPSI_SUBMISSION_UNKNOWN" in h.actions()


def test_the_case_screen_carries_when_the_submit_was_claimed():
    """The unknown-outcome panel warns about a same-day submit before anyone
    declares it not lodged, so it needs the claim time off the case itself."""
    started = ago(60)
    with Harness(_unknown(submit_started_at=started)) as h:
        response = h.http.get("/cases/c1", headers=H)

    assert response.json()["submit_started_at"] == started
    assert response.json()["form_status"]["locked"] is True


def test_the_stale_sweep_cannot_overwrite_an_answer_that_landed_first():
    """Conditional on `stage = 'submitting'` inside the UPDATE: a receipt
    written between the read and the sweep stands."""
    store = seed(filing={"stage": "submitting", "submit_started_at": ago(400)})
    row = store.get("tpsi_filings", "f1")
    with Harness(store) as h:
        h.store.get("tpsi_filings", "f1")["stage"] = "submitted"
        assert filings.expire_stale_claim(dict(row)) is None
        assert h.stage() == "submitted"


# --------------------------------------------------------------------------- #
#  AC8 — resolve: CR has it
# --------------------------------------------------------------------------- #

RECEIPT_IN = {
    "caseNo": "180256934", "pymtNo": "5010475972", "pymtRefNo": "733037536",
    "pymtMtd": "Deduct from Account", "transactionDate": "23/10/2026",
    "transactionTime": "09:15:30", "totalAmount": "2610.00",
    "paymentRcptList": [{"rcptNo": "D7700", "revCode": "16",
                         "docShtFrm": "NAR1L", "amtChrg": "2610.00"}],
}


#: The submit these receipts answer was made on 23 October 2026 (08:30 HKT) --
#: long past the in-flight window, and not "today", so the receipts below,
#: dated that day, are not before the claim (code review 01, S-8).
CLAIMED = "2026-10-23T00:30:00+00:00"


def _unknown(**filing):
    return seed(filing={"stage": "submission_unknown",
                        "submit_started_at": CLAIMED, **filing})


def _resolve(h, **body):
    return h.http.post("/tpsi/filings/f1/resolve", headers=H, json=body)


def test_resolve_lodged_records_cr_receipt_with_crs_own_time():
    with Harness(_unknown()) as h:
        response = _resolve(h, outcome="lodged", receipt=RECEIPT_IN)

        assert response.status_code == 200, response.text
        row = h.store.get("tpsi_filings", "f1")
        assert row["stage"] == "submitted"
        assert set(filings.RECEIPT_FIELDS) <= set(row["receipt"])
        assert set(filings.RECEIPT_LINE_FIELDS) <= set(
            row["receipt"]["paymentRcptList"][0])
        assert row["receipt"]["source"] == "operator_after_timeout"
        # Derived from the case, never typed.
        assert row["receipt"]["brNo"] == "12345678"
        assert row["receipt"]["accNo"] == "ACC"
        assert row["fee_amount"] == "2610.00"
        # 09:15:30 in Hong Kong is 01:15:30 UTC.
        assert datetime.fromisoformat(row["submitted_at"]) == datetime(
            2026, 10, 23, 1, 15, 30, tzinfo=timezone.utc)
        assert h.cr.count("docStatusEnquiry") == 1
        resolved = [e for e in h.events
                    if e["action_type"] == "TPSI_SUBMISSION_RESOLVED"]
        assert resolved[0]["after_state"]["outcome"] == "lodged"
        assert resolved[0]["after_state"]["receipt"]["caseNo"] == "180256934"
        assert resolved[0]["user_id"] == SUPER["id"]


def test_resolve_lodged_with_a_case_number_cr_does_not_know_is_422():
    with Harness(_unknown()) as h:
        h.cr.answers["/tpsi/docStatusEnquiry"] = httpx.Response(
            500, content=CASE_NOT_FOUND)
        response = _resolve(h, outcome="lodged", receipt=RECEIPT_IN)

        assert response.status_code == 422
        assert "180256934" in response.json()["detail"]["message"]
        assert "Case no does not exist" in response.json()["detail"]["message"]
        assert h.stage() == "submission_unknown"
        assert h.store.get("tpsi_filings", "f1").get("receipt") is None


def test_resolve_lodged_under_another_companys_br_number_is_422():
    with Harness(_unknown()) as h:
        h.cr.answers["/tpsi/docStatusEnquiry"] = doc_status_reply(br_no="99999999")
        response = _resolve(h, outcome="lodged", receipt=RECEIPT_IN)

        assert response.status_code == 422
        assert response.json()["detail"]["reason"] == "br_mismatch"
        assert h.stage() == "submission_unknown"


def test_resolve_lodged_when_cr_cannot_be_reached_is_503_and_writes_nothing():
    with Harness(_unknown()) as h:
        h.cr.answers["/tpsi/docStatusEnquiry"] = httpx.ConnectTimeout("no route")
        response = _resolve(h, outcome="lodged", receipt=RECEIPT_IN)

        assert response.status_code == 503
        assert "try again" in response.json()["detail"]["message"].lower()
        assert h.stage() == "submission_unknown"
        assert not [e for e in h.events
                    if e["action_type"] == "TPSI_SUBMISSION_RESOLVED"]


def test_resolve_lodged_with_an_incomplete_receipt_is_400_listing_every_gap():
    with Harness(_unknown()) as h:
        response = _resolve(h, outcome="lodged", receipt={"caseNo": "1"})

    assert response.status_code == 400
    assert len(response.json()["detail"]["problems"]) > 3
    assert h.cr.count("docStatusEnquiry") == 0


@pytest.mark.parametrize("stage", ["signed", "submitted", "submission_failed",
                                   "submitting"])
def test_resolve_refuses_anything_that_is_not_an_unknown_outcome(stage):
    with Harness(seed(filing={"stage": stage, "submit_started_at": ago(5)})) as h:
        response = _resolve(h, outcome="lodged", receipt=RECEIPT_IN)

    assert response.status_code == 409
    assert h.stage() == stage


def test_resolve_needs_tpsi_submit():
    from unittest.mock import patch

    with Harness(_unknown(), user=STAFF) as h, \
            patch("middleware.auth.get_supabase") as msb:
        (msb.return_value.table.return_value.select.return_value.eq.return_value
         .eq.return_value.execute.return_value.data) = []
        response = _resolve(h, outcome="not_lodged", checked_cr=True)

    assert response.status_code == 403
    assert h.stage() == "submission_unknown"


def test_resolve_needs_authentication():
    from fastapi.testclient import TestClient

    from main import app

    response = TestClient(app).post("/tpsi/filings/f1/resolve",
                                    json={"outcome": "not_lodged",
                                          "checked_cr": True})
    # This app's bearer scheme answers a missing header with 403, as every
    # other route's unauthenticated test in this suite accepts.
    assert response.status_code in (401, 403)


# --------------------------------------------------------------------------- #
#  AC9 — resolve: CR does not have it
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("checked", [None, False, "true", 1, "yes"])
def test_not_lodged_needs_a_literal_true(checked):
    body = {"outcome": "not_lodged"}
    if checked is not None:
        body["checked_cr"] = checked
    with Harness(_unknown()) as h:
        response = h.http.post("/tpsi/filings/f1/resolve", headers=H, json=body)

    assert response.status_code == 400
    assert h.stage() == "submission_unknown"


def test_not_lodged_reopens_the_ordinary_retry():
    with Harness(_unknown()) as h:
        response = _resolve(h, outcome="not_lodged", checked_cr=True)

        assert response.status_code == 200
        assert h.stage() == "submission_failed"
        assert "Levi" in h.store.get("tpsi_filings", "f1")["cr_error"]["message"]
        resolved = [e for e in h.events
                    if e["action_type"] == "TPSI_SUBMISSION_RESOLVED"]
        assert resolved[0]["after_state"] == {"outcome": "not_lodged"}

        assert h.validate().status_code == 200
        assert h.sign().status_code == 200
        assert h.submit().status_code == 202
        assert h.stage() == "submitted"
        assert h.cr.count("submitFormNar1") == 1


def test_not_lodged_says_whether_the_submit_was_today():
    from unittest.mock import patch

    from services.tpsi import fees

    started = ago(400)    # past the in-flight window, so declaring is allowed
    today_in_hk = filings.hk_date_of(started)
    with patch.object(fees, "_hk_today", return_value=today_in_hk), \
            Harness(_unknown(submit_started_at=started)) as h:
        today = _resolve(h, outcome="not_lodged", checked_cr=True).json()
    days_ago = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    with patch.object(fees, "_hk_today", return_value=today_in_hk), \
            Harness(_unknown(submit_started_at=days_ago)) as h:
        earlier = _resolve(h, outcome="not_lodged", checked_cr=True).json()

    assert today["submitted_today"] is True
    assert earlier["submitted_today"] is False
