"""services/approval_receipt — the receipt mailed after a client's own Confirm &
File (Levi 2026-10-17): which documents it carries, who it goes to, what the
trail records, and that nothing it does can fail the confirmation.

`conftest._no_receipt_mail_in_tests` stubs the ROUTER's binding of `send`;
these tests call the service itself.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import approval_receipt as receipt
from services import email_service

NAR1 = {"id": "c1", "case_no": "NAR-2026-0042", "entity_id": "e1", "form_code": "Nar1",
        "ar_period_year": 2026, "verification_xml": "<nar1/>", "verification_revision": 2}
ND2A = {"id": "k1", "case_no": "ND2A-2026-0001", "entity_id": "e1", "form_code": "Nd2a",
        "verification_xml": "<nd2a/>", "verification_revision": 1}
ND2B = {**ND2A, "id": "k2", "case_no": "ND2B-2026-0001", "form_code": "Nd2b",
        "verification_xml": "<nd2b/>"}
ENTITY = {"id": "e1", "company_name": "Kanenas Holding Limited", "company_name_zh": None,
          "br_number": "69123456", "company_type": "private",
          "incorporation_date": "2020-03-01"}
APPROVAL = {"id": "a1", "nar1_case_id": "c1", "recipient_email": "jane@client.example",
            "recipient_name": "Jane CHAN", "responded_at": "2026-10-17T07:31:05+00:00",
            "revision": 2, "outcome": "approved"}
SENT = {"id": "m1", "to": ["jane@client.example"], "intended_to": ["jane@client.example"],
        "cc": ["renewal@getstarted.hk"], "intended_cc": ["renewal@getstarted.hk"],
        "reply_to": ["renewal@getstarted.hk"], "intended_reply_to": ["renewal@getstarted.hk"],
        "redirected": False}


def _renderers(nar1=b"%PDF-nar1", form=b"%PDF-form", resolution=b"%PDF-res"):
    return [
        patch("services.approval_receipt.nar1_form_fill.render", return_value=nar1),
        patch("services.approval_receipt.render_officer_form", return_value=form),
        patch("services.approval_receipt.resolution.render", return_value=resolution),
        patch("services.approval_receipt.nar1_cases.current_filing", return_value=None),
        patch("services.approval_receipt.officer_cases.composite", new_callable=AsyncMock,
              return_value={"entries": [{"id": "n1"}], "officers": [{"name": "A"}]}),
    ]


class _Stack:
    def __init__(self, patches):
        self._patches = patches

    def __enter__(self):
        return [p.__enter__() for p in self._patches]

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.__exit__(*exc)
        return False


# --------------------------------------------------------------------------- #
#  What it attaches
# --------------------------------------------------------------------------- #

async def test_a_nar1_receipt_carries_the_copy_the_client_confirmed():
    with _Stack(_renderers()) as (render, *_):
        files, failures = await receipt.documents(NAR1, ENTITY, APPROVAL)
    assert files == [("NAR1-NAR-2026-0042-Rev2.pdf", b"%PDF-nar1")]
    assert failures == []
    # The FROZEN copy, rendered as the send renders it.
    assert render.call_args.args[0] == "<nar1/>"
    assert render.call_args.kwargs["incorporated_on"] == "2020-03-01"


async def test_a_first_send_is_named_without_a_revision():
    with _Stack(_renderers()):
        files, _ = await receipt.documents(NAR1, ENTITY, {**APPROVAL, "revision": 1})
    assert files[0][0] == "NAR1-NAR-2026-0042.pdf"


async def test_an_nd2a_receipt_carries_the_form_and_the_written_resolution():
    with _Stack(_renderers()) as (_n, form, res, _f, composite):
        files, failures = await receipt.documents(ND2A, ENTITY, {**APPROVAL, "revision": 1})
    assert [name for name, _ in files] == ["ND2A-ND2A-2026-0001.pdf",
                                           "Written-Resolution-ND2A-2026-0001.pdf"]
    assert failures == []
    assert form.call_args.args[:2] == ("Nd2a", "<nd2a/>")
    assert form.call_args.kwargs["public_only"] is False
    assert res.call_args.args[2] == [{"id": "n1"}]


async def test_an_nd2b_receipt_carries_the_form_only():
    with _Stack(_renderers()) as (_n, _form, res, *_):
        files, _ = await receipt.documents(ND2B, ENTITY, {**APPROVAL, "revision": 1})
    assert [name for name, _ in files] == ["ND2B-ND2B-2026-0001.pdf"]
    res.assert_not_called()


async def test_a_case_sent_before_the_copy_was_kept_attaches_nothing_and_says_why():
    with _Stack(_renderers()) as (render, *_):
        files, failures = await receipt.documents({**NAR1, "verification_xml": None},
                                                  ENTITY, APPROVAL)
    assert files == []
    assert len(failures) == 1 and "NAR1" in failures[0]["file"]
    render.assert_not_called()


async def test_a_document_that_will_not_render_is_left_off_not_fatal():
    patches = _renderers()
    patches[2] = patch("services.approval_receipt.resolution.render",
                       side_effect=RuntimeError("font missing"))
    with _Stack(patches):
        files, failures = await receipt.documents(ND2A, ENTITY, {**APPROVAL, "revision": 1})
    assert [name for name, _ in files] == ["ND2A-ND2A-2026-0001.pdf"]
    assert failures[0]["file"] == "Written-Resolution-ND2A-2026-0001.pdf"
    assert "font missing" in failures[0]["reason"]


# --------------------------------------------------------------------------- #
#  Naming what is being confirmed (nd2-change-requests PRD section 6, tests 8 and 10)
# --------------------------------------------------------------------------- #

NAR1_TITLE = "Form NAR1 — Annual Return 2026"
ND2A_TITLE = "Form ND2A — Change of company secretary and director"
ND2B_TITLE = "Form ND2B — Change in particulars of company secretary and director"
RESOLUTION_TITLE = "Written resolution of the directors"


def test_a_nar1_names_its_return_year_and_its_revision_from_rev_2():
    assert receipt.confirmed_documents(NAR1, APPROVAL) == [
        {"title": f"{NAR1_TITLE} (Rev. 2)", "file_name": "NAR1-NAR-2026-0042-Rev2.pdf"}]
    # The first send is unmarked, as the verification letter's subject is.
    assert receipt.confirmed_documents(NAR1, {**APPROVAL, "revision": 1}) == [
        {"title": NAR1_TITLE, "file_name": "NAR1-NAR-2026-0042.pdf"}]


def test_an_nd2a_names_the_form_and_the_written_resolution():
    docs = receipt.confirmed_documents(ND2A, {**APPROVAL, "revision": 1})
    assert docs == [
        {"title": ND2A_TITLE, "file_name": "ND2A-ND2A-2026-0001.pdf"},
        {"title": RESOLUTION_TITLE, "file_name": "Written-Resolution-ND2A-2026-0001.pdf"}]
    # The resolution travels with the form; it carries no revision of its own.
    revised = receipt.confirmed_documents(ND2A, {**APPROVAL, "revision": 3})
    assert revised[0]["title"] == f"{ND2A_TITLE} (Rev. 3)"
    assert revised[1]["title"] == RESOLUTION_TITLE


def test_an_nd2b_names_the_form_only():
    assert receipt.confirmed_documents(ND2B, {**APPROVAL, "revision": 2}) == [
        {"title": f"{ND2B_TITLE} (Rev. 2)", "file_name": "ND2B-ND2B-2026-0001-Rev2.pdf"}]


def test_the_revision_is_the_links_own_else_the_cases():
    # Same rule as the attachment: a director who confirmed Rev. 1 is not told
    # they confirmed Rev. 2 because the case has since moved on.
    assert receipt.confirmed_documents(NAR1, {"revision": 1})[0]["title"] == NAR1_TITLE
    assert receipt.confirmed_documents(NAR1, {})[0]["title"] == f"{NAR1_TITLE} (Rev. 2)"


def test_a_nar1_with_no_return_year_is_named_without_one():
    docs = receipt.confirmed_documents({**NAR1, "ar_period_year": None}, APPROVAL)
    assert docs[0]["title"] == "Form NAR1 — Annual Return (Rev. 2)"


@pytest.mark.parametrize("case", [NAR1, ND2A, ND2B])
@pytest.mark.parametrize("revision", [1, 2, 5])
def test_the_file_names_are_the_ones_the_send_gives_its_attachments(case, revision):
    """The page promises these names, so they must match what the verification
    email actually attached. The send builds them INLINE (the NAR1 send in
    routers/cases.py; ND2A and ND2B in routers/officer_changes.py; the
    resolution through `resolution.file_name`), so this restates those
    formulas: if either side changes, this fails rather than the page quietly
    naming a file that does not exist."""
    rev = f"-Rev{revision}" if revision >= 2 else ""
    if case["form_code"] == "Nar1":
        expected = f"NAR1-{case['case_no']}{rev}.pdf"
    else:
        expected = f"{case['form_code'].upper()}-{case['case_no']}{rev}.pdf"
    docs = receipt.confirmed_documents(case, {"revision": revision})
    assert docs[0]["file_name"] == expected
    if case["form_code"] == "Nd2a":
        assert docs[1]["file_name"] == f"Written-Resolution-{case['case_no']}.pdf"


def test_a_case_with_no_number_is_named_by_its_id_as_the_send_does():
    case = {**NAR1, "case_no": None}
    assert receipt.confirmed_documents(case, {"revision": 1})[0]["file_name"] == "NAR1-c1.pdf"


# --------------------------------------------------------------------------- #
#  Sending it
# --------------------------------------------------------------------------- #

def _world(case=NAR1, sent=SENT, send_effect=None, files=(("NAR1-x.pdf", b"%PDF"),),
           failures=()):
    return [
        patch("services.approval_receipt.nar1_cases.get_case", return_value=case),
        patch("services.approval_receipt.nar1_cases.entity_for", return_value=ENTITY),
        patch("services.approval_receipt.documents", new_callable=AsyncMock,
              return_value=(list(files), list(failures))),
        patch("services.approval_receipt.email_service.send",
              return_value=sent, side_effect=send_effect),
        patch("services.approval_receipt.log_event", new_callable=AsyncMock),
    ]


async def test_it_goes_to_the_director_who_pressed_copied_to_renewals():
    with _Stack(_world()) as (_c, _e, _d, send, _log):
        await receipt.send("c1", APPROVAL)
    kwargs = send.call_args.kwargs
    assert kwargs["to"] == ["jane@client.example"]
    assert kwargs["cc"] == [email_service.CLIENT_CC]
    assert kwargs["reply_to"] == email_service.CLIENT_CC
    assert kwargs["attachments"] == [("NAR1-x.pdf", b"%PDF")]
    assert kwargs["subject"] == "[Rev. 2] NAR1 Confirmation Received - Kanenas Holding Limited"
    assert "NAR1-x.pdf" in kwargs["html"]


async def test_the_trail_records_it_as_an_email_tagged_as_the_receipt():
    with _Stack(_world(failures=[{"file": "x.pdf", "reason": "r"}])) as (*_, log):
        await receipt.send("c1", APPROVAL)
    call = log.await_args
    assert call.kwargs["action_type"] == "EMAIL_SENT"
    assert call.kwargs["user_id"] is None
    assert call.kwargs["user_display_name"] == "G-FlowDesk (automatic)"
    assert call.kwargs["entity_type"] == "nar1_case" and call.kwargs["entity_id"] == "c1"
    assert call.kwargs["case_id"] == "e1"
    meta = call.kwargs["metadata"]
    assert meta["template"] == "approval_receipt"
    assert meta["approval_id"] == "a1"
    assert meta["intended_to"] == ["jane@client.example"] and meta["to"] == SENT["to"]
    assert meta["attachments"] == ["NAR1-x.pdf"]
    assert meta["attachment_failures"] == [{"file": "x.pdf", "reason": "r"}]
    # Identifiers only — never the PDF bytes.
    assert b"%PDF" not in repr(call.kwargs).encode()


async def test_a_resend_refusal_is_swallowed_and_nothing_is_audited():
    with _Stack(_world(send_effect=email_service.EmailError("rejected"))) as (*_, log):
        await receipt.send("c1", APPROVAL)   # must not raise
    log.assert_not_awaited()


async def test_anything_else_going_wrong_is_swallowed_too():
    patches = _world()
    patches[0] = patch("services.approval_receipt.nar1_cases.get_case",
                       side_effect=RuntimeError("db down"))
    with _Stack(patches) as (_c, _e, _d, send, _log):
        await receipt.send("c1", APPROVAL)
    send.assert_not_called()


async def test_an_audit_failure_does_not_raise():
    patches = _world()
    patches[4] = patch("services.approval_receipt.log_event", new_callable=AsyncMock,
                       side_effect=RuntimeError("audit down"))
    with _Stack(patches):
        await receipt.send("c1", APPROVAL)


async def test_no_address_on_the_token_sends_nothing():
    with _Stack(_world()) as (_c, _e, _d, send, _log):
        await receipt.send("c1", {**APPROVAL, "recipient_email": None})
    send.assert_not_called()


# --------------------------------------------------------------------------- #
#  The receipt names every document, attached or not (PRD section 6, test 10)
# --------------------------------------------------------------------------- #

async def test_the_receipt_names_every_document_even_when_one_could_not_be_attached():
    """An ND2A whose resolution failed to render goes out carrying the form
    only; the letter still says the client confirmed both."""
    failures = [{"file": "Written-Resolution-ND2A-2026-0001.pdf", "reason": "font missing"}]
    world = _world(case=ND2A, files=(("ND2A-ND2A-2026-0001.pdf", b"%PDF"),),
                   failures=failures)
    with _Stack(world) as (_c, _e, _d, send, _log):
        await receipt.send("k1", {**APPROVAL, "revision": 1})
    html = send.call_args.kwargs["html"]
    assert ND2A_TITLE in html
    assert RESOLUTION_TITLE in html
    # The Attached box is unchanged: it lists only what is actually attached.
    assert "Written-Resolution-ND2A-2026-0001.pdf" not in html


async def test_the_trail_records_the_titles_the_client_confirmed():
    with _Stack(_world(case=ND2A, files=(("ND2A-x.pdf", b"%PDF"),))) as (*_, log):
        await receipt.send("k1", {**APPROVAL, "revision": 1})
    assert log.await_args.kwargs["metadata"]["documents"] == [ND2A_TITLE, RESOLUTION_TITLE]


async def test_a_nar1_receipt_names_the_return_and_its_year():
    with _Stack(_world()) as (_c, _e, _d, send, log):
        await receipt.send("c1", APPROVAL)
    assert f"{NAR1_TITLE} (Rev. 2)" in send.call_args.kwargs["html"]
    assert log.await_args.kwargs["metadata"]["documents"] == [f"{NAR1_TITLE} (Rev. 2)"]
