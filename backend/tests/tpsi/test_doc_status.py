"""CR's `documentStatus` -> one of six treatments.

The vocabulary is OPEN (see services/tpsi/doc_status), so the test that matters
most is not any single mapping — it is that an unanticipated string lands
somewhere honest instead of on a colour that claims something CR did not say.
"""
import pytest

from services.tpsi import doc_status as ds


# ── the three CR has actually been seen to send ──────────────────────────────
# Two came off live replies; `Lodged` came off CR's own response example in
# §6.5.5 of TPSI API Interface v1.0.14 (found 2026-09-16, while fixing the
# request shape in the same section). Everything else this module recognises is
# reasonable guessing, and the line between the two is worth keeping visible.

def test_the_three_strings_cr_has_actually_been_seen_to_send():
    assert ds.normalise("Registered") == ds.REGISTERED
    assert ds.normalise("Pending") == ds.PENDING
    assert ds.normalise("Lodged") == ds.PENDING


def test_lodged_is_pending_and_not_registered():
    """The receipt, not the decision. A lodged document is in CR's hands and
    undecided; calling it registered would put a green tick and a finished case
    on a return the registry may still refuse."""
    assert ds.normalise("Lodged") == ds.PENDING
    assert ds.normalise("Lodged for registration") == ds.PENDING


# ── nothing said is not "something unrecognisable" ───────────────────────────

@pytest.mark.parametrize("raw", [None, "", "   ", "\t\n"])
def test_no_answer_is_not_checked_never_unknown(raw):
    """CR naming no status is indistinguishable from not having been asked.

    UNKNOWN would claim the register answered with something we could not read,
    which is an invention about a call that returned nothing.
    """
    assert ds.normalise(raw) == ds.NOT_CHECKED


# ── the shapes one field of 20 free-text characters actually arrives in ──────

@pytest.mark.parametrize("raw", [
    "REGISTERED", "registered", " Registered ", "Registered.", "Registered ",
])
def test_case_padding_and_punctuation_do_not_change_the_answer(raw):
    assert ds.normalise(raw) == ds.REGISTERED


# ── order is load-bearing ────────────────────────────────────────────────────

def test_a_rejected_registration_is_a_refusal_not_a_registration():
    """REJECTED is tested first. The other order calls a refusal a win."""
    assert ds.normalise("Registration Rejected") == ds.REJECTED


def test_pending_registration_is_pending():
    """PENDING before REGISTERED. The other order reads as on the register."""
    assert ds.normalise("Pending Registration") == ds.PENDING


def test_approved_for_registration_is_approved_not_registered():
    assert ds.normalise("Approved for reg") == ds.APPROVED


# ── whole words, not substrings ──────────────────────────────────────────────

def test_returned_is_matched_as_a_word_not_inside_return():
    """"Returned" is a refusal; "Return" is the noun for the document itself.

    A bare substring match would read every "Annual Return ..." status as a
    rejection, which is the worst direction for this to be wrong in.
    """
    assert ds.normalise("Returned") == ds.REJECTED
    assert ds.normalise("Annual Return") == ds.UNKNOWN


# ── the four buckets ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,code", [
    ("Pending", ds.PENDING),
    ("In Progress", ds.PENDING),
    ("Processing", ds.PENDING),
    ("Received", ds.PENDING),
    ("Submitted", ds.PENDING),
    ("Awaiting Vetting", ds.PENDING),
    ("Approved", ds.APPROVED),
    ("Accepted", ds.APPROVED),
    ("Vetted", ds.APPROVED),
    ("Registered", ds.REGISTERED),
    ("Rejected", ds.REJECTED),
    ("Refused", ds.REJECTED),
    ("Withdrawn", ds.REJECTED),
    ("Cancelled", ds.REJECTED),
    ("Canceled", ds.REJECTED),
])
def test_the_recognised_strings(raw, code):
    assert ds.normalise(raw) == code


@pytest.mark.parametrize("raw", ["Zorb", "XYZ-42", "已登記", "n/a"])
def test_an_unanticipated_answer_is_unknown_never_guessed(raw):
    assert ds.normalise(raw) == ds.UNKNOWN


# ── every code has a label, and only the two CR cannot move off are terminal ──

def test_every_code_has_a_label():
    assert set(ds.CR_STATUS_LABELS) == set(ds.CR_STATUS_CODES)
    assert all(ds.CR_STATUS_LABELS[c] for c in ds.CR_STATUS_CODES)


def test_only_registered_and_rejected_are_terminal():
    """The poller's selection rule reads this tuple. Widening it would stop
    checking a case CR has not finished with; narrowing it would keep spending
    CR authentications on a decided one."""
    assert ds.TERMINAL_CODES == (ds.REGISTERED, ds.REJECTED)
    assert ds.NOT_CHECKED not in ds.TERMINAL_CODES
    assert ds.PENDING not in ds.TERMINAL_CODES
    assert ds.APPROVED not in ds.TERMINAL_CODES
    # UNKNOWN is deliberately NOT terminal: an answer we could not read is not
    # a decision, and a case sitting on one must keep being asked.
    assert ds.UNKNOWN not in ds.TERMINAL_CODES


# ── describe() ───────────────────────────────────────────────────────────────

def test_describe_carries_crs_own_words_through_untouched():
    out = ds.describe("Registered")
    assert out == {
        "code": ds.REGISTERED,
        "label": "Registered by CR",
        "cr_text": "Registered",
        "terminal": True,
    }


def test_describe_on_an_unknown_keeps_the_only_informative_thing_it_has():
    out = ds.describe("Zorb")
    assert out["code"] == ds.UNKNOWN
    assert out["cr_text"] == "Zorb"


def test_describe_prefers_the_stored_code_over_re_deriving():
    """The dashboard filtered and counted on the STORED code. Re-deriving here
    could make a case's own screen disagree with the listing that opened it."""
    out = ds.describe("Registered", code=ds.PENDING)
    assert out["code"] == ds.PENDING
    assert out["cr_text"] == "Registered"


def test_describe_falls_back_when_the_stored_code_is_not_one_of_ours():
    out = ds.describe("Registered", code="nonsense")
    assert out["code"] == ds.REGISTERED


def test_describe_with_nothing_at_all():
    out = ds.describe(None)
    assert out["code"] == ds.NOT_CHECKED
    assert out["cr_text"] is None
    assert out["terminal"] is False
