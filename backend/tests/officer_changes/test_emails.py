"""The officer-change client email (spec B-14): what it says, and what it never says."""
import html as htmllib
import re
from datetime import date

from services import email_service
from services.officer_changes import emails

CASE = {"id": "K1", "case_no": "ND2A-2026-0001", "form_code": "Nd2a"}
ENTITY = {"company_name": "Kanenas Holding Limited <b>", "br_number": "69123456"}
HOME = "Flat A, 10/F, Harbour View"


def _entries():
    return [
        {"kind": "cessation", "capacity": "director", "cessation_reason": "R",
         "effective_date": "2026-09-28", "party": {"name": "CHAN Tai Man"}},
        {"kind": "appointment", "capacity": "company_secretary",
         "effective_date": "2026-09-29", "party": {"name": "WONG Ka Yan",
                                                    "hkid": "A1234563"}},
    ]


def _nd2b_entries():
    return [{"kind": "change", "capacity": "director", "party": {"name": "LEE Siu Ming"},
             "items": [
                 {"key": "name_en", "label": "Name in English", "old_text": "LEE Siu Ming",
                  "new_text": "LI Siu Ming", "effective_date": "2026-09-20", "omitted": False},
                 {"key": "residential_address", "label": "Residential address",
                  "old_text": HOME, "new_text": "Flat B, 2/F", "effective_date": "2026-09-21",
                  "omitted": False},
                 {"key": "hkid", "label": "Hong Kong identity card number",
                  "old_text": "A1234563", "new_text": "B7654321",
                  "effective_date": "2026-09-22", "omitted": False},
                 {"key": "email", "label": "Email address", "old_text": "a@x.com",
                  "new_text": "b@x.com", "effective_date": "2026-09-23", "omitted": True},
             ]}]


def test_summary_names_each_change_with_its_date():
    lines = emails.changes_summary(_entries())
    assert lines == [
        "CHAN Tai Man ceases to act as Director on 28 September 2026.",
        "WONG Ka Yan is appointed Company Secretary on 29 September 2026.",
    ]


def test_nd2b_summary_shows_names_but_never_an_address_or_id_number():
    lines = emails.changes_summary(_nd2b_entries())
    text = " ".join(lines)
    assert "Name in English changed from LEE Siu Ming to LI Siu Ming" in text
    assert "Residential address changed" in text
    assert "Hong Kong identity card number changed" in text
    assert HOME not in text and "Flat B" not in text
    assert "A1234563" not in text and "B7654321" not in text
    assert "b@x.com" not in text  # the omitted line is not filed, so not mentioned
    assert len(lines) == 3


def test_letter_has_the_nar1_shape_and_a_confirm_button():
    subject, body = emails.officer_change_email(
        CASE, ENTITY, _entries(), approval_url="https://x.test/a?t=1&u=2",
        respond_by=date(2026, 10, 10))
    assert subject == ("[Action Required] ND2A Review & Confirmation - "
                       "Kanenas Holding Limited <b>")
    assert "Dear Client," in body
    assert "Get Started HK Limited" in body
    assert email_service.RENEWAL_MAILBOX in body
    assert "Confirm ND2A" in body
    assert "Replies to this email are not monitored" in body
    assert "Kanenas Holding Limited &lt;b&gt;" in body and "<b>" not in body.split("Kanenas")[1][:5]
    assert "https://x.test/a?t=1&amp;u=2" in body


def test_letter_never_claims_silence_is_consent():
    _, body = emails.officer_change_email(CASE, ENTITY, _entries(),
                                          approval_url="https://x.test/a",
                                          respond_by=date(2026, 10, 10))
    assert "deemed confirmed" not in body
    assert "we will proceed with filing" not in body


def test_without_a_link_it_asks_for_a_reply_and_drops_the_unmonitored_line():
    _, body = emails.officer_change_email(CASE, ENTITY, _entries(), approval_url=None,
                                          respond_by=None)
    assert "reply to this email" in body
    assert "not monitored" not in body
    assert "Confirm ND2A" not in body
    # No button, so no declaration made by pressing it and no receipt to promise.
    assert "make the following declaration" not in body
    assert "Submission Authorisation Receipt" not in body
    # What the template still says either way.
    assert "We can proceed with submission only after receiving your approval." in body
    assert "renewal@getstarted.hk" in body


def test_nd2b_letter_is_titled_for_nd2b_and_carries_no_identity_number():
    subject, body = emails.officer_change_email(
        {**CASE, "form_code": "Nd2b", "case_no": "ND2B-2026-0001"}, ENTITY,
        _nd2b_entries(), approval_url="https://x.test/a", respond_by="2026-10-10")
    assert subject.startswith("[Action Required] ND2B Review & Confirmation")
    assert "Confirm ND2B" in body and "Form ND2B" in body
    assert "B7654321" not in body and HOME not in body


