"""services/nar1_cr_status.py — asking CR what it did, and recording it.

The exclusions are the feature, as they are in `auto_approve_nar1`: this module
writes a statutory status onto a case, and every branch below is a way it could
write one CR never sent.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import nar1_cr_status as crs
from services.tpsi import doc_status as ds
from services.tpsi import filings as tpsi_filings


def case(**over):
    base = {
        "id": "c1",
        "case_no": "NAR-2026-0001",
        "entity_id": "e1",
        "closed_at": None,
        "manual_receipt": None,
        "cr_doc_status": None,
        "cr_doc_status_code": None,
        "cr_status_checked_at": None,
        "cr_document_ref_no": None,
    }
    base.update(over)
    return base


def filing(stage="submitted", **over):
    base = {"id": "f1", "stage": stage,
            "receipt": {"caseNo": "151120654", "brNo": "78799952"}}
    base.update(over)
    return base


def cr_rows(status="Registered", ref="NAR1-REF-1", name="NAR1"):
    return [{"caseNo": "151120654", "documentStatus": status,
             "documentRefNo": ref, "documentName": name}]


def _world(rows=None, store=None):
    """Nothing reaches Supabase and nothing reaches CR."""
    return (
        patch("services.nar1_cr_status.reads.case_status",
              return_value=rows if rows is not None else cr_rows()),
        patch("services.nar1_cr_status._store", store or MagicMock()),
        patch("services.nar1_cr_status.tpsi_filings.mark_registered",
              return_value=True),
    )


class _Stack:
    def __init__(self, *patches):
        self._patches = patches

    def __enter__(self):
        self._entered = [p.__enter__() for p in self._patches]
        return self._entered

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.__exit__(*exc)
        return False


# --------------------------------------------------------------------------- #
#  Which case may be asked about at all
# --------------------------------------------------------------------------- #

def test_an_unfiled_case_is_not_asked_about():
    """There is nothing at CR to ask about, and `docStatusEnquiry` would have no
    key to match on."""
    assert crs.due_for_check(case(), filing("validated")) == \
        "the return has not been filed with CR"
    assert crs.due_for_check(case(), None) is not None


@pytest.mark.parametrize("stage", ["submitted", "registered", "edrive"])
def test_a_filed_case_is_asked_about(stage):
    assert crs.due_for_check(case(), filing(stage)) is None


def test_an_off_portal_case_is_asked_about_even_though_its_filing_never_went():
    """The manual path's filing row is still at 'validated'. Reading the stage
    alone would report a filed case as unfiled and never poll it — which is
    exactly why the CR columns live on the case, not on that row."""
    c = case(manual_receipt={"caseNo": "151120654"})
    assert crs.due_for_check(c, filing("validated")) is None


@pytest.mark.parametrize("code", ds.TERMINAL_CODES)
def test_a_case_cr_has_finished_with_is_not_asked_again(code):
    """Levi: "only check for things after submission and not yet confirmed or
    rejected with CR". Every further enquiry is a CR round trip for an answer
    that cannot change."""
    c = case(cr_doc_status_code=code)
    assert "already finished" in crs.due_for_check(c, filing())


@pytest.mark.parametrize("code", [ds.NOT_CHECKED, ds.PENDING, ds.APPROVED,
                                  ds.UNKNOWN])
def test_an_undecided_case_keeps_being_asked(code):
    """UNKNOWN especially: an answer we could not read is not a decision, and a
    case sitting on one must keep being asked."""
    assert crs.due_for_check(case(cr_doc_status_code=code), filing()) is None


def test_a_closed_case_is_not_asked_about():
    c = case(closed_at="2026-09-05T02:00:00Z", manual_receipt={"caseNo": "1"})
    assert crs.due_for_check(c, filing()) == "the case is closed"


def test_a_filed_case_with_no_cr_case_number_is_not_asked_about():
    """Refused rather than enquired with a blank key, which CR answers with
    every document the presenter has ever filed."""
    c = case()
    assert crs.due_for_check(c, filing(receipt={"brNo": "78799952"})) == \
        "no CR case number is recorded for this case"


def test_the_cr_case_number_is_crs_own_not_the_portals():
    """`RECEIPT_DERIVED`'s note: for a few hours the portal's NAR-2026-… number
    was written under CR's `caseNo` key. This must read the receipt's."""
    assert crs.cr_case_number(case(), filing()) == "151120654"
    assert crs.cr_case_number(
        case(manual_receipt={"caseNo": "180256934"}), None) == "180256934"


# --------------------------------------------------------------------------- #
#  Which of CR's rows is THIS return
# --------------------------------------------------------------------------- #

def test_one_row_is_unambiguous():
    row, refusal = crs.pick_document(cr_rows(), None)
    assert refusal is None and row["documentStatus"] == "Registered"


def test_no_rows_refuses_rather_than_writing_nothing_silently():
    row, refusal = crs.pick_document([], None)
    assert row is None and "no documents" in refusal


def test_a_known_reference_wins_over_everything():
    rows = [
        {"documentRefNo": "OTHER", "documentStatus": "Rejected", "documentName": "NAR1"},
        {"documentRefNo": "MINE", "documentStatus": "Registered", "documentName": "NAR1"},
    ]
    row, refusal = crs.pick_document(rows, "MINE")
    assert refusal is None and row["documentStatus"] == "Registered"


def test_several_documents_are_disambiguated_by_name():
    rows = [
        {"documentRefNo": "A", "documentStatus": "Registered", "documentName": "ND2A"},
        {"documentRefNo": "B", "documentStatus": "Pending", "documentName": "NAR1"},
    ]
    row, refusal = crs.pick_document(rows, None)
    assert refusal is None and row["documentRefNo"] == "B"


def test_an_ambiguous_answer_refuses_rather_than_guessing():
    """Attributing another form's rejection to this NAR1 would put a wrong red
    badge on a return that is perfectly fine."""
    rows = [
        {"documentRefNo": "A", "documentStatus": "Rejected", "documentName": "ND2A"},
        {"documentRefNo": "B", "documentStatus": "Registered", "documentName": "NSC1"},
    ]
    row, refusal = crs.pick_document(rows, None)
    assert row is None
    assert "2 documents" in refusal


# --------------------------------------------------------------------------- #
#  refresh() — the only writer
# --------------------------------------------------------------------------- #

def test_a_registered_answer_is_stored_and_the_filing_is_promoted():
    store, f = MagicMock(), filing("submitted")
    with _Stack(*_world(store=store)) as entered:
        report = crs.refresh(MagicMock(), case(), f)
    mark = entered[2]

    patch_written = store.call_args.args[1]
    assert patch_written["cr_doc_status"] == "Registered"
    assert patch_written["cr_doc_status_code"] == ds.REGISTERED
    assert patch_written["cr_status_checked_at"]
    assert patch_written["cr_document_ref_no"] == "NAR1-REF-1"

    assert report["checked"] is True
    assert report["changed"] is True
    assert report["previous"] == ds.NOT_CHECKED
    assert report["stage_promoted"] is True
    mark.assert_called_once_with("f1")


def test_a_rejection_does_not_touch_the_filing_stage():
    """`submission_failed` means submitFormNar1 refused and NOTHING WAS CHARGED.
    A rejection after filing means the opposite — delivered, charged, refused —
    and collapsing the two would tell an operator no money moved when it did."""
    with _Stack(*_world(rows=cr_rows("Rejected"))) as entered:
        report = crs.refresh(MagicMock(), case(), filing("submitted"))
    entered[2].assert_not_called()
    assert report["code"] == ds.REJECTED
    assert report["stage_promoted"] is False


def test_a_manual_case_is_stored_but_promotes_no_filing():
    """There is no submitted row to promote: its filing never went to CR."""
    c = case(manual_receipt={"caseNo": "180256934"})
    with _Stack(*_world()) as entered:
        report = crs.refresh(MagicMock(), c, filing("validated"))
    entered[2].assert_not_called()
    assert report["code"] == ds.REGISTERED
    assert report["stage_promoted"] is False


def test_the_same_answer_twice_is_not_a_change():
    """`NAR1_CR_STATUS_CHANGED` must fire on a MOVE, or the one question anybody
    asks the trail — when did CR register this — is buried in heartbeats."""
    c = case(cr_doc_status_code=ds.PENDING, cr_doc_status="Pending")
    with _Stack(*_world(rows=cr_rows("Pending"))):
        report = crs.refresh(MagicMock(), c, filing())
    assert report["checked"] is True
    assert report["changed"] is False


def test_a_heartbeat_does_not_touch_updated_at():
    """The dashboard's Last Updated column is sortable and is how an operator
    finds the case that changed. A nightly poll that bumped it would reset every
    filed case in the book to "today" each morning and make the column say
    nothing. `cr_status_checked_at` is the column for when it was last ASKED."""
    store = MagicMock()
    c = case(cr_doc_status_code=ds.PENDING, cr_doc_status="Pending")
    with _Stack(*_world(rows=cr_rows("Pending"), store=store)):
        crs.refresh(MagicMock(), c, filing())
    written = store.call_args.args[1]
    assert "updated_at" not in written
    assert written["cr_status_checked_at"]


def test_a_real_move_does_touch_updated_at():
    store = MagicMock()
    c = case(cr_doc_status_code=ds.PENDING, cr_doc_status="Pending")
    with _Stack(*_world(rows=cr_rows("Registered"), store=store)):
        crs.refresh(MagicMock(), c, filing())
    assert store.call_args.args[1]["updated_at"]


def test_a_skipped_case_writes_nothing_and_says_why():
    store = MagicMock()
    with _Stack(*_world(store=store)):
        report = crs.refresh(MagicMock(), case(), filing("validated"))
    store.assert_not_called()
    assert report["checked"] is False
    assert report["skipped"] == "the return has not been filed with CR"


def test_an_ambiguous_cr_answer_leaves_the_previous_one_standing():
    """Nothing is written: the previous answer — including "never checked" — is
    still the truthful one, and overwriting it with a guess is the failure this
    branch exists for."""
    rows = [
        {"documentRefNo": "A", "documentStatus": "Rejected", "documentName": "ND2A"},
        {"documentRefNo": "B", "documentStatus": "Registered", "documentName": "NSC1"},
    ]
    store = MagicMock()
    with _Stack(*_world(rows=rows, store=store)):
        report = crs.refresh(MagicMock(), case(), filing())
    store.assert_not_called()
    assert report["checked"] is False
    assert "none could be identified" in report["skipped"]


def test_a_case_number_cr_does_not_hold_is_a_SKIP_carrying_crs_words():
    """Seen live on 2026-09-16: CR answers an unknown case number with the
    fault `Case no does not exist.`

    A fault on THIS call can only be about the criteria we sent — there is no
    return in a status enquiry for CR to find fault with — so nothing can be
    written from it, the previous answer stands, and one bad case number must
    not abandon the rest of a 400-case run. CR's own words are carried because
    the fix is the number typed on the Confirmation stage, and "CR refused it"
    would send an operator to the company profile instead.
    """
    from services.tpsi.errors import TpsiValidationError

    store = MagicMock()
    fault = TpsiValidationError([("", "Case no does not exist.")])
    with _Stack(*_world(store=store)) as _, \
         patch("services.nar1_cr_status.reads.case_status", side_effect=fault):
        report = crs.refresh(MagicMock(), case(), filing())

    store.assert_not_called()
    assert report["checked"] is False
    assert "does not recognise the case number" in report["skipped"]
    assert "Case no does not exist." in report["skipped"]
    # NOT "CR says: : Case no does not exist." — CR sends this fault with an
    # EMPTY code, and `_FaultError.__str__` renders "code: message", so the
    # default string puts a stray colon in the middle of the sentence.
    assert ": :" not in report["skipped"]


def test_a_blank_status_is_recorded_as_not_checked_not_unknown():
    """CR naming no status is indistinguishable from not having been asked."""
    with _Stack(*_world(rows=cr_rows(status=""))):
        report = crs.refresh(MagicMock(), case(), filing())
    assert report["code"] == ds.NOT_CHECKED
    assert report["cr_text"] is None


def test_a_missing_reference_never_clears_the_one_already_learnt():
    """CR omitting the reference on one reply must not throw away the exact key
    that makes the next enquiry unambiguous."""
    store = MagicMock()
    c = case(cr_document_ref_no="KNOWN")
    with _Stack(*_world(rows=cr_rows(ref=""), store=store)):
        report = crs.refresh(MagicMock(), c, filing())
    assert "cr_document_ref_no" not in store.call_args.args[1]
    assert report["document_ref_no"] == "KNOWN"


def test_the_enquiry_is_by_cr_case_number_and_nothing_else():
    """NEVER by BR number plus a date range: that returns every document the
    company filed in the window, and would attribute another form's status to
    this NAR1."""
    with _Stack(*_world()) as entered:
        crs.refresh(MagicMock(), case(), filing())
    kwargs = entered[0].call_args.kwargs
    assert kwargs == {"case_no": "151120654"}


# --------------------------------------------------------------------------- #
#  record() — two codes, one check
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_a_check_that_changed_nothing_writes_only_the_heartbeat():
    log = AsyncMock()
    with patch("services.nar1_cr_status.log_event", new=log):
        await crs.record({"checked": True, "changed": False, "code": ds.PENDING,
                          "previous": ds.PENDING, "cr_text": "Pending"},
                         case(), user_id=None, user_display_name="job")
    assert log.await_count == 1
    assert log.await_args.kwargs["action_type"] == "TPSI_DOC_STATUS_CHECKED"


@pytest.mark.asyncio
async def test_the_trail_records_crs_case_number_and_never_the_portals():
    """`nar1_cases.RECEIPT_DERIVED`'s note: for a few hours the portal's
    NAR-2026-… number was written under CR's `caseNo` key. `record()` cannot
    recover CR's number on its own — on the e-Sign path it lives on the FILING's
    receipt — so `refresh()` carries it in the report."""
    with _Stack(*_world()):
        result = crs.refresh(MagicMock(), case(), filing())
    assert result["cr_case_no"] == "151120654"

    log = AsyncMock()
    with patch("services.nar1_cr_status.log_event", new=log):
        await crs.record(result, case(), user_id=None, user_display_name="job")
    metadata = log.await_args_list[0].kwargs["metadata"]
    assert metadata["cr_case_no"] == "151120654"
    assert metadata["case_no"] == "NAR-2026-0001"


@pytest.mark.asyncio
async def test_a_move_writes_both():
    log = AsyncMock()
    with patch("services.nar1_cr_status.log_event", new=log):
        await crs.record({"checked": True, "changed": True, "code": ds.REGISTERED,
                          "previous": ds.PENDING, "cr_text": "Registered",
                          "stage_promoted": True},
                         case(), user_id="u1", user_display_name="Levi")
    assert log.await_count == 2
    codes = [c.kwargs["action_type"] for c in log.await_args_list]
    assert codes == ["TPSI_DOC_STATUS_CHECKED", "NAR1_CR_STATUS_CHANGED"]
    change = log.await_args_list[1].kwargs
    assert change["old_value"] == ds.PENDING
    assert change["new_value"] == ds.REGISTERED
    # audit_log.case_id holds the ENTITY id — routers/cases.py::_audit_target.
    assert change["case_id"] == "e1"
    assert change["entity_id"] == "c1"


@pytest.mark.asyncio
async def test_heartbeat_false_drops_only_the_heartbeat_never_the_move():
    """The poller suppresses the per-case heartbeat because it writes one per
    RUN instead — 96 runs a day made per-case rows unaffordable. What it must
    never suppress is the row somebody actually goes looking for: the move.
    """
    log = AsyncMock()
    with patch("services.nar1_cr_status.log_event", new=log):
        await crs.record({"checked": True, "changed": True, "code": ds.REGISTERED,
                          "previous": ds.PENDING, "cr_text": "Registered"},
                         case(), user_id=None, user_display_name="job",
                         heartbeat=False)
    codes = [c.kwargs["action_type"] for c in log.await_args_list]
    assert codes == ["NAR1_CR_STATUS_CHANGED"]


@pytest.mark.asyncio
async def test_heartbeat_false_on_an_unchanged_case_writes_nothing():
    log = AsyncMock()
    with patch("services.nar1_cr_status.log_event", new=log):
        await crs.record({"checked": True, "changed": False, "code": ds.PENDING,
                          "previous": ds.PENDING, "cr_text": "Pending"},
                         case(), user_id=None, user_display_name="job",
                         heartbeat=False)
    log.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_skipped_case_is_not_in_the_trail_at_all():
    """A case that was never asked about produced no CR answer, and a heartbeat
    row for it would claim the job checked something it did not."""
    log = AsyncMock()
    with patch("services.nar1_cr_status.log_event", new=log):
        await crs.record({"checked": False, "skipped": "nope"}, case(),
                         user_id=None, user_display_name="job")
    log.assert_not_awaited()


# --------------------------------------------------------------------------- #
#  mark_registered — the conditional update
# --------------------------------------------------------------------------- #

def test_mark_registered_only_ever_moves_a_submitted_row():
    """Conditional INSIDE the update, not read-then-written: this runs from a
    nightly job walking hundreds of cases, so the window between a read and a
    write is as long as the rest of the run."""
    table = MagicMock()
    table.update.return_value = table
    table.eq.return_value = table
    table.execute.return_value = MagicMock(data=[{"id": "f1"}])
    with patch("services.tpsi.filings.get_supabase") as sb:
        sb.return_value.table.return_value = table
        assert tpsi_filings.mark_registered("f1") is True

    table.update.assert_called_once_with({"stage": "registered"})
    assert [c.args for c in table.eq.call_args_list] == [
        ("id", "f1"), ("stage", "submitted")]
