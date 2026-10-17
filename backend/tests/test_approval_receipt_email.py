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
    ("Nar1", "NAR1 Confirmation Received - Kanenas Holding Limited"),
    ("Nd2a", "ND2A Confirmation Received - Kanenas Holding Limited"),
    ("Nd2b", "ND2B Confirmation Received - Kanenas Holding Limited"),
])
def test_the_subject_names_the_form_and_the_company(form_code, expected):
    subject, _ = _receipt(form_code=form_code)
    assert subject == expected


def test_a_revised_draft_says_which_revision_was_confirmed():
    subject, html = _receipt(revision=2)
    assert subject == "[Rev. 2] NAR1 Confirmation Received - Kanenas Holding Limited"
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
    assert "If you did not confirm this form" in text
    assert "renewal@getstarted.hk" in text
    assert "nothing more you need to do" in text.lower() or \
        "do not need to do anything" in text.lower()


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
