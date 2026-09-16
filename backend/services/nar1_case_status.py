"""The WORKFLOW status — where the case is in GSHK's process.

Deliberately NOT the FORM status (services/tpsi/filings.py), which answers where
the document is in CR's process. The v11 header shows both, side by side; merging
them loses information in both directions.

D-6, the single-writer split: TPSI owns every CR fact (tpsi_filings.stage),
nar1_cases owns every client fact (verification_sent_at, client_approved) and
every off-portal fact (manual_receipt). This module WRITES NOTHING -- it is a
pure function of those two records, so the badge cannot drift out of step with
the facts underneath it, and there is no third place for them to disagree.

`COMPLETED` IS GONE (Levi 2026-09-16: "completed should not be there.. it should
be the steps throughout the workflow plus the final CR statuses"). It said
nothing CR had agreed to: a case went green the instant `submitFormNar1`
returned a receipt, while CR had only RECEIVED the return and could still refuse
it. In its place are the five CR codes from services/tpsi/doc_status, which are
what the register actually says -- starting at `cr_not_checked`, which is the
honest answer for a filed return nobody has asked CR about yet.

Removed, not aliased. A code no row can carry but that every filter, count and
test still offers is worse than one that is gone: it renders an always-zero tab
on the dashboard and invites the next writer to set it.

The first six codes are the six badges wireframe_v11 renders for the stages
(bw-data, bw-verify, bw-awaiting, bw-rejected, bw-sign, bw-submit). CLOSED was
added after v11: a case the client abandoned finishes somewhere, and "Completed"
was the one thing it must never be called -- which is now moot, since nothing is
called that any more.
"""
from services.tpsi.doc_status import (
    CR_STATUS_CODES,
    CR_STATUS_LABELS,
    NOT_CHECKED as CR_NOT_CHECKED,
)  # noqa: F401 -- CR_NOT_CHECKED is re-exported for callers of this module
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

#: The client no longer wants the return filed. TERMINAL AND PERMANENT: there is
#: no route back out of it, by design (Levi 2026-09-05).
#:
#: A separate code rather than a flag on top of the badge the case happened to
#: be wearing. "Awaiting Client" on an abandoned case is a queue entry somebody
#: chases; a filed-and-registered badge is a claim that a statutory return is on
#: the register. Neither is true, and the dashboard has to be able to filter
#: these out of the work.
CLOSED = "closed"

#: The stages, then the CR codes, then closed. Order is the order the dashboard
#: filter offers them in, which is the order a case moves through them.
GSHK_STATUSES = (
    DATA_VERIFICATION, CLIENT_VERIFICATION, AWAITING_CLIENT, CLIENT_REJECTED,
    SIGNING, SUBMISSION,
)

WORKFLOW_STATUSES = GSHK_STATUSES + CR_STATUS_CODES + (CLOSED,)

WORKFLOW_LABELS = {
    DATA_VERIFICATION: "Data Verification",
    CLIENT_VERIFICATION: "Client Verification",
    AWAITING_CLIENT: "Awaiting Client",
    CLIENT_REJECTED: "Client Rejected",
    SIGNING: "Signing",
    SUBMISSION: "Submission",
    **CR_STATUS_LABELS,
    CLOSED: "Closed",
}

#: Filing stages that mean the document is finished at CR.
_FINISHED = (STAGE_SUBMITTED, STAGE_REGISTERED, STAGE_EDRIVE)

#: 42 days after the anniversary the statutory filing window closes. Negative
#: days_to_anniversary counts UP from a passed anniversary (migration 019, floor
#: removed by 033), so anything below this is out of time.
FILING_WINDOW_DAYS = 42


#: The badges that mean nobody is waiting on GSHK to FILE anything. Used by the
#: overdue overlay below, and by the dashboard, which must not put them in a
#: queue for a filing that has already gone.
#:
#: EVERY CR code is here, `cr_rejected` included. The overlay answers "somebody
#: still has to file this before the window shuts", and on a rejected return
#: that is a statement about a deadline which has already been missed in a
#: different way -- the red badge is the alarm, and stacking an overdue marker
#: on top of it says the same thing twice while implying the filing never
#: happened. (The dashboard does treat `cr_rejected` as Action Required; that is
#: a separate judgement about whose move it is, made in DashboardPage.jsx.)
TERMINAL_STATUSES = CR_STATUS_CODES + (CLOSED,)


