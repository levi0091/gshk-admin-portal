"""Code review 01, fix round 1: the gaps the first pass left open.

B1 — the reviewer's reproduction, inverted. A submit claimed at T0 whose
answer had not arrived when the stale-claim sweep ran was declared "not
lodged"; CR's receipt then arrived, matched no row, was dropped (while
TPSI_SUBMISSION_SUCCESS was audited), and the ordinary retry reached
submitFormNar1 a second time. The fix has four parts and each has a test:
the cut-off outlasts the worst real call, a lost claim sends nothing, "not
lodged" is refused while a call may still be in flight, and a late receipt is
always stored — or, if it cannot be, kept whole in the audit row.

B2 — a submitForm reply with no case number in it was stored as `submitted`.
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from services.tpsi import client as tpsi_client
from services.tpsi import filings
from tests.tpsi.cr_harness import (CR_NS, H, RECEIPT, Harness, ago,
                                   doc_status_reply, envelope, seed)

#: A claim made on 23 October 2026, 08:30 Hong Kong time, long past any
#: in-flight window. The receipt below is dated the same day.
CLAIMED = "2026-10-23T00:30:00+00:00"

RECEIPT_IN = {
    "caseNo": "180256934", "pymtNo": "5010475972", "pymtRefNo": "733037536",
    "pymtMtd": "Deduct from Account", "transactionDate": "23/10/2026",
    "transactionTime": "09:15:30", "totalAmount": "2610.00",
    "paymentRcptList": [{"rcptNo": "D7700", "revCode": "16",
                         "docShtFrm": "NAR1L", "amtChrg": "2610.00"}],
}


def _unknown(**filing):
    return seed(filing={"stage": "submission_unknown",
                        "submit_started_at": CLAIMED, **filing})


def _resolve(h, **body):
    return h.http.post("/tpsi/filings/f1/resolve", headers=H, json=body)


def _declare_not_lodged_mid_call(h):
    """What the 240 s sweep plus a same-day "not lodged" left on the row."""
    row = h.store.get("tpsi_filings", "f1")
    row["stage"] = "submission_failed"
    row["cr_error"] = {"faults": [], "kind": "declared_not_lodged",
                       "message": "declared not lodged"}


# --------------------------------------------------------------------------- #
#  B1.4 — a late receipt is always stored (the reviewer's repro, inverted)
# --------------------------------------------------------------------------- #

def test_a_receipt_that_arrives_after_not_lodged_is_stored_and_cr_is_reached_once():
    with Harness() as h:
        h.cr.on_call["/tpsi/submitFormNar1"] = lambda: _declare_not_lodged_mid_call(h)
        assert h.submit().status_code == 202

        row = h.store.get("tpsi_filings", "f1")
        assert row["stage"] == "submitted"
        assert row["receipt"]["caseNo"] == "180256934"

        # The operator's retry, as on PROD: every step refuses now.
        h.validate()
        h.sign()
        h.submit()
        assert h.cr.count("submitFormNar1") == 1


def test_a_late_receipt_survives_the_retry_path_having_been_reached():
    """Declared not lodged, then re-validated and re-signed before CR answered:
    CR's receipt still wins over anything the retry path reached since."""
    with Harness() as h:
        def retried_meanwhile():
            _declare_not_lodged_mid_call(h)
            h.store.get("tpsi_filings", "f1")["stage"] = "signed"

        h.cr.on_call["/tpsi/submitFormNar1"] = retried_meanwhile
        h.submit()

        assert h.stage() == "submitted"
        assert h.store.get("tpsi_filings", "f1")["receipt"]["caseNo"] == "180256934"


def test_every_success_audit_carries_the_whole_receipt_and_says_it_was_stored():
    with Harness() as h:
        h.submit()

    success = [e for e in h.events if e["action_type"] == "TPSI_SUBMISSION_SUCCESS"]
    assert success[0]["metadata"]["stored"] is True
    assert success[0]["after_state"]["receipt"]["pymtRefNo"] == "733037536"
    assert success[0]["after_state"]["receipt"]["paymentRcptList"]