def test_markup_is_table_based_with_no_style_block():
    _, body = emails.officer_change_email(CASE, ENTITY, _entries(),
                                          approval_url="https://x.test/a",
                                          respond_by=date(2026, 10, 10))
    assert "<style" not in body and "display:flex" not in body and "grid" not in body
    assert body.startswith("<table")


# -- revisions (Levi 2026-10-02, migration 051) ---------------------------------

def _letter(case=CASE, entries=None, **over):
    return emails.officer_change_email(case, ENTITY, entries or _entries(),
                                       approval_url="https://x.test/a",
                                       respond_by=date(2026, 10, 10), **over)


def test_the_first_letter_is_unchanged():
    assert _letter(revision=1) == _letter()
    assert "Revised draft" not in _letter()[1]


def test_a_resend_says_which_revision_it_is_in_the_subject():
    subject, _ = _letter(revision=2)
    assert subject.startswith("[Action Required] [Rev. 2] ND2A Review & Confirmation")
    nd2b, _ = _letter(case={**CASE, "form_code": "Nd2b"}, entries=_nd2b_entries(),
                      revision=3)
    assert nd2b.startswith("[Action Required] [Rev. 3] ND2B Review & Confirmation")


def test_a_revised_letter_opens_with_nar1s_own_notice():
    """The same words on all three forms — the notice is email_service's."""
    _, body = _letter(revision=2)
    assert email_service.revision_notice(2) in body
    assert body.index("Revised draft") < body.index("Dear Client")
    assert "&middot; Rev. 2</div>" in body
    assert "Ref ND2A-2026-0001 · Rev. 2" in body


# -- Jacqueline's feedback (A1, A2, A3, A5, A8, B2, BQ1) ------------------------------

def _body(entries=None, case=CASE, **kw):
    kw.setdefault("approval_url", "https://x.test/a")
    kw.setdefault("respond_by", date(2026, 10, 10))
    return emails.officer_change_email(case, ENTITY, entries or _entries(), **kw)[1]


def test_undated_change_reads_to_be_confirmed():
    entries = _entries()
    entries[1]["effective_date"] = None
    assert emails.changes_summary(entries)[1] == (
        "WONG Ka Yan is appointed Company Secretary, with effect from a date to be "
        "confirmed when we file this notice.")


def test_the_old_draft_paragraphs_are_gone():
    """GSHK's template has no place for the PI paragraph, the change list, the
    respond-by date or the "15 days" sentence (Levi 2026-11-06)."""
    for body in (_body(), _body(_nd2b_entries(), case={**CASE, "form_code": "Nd2b"})):
        text = _text(body)
        assert "protected-information" not in text
        assert "please keep this email private" not in text
        assert "ceases to act as" not in text and "is appointed" not in text
        assert "10 October 2026" not in text
        assert "15 days" not in text and "Please let us know" not in text


def test_attachments_are_listed():
    body = _body(attachments=["ND2A-ND2A-2026-0001.pdf", "Written <Resolution>.pdf"])
    assert "Attached:" in body and "ND2A-ND2A-2026-0001.pdf" in body
    assert "Written &lt;Resolution&gt;.pdf" in body


def test_esign_director_is_told_no_signature_needed():
    body = _body(consent={"mode": "esign", "url": None, "name": "LEE Ka Ho"})
    assert "No signature is needed from you" in body
    assert "e-Registry account we set up with you" in body
    assert "Sign consent to act" not in body


def test_no_letter_carries_a_consent_link():
    """Levi 2026-10-05: the consent is CR's PIN signature from the director's
    own e-Registry account; there is no in-portal consent to link to."""
    body = _body(consent={"mode": "econsent", "url": "https://x.test/c?t=9",
                            "name": "LEE Ka Ho"})
    assert "Sign consent to act" not in body and "https://x.test/c?t=9" not in body


def test_no_consent_paragraph_for_other_recipients():
    body = _body(consent=None)
    assert "Sign consent to act" not in body and "No signature is needed from you" not in body


def test_no_letter_says_we_will_proceed_without_approval():
    assert "we will proceed with filing" not in _body()
    assert "we will proceed with filing" not in _body(
        _nd2b_entries(), case={**CASE, "form_code": "Nd2b"})


# -- GSHK's ND2A / ND2B templates, verbatim (Levi 2026-11-06) ------------------

def _text(html: str) -> str:
    """Visible text, with a tag boundary read as a space and no space before
    punctuation, so a sentence split by <strong> still reads as one."""
    flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
    return htmllib.unescape(re.sub(r"\s+([.,;])", r"\1", flat))


def _in_order(text: str, pieces: list[str]):
    at = -1
    for piece in pieces:
        found = text.find(piece, at + 1)
        assert found > at, f"{piece!r} missing or out of order"
        at = found


