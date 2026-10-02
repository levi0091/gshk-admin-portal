"""Consent + overall signatures in one verifyPinSigning call, and the free
submit (spec §5, §8; CR's reference program createEFormSignatureV2)."""
import pytest

from services.officer_changes import signing
from services.tpsi import filings
from services.tpsi.errors import TpsiError
from services.tpsi.soap import CR_NS

PASSWORD = "Director-Secret-1"
VALIDATED = (
    '<cr:submission><cr:EForm id="eForm"><cr:formModel id="formData">'
    "<cr:language>E</cr:language>"
    '<cr:appOfNpBeans><cr:appOfNpBean id="S1"><cr:cpty>D</cr:cpty>'
    "<cr:selectPersonId>ER-DIR-1</cr:selectPersonId></cr:appOfNpBean>"
    "<cr:appOfNpBean><cr:cpty>S</cr:cpty></cr:appOfNpBean></cr:appOfNpBeans>"
    '<cr:appOfBcBeans><cr:appOfBcBean id="S2"><cr:cpty>D</cr:cpty></cr:appOfBcBean>'
    "</cr:appOfBcBeans>"
    "<cr:selectPersonName>GET STARTED HK LIMITED</cr:selectPersonName>"
    "</cr:formModel><cr:formDataSignatures/></cr:EForm>"
    '<cr:EFormSignatures><ds:Signature id="CR">crsig</ds:Signature></cr:EFormSignatures>'
    "</cr:submission>"
)


class FakeClient:
    def __init__(self, response=b"", error=None):
        self.calls, self.response, self.error = [], response, error

    def post_form(self, operation, form_code, payload):
        self.calls.append((operation, form_code, payload))
        if self.error:
            raise self.error
        return self.response


@pytest.fixture
def chain(monkeypatch):
    state = {"filing": {"id": "F1", "form_code": "Nd2a", "stage": "validated",
                        "validated_xml": VALIDATED, "nar1_case_id": "K1"},
             "updates": [], "pins": []}
    monkeypatch.setattr(filings, "get_filing", lambda fid: dict(state["filing"]))
    monkeypatch.setattr(filings, "_update", lambda fid, p: state["updates"].append(p))
    monkeypatch.setattr(filings, "_refuse_if_case_finished", lambda f, a: None)
    monkeypatch.setattr(filings, "_write_back_receipt", lambda f, r: None)
    monkeypatch.setattr(signing, "signing_public_key_pem", lambda xml: "PEM")

    def fake_pin(digest_input, user_id, password, key, uri="#eForm"):
        state["pins"].append({"input": digest_input, "user": user_id, "uri": uri,
                              "key": key})
        return f'<cr:PinSign URI="{uri}">{user_id}</cr:PinSign>'

    monkeypatch.setattr(signing, "build_pin_sign", fake_pin)
    monkeypatch.setattr(signing, "parse_response", lambda raw, tag: raw)
    monkeypatch.setattr(signing, "text_of", lambda el, name: "OK")
    return state


CONSENTS = [{"bean_id": "S1", "user_id": "ER-DIR-1", "password": PASSWORD},
            {"bean_id": "S2", "user_id": "ER-CORP-SIGNER", "password": PASSWORD}]


def test_consents_then_overall_in_one_call(chain):
    client = FakeClient()
    out = signing.sign(client, "F1", signatory_user_id="STAFF-1",
                       eservice_password="staff-pw", consents=CONSENTS)
    assert out["consents"] == 2
    assert [p["uri"] for p in chain["pins"]] == ["#S1", "#S2", "#eForm"]
    s1, s2, overall = chain["pins"]
    assert s1["input"].startswith(f'<cr:appOfNpBean xmlns:cr="{CR_NS}" id="S1">')
    assert s1["input"].endswith("</cr:appOfNpBean>") and "cpty>S<" not in s1["input"]
    assert s2["input"].startswith(f'<cr:appOfBcBean xmlns:cr="{CR_NS}" id="S2">')
    # The overall signature covers the EForm WITH the consents inside it.
    assert overall["input"].startswith(f'<cr:EForm xmlns:cr="{CR_NS}" id="eForm">')
    assert '<cr:PinSign URI="#S1">' in overall["input"]
    assert overall["user"] == "STAFF-1"
    assert len(client.calls) == 1 and client.calls[0][0] == "verifyPinSigning"
    payload = client.calls[0][2]
    consents_at = payload.index("<cr:formDataSignatures>")
    assert payload.index('URI="#S1"') < payload.index('URI="#S2"') < payload.index("</cr:formDataSignatures>")
    assert consents_at < payload.index("</cr:EForm>")
    assert payload.index('<ds:Signature id="CR">') < payload.index('URI="#eForm"')
    assert chain["updates"][-1]["stage"] == "signed"
    assert PASSWORD not in str(chain["updates"])


def test_an_nd2b_carries_only_the_overall_signature(chain):
    chain["filing"]["form_code"] = "Nd2b"
    signing.sign(FakeClient(), "F1", signatory_user_id="STAFF-1",
                 eservice_password="pw", consents=[])
    assert [p["uri"] for p in chain["pins"]] == ["#eForm"]