def test_a_receipt_that_cannot_be_stored_is_kept_whole_in_the_trail(capsys):
    """The row was re-claimed by somebody else meanwhile, so the write is keyed
    to a claim that no longer exists. The receipt is the only proof CR filed,
    so it goes to stderr and into the audit row, which is insert-only."""
    with Harness() as h:
        def reclaimed():
            row = h.store.get("tpsi_filings", "f1")
            row["submit_started_at"] = ago(1)

        h.cr.on_call["/tpsi/submitFormNar1"] = reclaimed
        h.submit()

        success = [e for e in h.events
                   if e["action_type"] == "TPSI_SUBMISSION_SUCCESS"]
        assert success[0]["metadata"]["stored"] is False
        assert success[0]["after_state"]["receipt"]["caseNo"] == "180256934"
        assert "180256934" in capsys.readouterr().err
        assert h.stage() != "submitted"


# --------------------------------------------------------------------------- #
#  B1.1 — the cut-off outlasts the worst real call, and 401 is not re-posted
# --------------------------------------------------------------------------- #

def _all_phases(timeout: httpx.Timeout) -> float:
    return float(timeout.connect + timeout.read + timeout.write + timeout.pool)


def test_the_stale_cut_off_outlasts_the_worst_case_submit_call():
    """If anyone raises a client timeout above the cut-off, this fails before
    a live call can outlast the claim that protects it. The submit call can
    authenticate first (token() on an empty cache) and then post -- once.
    EVERY httpx phase is counted (connect, read, write, pool), not just the two
    that usually matter (code review 02, N-7)."""
    worst = (filings.MAX_START_DELAY_SECONDS
             + _all_phases(tpsi_client._TIMEOUT)          # authenticate
             + _all_phases(tpsi_client._SUBMIT_TIMEOUT))  # submitForm
    assert filings.STALE_CLAIM_SECONDS > worst
    assert tpsi_client.worst_case_seconds(tpsi_client._SUBMIT_TIMEOUT) == \
        _all_phases(tpsi_client._SUBMIT_TIMEOUT)
    assert tpsi_client._SUBMIT_TIMEOUT.read == 180
    assert tpsi_client._TIMEOUT.read == 60


def test_no_phase_is_left_to_httpx_to_default_to_the_read_timeout():
    """`httpx.Timeout(180.0, connect=15.0)` also set write=180 and pool=180,
    so a stalled upload could take as long as the answer. Each phase is named."""
    for timeout in (tpsi_client._TIMEOUT, tpsi_client._SUBMIT_TIMEOUT):
        assert timeout.write <= 15 and timeout.pool <= 15 and timeout.connect <= 15


def test_a_401_on_submitform_is_not_posted_a_second_time():
    """The one permitted re-login-and-retry would re-post a chargeable call
    under a fresh 180 s wait — outside every bound the claim relies on. A 401
    there means CR processed nothing, so it is a plain refusal."""
    with Harness() as h:
        h.cr.answers["/tpsi/submitFormNar1"] = httpx.Response(401, content=b"")
        h.submit()

        assert h.cr.count("submitFormNar1") == 1
        assert h.stage() == "submission_failed"
        assert h.store.get("tpsi_filings", "f1")["cr_error"]["kind"] == "auth"


def test_other_calls_keep_their_single_re_login_on_a_stale_token():
    with Harness() as h:
        h.cr.answers["/tpsi/enquireDepositAccount"] = [
            httpx.Response(401),
            envelope(f'<cr:enquireDepositAccountResponse xmlns:cr="{CR_NS}">'
                     "<cr:accountBalance>5</cr:accountBalance>"
                     "</cr:enquireDepositAccountResponse>"),
        ]
        from services.tpsi import reads

        assert str(reads.check_balance(h.tpsi, "ACC")) == "5"
        assert h.cr.count("enquireDepositAccount") == 2


