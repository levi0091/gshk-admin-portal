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
    assert saved["stage"] == filings.STAGE_FAILED


def test_receipt_writeback_failure_does_not_fail_the_submission():
    """By this point CR has been paid and the filing cannot be undone — a
    bookkeeping failure must not surface as a failed submission."""
    with patch.object(filings, "get_filing", return_value=_signed()), \
         patch.object(filings, "_update"), \
         patch.object(filings, "get_supabase", side_effect=RuntimeError("db down")), \
         patch("services.tpsi.reads.check_balance", return_value=Decimal("999999")):
        result = filings.submit(_client(), "f1", confirm=True, deposit_account="ACC")
    assert result["receipt"]["caseNo"] == "180256934"