def _code(case: dict, filing: dict | None) -> str:
    stage = (filing or {}).get("stage")

    # CLOSED WINS OVER EVERYTHING, including a filed return.
    #
    # `POST /cases/{id}/close` refuses a case CR already holds, so the portal
    # cannot produce a row that is both — but a data repair could, and if one
    # ever does, "closed" is the honest answer: somebody deliberately ended
    # this case, and that decision is not something a stage lookup may
    # overrule. Testing it last would let the filing stage speak for a case
    # whose whole point is that it was abandoned.
    if case.get("closed_at"):
        return CLOSED

    # Off-portal completion next: the manual path never calls CR, so its filing
    # is still sitting at 'validated' while the return is genuinely with CR.
    # Testing the stage first would report a filed case as still Signing.
    if case.get("manual_receipt") or stage in _FINISHED:
        return _cr_code(case)

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


def _cr_code(case: dict) -> str:
    """What CR says about a return it has already received.

    The STORED code, never re-derived from `cr_doc_status`: the dashboard sorted,
    filtered and counted on what is stored (migration 043 restates this branch
    in SQL), and re-deriving here would let a case's own screen disagree with
    the listing that opened it.

    Falls back to `cr_not_checked` rather than to anything CR-flavoured. A
    deployment with no poller running has a filed return and no CR answer, and
    that is exactly what `cr_not_checked` says.
    """
    code = case.get("cr_doc_status_code")
    return code if code in CR_STATUS_CODES else CR_NOT_CHECKED


def badge_from_row(row: dict) -> dict:
    """The same badge, for a row that already carries the answer.

    `nar1_case_registry` (migration 024) restates _code() in SQL because the
    dashboard sorts and filters on the badge and PostgREST cannot do either to an
    expression. This is the ONE place that reads those columns back, so the
    listing hands the frontend the identical shape derive() produces -- a case on
    the dashboard and the same case on its detail screen must not differ in the
    key names of their badge, let alone its value.

    It does NOT re-derive. Re-deriving in Python would silently paper over a
    divergence between the two implementations, and tests/test_migration_024.py
    exists precisely to make that divergence loud.
    """
    code = row["workflow_status"]
    return {
        "code": code,
        "label": WORKFLOW_LABELS[code],
        "off_portal": bool(row.get("workflow_off_portal")),
        "overdue": bool(row.get("workflow_overdue")),
        # CR's own words, carried beside the code for the same reason
        # `doc_status.describe` carries them: on `cr_unknown` they are the only
        # informative thing there is, and on a recognised code they are the
        # evidence an operator quotes back to CR.
        "cr_text": row.get("cr_doc_status") or None,
    }


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
        "cr_text": case.get("cr_doc_status") or None,
        # An independent overlay, never a stage: a case can be overdue at any
        # step. Meaningless once filed -- whether it was filed LATE is a
        # different question this badge does not answer.
        #
        # LIVE since migration 033, having been permanently false before it.
        # 019 floored days_to_anniversary at -FILING_WINDOW_DAYS, so `days <
        # -42` could not hold -- verified on DEV at the time, 5,998 rows, range
        # exactly [-42, 322], zero matches. Levi 2026-09-04 asked for the floor
        # to go ("we should not floor the days to anniversary at -42"), 033
        # removed it, and this comparison started meaning what it says.
        #
        # It fires on a case that is not finished more than 42 days after its
        # anniversary. It does NOT say the return was filed late -- that needs
        # a filed date, which DEV holds on 2 of 7,959 rows.
        #
        # A CLOSED case is never overdue. The overlay exists to say "somebody
        # still has to file this"; on a case that will never be filed, it is an
        # alarm about work that was deliberately cancelled -- which is exactly
        # the noise closing a case exists to remove.
        #
        # nar1_case_registry (024, restated by 033, 039 and 043) carries the
        # identical predicate; the two must not diverge.
        "overdue": (
            code not in TERMINAL_STATUSES
            and days is not None
            and days < -FILING_WINDOW_DAYS
        ),
    }