def test_a_receipt_arriving_after_an_operator_recorded_one_says_so(capsys):
    """Code review 02, N-10: correct to keep it, alarming to log as a failure to
    store. The reason names what happened -- the row already holds a receipt."""
    with Harness() as h:
        def operator_recorded_it():
            row = h.store.get("tpsi_filings", "f1")
            row["stage"] = "submitted"
            row["receipt"] = {"caseNo": "180256934", "source": "operator_after_timeout"}

        h.cr.on_call["/tpsi/submitFormNar1"] = operator_recorded_it
        h.submit()

        err = capsys.readouterr().err
        assert "already recorded" in err
        assert "could not be stored" not in err
        success = [e for e in h.events
                   if e["action_type"] == "TPSI_SUBMISSION_SUCCESS"]
        assert success[0]["metadata"]["stored"] is False
        assert success[0]["metadata"]["reason"] == "already recorded by an operator"


def test_a_receipt_never_overwrites_an_edrive_row():
    """Code review 02, N-8: an e-Drive row already holds the return."""
    assert filings.STAGE_EDRIVE not in filings._RECEIPT_OVERWRITES
    assert filings.STAGE_SUBMITTED not in filings._RECEIPT_OVERWRITES
    assert filings.STAGE_REGISTERED not in filings._RECEIPT_OVERWRITES


def test_hk_date_of_is_public_for_the_route():
    """Code review 02, N-9: the route calls it, so it is not a private name."""
    assert filings.hk_date_of("2026-10-23T00:30:00+00:00").isoformat() == "2026-10-23"


# --------------------------------------------------------------------------- #
#  B1.2 — a claim lost before the post sends nothing
# --------------------------------------------------------------------------- #

def test_a_claim_swept_before_the_background_call_sends_nothing():
    with Harness() as h:
        claim = filings.begin_submit(h.tpsi, "f1", True, "ACC")
        h.store.get("tpsi_filings", "f1")["stage"] = "submission_unknown"

        outcome = filings.finish_submit(h.tpsi, claim)

        assert h.cr.count("submitFormNar1") == 0
        assert outcome.sent is False
        assert h.stage() == "submission_unknown"


def test_a_lost_claim_is_audited_as_nothing_sent():
    from routers.tpsi import _finish_submit
    import asyncio

    with Harness() as h:
        claim = filings.begin_submit(h.tpsi, "f1", True, "ACC")
        h.store.get("tpsi_filings", "f1")["submit_started_at"] = ago(1)
        asyncio.run(_finish_submit(h.tpsi, claim, {"id": "u1",
                                                   "display_name": "Levi"}))

    unknown = [e for e in h.events if e["action_type"] == "TPSI_SUBMISSION_UNKNOWN"]
    assert unknown[0]["metadata"]["sent"] is False
    assert "nothing was sent" in unknown[0]["metadata"]["reason"]
    assert h.cr.count("submitFormNar1") == 0


def test_a_background_call_that_starts_too_late_sends_nothing_and_says_so():
    """The thread pool was busy; by the time the call could start, it could
    outlast the cut-off. Nothing has been sent, so the honest outcome is a
    refusal the ordinary retry accepts."""
    with Harness() as h:
        claim = filings.begin_submit(h.tpsi, "f1", True, "ACC")
        late = ago(filings.MAX_START_DELAY_SECONDS + 5)
        h.store.get("tpsi_filings", "f1")["submit_started_at"] = late
        claim.started_at = late

        outcome = filings.finish_submit(h.tpsi, claim)

        assert h.cr.count("submitFormNar1") == 0
        assert outcome.sent is False
        assert h.stage() == "submission_failed"
        assert "nothing was sent" in h.store.get(
            "tpsi_filings", "f1")["cr_error"]["message"]


