"""services/nar1_case_status.py — the derived workflow badge.

Every case here is a (filing stage, case facts) pair and its expected badge.
The point of a pure function is that this table IS the specification.
"""
import pytest

from services import nar1_case_status as st


def case(**over):
    base = {
        "verification_sent_at": None,
        "client_approved": None,
        "manual_receipt": None,
        "manual_submitted_at": None,
    }
    base.update(over)
    return base


def filing(stage):
    return {"stage": stage}


@pytest.mark.parametrize("stage", [None, "draft", "validation_failed"])
def test_no_validated_filing_means_data_verification(stage):
    f = filing(stage) if stage else None
    assert st.derive(case(), f)["code"] == "data_verification"


def test_validated_but_not_sent_is_client_verification():
    assert st.derive(case(), filing("validated"))["code"] == "client_verification"


def test_sent_and_unanswered_is_awaiting_client():
    c = case(verification_sent_at="2026-08-16T00:00:00Z")
    assert st.derive(c, filing("validated"))["code"] == "awaiting_client"


def test_a_no_from_the_client_is_its_own_badge():
    """Rejection is not "back to square one" -- the trail must show a client
    said no, which "Data Verification" would erase."""
    c = case(verification_sent_at="2026-08-16T00:00:00Z", client_approved=False)
    assert st.derive(c, filing("validated"))["code"] == "client_rejected"


def test_approved_is_signing():
    c = case(verification_sent_at="2026-08-16T00:00:00Z", client_approved=True)
    assert st.derive(c, filing("validated"))["code"] == "signing"


def test_a_failed_signature_stays_in_signing():
    """signing_failed is free and recoverable -- the user retries here, so the
    badge must not advance past the step they are still on."""
    c = case(verification_sent_at="2026-08-16T00:00:00Z", client_approved=True)
    assert st.derive(c, filing("signing_failed"))["code"] == "signing"


def test_signed_is_submission():
    c = case(verification_sent_at="2026-08-16T00:00:00Z", client_approved=True)
    assert st.derive(c, filing("signed"))["code"] == "submission"


def test_a_failed_submission_stays_in_submission():
    c = case(verification_sent_at="2026-08-16T00:00:00Z", client_approved=True)
    assert st.derive(c, filing("submission_failed"))["code"] == "submission"


@pytest.mark.parametrize("stage", ["submitted", "registered"])
def test_filed_with_cr_is_completed(stage):
    c = case(verification_sent_at="2026-08-16T00:00:00Z", client_approved=True)
    assert st.derive(c, filing(stage))["code"] == "completed"


def test_a_manual_receipt_completes_the_case_without_any_cr_stage():
    """The manual path never calls CR, so the filing is still 'validated' -- the
    case is nevertheless finished, and the badge has to say so."""
    c = case(client_approved=True, verification_sent_at="2026-08-16T00:00:00Z",
             manual_receipt={"caseNo": "180256934"})
    assert st.derive(c, filing("validated"))["code"] == "completed"


def test_edrive_completes_the_case_and_flags_it_off_portal():
    """CR: a form sent to e-Drive is inconvertible to TPSI format -- it is
    finished somewhere else, and the caller has to be able to say so."""
    c = case(verification_sent_at="2026-08-16T00:00:00Z", client_approved=True)
    result = st.derive(c, filing("edrive"))
    assert result["code"] == "completed"
    assert result["off_portal"] is True


def test_off_portal_is_false_on_an_ordinary_completion():
    c = case(verification_sent_at="2026-08-16T00:00:00Z", client_approved=True)
    assert st.derive(c, filing("submitted"))["off_portal"] is False


def test_overdue_is_an_overlay_not_a_stage():
    """42 days past the anniversary can be true of a case at ANY step, so it is
    a separate flag -- folding it into the code would hide the real step."""
    c = case(days_to_anniversary=-43)
    result = st.derive(c, None)
    assert result["code"] == "data_verification"
    assert result["overdue"] is True


def test_the_last_day_of_the_filing_window_is_not_yet_overdue():
    """42 days after the anniversary is the LAST day inside the statutory
    window, not the first day outside it. Off by one here is a compliance
    error, not a rounding preference."""
    assert st.derive(case(days_to_anniversary=-42), None)["overdue"] is False
    assert st.derive(case(days_to_anniversary=-43), None)["overdue"] is True


def test_a_completed_case_is_never_flagged_overdue():
    """It was filed. Whether it was filed late is a different question and not
    this badge's to answer."""
    c = case(verification_sent_at="x", client_approved=True, days_to_anniversary=-99)
    assert st.derive(c, filing("submitted"))["overdue"] is False


def test_every_code_has_a_label():
    assert set(st.WORKFLOW_LABELS) == set(st.WORKFLOW_STATUSES)


def test_there_are_exactly_eight_badges():
    """wireframe_v11 defines seven; CLOSED is the eighth, added 2026-09-05.

    The count is asserted rather than the membership because a NINTH added
    without a home would have nowhere to render: every code needs a label here,
    a class in `CaseStatusBadge.jsx`, a branch in the SQL view (migration 039)
    and a place in the dashboard's `WORKFLOW_ORDER`. Four files, and the count
    is the cheap tripwire that says to visit them.
    """
    assert len(st.WORKFLOW_STATUSES) == 8
    assert st.CLOSED in st.WORKFLOW_STATUSES
    assert set(st.WORKFLOW_LABELS) == set(st.WORKFLOW_STATUSES)