def test_a_payload_without_formdatasignatures_gets_one_after_the_form_model():
    xml = VALIDATED.replace("<cr:formDataSignatures/>", "")
    out = signing.insert_form_data_signatures(xml, "<cr:PinSign/>")
    assert "</cr:formModel><cr:formDataSignatures><cr:PinSign/></cr:formDataSignatures></cr:EForm>" in out


def test_a_missing_consent_credential_stops_before_cr(chain):
    client = FakeClient()
    with pytest.raises(signing.ConsentCredentialMissing):
        signing.sign(client, "F1", signatory_user_id="STAFF-1", eservice_password="pw",
                     consents=[{"bean_id": "S1", "user_id": "ER-DIR-1", "password": ""}])
    assert client.calls == [] and chain["pins"] == []


def test_the_form_level_signatory_is_checked_not_a_directors_consent_id(chain):
    # The bean's own selectPersonId (ER-DIR-1) is not the signatory.
    signing.sign(FakeClient(), "F1", signatory_user_id="STAFF-1",
                 eservice_password="pw", consents=CONSENTS)
    declared = VALIDATED.replace("<cr:selectPersonName>",
                                 "<cr:selectPersonId>SOMEONE-ELSE</cr:selectPersonId>"
                                 "<cr:selectPersonName>")
    chain["filing"]["validated_xml"] = declared
    with pytest.raises(filings.SignatoryMismatch):
        signing.sign(FakeClient(), "F1", signatory_user_id="STAFF-1",
                     eservice_password="pw", consents=CONSENTS)


def test_signing_needs_a_validated_filing(chain):
    chain["filing"]["stage"] = "draft"
    with pytest.raises(ValueError):
        signing.sign(FakeClient(), "F1", signatory_user_id="S", eservice_password="p",
                     consents=[])


def test_a_cr_refusal_marks_signing_failed(chain):
    with pytest.raises(TpsiError):
        signing.sign(FakeClient(error=TpsiError("bad pin")), "F1", signatory_user_id="S",
                     eservice_password="p", consents=[])
    assert chain["updates"][-1]["stage"] == "signing_failed"


def test_submit_needs_confirm_and_sends_no_deposit_account(chain, monkeypatch):
    chain["filing"].update(stage="signed", signed_xml="<cr:submission>SIGNED</cr:submission>")
    client = FakeClient()
    with pytest.raises(filings.SubmitGateError):
        signing.submit(client, "F1", confirm=False)
    assert client.calls == []
    monkeypatch.setattr(filings, "parse_receipt", lambda raw: {"caseNo": "123"})
    out = signing.submit(client, "F1", confirm=True)
    assert out["receipt"] == {"caseNo": "123"}
    assert client.calls == [("submitForm", "Nd2a", "<cr:submission>SIGNED</cr:submission>")]
    assert chain["updates"][-1]["stage"] == "submitted"
    assert chain["updates"][-1]["fee_amount"] == "0"


def test_submit_refusal_marks_submission_failed(chain):
    chain["filing"].update(stage="signed", signed_xml="<x/>")
    with pytest.raises(TpsiError):
        signing.submit(FakeClient(error=TpsiError("no")), "F1", confirm=True)
    assert chain["updates"][-1]["stage"] == "submission_failed"


def test_submit_needs_a_signed_filing(chain):
    with pytest.raises(ValueError):
        signing.submit(FakeClient(), "F1", confirm=True)


# -- the receipt of a free form (measured on CR TEST, 2026-10-02) ----------------

#: CR TEST's real receipt for ND2B case 141946253: no payment block, so no refNo,
#: transaction date, time or amount — the document reference is only in the
#: barcode field.
CR_TEST_RECEIPT = {
    "caseNo": "141946253", "brNo": "T0001137", "accNo": None,
    "chiCoyName": "二六零七二七一零零一一六測試有限公司",
    "engCoyName": "CGAHCHBAABBG TEST COMPANY LIMITED",
    "docCodesWithBarcode": "ND2B (T0022892651)", "pymtNo": None, "pymtRefNo": None,
    "pymtMtd": None, "transactionDate": None, "transactionTime": None,
    "totalAmount": None, "refNo": None, "paymentRcptList": [],
}


def test_a_free_forms_receipt_gains_its_document_reference_and_keeps_crs_fields():
    out = signing.with_document_ref(CR_TEST_RECEIPT)
    assert out["documentRefNo"] == "T0022892651"
    assert {k: out[k] for k in CR_TEST_RECEIPT} == CR_TEST_RECEIPT


def test_a_receipt_that_names_its_reference_is_left_alone():
    receipt = {**CR_TEST_RECEIPT, "refNo": "R1"}
    assert signing.with_document_ref(receipt) == receipt
    no_barcode = {**CR_TEST_RECEIPT, "docCodesWithBarcode": None}
    assert signing.with_document_ref(no_barcode) == no_barcode
