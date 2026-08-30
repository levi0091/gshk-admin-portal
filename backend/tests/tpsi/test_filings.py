from unittest.mock import MagicMock, patch

import pytest

from services.tpsi import errors, filings

VALIDATE_OK = b"""<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
 <soap:Body><cr:validateFormResponse
   xmlns:ds="http://www.w3.org/2000/09/xmldsig#"
   xmlns:cr="http://interfaces.service.webservice.icris3e.cr.gov.hk/">
  <cr:submission>
   <cr:EForm id="eForm"><cr:formModel id="formData">
     <cr:formCode>NAR1</cr:formCode><cr:brNo>00011651</cr:brNo>
   </cr:formModel></cr:EForm>
   <cr:EFormSignatures><ds:Signature id="CR">
     <ds:SignatureValue>SIGVALUE123</ds:SignatureValue>
   </ds:Signature></cr:EFormSignatures>
  </cr:submission>
 </cr:validateFormResponse></soap:Body></soap:Envelope>"""

FAULT = b"""<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
 <soap:Body><soap:Fault><faultcode>soap:Server</faultcode>
 <faultstring>err</faultstring><detail>
 <cr:EfilingWebServiceError xmlns:cr="http://x/"><webServiceFaultBeans>
 <faultCode>ERR_MSG_REQUIRED</faultCode><faultString>brNo is required</faultString>
 </webServiceFaultBeans></cr:EfilingWebServiceError></detail>
 </soap:Fault></soap:Body></soap:Envelope>"""

EDRIVE_OK = b"""<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
 <soap:Body><cr:uploadToEdriveResponse
   xmlns:cr="http://interfaces.service.webservice.icris3e.cr.gov.hk/">
   <cr:submission><cr:result>Form submitted to E drive successfully.</cr:result>
   </cr:submission></cr:uploadToEdriveResponse></soap:Body></soap:Envelope>"""


def _row(**over):
    row = {
        "id": "f1", "entity_id": "e1", "form_code": "Nar1",
        "stage": filings.STAGE_DRAFT, "request_xml": "<formCode>NAR1</formCode>",
        "validated_xml": None, "signed_xml": None,
        "presenter_user_id": "u1", "presentor_account_id": "ACCT",
    }
    row.update(over)
    return row


def test_validate_posts_the_right_operation_and_form_code():
    client = MagicMock()
    client.post_form.return_value = VALIDATE_OK
    with patch.object(filings, "get_filing", return_value=_row()), \
         patch.object(filings, "_update", return_value=None):
        filings.validate(client, "f1")
    assert client.post_form.call_args[0][0] == "validateForm"
    assert client.post_form.call_args[0][1] == "Nar1"


def test_validate_stores_the_cr_signed_payload_and_advances_stage():
    client = MagicMock()
    client.post_form.return_value = VALIDATE_OK
    saved = {}
    with patch.object(filings, "get_filing", return_value=_row()), \
         patch.object(filings, "_update", side_effect=lambda i, p: saved.update(p)):
        filings.validate(client, "f1")
    assert saved["stage"] == filings.STAGE_VALIDATED
    assert "SIGVALUE123" in saved["validated_xml"]
    assert saved["validated_at"] is not None


def test_validated_payload_is_stored_verbatim():
    """Request and response share one namespace convention, so the payload is
    carried forward unchanged — CR's digest covers these exact bytes."""
    client = MagicMock()
    client.post_form.return_value = VALIDATE_OK
    saved = {}
    with patch.object(filings, "get_filing", return_value=_row()), \
         patch.object(filings, "_update", side_effect=lambda i, p: saved.update(p)):
        filings.validate(client, "f1")
    assert saved["validated_xml"] in VALIDATE_OK.decode()
    assert saved["validated_xml"].startswith("<cr:submission>")


