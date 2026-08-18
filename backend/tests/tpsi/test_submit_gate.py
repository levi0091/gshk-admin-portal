"""The submit gate — the guard on a chargeable, irreversible CR submission.

One refusal test per gate condition, because a gate that only fails on the
first condition it happens to check is not a gate.
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from services.tpsi import filings

RECEIPT = b"""<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
 <soap:Body><cr:submitFormResponse
   xmlns:cr="http://interfaces.service.webservice.icris3e.cr.gov.hk/">
  <cr:receipt>
   <cr:accNo>N00061980009</cr:accNo><cr:brNo>00011651</cr:brNo>
   <cr:caseNo>180256934</cr:caseNo>
   <cr:docCodesWithBarcode>NAR1(73198499393)</cr:docCodesWithBarcode>
   <cr:pymtNo>5010475972</cr:pymtNo><cr:pymtRefNo>733037536</cr:pymtRefNo>
   <cr:transactionDate>28/06/2022</cr:transactionDate>
   <cr:transactionTime>13:36:44</cr:transactionTime>
   <cr:totalAmount>105.0</cr:totalAmount>
   <cr:paymentRcptList><amtChrg>105.0</amtChrg><docShtFrm>NAR1</docShtFrm>
     <rcptNo>D77000078859</rcptNo><revCode>118</revCode>
     <revDesc>Annual return fee</revDesc></cr:paymentRcptList>
  </cr:receipt></cr:submitFormResponse></soap:Body></soap:Envelope>"""


def _signed(**over):
    row = {
        "id": "f1", "entity_id": "e1", "form_code": "Nar1",
        "stage": filings.STAGE_SIGNED,
        "signed_xml": '<cr:submission><cr:EForm id="eForm"/></cr:submission>',
        "validated_xml": "<cr:submission/>", "form_filing_id": "ff1",
        "presenter_user_id": "u1", "presentor_account_id": "ACCT",
    }
    row.update(over)
    return row


def _client():
    client = MagicMock()
    client.post_form.return_value = RECEIPT
    return client


# ---- the four gate conditions, one refusal test each ----------------------

def test_refuses_when_not_signed():
    with patch.object(filings, "get_filing",
                      return_value=_signed(stage=filings.STAGE_VALIDATED)), \
         patch("services.tpsi.reads.check_balance", return_value=Decimal("999999")):
        with pytest.raises(filings.SubmitGateError, match="signed"):
            filings.submit(_client(), "f1", confirm=True, deposit_account="ACC")


def test_refuses_when_signed_xml_is_missing():
    with patch.object(filings, "get_filing", return_value=_signed(signed_xml=None)), \
         patch("services.tpsi.reads.check_balance", return_value=Decimal("999999")):
        with pytest.raises(filings.SubmitGateError, match="signed payload"):
            filings.submit(_client(), "f1", confirm=True, deposit_account="ACC")


def test_refuses_when_balance_is_below_the_fee():
    with patch.object(filings, "get_filing", return_value=_signed()), \
         patch("services.tpsi.reads.check_balance", return_value=Decimal("10")):
        with pytest.raises(filings.SubmitGateError, match="balance"):
            filings.submit(_client(), "f1", confirm=True, deposit_account="ACC")


def test_refuses_without_explicit_confirmation():
    with patch.object(filings, "get_filing", return_value=_signed()), \
         patch("services.tpsi.reads.check_balance", return_value=Decimal("999999")):
        with pytest.raises(filings.SubmitGateError, match="confirm"):
            filings.submit(_client(), "f1", confirm=False, deposit_account="ACC")


def test_confirm_must_be_true_not_merely_truthy():
    """`confirm="yes"` must not sail through — the check is identity, not truth."""
    with patch.object(filings, "get_filing", return_value=_signed()), \
         patch("services.tpsi.reads.check_balance", return_value=Decimal("999999")):
        with pytest.raises(filings.SubmitGateError, match="confirm"):
            filings.submit(_client(), "f1", confirm="yes", deposit_account="ACC")


# ---- double-charge protection --------------------------------------------

def test_refuses_a_filing_already_submitted():
    with patch.object(filings, "get_filing",
                      return_value=_signed(stage=filings.STAGE_SUBMITTED)), \
         patch("services.tpsi.reads.check_balance", return_value=Decimal("999999")):
        with pytest.raises(filings.SubmitGateError):
            filings.submit(_client(), "f1", confirm=True, deposit_account="ACC")


def test_refuses_a_filing_sent_to_edrive():
    """CR: a form sent to e-Drive is inconvertible back to TPSI format."""
    with patch.object(filings, "get_filing",
                      return_value=_signed(stage=filings.STAGE_EDRIVE)), \
         patch("services.tpsi.reads.check_balance", return_value=Decimal("999999")):
        with pytest.raises(filings.SubmitGateError):
            filings.submit(_client(), "f1", confirm=True, deposit_account="ACC")


def test_a_refused_submit_sends_nothing_to_cr():
    """The point of the gate: no refusal path may reach the chargeable call."""
    client = _client()
    with patch.object(filings, "get_filing", return_value=_signed()), \
         patch("services.tpsi.reads.check_balance", return_value=Decimal("999999")):
        with pytest.raises(filings.SubmitGateError):
            filings.submit(client, "f1", confirm=False, deposit_account="ACC")
    client.post_form.assert_not_called()


# ---- the balance check must be live --------------------------------------

def test_balance_is_read_live_on_every_submit():
    """Balance moves between calls; a cached value could authorise a submit the
    account can no longer cover."""
    calls = []

    def spy(client, account_no):
        calls.append(account_no)
        return Decimal("999999")

    with patch.object(filings, "get_filing", return_value=_signed()), \
         patch.object(filings, "_update"), \
         patch.object(filings, "_write_back_receipt"), \
         patch("services.tpsi.reads.check_balance", side_effect=spy):
        filings.submit(_client(), "f1", confirm=True, deposit_account="ACC")
    assert calls == ["ACC"]


# ---- happy path -----------------------------------------------------------

def test_successful_submit_records_the_receipt_and_stage():
    saved = {}
    with patch.object(filings, "get_filing", return_value=_signed()), \
         patch.object(filings, "_update", side_effect=lambda i, p: saved.update(p)), \
         patch.object(filings, "_write_back_receipt"), \
         patch("services.tpsi.reads.check_balance", return_value=Decimal("999999")):
        result = filings.submit(_client(), "f1", confirm=True, deposit_account="ACC")

    assert saved["stage"] == filings.STAGE_SUBMITTED
    assert saved["receipt"]["caseNo"] == "180256934"
    assert result["receipt"]["totalAmount"] == "105.0"
    assert saved["balance_at_submit"] is not None
    assert saved["submitted_at"] is not None


def test_submit_request_carries_the_deposit_account():
    """<cr:depositAccountNo> appears on submitForm and nowhere else."""
    client = _client()
    with patch.object(filings, "get_filing", return_value=_signed()), \
         patch.object(filings, "_update"), \
         patch.object(filings, "_write_back_receipt"), \
         patch("services.tpsi.reads.check_balance", return_value=Decimal("999999")):
        filings.submit(client, "f1", confirm=True, deposit_account="010000204551")
    operation, form_code, body = client.post_form.call_args[0]
    assert operation == "submitForm"
    assert form_code == "Nar1"
    assert "<cr:depositAccountNo>010000204551</cr:depositAccountNo>" in body


def test_submit_does_not_duplicate_an_existing_deposit_account():
    client = _client()
    existing = ('<cr:submission><cr:EForm id="eForm"/>'
                "<cr:depositAccountNo>010000204551</cr:depositAccountNo>"
                "</cr:submission>")
    with patch.object(filings, "get_filing",
                      return_value=_signed(signed_xml=existing)), \
         patch.object(filings, "_update"), \
         patch.object(filings, "_write_back_receipt"), \
         patch("services.tpsi.reads.check_balance", return_value=Decimal("999999")):
        filings.submit(client, "f1", confirm=True, deposit_account="010000204551")
    body = client.post_form.call_args[0][2]
    assert body.count("<cr:depositAccountNo>") == 1


def test_receipt_parses_the_payment_lines():
    receipt = filings.parse_receipt(RECEIPT)
    assert receipt["caseNo"] == "180256934"
    assert len(receipt["paymentRcptList"]) == 1
    assert receipt["paymentRcptList"][0]["amtChrg"] == "105.0"


def test_preview_reports_fee_and_balance_without_submitting():
    client = _client()
    with patch.object(filings, "get_filing", return_value=_signed()), \
         patch("services.tpsi.reads.check_balance", return_value=Decimal("999999")):
        preview = filings.preview(client, "f1", deposit_account="ACC")
    assert preview["fee"] == "105.00"
    assert preview["sufficient"] is True
    assert preview["ready"] is True
    client.post_form.assert_not_called()


def test_preview_reports_not_ready_before_signing():
    client = _client()
    with patch.object(filings, "get_filing",
                      return_value=_signed(stage=filings.STAGE_VALIDATED)), \
         patch("services.tpsi.reads.check_balance", return_value=Decimal("999999")):
        assert filings.preview(client, "f1", deposit_account="ACC")["ready"] is False


def test_failed_submit_records_the_error_and_does_not_mark_submitted():
    from services.tpsi.errors import TpsiValidationError

    client = MagicMock()
    client.post_form.side_effect = TpsiValidationError([("ERR_X", "boom")])
    saved = {}
    with patch.object(filings, "get_filing", return_value=_signed()), \
         patch.object(filings, "_update", side_effect=lambda i, p: saved.update(p)), \
         patch("services.tpsi.reads.check_balance", return_value=Decimal("999999")):
        with pytest.raises(TpsiValidationError):
            filings.submit(client, "f1", confirm=True, deposit_account="ACC")
    # A CHARGEABLE call was rejected — distinct from a free validation
    # failure, and the stored status must distinguish them.
    assert saved["stage"] == filings.STAGE_SUBMISSION_FAILED


def test_receipt_writeback_failure_does_not_fail_the_submission():
    """By this point CR has been paid and the filing cannot be undone — a
    bookkeeping failure must not surface as a failed submission."""
    with patch.object(filings, "get_filing", return_value=_signed()), \
         patch.object(filings, "_update"), \
         patch.object(filings, "get_supabase", side_effect=RuntimeError("db down")), \
         patch("services.tpsi.reads.check_balance", return_value=Decimal("999999")):
        result = filings.submit(_client(), "f1", confirm=True, deposit_account="ACC")
    assert result["receipt"]["caseNo"] == "180256934"


# ---- the off-portal interlock (BE-6 fix round 1) ---------------------------
#
# nar1_cases.manual_conflict() guards the manual path against a live filing but
# only in one direction: it ALLOWS a manual completion while a filing sits at
# 'validated', and 'validated' -> 'signed' -> 'submitted' then knew nothing about
# the case having been filed on paper. Every step that puts the form in front of
# CR now refuses.


def _case_supabase(case: dict | None):
    """A Supabase double for the nar1_cases lookup manual_completion() makes."""
    table = MagicMock()
    (table.select.return_value.eq.return_value.limit.return_value
     .execute.return_value.data) = [case] if case else []
    sb = MagicMock()
    sb.table.return_value = table
    return sb


COMPLETED_CASE = {
    "id": "c1", "case_no": "NAR-2026-0007",
    "manual_receipt": {"caseNo": "180256934"},
    "manual_submitted_at": "2026-08-18T02:00:00+00:00",
}


def test_submit_refuses_a_case_already_filed_off_portal():
    """Every other gate condition passes: signed, payload stored, funds ample,
    confirm=True. Only the interlock stands between this and a second lodgement
    of the same statutory return."""
    filing = _signed(nar1_case_id="c1")
    with patch.object(filings, "get_filing", return_value=filing), \
         patch.object(filings, "get_supabase",
                      return_value=_case_supabase(COMPLETED_CASE)), \
         patch("services.tpsi.reads.check_balance") as balance:
        with pytest.raises(filings.ManualCompletionInterlock, match="off-portal"):
            filings.submit(_client(), "f1", confirm=True, deposit_account="ACC")
    # Refused before ANY CR traffic, the free balance read included.
    balance.assert_not_called()


def test_sign_refuses_a_case_already_filed_off_portal():
    """The refusal has to surface here, not one step later at the charge."""
    filing = _signed(nar1_case_id="c1", stage=filings.STAGE_VALIDATED)
    client = _client()
    with patch.object(filings, "get_filing", return_value=filing), \
         patch.object(filings, "get_supabase",
                      return_value=_case_supabase(COMPLETED_CASE)):
        with pytest.raises(filings.ManualCompletionInterlock, match="off-portal"):
            filings.sign(client, "f1", "DIRECTOR1", "pw")
    client.post_form.assert_not_called()


def test_edrive_refuses_a_case_already_filed_off_portal():
    """e-Drive is a lodgement channel too — STAGE_EDRIVE is in
    nar1_cases.CR_FILED_STAGES — and it is reachable straight from 'validated',
    so guarding only sign/submit would leave the same door open."""
    filing = _signed(nar1_case_id="c1", stage=filings.STAGE_VALIDATED)
    client = _client()
    with patch.object(filings, "get_filing", return_value=filing), \
         patch.object(filings, "get_supabase",
                      return_value=_case_supabase(COMPLETED_CASE)):
        with pytest.raises(filings.ManualCompletionInterlock, match="off-portal"):
            filings.upload_edrive(client, "f1")
    client.post_form.assert_not_called()


def test_the_interlock_is_a_submit_gate_error_so_the_route_audits_the_refusal():
    """routers/tpsi.submit_filing logs TPSI_SUBMISSION_FAILED for
    SubmitGateError. If the interlock stopped being one, a refused submit would
    vanish from the audit trail."""
    assert issubclass(filings.ManualCompletionInterlock, filings.SubmitGateError)


def test_a_case_with_no_off_portal_receipt_does_not_block_the_chain():
    """The interlock keys on manual_receipt — the recorded SUBMISSION — not on a
    wet-signed scan having been uploaded. Uploading the scan is preparation and
    must leave the e-Sign chain usable."""
    case = {"id": "c1", "manual_receipt": None,
            "manual_signed_document_id": "d1"}
    with patch.object(filings, "get_filing",
                      return_value=_signed(nar1_case_id="c1")), \
         patch.object(filings, "get_supabase", return_value=_case_supabase(case)), \
         patch.object(filings, "_update"), \
         patch.object(filings, "_write_back_receipt"), \
         patch("services.tpsi.reads.check_balance", return_value=Decimal("999999")):
        result = filings.submit(_client(), "f1", confirm=True, deposit_account="ACC")
    assert result["receipt"]["caseNo"] == "180256934"


def test_a_filing_with_no_case_is_not_looked_up_at_all():
    """NNC1 and bare TPSI filings carry no nar1_case_id. Reading nar1_cases for
    them would be a round trip on every submit that can never find anything."""
    sb = MagicMock()
    with patch.object(filings, "get_filing", return_value=_signed()), \
         patch.object(filings, "get_supabase", return_value=sb), \
         patch.object(filings, "_update"), \
         patch.object(filings, "_write_back_receipt"), \
         patch("services.tpsi.reads.check_balance", return_value=Decimal("999999")):
        filings.submit(_client(), "f1", confirm=True, deposit_account="ACC")
    assert not any(c.args and c.args[0] == "nar1_cases" for c in sb.table.call_args_list)


def test_the_interlock_fails_closed_when_the_case_cannot_be_read():
    """A Supabase outage must block the chargeable call, not wave it through."""
    broken = MagicMock()
    broken.table.side_effect = RuntimeError("supabase unreachable")
    with patch.object(filings, "get_filing",
                      return_value=_signed(nar1_case_id="c1")), \
         patch.object(filings, "get_supabase", return_value=broken), \
         patch("services.tpsi.reads.check_balance") as balance:
        with pytest.raises(RuntimeError, match="supabase unreachable"):
            filings.submit(_client(), "f1", confirm=True, deposit_account="ACC")
    balance.assert_not_called()