# --------------------------------------------------------------------------- #
#  B1.3 — "not lodged" is refused while a call may still be with CR
# --------------------------------------------------------------------------- #

def test_not_lodged_is_refused_while_a_submit_may_still_be_in_flight():
    with Harness(_unknown(submit_started_at=ago(100))) as h:
        response = _resolve(h, outcome="not_lodged", checked_cr=True)

        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "may_be_in_flight"
        assert "HKT" in response.json()["detail"]["message"]
        assert h.stage() == "submission_unknown"


def test_the_service_refuses_it_too_so_a_script_cannot_skip_the_route():
    with Harness(_unknown(submit_started_at=ago(100))):
        with pytest.raises(filings.ResolveRefused) as exc:
            filings.resolve_not_lodged("f1", actor="script")
    assert exc.value.status == 409


def test_a_repaired_legacy_row_with_no_claim_time_can_be_declared():
    with Harness(_unknown(submit_started_at=None)) as h:
        response = _resolve(h, outcome="not_lodged", checked_cr=True)

    assert response.status_code == 200
    assert h.stage() == "submission_failed"


def test_the_case_and_the_filing_say_when_not_lodged_becomes_possible():
    started = ago(100)
    with Harness(_unknown(submit_started_at=started)) as h:
        case = h.http.get("/cases/c1", headers=H).json()
        filing = h.http.get("/tpsi/filings/f1", headers=H).json()

    expected = (datetime.fromisoformat(started)
                + timedelta(seconds=filings.STALE_CLAIM_SECONDS))
    assert datetime.fromisoformat(case["not_lodged_after"]) == expected
    assert datetime.fromisoformat(filing["not_lodged_after"]) == expected


# --------------------------------------------------------------------------- #
#  B2 — a reply with no case number is not a receipt
# --------------------------------------------------------------------------- #

def test_a_reply_with_no_case_number_is_unknown_and_keeps_what_cr_sent():
    body = envelope(f'<cr:submitFormResponse xmlns:cr="{CR_NS}"/>')
    with Harness() as h:
        h.cr.answers["/tpsi/submitFormNar1"] = body
        h.submit()

        row = h.store.get("tpsi_filings", "f1")
        assert row["stage"] == "submission_unknown"
        assert row.get("receipt") is None
        assert "submitFormResponse" in row["cr_error"]["raw"]
        assert len(row["cr_error"]["raw"]) <= 2048


# --------------------------------------------------------------------------- #
#  S-1 — the stale repair is the system's act, observed by a reader
# --------------------------------------------------------------------------- #

def test_the_stale_repair_is_attributed_to_the_system_not_the_reader():
    with Harness(seed(filing={"stage": "submitting",
                              "submit_started_at": ago(2000)})) as h:
        h.http.get("/tpsi/filings/f1", headers=H)

    unknown = [e for e in h.events if e["action_type"] == "TPSI_SUBMISSION_UNKNOWN"]
    assert unknown[0]["user_id"] is None
    assert unknown[0]["user_display_name"] == "G-FlowDesk (automatic)"
    assert unknown[0]["metadata"]["observed_by"] == "Levi"


# --------------------------------------------------------------------------- #
#  S-4 — restart is refused over a locked filing wherever it sorts
# --------------------------------------------------------------------------- #

def test_restart_is_refused_when_an_older_filing_is_locked_behind_a_newer_draft():
    newer = {"id": "f2", "entity_id": "e1", "nar1_case_id": "c1",
             "form_code": "Nar1", "stage": "draft", "request_xml": "<x/>",
             "created_at": "2026-10-25T01:00:00+00:00"}
    store = seed(filing={"stage": "submission_unknown",
                         "submit_started_at": CLAIMED,
                         "created_at": "2026-10-20T01:00:00+00:00"},
                 more_filings=[newer])
    with Harness(store) as h:
        response = h.http.patch("/cases/c1", headers=H,
                                json={"restart_verification": True})

        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "filing_locked"
        assert h.store.get("nar1_cases", "c1")["client_approved"] is True