def test_validate_failure_records_the_errors_and_marks_failed():
    client = MagicMock()
    client.post_form.return_value = FAULT
    saved = {}
    with patch.object(filings, "get_filing", return_value=_row()), \
         patch.object(filings, "_update", side_effect=lambda i, p: saved.update(p)):
        with pytest.raises(errors.TpsiValidationError):
            filings.validate(client, "f1")
    # Step-specific, not a generic "failed": a validation failure is free
    # and retryable, and the status has to say so (migration 018).
    assert saved["stage"] == filings.STAGE_VALIDATION_FAILED
    assert "brNo is required" in str(saved["cr_error"])


def test_validate_refuses_a_submitted_filing():
    """The money invariant: the double-charge guard is the partial unique
    index on stage='submitted'. Walking a submitted row back to 'validated'
    would drop it from that index's coverage and let it be resubmitted."""
    client = MagicMock()
    with patch.object(filings, "get_filing", return_value=_row(stage=filings.STAGE_SUBMITTED)), \
         patch.object(filings, "_update") as updated:
        with pytest.raises(ValueError, match="submitted"):
            filings.validate(client, "f1")
    updated.assert_not_called()
    client.post_form.assert_not_called()


def test_validate_refuses_a_signed_filing():
    client = MagicMock()
    with patch.object(filings, "get_filing", return_value=_row(stage=filings.STAGE_SIGNED)), \
         patch.object(filings, "_update") as updated:
        with pytest.raises(ValueError, match="signed"):
            filings.validate(client, "f1")
    updated.assert_not_called()
    client.post_form.assert_not_called()


def test_validate_refuses_an_edrive_filing():
    client = MagicMock()
    with patch.object(filings, "get_filing", return_value=_row(stage=filings.STAGE_EDRIVE)), \
         patch.object(filings, "_update") as updated:
        with pytest.raises(ValueError, match="edrive"):
            filings.validate(client, "f1")
    updated.assert_not_called()
    client.post_form.assert_not_called()


def test_validate_allows_redoing_a_draft_filing():
    """The existing default-stage fixture case, made explicit: a fresh draft
    must still be validatable."""
    client = MagicMock()
    client.post_form.return_value = VALIDATE_OK
    saved = {}
    with patch.object(filings, "get_filing", return_value=_row(stage=filings.STAGE_DRAFT)), \
         patch.object(filings, "_update", side_effect=lambda i, p: saved.update(p)):
        filings.validate(client, "f1")
    assert saved["stage"] == filings.STAGE_VALIDATED


def test_validate_allows_redoing_an_already_validated_filing():
    """A user fixing field errors after a first validate and retrying is
    legitimate — only signed/submitted/edrive are refused."""
    client = MagicMock()
    client.post_form.return_value = VALIDATE_OK
    saved = {}
    with patch.object(filings, "get_filing",
                      return_value=_row(stage=filings.STAGE_VALIDATED,
                                        validated_xml="<cr:submission>old</cr:submission>")), \
         patch.object(filings, "_update", side_effect=lambda i, p: saved.update(p)):
        filings.validate(client, "f1")
    assert saved["stage"] == filings.STAGE_VALIDATED
    assert "SIGVALUE123" in saved["validated_xml"]


def test_edrive_requires_a_validated_filing():
    """e-Drive takes the validated payload; a draft has no CR signature yet."""
    client = MagicMock()
    with patch.object(filings, "get_filing", return_value=_row(stage=filings.STAGE_DRAFT)):
        with pytest.raises(ValueError, match="validated"):
            filings.upload_edrive(client, "f1")


def test_edrive_marks_the_filing_and_is_terminal():
    """CR: 'The Web-Form is inconvertible to TPSI format after submitting to
    e-Drive' — it must not then be submitted through TPSI."""
    client = MagicMock()
    client.post_form.return_value = EDRIVE_OK
    saved = {}
    with patch.object(filings, "get_filing",
                      return_value=_row(stage=filings.STAGE_VALIDATED,
                                        validated_xml="<submission/>")), \
         patch.object(filings, "_update", side_effect=lambda i, p: saved.update(p)):
        result = filings.upload_edrive(client, "f1")
    assert saved["stage"] == filings.STAGE_EDRIVE
    assert "successfully" in result["result"]


