"""What CR did with a document AFTER it was filed — docStatusEnquiry, normalised.

A third vocabulary, and it is not either of the two that already exist.

  FORM status     tpsi_filings.stage      where the document is in OUR chain
                                          (validate -> sign -> submit)
  WORKFLOW status nar1_case_status        where the case is in GSHK's process
  CR STATUS       this module             what CR's own register says about a
                                          document it has already received

The first two end at "we handed it over". This one begins there. A NAR1 that
`submitFormNar1` accepted and charged for is not yet on the register: CR vets it
and can still refuse it, and until this module has asked, nobody in the portal
knows which.

THE VOCABULARY IS OPEN, AND THAT IS A MEASUREMENT, NOT A HEDGE.
`TPSI API Interface v1.0.14.docx` §6.5.4 declares `documentStatus` as
`String(20)` with the remark "Document Status" and enumerates NO values;
`TPSIT User Guideline v1.0.5.docx` does not contain the word "status". Three
values have ever been seen: `Registered` and `Pending`, and — found on
2026-09-16 in the response example embedded in §6.5.5 of that same docx —
`Lodged`, which none of the guessed-at phrases here had covered. The list below
is therefore three attestations and a quantity of reasonable guessing, and it is
important to know which is which. So CR's exact words are stored and shown verbatim,
a TREATMENT is derived from them here, and anything unanticipated lands on
`UNKNOWN` — grey, with CR's own wording on the badge — rather than on a wrong
colour or on nothing at all. `nar1_cases.RECEIPT_VOCABULARY` takes the same
posture for the same reason: CR has more codes than GSHK has seen.

NOT_CHECKED IS NOT PENDING. "We have not asked CR" and "CR told us it is
pending" are different facts, and one code for both would let a deployment with
no cron job report an answer it never received. It is also the state Levi asked
for as the pre-batch-job fallback: filed, and grey, until something checks.
"""
from __future__ import annotations

import re

#: Filed, and CR has not been asked — or was asked and named no document.
#: The state every filed case starts in, and the only one that is OUR fact
#: rather than CR's.
NOT_CHECKED = "cr_not_checked"

#: CR holds it and has not decided.
PENDING = "cr_pending"

#: CR has decided yes, and it is not on the register yet.
APPROVED = "cr_approved"

#: On the register. The one terminal answer that means the statutory job is
#: finished.
REGISTERED = "cr_registered"

#: CR will not register it. Withdrawal and cancellation are folded in here: the
#: operator's position is identical (nothing is on the register, something has
#: to be re-filed), and a seventh badge for a string CR may never send is a
#: column nobody can read.
REJECTED = "cr_rejected"

#: CR answered something this module does not recognise. Grey, never guessed at,
#: and the raw text is what the screen shows.
UNKNOWN = "cr_unknown"

CR_STATUS_CODES = (NOT_CHECKED, PENDING, APPROVED, REGISTERED, REJECTED, UNKNOWN)

#: The codes CR can no longer move away from. `refresh` skips these and so does
#: the nightly poller — Levi 2026-09-16: "we should only check for things after
#: submission and not yet confirmed or rejected with CR".
TERMINAL_CODES = (REGISTERED, REJECTED)

CR_STATUS_LABELS = {
    NOT_CHECKED: "Awaiting CR status",
    PENDING: "Pending at CR",
    APPROVED: "Approved by CR",
    REGISTERED: "Registered by CR",
    REJECTED: "Rejected by CR",
    UNKNOWN: "Other CR status",
}

#: The phrases, in the order they are tested. ORDER IS LOAD-BEARING and each
#: position is a real case, not a preference:
#:
#:   REJECTED before everything   "registration rejected" is a refusal, and
#:                                testing REGISTERED first would call it a win.
#:   PENDING before REGISTERED    "pending registration" is pending. The other
#:                                way round it reads as on the register.
#:   APPROVED before REGISTERED   "approved for registration" is approved.
#:
#: Matched on WHOLE WORDS, never bare substrings: "returned" must not be found
#: inside "return", which is the noun for the document this whole module is
#: about.
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (REJECTED, ("reject", "rejected", "refuse", "refused", "returned",
                "withdraw", "withdrawn", "cancel", "cancelled", "canceled",
                "not accepted", "declined")),
    # "lodged" IS ATTESTED, unlike most of this list: it is the documentStatus
    # in CR's own §6.5.5 response example, which makes it the third value CR
    # has ever been seen to send (after Registered and Pending) and the only one
    # that arrived from the specification rather than from a live reply. A
    # document is lodged when the registry has it and has not yet ruled on it,
    # so it belongs here and not under REGISTERED — "lodged" is the receipt,
    # "registered" is the decision.
    (PENDING, ("pending", "in progress", "in-progress", "progress",
               "processing", "under process", "received", "submitted",
               "lodged", "lodgement", "awaiting", "queued", "vetting")),
    (APPROVED, ("approve", "approved", "accepted", "vetted", "passed")),
    (REGISTERED, ("register", "registered", "registration", "completed",
                  "filed")),
)


def _words(text: str) -> str:
    """Lower-cased, single-spaced, punctuation turned into gaps.

    CR's field is 20 characters of free text typed by somebody: "Registered",
    "REGISTERED", "Registered." and "Pending/Vetting" all have to reach the same
    answer, and the separator is not something to guess at per deployment.
    """
    return " " + re.sub(r"[^a-z0-9]+", " ", text.lower()).strip() + " "


def normalise(raw: str | None) -> str:
    """CR's own words -> one of CR_STATUS_CODES.

    Blank, whitespace and None are NOT_CHECKED, not UNKNOWN: CR naming no status
    is indistinguishable from not having been asked, and claiming the register
    said something unrecognisable would be an invention.
    """
    text = (raw or "").strip()
    if not text:
        return NOT_CHECKED

    padded = _words(text)
    for code, phrases in _RULES:
        for phrase in phrases:
            if f" {phrase} " in padded:
                return code
    return UNKNOWN


def describe(raw: str | None, code: str | None = None) -> dict:
    """The CR-status badge for one case — the shape the screen renders.

    `raw` is carried through UNTOUCHED beside the label. On an UNKNOWN the raw
    text is the only thing that says anything at all, and on a recognised code
    it is the evidence for the label: an operator ringing CR quotes what CR
    said, not what this module decided it meant.

    `code` lets a caller pass the STORED code rather than re-deriving from
    `raw`. The stored one wins, because it is what the dashboard filtered and
    counted on — re-deriving here could make a case's own screen disagree with
    the listing that opened it, which is the divergence `badge_from_row` exists
    to prevent for the workflow badge.
    """
    resolved = code if code in CR_STATUS_CODES else normalise(raw)
    return {
        "code": resolved,
        "label": CR_STATUS_LABELS[resolved],
        "cr_text": (raw or "").strip() or None,
        "terminal": resolved in TERMINAL_CODES,
    }