# --------------------------------------------------------------------------- #
#  S-5 — a NAR1 filing must belong to a case
# --------------------------------------------------------------------------- #

def test_a_nar1_filing_with_no_case_cannot_be_opened():
    with Harness() as h:
        response = h.http.post("/tpsi/filings", headers=H, json={
            "entity_id": "e1", "form_code": "Nar1", "form_xml": "<x/>"})

    assert response.status_code == 400
    assert "case" in response.json()["detail"]
    assert len(h.store.rows("tpsi_filings")) == 1


def test_the_service_refuses_it_too():
    with pytest.raises(ValueError, match="case"):
        filings.create_filing(entity_id="e1", form_code="Nar1",
                              form_xml="<x/>", user_id="u1")


# --------------------------------------------------------------------------- #
#  S-7 — a refusal with no fault list still says what happened
# --------------------------------------------------------------------------- #

def test_a_faultless_failure_carries_its_message_and_kind():
    status = filings.form_status({"stage": "submission_failed", "cr_error": {
        "faults": [], "kind": "auth", "message": "TPSI rejected the token twice"}})
    assert status["message"] == "TPSI rejected the token twice"
    assert status["kind"] == "auth"


def test_a_stage_that_is_not_a_failure_carries_no_message():
    status = filings.form_status({"stage": "signed", "cr_error": None})
    assert status.get("message") is None


# --------------------------------------------------------------------------- #
#  S-8 — a listed document must be THIS return
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name,ref,date", [
    ("ND2A", "ND2A(55)", "23/10/2026"),                  # a different form
    ("Annual Return", "NAR1(731)", "28/06/2025"),        # last year's return
])
def test_a_listed_document_that_is_not_this_return_is_refused(name, ref, date):
    with Harness(_unknown()) as h:
        h.cr.answers["/tpsi/docStatusEnquiry"] = doc_status_reply(
            document_name=name, document_ref_no=ref, submission_date=date)
        response = _resolve(h, outcome="lodged", receipt=RECEIPT_IN)

        assert response.status_code == 422
        assert response.json()["detail"]["reason"] == "not_this_return"
        assert h.stage() == "submission_unknown"


# --------------------------------------------------------------------------- #
#  B3 (review 02) -- CR calls an NAR1 "Annual Return"
# --------------------------------------------------------------------------- #

def test_crs_own_documented_example_is_recognised_as_the_return():
    """The exact reply CR publishes (TPSI API Interface v1.0.14, 6.5.5),
    through the real `reads.case_status` parser: documentName "Annual Return",
    documentRefNo "NAR1(731)". The first S-8 fix looked for the string "NAR1" in
    documentName only, so it refused this -- and an operator pushed to "CR does
    not have it" files a held return again, which is the PROD incident."""
    from datetime import date

    from tests.tpsi.test_reads import STATUS

    class Client:
        def post_soap(self, path, body):
            return STATUS

    rows = filings.verify_lodged(Client(), "180256934", "11651", date(2022, 6, 28))
    assert rows[0]["documentName"] == "Annual Return"
    assert rows[0]["documentRefNo"] == "NAR1(731)"


def test_the_route_accepts_the_harness_default_which_is_crs_real_wording():
    with Harness(_unknown()) as h:
        response = _resolve(h, outcome="lodged", receipt=RECEIPT_IN)

    assert response.status_code == 200, response.text
    assert h.stage() == "submitted"