def test_create_filing_starts_at_draft():
    with patch.object(filings, "_insert", side_effect=lambda p: p):
        row = filings.create_filing(
            entity_id="e1", form_code="Nar1",
            form_xml="<formCode>NAR1</formCode>", user_id="u1",
        )
    assert row["stage"] == filings.STAGE_DRAFT
    assert row["form_code"] == "Nar1"


def test_unknown_form_code_is_rejected_before_any_call():
    with patch.object(filings, "_insert", side_effect=lambda p: p):
        with pytest.raises(KeyError):
            filings.create_filing(
                entity_id="e1", form_code="Zzz9", form_xml="<x/>", user_id="u1"
            )


# ---- sign ---------------------------------------------------------------

SIGN_OK = b"""<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
 <soap:Body><cr:verifyPinSigningResponse
   xmlns:cr="http://interfaces.service.webservice.icris3e.cr.gov.hk/">
   <cr:result>Pin Signature(s) Verified Successfully.</cr:result>
 </cr:verifyPinSigningResponse></soap:Body></soap:Envelope>"""

def _cr_certificate_b64():
    """A stand-in for the <ds:X509Certificate> CR puts on every validate
    response. `sign()` encrypts <cr:EncryptionKey> to THIS certificate's public
    key rather than to TPSI_CR_PUBLIC_KEY, so a validated payload without one
    cannot be signed — which is why the fixture below carries a real DER."""
    import base64 as _b64
    import datetime as _dt

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ICRIS TEST")])
    now = _dt.datetime(2026, 1, 1)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + _dt.timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )
    return _b64.b64encode(
        cert.public_bytes(serialization.Encoding.DER)
    ).decode()


CR_CERT_B64 = _cr_certificate_b64()

VALIDATED_XML = (
    '<cr:submission><cr:EForm id="eForm"><cr:formModel id="formData">'
    "<cr:formCode>NAR1</cr:formCode></cr:formModel></cr:EForm>"
    '<cr:EFormSignatures><cr:Signature id="CR">'
    f"<ds:X509Certificate>{CR_CERT_B64}</ds:X509Certificate>"
    "</cr:Signature></cr:EFormSignatures>"
    "</cr:submission>"
)


def test_sign_requires_a_validated_filing():
    with patch.object(filings, "get_filing", return_value=_row(stage=filings.STAGE_DRAFT)):
        with pytest.raises(ValueError, match="validated"):
            filings.sign(MagicMock(), "f1", "U", "pw")


def test_sign_places_pinsign_inside_eformsignatures_below_cr_signature():
    client = MagicMock()
    client.post_form.return_value = SIGN_OK
    saved = {}
    with patch.object(filings, "get_filing",
                      return_value=_row(stage=filings.STAGE_VALIDATED,
                                        validated_xml=VALIDATED_XML)), \
         patch.object(filings, "_update", side_effect=lambda i, p: saved.update(p)):
        filings.sign(client, "f1", "USERID", "pw")

    signed = saved["signed_xml"]
    assert signed.index('id="CR"') < signed.index("PinSign")
    assert signed.index("PinSign") < signed.index("</cr:EFormSignatures>")
    assert saved["stage"] == filings.STAGE_SIGNED


def test_sign_signs_the_eform_element_only_not_the_signatures():
    """The overall signature's scope is EForm (URI='#eForm')."""
    captured = {}
    client = MagicMock()
    client.post_form.return_value = SIGN_OK
    with patch.object(filings, "get_filing",
                      return_value=_row(stage=filings.STAGE_VALIDATED,
                                        validated_xml=VALIDATED_XML)), \
         patch.object(filings, "_update"), \
         patch("services.tpsi.crypto.build_pin_sign",
               side_effect=lambda eform, *a, **k: captured.setdefault("eform", eform) or "<cr:PinSign/>"):
        filings.sign(client, "f1", "USERID", "pw")
    assert captured["eform"].startswith("<cr:EForm")
    assert captured["eform"].endswith("</cr:EForm>")
    assert "EFormSignatures" not in captured["eform"]


