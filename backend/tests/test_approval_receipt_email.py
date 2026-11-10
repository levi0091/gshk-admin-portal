"""email_service.approval_receipt_email — the receipt a director gets after
pressing Confirm & File (Levi 2026-10-17; NAR1, ND2A and ND2B alike).

The same family as the verification letter (tables, inline styles, the GSHK
footer); what it says is when the confirmation was recorded, by whom, and what
was confirmed, with the confirmed documents attached.
"""
import re

import pytest

from services import email_service as es

CASE = {"id": "k1", "case_no": "NAR-2026-0042", "ar_period_year": 2026, "form_code": "Nar1"}
ENTITY = {"company_name": "Kanenas Holding Limited", "br_number": "69123456"}
# 07:31 UTC is 15:31 in Hong Kong.
AT = "2026-10-17T07:31:05+00:00"


def _receipt(case=CASE, **over):
    kwargs = dict(form_code="Nar1", confirmed_by="Jane CHAN",
                  confirmed_email="jane@client.example", confirmed_at=AT,
                  revision=1, attachments=["NAR1-NAR-2026-0042.pdf"])
    kwargs.update(over)
    return es.approval_receipt_email(case, ENTITY, **kwargs)


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


@pytest.mark.parametrize("form_code, expected", [
    ("Nar1", "Approval Receipt - Form NAR1 | Kanenas Holding Limited"),
    ("Nd2a", "Approval Receipt - Form ND2A | Kanenas Holding Limited"),
    ("Nd2b", "Approval Receipt - Form ND2B | Kanenas Holding Limited"),
])
def test_the_subject_names_the_form_and_the_company(form_code, expected):
    subject, _ = _receipt(form_code=form_code)
    assert subject == expected


def test_a_revised_draft_says_which_revision_was_confirmed():
    subject, html = _receipt(revision=2)
    assert subject == "[Rev. 2] Approval Receipt - Form NAR1 | Kanenas Holding Limited"
    assert "Form NAR1, Annual Return 2026 (Rev. 2)" in _text(html)


def test_it_states_the_moment_in_hong_kong_time():
    _, html = _receipt()
    text = _text(html)
    assert "17 October 2026" in text
    assert "15:31 Hong Kong time" in text
    # Once, in the stamp — not repeated in the opening sentence.
    assert text.count("17 October 2026") == 1


def test_it_names_who_confirmed_and_from_which_address():
    text = _text(_receipt()[1])
    assert "Jane CHAN" in text and "jane@client.example" in text


def test_a_confirmer_with_no_name_is_named_by_address():
    text = _text(_receipt(confirmed_by=None)[1])
    assert "jane@client.example" in text
    assert "None" not in text


def test_it_names_the_form_the_case_and_every_attachment():
    _, html = _receipt(form_code="Nd2a", case={**CASE, "case_no": "ND2A-2026-0001",
                                               "form_code": "Nd2a"},
                       attachments=["ND2A-ND2A-2026-0001.pdf",
                                    "Written-Resolution-ND2A-2026-0001.pdf"])
    text = _text(html)
    assert "Form ND2A" in text and "ND2A-2026-0001" in text
    assert "ND2A-ND2A-2026-0001.pdf" in text
    assert "Written-Resolution-ND2A-2026-0001.pdf" in text
    assert "Copies of the documents you confirmed are attached" in text


def test_one_attachment_is_a_copy_and_none_is_said_plainly():
    assert "A copy of the form you confirmed is attached" in _text(_receipt()[1])
    text = _text(_receipt(attachments=[])[1])
    assert "We could not attach a copy of the form to this email" in text
    assert "is attached" not in text


def test_an_annual_return_names_its_year():
    assert "Annual Return 2026" in _text(_receipt()[1])


def test_it_tells_the_reader_what_to_do_if_it_was_not_them():
    text = _text(_receipt()[1])
    assert ("If you do not recognise this approval or identify an error Please contact "
            "renewal@getstarted.hk immediately. If submission has already taken place, "
            "changes may require a separate correction or further filing.") in text


# --- GSHK's `Approval receipt` template, verbatim (Levi 2026-11-06) ----------

def test_the_body_follows_the_template_in_order():
    # `_text` puts a space where a tag was, so "<strong>X</strong>." reads "X .".
    text = re.sub(r"\s+([.,;])", r"\1", _text(_receipt()[1]))
    in_order = [
        "Dear Client,",
        "Approval and Submission Authorisation Receipt",
        "This email acknowledges and records the approval received through our system "
        "for the document identified below, together with authorisation for Get Started "
        "HK Limited to submit it to the Companies Registry on behalf of "
        "Kanenas Holding Limited.",
        "Confirmation recorded",
        "Instruction recorded",
        "At the time of approval, the following declaration was accepted:",
        "Approved document",
        "What happens next?",
        "If you do not recognise this approval or identify an error",
        "Kind regards, Get Started HK Limited",
    ]
    at = -1
    for piece in in_order:
        found = text.find(piece, at + 1)
        assert found > at, f"{piece!r} missing or out of order"
        at = found