# ---- badge_from_row — the dashboard's read-back of the SQL answer ---------

@pytest.mark.parametrize("code", st.WORKFLOW_STATUSES)
def test_badge_from_row_produces_derives_shape_for_every_code(code):
    """The dashboard reads the badge out of nar1_case_registry rather than
    re-deriving it. The two screens must not differ in the key names."""
    badge = st.badge_from_row({"workflow_status": code,
                               "workflow_off_portal": False,
                               "workflow_overdue": False})
    assert set(badge) == {"code", "label", "off_portal", "overdue"}
    assert badge["code"] == code
    assert badge["label"] == st.WORKFLOW_LABELS[code]


def test_badge_from_row_carries_the_flags_the_view_computed():
    badge = st.badge_from_row({"workflow_status": "signing",
                               "workflow_off_portal": True,
                               "workflow_overdue": True})
    assert badge["off_portal"] is True
    assert badge["overdue"] is True


def test_badge_from_row_reads_a_missing_flag_as_false_not_none():
    """SQL NULL and a column the caller did not select both arrive as None. The
    frontend renders a flag, and `null` is not a third state it knows."""
    badge = st.badge_from_row({"workflow_status": "signing"})
    assert badge["off_portal"] is False
    assert badge["overdue"] is False


def test_badge_from_row_refuses_a_status_that_is_not_one_of_the_seven():
    """Loud, not silent. A code with no label means the view and this module
    have drifted apart, which is exactly what test_migration_024 exists to
    catch — swallowing it here would hide the drift behind a blank badge."""
    with pytest.raises(KeyError):
        st.badge_from_row({"workflow_status": "awaiting_cr"})


def test_badge_from_row_does_not_re_derive():
    """It reports what the SQL decided. Re-deriving in Python would paper over a
    divergence between the two implementations of one rule, and the whole point
    of the parity test is to make that divergence loud."""
    row = {"workflow_status": "completed", "workflow_off_portal": False,
           "workflow_overdue": False,
           # Facts that derive() would read as data_verification.
           "filing_stage": None, "verification_sent_at": None,
           "client_approved": None, "manual_receipt_present": False}
    assert st.badge_from_row(row)["code"] == "completed"


def test_the_module_does_no_io():
    """A pure function is what makes this table-driven test the specification.
    An import of the DB client here would make it untestable without Supabase."""
    import inspect
    src = inspect.getsource(st)
    assert "supabase" not in src.lower()


# ---- CLOSED — terminal, and above everything else -------------------------
#
# `POST /cases/{id}/close` refuses a case CR already holds, so the portal cannot
# write a row that is both closed and filed. These tests fix the ORDER anyway:
# `_code` is also fed rows by the dashboard view and by any future repair, and
# the branch order is the whole contract between the two implementations.

def test_a_closed_case_reads_closed_whatever_stage_its_filing_is_at():
    """The one badge that is not derived from where the work got to."""
    for stage in (None, "draft", "validated", "signed", "validation_failed"):
        filing = {"stage": stage} if stage else None
        badge = st.derive({"closed_at": "2026-09-05T02:00:00Z"}, filing)
        assert badge["code"] == st.CLOSED, stage
        assert badge["label"] == "Closed"


def test_closed_beats_a_filed_return_rather_than_the_other_way_round():
    """Not reachable through the API — the close route refuses a filed case —
    but if a repair ever writes one, somebody deliberately ended this case and a
    stage lookup must not overrule that."""
    closed_and_filed = {"closed_at": "2026-09-05T02:00:00Z",
                        "manual_receipt": {"caseNo": "1"}}
    assert st.derive(closed_and_filed, {"stage": "submitted"})["code"] == st.CLOSED


def test_an_open_case_is_unaffected_by_the_new_branch():
    """The guard is `closed_at`, not "the key is present"."""
    assert st.derive({"closed_at": None}, None)["code"] == st.DATA_VERIFICATION
    assert st.derive({}, None)["code"] == st.DATA_VERIFICATION


def test_a_closed_case_is_never_overdue():
    """The overlay says "somebody still has to file this". On a case that will
    never be filed it is an alarm about work that was deliberately cancelled —
    exactly the noise closing a case exists to remove."""
    long_past = {"closed_at": "2026-09-05T02:00:00Z", "days_to_anniversary": -200}
    assert st.derive(long_past, None)["overdue"] is False
    # The same case, still open, IS overdue — so the test above is about the
    # closure and not about the day count.
    assert st.derive({"days_to_anniversary": -200}, None)["overdue"] is True


def test_badge_from_row_carries_the_closed_code_through():
    """The dashboard reads the view's answer back rather than re-deriving it;
    an unknown code raises a KeyError on the label map, which is how a view that
    drifted from Python is meant to fail."""
    badge = st.badge_from_row({"workflow_status": st.CLOSED})
    assert badge == {"code": st.CLOSED, "label": "Closed",
                     "off_portal": False, "overdue": False}