def test_sign_never_stores_the_password():
    client = MagicMock()
    client.post_form.return_value = SIGN_OK
    saved = {}
    with patch.object(filings, "get_filing",
                      return_value=_row(stage=filings.STAGE_VALIDATED,
                                        validated_xml=VALIDATED_XML)), \
         patch.object(filings, "_update", side_effect=lambda i, p: saved.update(p)):
        filings.sign(client, "f1", "USERID", "sup3rs3cret")
    assert "sup3rs3cret" not in str(saved)


# ── The declared signatory must be the one signing (Q1) ─────────────────────
# CR's worksheet: selectPersonId is "Empty if sign by Body Corporate". So for
# every real GSHK client — whose secretary is GSHK Ltd, a body corporate — the
# return names no person and these guards never fire. Where a return DOES name
# one, a signature from another account makes it a false declaration.

_NAMED = VALIDATED_XML.replace(
    "<cr:formCode>NAR1</cr:formCode>",
    "<cr:formCode>NAR1</cr:formCode><cr:selectPersonId>EUSER-THEM</cr:selectPersonId>",
)


def test_declared_signatory_id_reads_the_named_person():
    assert filings.declared_signatory_id(_NAMED) == "EUSER-THEM"


@pytest.mark.parametrize("xml", [
    None,
    "",
    VALIDATED_XML,                                     # body corporate: no tag
    VALIDATED_XML.replace("<cr:formCode>NAR1</cr:formCode>",
                          "<cr:selectPersonId></cr:selectPersonId>"),  # empty
    VALIDATED_XML.replace("<cr:formCode>NAR1</cr:formCode>",
                          "<cr:selectPersonId>   </cr:selectPersonId>"),
])
def test_declared_signatory_id_is_none_when_no_person_is_named(xml):
    """An absent OR empty tag both mean "signed by a body corporate", which is
    the normal GSHK case — neither may be read as a signatory called "" that
    then mismatches every real account."""
    assert filings.declared_signatory_id(xml) is None


def test_sign_refuses_when_the_return_names_a_different_person():
    client = MagicMock()
    with patch.object(filings, "get_filing",
                      return_value=_row(stage=filings.STAGE_VALIDATED,
                                        validated_xml=_NAMED)), \
         patch.object(filings, "_update") as update:
        with pytest.raises(filings.SignatoryMismatch) as exc:
            filings.sign(client, "f1", "EUSER-ME", "pw")

    # Refused BEFORE CR is contacted, and without marking the filing failed —
    # nothing is wrong with the filing, it is simply not this user's to sign.
    client.post_form.assert_not_called()
    update.assert_not_called()
    assert "EUSER-THEM" in str(exc.value) and "EUSER-ME" in str(exc.value)


def test_sign_allows_the_person_the_return_actually_names():
    client = MagicMock()
    client.post_form.return_value = SIGN_OK
    with patch.object(filings, "get_filing",
                      return_value=_row(stage=filings.STAGE_VALIDATED,
                                        validated_xml=_NAMED)), \
         patch.object(filings, "_update"):
        filings.sign(client, "f1", "euser-them", "pw")   # case-insensitive
    client.post_form.assert_called_once()


def test_sign_is_unaffected_when_a_body_corporate_signs():
    """The dominant real path: GSHK Ltd is the named signatory, the return
    carries no selectPersonId, and the staff member's own account signs it."""
    client = MagicMock()
    client.post_form.return_value = SIGN_OK
    with patch.object(filings, "get_filing",
                      return_value=_row(stage=filings.STAGE_VALIDATED,
                                        validated_xml=VALIDATED_XML)), \
         patch.object(filings, "_update"):
        filings.sign(client, "f1", "ANY-STAFF-ACCOUNT", "pw")
    client.post_form.assert_called_once()


# ── Form status vocabulary (migration 018) ──────────────────────────────────
# The point of splitting `failed` is that a caller can tell a FREE, retryable
# validation failure from a rejected CHARGEABLE submission without opening
# cr_error. These lock that in.