def test_the_declaration_is_the_templates_own_words():
    text = _text(_receipt()[1])
    assert ("“I confirm that I am authorised to approve this document on behalf of "
            "the company. I have reviewed and confirmed that the information in the "
            "document is correct and complete to the best of my knowledge. I approve "
            "this version and authorise Get Started HK Limited to submit it to the "
            "Companies Registry on behalf of the company.”") in text


def test_what_happens_next_is_the_templates_own_sentence():
    assert ("We will proceed with submission based on this approval. This receipt "
            "records your approval and authorisation only; There is nothing more you "
            "need to do.") in _text(_receipt()[1])


def test_the_company_is_bold_in_the_acknowledgement():
    assert "<strong>Kanenas Holding Limited</strong>" in _receipt()[1]


def test_the_stamp_date_has_a_two_digit_day():
    text = _text(_receipt(confirmed_at="2026-11-01T15:24:00+00:00")[1])
    assert "01 November 2026" in text and "23:24 Hong Kong time" in text


def test_the_old_wording_is_gone():
    text = _text(_receipt()[1])
    assert "Thank you. We have recorded your confirmation" not in text
    assert "If you did not confirm this form" not in text
    assert "straight away" not in text


def test_it_carries_the_gshk_footer_and_the_company_signs_it():
    text = _text(_receipt()[1])
    assert es.GSHK_ADDRESS in text
    assert "Get Started HK Limited" in text


def test_every_value_is_escaped():
    subject, html = es.approval_receipt_email(
        CASE, {"company_name": "<b>A & B</b> Ltd", "br_number": "1"},
        form_code="Nar1", confirmed_by="<script>x</script>",
        confirmed_email="a@b.example", confirmed_at=AT, revision=1,
        attachments=["<i>.pdf"])
    assert "<b>A" not in html and "<script>" not in html and "<i>.pdf" not in html
    assert "&lt;b&gt;A &amp; B&lt;/b&gt; Ltd" in html


def test_it_is_built_for_outlook():
    _, html = _receipt()
    assert "<style" not in html.lower()
    assert "display:flex" not in html.replace(" ", "") and "grid" not in html


def test_its_only_link_is_the_renewals_mailbox():
    _, html = _receipt()
    links = re.findall(r'href="([^"]+)"', html)
    assert links and set(links) == {"mailto:renewal@getstarted.hk"}


def test_an_unreadable_moment_does_not_stop_the_receipt():
    subject, html = _receipt(confirmed_at="not a time")
    assert subject and "Jane CHAN" in _text(html)


def test_it_fits_a_phone_without_losing_outlooks_width():
    _, html = _receipt()
    assert 'width="600"' in html and "width:100%;max-width:600px" in html


# --- the Documents row (nd2-change-requests PRD section 6, test 10) ----------

DOCS = ["Form ND2A — Change of company secretary and director",
        "Written resolution of the directors"]


def test_the_ledger_has_a_documents_row_listing_every_title():
    _, html = _receipt(documents=DOCS, attachments=["ND2A-x.pdf"])
    text = _text(html)
    assert "Documents" in text
    for title in DOCS:
        assert title in text
    # Inside the stamp's ledger, in the same label/value cells as the other rows.
    ledger = html[html.index("Confirmed by"):html.index("Our reference")]
    assert DOCS[0] in ledger and DOCS[1] in ledger


def test_titles_are_listed_whether_or_not_anything_is_attached():
    text = _text(_receipt(documents=DOCS, attachments=[])[1])
    assert DOCS[1] in text
    assert "We could not attach a copy of the form to this email" in text


def test_the_attached_box_still_lists_only_what_is_attached():
    html = _receipt(documents=DOCS, attachments=["ND2A-x.pdf"])[1]
    box = html[html.index(">Attached<"):]
    assert "ND2A-x.pdf" in box
    assert DOCS[1] not in box


def test_without_documents_there_is_no_documents_row():
    assert "Documents" not in _text(_receipt()[1])


def test_document_titles_are_escaped_and_the_markup_stays_table_based():
    _, html = _receipt(documents=["<script>x</script> & co"])
    assert "<script>" not in html and "&lt;script&gt;x&lt;/script&gt; &amp; co" in html
    assert "<style" not in html.lower() and "<ul" not in html.lower()
