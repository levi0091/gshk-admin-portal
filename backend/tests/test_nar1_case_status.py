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


def test_a_completed_case_is_never_flagged_overdue():
    """It was filed. Whether it was filed late is a different question and not
    this badge's to answer."""
    c = case(verification_sent_at="x", client_approved=True, days_to_anniversary=-99)
    assert st.derive(c, filing("submitted"))["overdue"] is False


def test_every_code_has_a_label():
    assert set(st.WORKFLOW_LABELS) == set(st.WORKFLOW_STATUSES)


def test_there_are_exactly_seven_badges():
    """wireframe_v11 defines seven. An eighth would have nowhere to render."""
    assert len(st.WORKFLOW_STATUSES) == 7


def test_the_module_does_no_io():
    """A pure function is what makes this table-driven test the specification.
    An import of the DB client here would make it untestable without Supabase."""
    import inspect
    src = inspect.getsource(st)
    assert "supabase" not in src.lower()