def test_sign_failure_records_signing_failed_not_a_generic_failure(monkeypatch):
    from services.tpsi import errors

    saved = {}
    filing = {
        "id": "f1", "form_code": "Nar1", "stage": filings.STAGE_VALIDATED,
        # EFormSignatures must be present: the overall signature is spliced in
        # just before its closing tag, so sign() fails earlier without it.
        "validated_xml": (
            "<cr:submission><cr:EForm>x</cr:EForm>"
            "<cr:EFormSignatures>"
            f"<ds:X509Certificate>{CR_CERT_B64}</ds:X509Certificate>"
            "</cr:EFormSignatures></cr:submission>"
        ),
    }
    monkeypatch.setattr(filings, "get_filing", lambda _id: filing)
    monkeypatch.setattr(filings, "_update", lambda _id, payload: saved.update(payload))
    monkeypatch.setattr(
        "services.tpsi.crypto.build_pin_sign", lambda *a, **k: "<cr:PinSign/>"
    )
    monkeypatch.setattr(
        "services.tpsi.config.get_config",
        lambda: type("C", (), {"cr_public_key_pem": "pem"})(),
    )

    client = MagicMock()
    client.post_form.side_effect = errors.TpsiValidationError([("ERR_SIG", "bad pin")])

    with pytest.raises(errors.TpsiValidationError):
        filings.sign(client, "f1", "CHANTM01", "pw")

    assert saved["stage"] == filings.STAGE_SIGNING_FAILED
    assert saved["stage"] != filings.STAGE_VALIDATION_FAILED


def test_form_statuses_are_the_nine_the_ui_reports():
    # edrive is a valid stored value but is not offered in the UI, so it must
    # not appear in the reported vocabulary.
    assert len(filings.FORM_STATUSES) == 9
    assert filings.STAGE_EDRIVE not in filings.FORM_STATUSES
    # Every reported status needs a label, or the UI renders a raw enum.
    for status in filings.FORM_STATUSES:
        assert filings.FORM_STATUS_LABELS.get(status)


def test_a_submitted_filing_cannot_be_walked_back_by_revalidating(monkeypatch):
    # The double-charge guard is a partial unique index on stage='submitted';
    # re-validating would drop the row out of its coverage.
    for terminal in filings.TERMINAL_STAGES:
        monkeypatch.setattr(
            filings, "get_filing", lambda _id, s=terminal: {"id": "f1", "stage": s}
        )
        with pytest.raises(ValueError):
            filings.validate(MagicMock(), "f1")


# ---------------------------------------------------------------------------
# supersede — retiring an attempt CR has not filed
# ---------------------------------------------------------------------------


def _supersede_chain():
    """The PostgREST chain supersede() builds, with the filters recorded."""
    sb = MagicMock()
    chain = sb.table.return_value.update.return_value.eq.return_value.not_.in_
    return sb, chain


def test_supersede_sets_the_stage_nothing_else_ever_wrote():
    sb, chain = _supersede_chain()
    chain.return_value.execute.return_value.data = [{"id": "f1"}]
    with patch("services.tpsi.filings.get_supabase", return_value=sb):
        assert filings.supersede("f1") is True
    sb.table.return_value.update.assert_called_once_with(
        {"stage": filings.STAGE_SUPERSEDED})
    sb.table.return_value.update.return_value.eq.assert_called_once_with("id", "f1")


def test_supersede_refuses_a_filing_cr_already_holds_IN_THE_UPDATE():
    """Not read-then-write. A submit landing between a read and a write would
    otherwise retire a filing CR had just registered, and the case would show
    no filing at all while the return sat in the register."""
    sb, chain = _supersede_chain()
    chain.return_value.execute.return_value.data = []
    with patch("services.tpsi.filings.get_supabase", return_value=sb):
        assert filings.supersede("f1") is False
    column, stages = chain.call_args.args
    assert column == "stage"
    # Every terminal stage, so the guard cannot be widened in one place only.
    assert set(stages) == set(filings.TERMINAL_STAGES)


def test_a_superseded_filing_is_already_excluded_from_the_current_one():
    """The stage was defined and filtered on from the start; only the WRITE was
    missing. This pins the other half so neither can be removed alone."""
    assert filings.STAGE_SUPERSEDED in filings.TERMINAL_STAGES