@pytest.mark.parametrize("name,ref", [
    ("Annual Return", ""),            # the name alone
    ("Document", "NAR1(731)"),        # the reference alone
    ("", ""),                         # CR said nothing: not held against it
])
def test_nar1_is_recognised_by_name_or_by_reference_and_silence_is_not_refused(
        name, ref):
    with Harness(_unknown()) as h:
        h.cr.answers["/tpsi/docStatusEnquiry"] = doc_status_reply(
            document_name=name, document_ref_no=ref)
        response = _resolve(h, outcome="lodged", receipt=RECEIPT_IN)

    assert response.status_code == 200, response.text


def test_the_hints_are_the_ones_the_status_poll_already_uses():
    """One decision about what CR calls this return, not two (review 02, B3)."""
    from services import nar1_cr_status
    from services.tpsi import doc_status

    assert nar1_cr_status._NAR1_DOCUMENT_HINTS is doc_status.NAR1_DOCUMENT_HINTS
    assert filings.NAR1_DOCUMENT_HINTS is doc_status.NAR1_DOCUMENT_HINTS


def test_an_empty_document_list_is_still_accepted():
    """Conductor's decision, 2026-10-26: CR faults on an unknown case number,
    so an empty list is evidence it exists — and a same-day return is
    routinely unlisted for hours."""
    empty = envelope(
        f'<cr:enquireDocStatusResponse xmlns:cr="{CR_NS}"><cr:result>'
        "<cr:documentList/></cr:result></cr:enquireDocStatusResponse>")
    with Harness(_unknown()) as h:
        h.cr.answers["/tpsi/docStatusEnquiry"] = empty
        response = _resolve(h, outcome="lodged", receipt=RECEIPT_IN)

    assert response.status_code == 200
    assert h.stage() == "submitted"


def test_a_receipt_dated_before_the_submit_was_claimed_is_refused():
    with Harness(_unknown()) as h:
        response = _resolve(h, outcome="lodged",
                            receipt={**RECEIPT_IN, "transactionDate": "22/10/2026"})

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "before_claim"
    assert h.cr.count("docStatusEnquiry") == 0


# --------------------------------------------------------------------------- #
#  S-9 — the case number is digits, and is escaped anyway
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("case_no", ["18<x/>0", "NAR-2026-0319", "12345", "1" * 13])
def test_a_case_number_that_is_not_crs_shape_is_refused_before_cr(case_no):
    with Harness(_unknown()) as h:
        response = _resolve(h, outcome="lodged",
                            receipt={**RECEIPT_IN, "caseNo": case_no})

    assert response.status_code == 400
    assert h.cr.count("docStatusEnquiry") == 0


def test_the_status_enquiry_escapes_what_it_is_given():
    from services.tpsi import reads

    sent = {}

    class Client:
        def post_soap(self, path, body):
            sent["body"] = body
            return doc_status_reply()

    reads.case_status(Client(), case_no="1<2&3")
    assert "<cr:caseNo>1&lt;2&amp;3</cr:caseNo>" in sent["body"]


# --------------------------------------------------------------------------- #
#  S-10 — a credential that will not load is "try again", not a 500
# --------------------------------------------------------------------------- #

def test_resolve_answers_503_when_the_cr_credential_cannot_be_loaded():
    from unittest.mock import patch

    with Harness(_unknown()) as h, \
            patch("routers.tpsi.client_for",
                  side_effect=RuntimeError("shared credential unavailable")):
        response = _resolve(h, outcome="lodged", receipt=RECEIPT_IN)

        assert response.status_code == 503
        assert h.stage() == "submission_unknown"


# --------------------------------------------------------------------------- #
#  N-4 — the form_filings mirror carries CR's date, not today's
# --------------------------------------------------------------------------- #

def test_the_mirrored_filed_date_is_crs_transaction_date():
    store = _unknown(form_filing_id="ff1")
    store.tables["form_filings"] = [{"id": "ff1", "filed_with_cr": False}]
    with Harness(store) as h:
        assert _resolve(h, outcome="lodged", receipt=RECEIPT_IN).status_code == 200

        assert h.store.get("form_filings", "ff1")["filed_date"] == "2026-10-23"
