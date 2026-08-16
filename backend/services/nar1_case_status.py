"""The WORKFLOW status — where the case is in GSHK's process.

Deliberately NOT the FORM status (services/tpsi/filings.py), which answers where
the document is in CR's process. The v11 header shows both, side by side; merging
them loses information in both directions.

D-6, the single-writer split: TPSI owns every CR fact (tpsi_filings.stage),
nar1_cases owns every client fact (verification_sent_at, client_approved) and
every off-portal fact (manual_receipt). This module WRITES NOTHING -- it is a
pure function of those two records, so the badge cannot drift out of step with
the facts underneath it, and there is no third place for them to disagree.

The seven codes are exactly the seven badges wireframe_v11 renders (bw-data,
bw-verify, bw-awaiting, bw-rejected, bw-sign, bw-submit, bw-done).
"""
from services.tpsi.filings import (
    STAGE_EDRIVE,
    STAGE_REGISTERED,
    STAGE_SIGNED,
    STAGE_SIGNING_FAILED,
    STAGE_SUBMISSION_FAILED,
    STAGE_SUBMITTED,
    STAGE_VALIDATED,
)

DATA_VERIFICATION = "data_verification"
CLIENT_VERIFICATION = "client_verification"
AWAITING_CLIENT = "awaiting_client"
CLIENT_REJECTED = "client_rejected"
SIGNING = "signing"
SUBMISSION = "submission"
COMPLETED = "completed"

WORKFLOW_STATUSES = (
    DATA_VERIFICATION, CLIENT_VERIFICATION, AWAITING_CLIENT, CLIENT_REJECTED,
    SIGNING, SUBMISSION, COMPLETED,
)

WORKFLOW_LABELS = {
    DATA_VERIFICATION: "Data Verification",
    CLIENT_VERIFICATION: "Client Verification",
    AWAITING_CLIENT: "Awaiting Client",
    CLIENT_REJECTED: "Client Rejected",
    SIGNING: "Signing",
    SUBMISSION: "Submission",
    COMPLETED: "Completed",
}

#: Filing stages that mean the document is finished at CR.
_FINISHED = (STAGE_SUBMITTED, STAGE_REGISTERED, STAGE_EDRIVE)

#: 42 days after the anniversary the statutory filing window closes. Negative
#: days_to_anniversary counts UP from a passed anniversary (migration 019), so
#: anything below this is out of time.
FILING_WINDOW_DAYS = 42


def _code(case: dict, filing: dict | None) -> str:
    stage = (filing or {}).get("stage")

    # Off-portal completion first: the manual path never calls CR, so its filing
    # is still sitting at 'validated' while the case is genuinely finished.
    # Testing the stage first would report a finished case as still Signing.
    if case.get("manual_receipt"):
        return COMPLETED
    if stage in _FINISHED:
        return COMPLETED

    # Nothing validated -> the data is still being worked on. validation_failed
    # lands here too: it is free to fix and retry, and that IS data verification.
    if stage != STAGE_VALIDATED and stage not in (
        STAGE_SIGNED, STAGE_SUBMISSION_FAILED, STAGE_SIGNING_FAILED
    ):
        return DATA_VERIFICATION

    if case.get("client_approved") is False:
        return CLIENT_REJECTED
    if not case.get("verification_sent_at"):
        return CLIENT_VERIFICATION
    if case.get("client_approved") is None:
        return AWAITING_CLIENT

    # Approved. Which side of the signature are we on?
    if stage == STAGE_SIGNED or stage == STAGE_SUBMISSION_FAILED:
        return SUBMISSION
    return SIGNING


def derive(case: dict, filing: dict | None) -> dict:
    """The workflow badge for one case.

    `case`   a nar1_cases row (plus days_to_anniversary when the caller has it)
    `filing` the case's current tpsi_filings row, or None before one exists
    """
    code = _code(case, filing)
    days = case.get("days_to_anniversary")
    return {
        "code": code,
        "label": WORKFLOW_LABELS[code],
        # e-Drive is terminal for TPSI and finished in CR's Web Guided Wizard,
        # so the case is complete but not by us. The UI has no badge for it
        # (Levi, 2026-08-02: e-Drive is not offered), hence a flag, not a code.
        "off_portal": (filing or {}).get("stage") == STAGE_EDRIVE,
        # An independent overlay, never a stage: a case can be overdue at any
        # step. Meaningless once filed -- whether it was filed LATE is a
        # different question this badge does not answer.
        "overdue": (
            code != COMPLETED
            and days is not None
            and days < -FILING_WINDOW_DAYS
        ),
    }