ND2A_DECLARATION = (
    "\u201cI confirm that I am authorised to approve this document on behalf of the "
    "company. I have reviewed the document and confirm that the information in it is "
    "correct and complete to the best of my knowledge. I approve this version and "
    "authorise Get Started HK Limited to submit it to the Companies Registry on behalf "
    "of the company.\u201d")
ND2B_DECLARATION = (
    "\u201cI confirm that I am authorised to approve this document on behalf of the "
    "company. I have reviewed and confirmed that the information in document is correct "
    "and complete to the best of my knowledge. I approve this version and authorise Get "
    "Started HK Limited to submit it to the Companies Registry on behalf of the "
    "company.\u201d")
RECEIPT_SENTENCE = ("We can proceed with submission only after receiving your approval. "
                    "Our system will record your approval and send you a Submission "
                    "Authorisation Receipt.")


def test_the_nd2a_letter_is_the_templates_text_in_the_templates_order():
    text = _text(_body())
    _in_order(text, [
        "Dear Client,",
        "Your Form ND2A is now available.",
        "Please review the attached Form carefully, with particular attention:",
        "\u2022 Director\u2019s name",
        "\u2022 Director's Details",
        "Approval and authorisation",
        "If all information is correct, please click the \u201cConfirm ND2A\u201d button. "
        "By clicking this, you make the following declaration:",
        ND2A_DECLARATION,
        RECEIPT_SENTENCE,
        "Errors or changes",
        "When you identify any error, do not approve the document. Contact "
        "renewal@getstarted.hk immediately. Any changes you request after approval will "
        "be subject to a HK$1,000 service fee. If the form has already been submitted, "
        "changes may also require a separate correction or further filing.",
        "This is an automatically generated email. Replies to this email are not "
        "monitored.",
        "Kind regards, Get Started HK Limited",
        "Confirm ND2A",
    ])


def test_the_nd2b_letter_is_the_templates_text_in_the_templates_order():
    text = _text(_body(_nd2b_entries(), case={**CASE, "form_code": "Nd2b"}))
    _in_order(text, [
        "Dear Client,",
        "Your Form ND2B is now available.",
        "Please review the attached Form carefully, with particular attention:",
        "\u2022 Page 2:",
        "Correspondence Address (if applicable)",
        "Partial Number of Hong Kong Identity Card (if applicable)",
        "Partial Number of Passport (if applicable)",
        "\u2022 PI-ND2B: Director\u2019s Residential Address and/or Passport Details",
        "Approval and authorisation",
        "If the information is correct, please click the \u201cConfirm ND2B\u201d button. "
        "By clicking this, you make the following declaration:",
        ND2B_DECLARATION,
        RECEIPT_SENTENCE,
        "Errors or changes",
        "If you identify any error, do not approve the document. Contact "
        "renewal@getstarted.hk immediately. Any changes you request after approval will "
        "be subject to a HK$1,000 service fee. When the form has already been submitted, "
        "changes may also require a separate correction or further filing.",
        "This is an automatically generated email. Replies to this email are not "
        "monitored.",
        "Kind regards, Get Started HK Limited",
        "Confirm ND2B",
    ])


def test_the_two_letters_differ_where_the_templates_do():
    a = _text(_body())
    b = _text(_body(_nd2b_entries(), case={**CASE, "form_code": "Nd2b"}))
    assert ND2A_DECLARATION in a and ND2B_DECLARATION not in a
    assert ND2B_DECLARATION in b and ND2A_DECLARATION not in b
    assert "Director's Details" in a and "Correspondence Address" not in a
    assert "Correspondence Address" in b and "Director's Details" not in b
    assert "When you identify any error" in a and "If you identify any error" in b


def test_the_subject_is_still_the_templates():
    assert emails.officer_change_email(
        CASE, ENTITY, _entries(), approval_url=None, respond_by=None)[0] == (
        "[Action Required] ND2A Review & Confirmation - Kanenas Holding Limited <b>")


def test_renewals_is_a_mailto_link_in_the_errors_paragraph():
    assert 'href="mailto:renewal@getstarted.hk"' in _body()


def test_a_revised_nd2b_keeps_the_template_text_under_the_notice():
    _, body = _letter(case={**CASE, "form_code": "Nd2b"}, entries=_nd2b_entries(),
                      revision=2)
    assert email_service.revision_notice(2) in body
    assert ND2B_DECLARATION in _text(body)
    assert body.index("Revised draft") < body.index("Dear Client")


def test_an_alternate_director_is_labelled_as_one():
    entries = [{"kind": "appointment", "capacity": "alternate_director",
                "effective_date": "2026-09-29", "party": {"name": "LEE Ka Ho"}}]
    assert emails.changes_summary(entries) == [
        "LEE Ka Ho is appointed Alternate Director on 29 September 2026."]
