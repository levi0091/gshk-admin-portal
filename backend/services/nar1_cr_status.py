"""Ask CR what it did with a filed return, and record the answer.

THE ONLY WRITER of `nar1_cases.cr_doc_status*`. The Check-now button and the
scheduled poller both come through `refresh()`, so a hand-check and a cron run
cannot produce two different answers for one case — which is the divergence
`badge_from_row` exists to prevent one step earlier in the same pipeline.

WHY THE COLUMNS ARE ON `nar1_cases` AND NOT ON `tpsi_filings`. D-6 gives CR
facts to `tpsi_filings`, and this is a CR fact — but only for the e-Sign path.
A return signed on paper and filed off-portal has a CR case number (on
`manual_receipt`) and no submitted filing at all: its filing row is still
sitting at `validated`, and writing "CR registered it" onto a row whose own
stage says it was never sent would be a record that contradicts itself. The
case is the thing both paths have, and `manual_receipt` — CR's own receipt —
is already precedent for a CR fact living there.

`tpsi_filings.stage` is still promoted `submitted -> registered` when CR
confirms, because that is exactly what migration 018 defined `registered` to
mean ("CR confirmed the filing via docStatusEnquiry") and it is the e-Sign
filing's own lifecycle.

A REJECTION DOES NOT BECOME `submission_failed`. `submission_failed` means
`submitFormNar1` itself refused and NOTHING WAS CHARGED. A CR rejection after
filing means the opposite: the return was delivered, the fee was taken, and CR
refused it afterwards. Collapsing the two would tell an operator no money moved
when it did.
"""
from __future__ import annotations

from datetime import datetime, timezone

from db.supabase import get_supabase
from services import nar1_cases
from services import audit_events as ev
from services.audit_service import log_event
from services.tpsi import doc_status as ds
from services.tpsi import filings as tpsi_filings
from services.tpsi import reads
from services.tpsi.errors import TpsiValidationError

_TABLE = "nar1_cases"

#: The columns this module owns. Named once so the migration, the view and the
#: tests have one list to agree with.
COLUMNS = (
    "cr_doc_status",
    "cr_doc_status_code",
    "cr_status_checked_at",
    "cr_document_ref_no",
)

#: How CR names an annual return in `documentName`, upper-cased. Used ONLY to
#: disambiguate when one CR case number carries several documents — never to
#: reject a single unambiguous row, because CR's wording here is not specified
#: either and a stricter test would silently stop updating every case.
_NAR1_DOCUMENT_HINTS = ("NAR1", "ANNUAL RETURN")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def receipt_of(case: dict, filing: dict | None) -> dict:
    """The receipt this case is evidenced by, from whichever path produced it.

    Same precedence as `nar1_cases.composite` — the filing's own receipt first,
    then the transcribed off-portal one. The two never coexist on a real case
    (`manual-submit` refuses a case CR already holds), but the order is stated
    rather than left to whichever happens to be non-empty.
    """
    return (filing or {}).get("receipt") or case.get("manual_receipt") or {}


def cr_case_number(case: dict, filing: dict | None) -> str | None:
    """CR's own case number for this return, or None.

    NOT the portal's NAR-2026-… — see `nar1_cases.RECEIPT_DERIVED`, where
    exactly that confusion shipped for a few hours. This is the number CR prints
    on its receipt and the only key `docStatusEnquiry` will match on.
    """
    value = str(receipt_of(case, filing).get("caseNo") or "").strip()
    return value or None


def is_filed(case: dict, filing: dict | None) -> bool:
    """Has CR received this return, by either route?

    The off-portal test comes FIRST for the same reason `nar1_case_status._code`
    orders it that way: a manually filed case's filing row is still at
    `validated`, so reading the stage alone would report a finished case as
    unfiled.
    """
    if case.get("manual_receipt"):
        return True
    return (filing or {}).get("stage") in nar1_cases.CR_FILED_STAGES


def current_code(case: dict) -> str:
    """The stored CR code, or NOT_CHECKED. Never re-derived from the raw text —
    the dashboard filtered and counted on what is stored."""
    code = case.get("cr_doc_status_code")
    return code if code in ds.CR_STATUS_CODES else ds.NOT_CHECKED


def due_for_check(case: dict, filing: dict | None = None) -> str | None:
    """Why this case must NOT be polled, or None.

    Levi 2026-09-16: "we should only check for things after submission and not
    yet confirmed or rejected with CR". Returned as text rather than a boolean
    so a run's report says WHICH exclusion applied — "skipped 41" tells an
    operator nothing they can act on.
    """
    if case.get("closed_at"):
        # Unreachable through the portal (close refuses a filed case) but a
        # repair could write one, and spending a CR authentication on a case
        # nobody is waiting for is the noise closing exists to remove.
        return "the case is closed"
    if not is_filed(case, filing):
        return "the return has not been filed with CR"
    code = current_code(case)
    if code in ds.TERMINAL_CODES:
        return f"CR has already finished with it ({ds.CR_STATUS_LABELS[code]})"
    if not cr_case_number(case, filing):
        return "no CR case number is recorded for this case"
    return None


def pick_document(rows: list[dict], known_ref: str | None) -> tuple[dict | None, str | None]:
    """Which of CR's rows is THIS return. Returns (row, refusal).

    CR answers a case-number enquiry with every document in that case. For a
    NAR1 that is one row in practice — but "in practice" is not a basis for
    writing a statutory status, so an ambiguous answer refuses rather than
    picks. Attributing another form's rejection to this NAR1 would be a wrong
    red badge on a return that is perfectly fine.

    AN EMPTY LIST MEANS CR KNOWS THE CASE AND HAS LISTED NOTHING ON IT — it does
    NOT mean the case number is wrong, and the old wording ("CR returned no
    documents for this case number") read as though it did. Measured against
    both CR environments on 2026-09-17: a case number CR does not hold comes back
    as a FAULT (`Case no does not exist.` — verified with `999999999` and `wddw`
    on production and on test), never as an empty list. So if we are here with no
    rows, CR matched the key and simply has nothing listed against it yet. Two
    real PROD returns filed at 16:21 and 17:29 HK were still unlisted at 00:31
    the same night, by case number, by document reference AND by BR number over
    a twelve-month window.
    """
    if not rows:
        return None, ("CR holds this case but has not yet listed any document "
                      "against it — the case number is not in question. A "
                      "return filed today is normally listed later; the next "
                      "check will pick it up")

    if known_ref:
        for row in rows:
            if (row.get("documentRefNo") or "").strip() == known_ref:
                return row, None

    if len(rows) == 1:
        return rows[0], None

    named = [
        row for row in rows
        if any(h in (row.get("documentName") or "").upper()
               for h in _NAR1_DOCUMENT_HINTS)
    ]
    if len(named) == 1:
        return named[0], None

    return None, (
        f"CR returned {len(rows)} documents for this case number and none "
        f"could be identified as this annual return"
    )


def _fault_text(exc: TpsiValidationError) -> str:
    """CR's fault messages, without the empty code prefix `str(exc)` produces.

    `_FaultError.__str__` renders "code: message" pairs, and CR sends this
    particular fault with an EMPTY code — so the default is ": Case no does not
    exist.", a leading colon in the middle of a sentence on screen.
    """
    messages = [m.strip() for _, m in (exc.faults or []) if (m or "").strip()]
    return " ".join(messages) or str(exc).strip(": ") or "no reason given"


def _store(case_id: str, patch: dict) -> None:
    get_supabase().table(_TABLE).update(patch).eq("id", case_id).execute()


def refresh(client, case: dict, filing: dict | None = None) -> dict:
    """Ask CR about one case and record what it said. Returns a report.

    NEVER RAISES for a case that simply cannot be asked — those come back with
    `skipped` set, because a poller walking 400 cases must not stop at the first
    one with no receipt. A TRANSPORT failure does raise: the caller decides
    whether that ends the run (it does not — see jobs/poll_cr_status).
    """
    report = {
        "case_id": case.get("id"),
        "case_no": case.get("case_no"),
        "checked": False,
        "skipped": None,
        "previous": current_code(case),
        "code": current_code(case),
        "cr_text": case.get("cr_doc_status"),
        "changed": False,
        "document_ref_no": case.get("cr_document_ref_no"),
        "checked_at": case.get("cr_status_checked_at"),
        # CR'S OWN case number, carried in the report because `record()` cannot
        # recover it: on the e-Sign path it lives on the FILING's receipt, and
        # an audit row that fell back to the portal's NAR-2026-… under a key
        # called `cr_case_no` would be the identifier confusion
        # `nar1_cases.RECEIPT_DERIVED` already shipped once.
        "cr_case_no": cr_case_number(case, filing),
        "stage_promoted": False,
    }

    reason = due_for_check(case, filing)
    if reason:
        report["skipped"] = reason
        return report

    try:
        rows = reads.case_status(client, case_no=report["cr_case_no"])
    except TpsiValidationError as exc:
        # "CR COULD NOT IDENTIFY THIS CASE" IS A SKIP, NOT A FAILURE, and this
        # is the commonest real one: CR answers a case number it does not hold
        # with the fault `Case no does not exist.` — seen live on 2026-09-16
        # against a manual receipt whose caseNo had been typed as test data.
        #
        # Every validation fault on this call means the same thing, which is why
        # the whole class is caught rather than its wording matched.
        # `docStatusEnquiry` submits no return for CR to check: the only thing
        # it can find fault with is the criteria we sent. So nothing can be
        # written from it, the previous answer — including "never checked" — is
        # still the truthful one, and the rest of the book must not be abandoned
        # over one bad case number.
        #
        # CR'S OWN WORDS ARE CARRIED, because the fix is in the number somebody
        # typed on the Confirmation stage and "CR refused" would send them
        # looking at the company profile instead.
        # A PLAIN HYPHEN, NOT AN EM DASH. This sentence is printed by the cron
        # job as well as shown on screen, and `main()` is run by hand from
        # PowerShell, whose console is cp1252 — an em dash arrives there as a
        # replacement character in the middle of the one line that is supposed
        # to tell somebody what to fix.
        # Recorded as a check for the same reason the empty answer below is: we
        # asked, and CR answered. A case number CR will never hold must not sit
        # at the head of every run's queue for the rest of its life.
        checked_at = _now()
        _store(case["id"], {"cr_status_checked_at": checked_at})
        report["checked_at"] = checked_at
        report["skipped"] = (
            f"CR does not recognise the case number {report['cr_case_no']!r} - "
            f"CR says: {_fault_text(exc)}"
        )
        return report

    row, refusal = pick_document(rows, case.get("cr_document_ref_no"))
    if refusal:
        # NOT an error and NOT a status. No status is written: the previous
        # answer — including "never checked" — is still the truthful one, and
        # overwriting it with a guess is the failure this branch exists for.
        #
        # BUT THE CHECK ITSELF IS RECORDED, because it happened. CR was asked
        # and CR answered; only the answer was "nothing listed". Leaving
        # `cr_status_checked_at` NULL here was wrong in three ways at once, all
        # of them visible on PROD on 2026-09-17 after some twenty real checks:
        #
        #   * the CR Status stage still read "Not yet checked with CR", which
        #     is a false statement about work the portal had genuinely done;
        #   * `jobs.poll_cr_status` orders by `cr_status_checked_at NULLS
        #     FIRST`, so a case CR has nothing to say about sorts to the front
        #     of every run FOREVER — at two cases that is invisible, at a full
        #     book it starves the cases that would have moved;
        #   * an operator had no way to tell "nobody has asked" from "we ask
        #     every fifteen minutes and CR has not listed it yet".
        #
        # `updated_at` is deliberately NOT touched — see the note below. Nothing
        # about the case changed; only the time we last asked.
        checked_at = _now()
        _store(case["id"], {"cr_status_checked_at": checked_at})
        report["skipped"] = refusal
        report["checked_at"] = checked_at
        return report

    raw = (row.get("documentStatus") or "").strip() or None
    code = ds.normalise(raw)
    ref = (row.get("documentRefNo") or "").strip() or None
    checked_at = _now()
    changed = code != report["previous"]

    patch = {
        "cr_doc_status": raw,
        "cr_doc_status_code": code,
        "cr_status_checked_at": checked_at,
    }
    # `updated_at` ONLY WHEN CR'S ANSWER ACTUALLY MOVED. The dashboard's Last
    # Updated column is sortable and is how an operator finds the case that
    # changed; a heartbeat that touched it would reset every filed case in the
    # book to "just now" every 15 minutes and make the column say nothing. When
    # it was last CHECKED is its own column (`cr_status_checked_at`), which is
    # what the CR Status stage shows.
    if changed:
        patch["updated_at"] = checked_at
    if ref:
        # Only ever WIDENED, never cleared: CR omitting the reference on one
        # reply must not throw away the exact key that makes the next enquiry
        # unambiguous.
        patch["cr_document_ref_no"] = ref
    _store(case["id"], patch)

    report.update({
        "checked": True,
        "code": code,
        "cr_text": raw,
        "changed": changed,
        "document_ref_no": ref or report["document_ref_no"],
        # Returned rather than re-read: a green badge from three weeks ago and
        # one from this morning are not the same claim, and the screen shows
        # which — asking Supabase again for a value we just wrote is a round
        # trip for a string we are already holding.
        "checked_at": checked_at,
    })

    # The FORM badge follows CR too, but only on the path that has a submitted
    # filing to promote. `registered` is what migration 018 defined for exactly
    # this moment.
    if (code == ds.REGISTERED and filing
            and filing.get("stage") == tpsi_filings.STAGE_SUBMITTED):
        tpsi_filings.mark_registered(filing["id"])
        report["stage_promoted"] = True

    return report


async def record(report: dict, case: dict, *, user_id, user_display_name,
                 heartbeat: bool = True) -> None:
    """Put the check in the trail.

    TWO CODES, and the split is deliberate. `NAR1_CR_STATUS_CHANGED` fires ONLY
    on a move, so the question an operator actually asks — when did CR register
    this — is answerable by filtering to one code rather than by reading a month
    of heartbeats. `TPSI_DOC_STATUS_CHECKED` says the check happened at all.

    `heartbeat=False` SUPPRESSES ONLY THE LATTER, and only the poller passes it.
    Since 2026-09-16 the schedule is every 15 minutes rather than nightly, and a
    per-case heartbeat 96 times a day would write more rows a year than the
    whole Viewpoint import — so the job writes ONE summary row per run instead
    (`jobs.poll_cr_status.record_run`) and the evidence that it is alive is kept
    without burying the case's own trail. A check an OPERATOR asked for keeps
    its per-case row: somebody did that to that case, which is the kind of thing
    an audit trail is for.
    """
    if not report.get("checked"):
        return

    # audit_log.case_id holds the ENTITY id — routers/cases.py::_audit_target.
    common = dict(
        case_id=case.get("entity_id"),
        entity_type="nar1_case",
        entity_id=case["id"],
        user_id=user_id,
        user_display_name=user_display_name,
    )

    if heartbeat:
        await log_event(
            action_type=ev.TPSI_DOC_STATUS_CHECKED,
            event_code=ev.TPSI_DOC_STATUS_CHECKED,
            metadata={
                # TWO DIFFERENT NUMBERS, never interchangeable: `case_no` is
                # the portal's NAR-2026-…, `cr_case_no` is what CR prints on
                # its own receipt and the only key docStatusEnquiry matches on.
                "case_no": case.get("case_no"),
                "cr_case_no": report.get("cr_case_no"),
                # CR's own words, not our code: the trail should be readable
                # against what CR's own screen says.
                "document_status": report.get("cr_text"),
                "document_ref_no": report.get("document_ref_no"),
                "code": report.get("code"),
            },
            **common,
        )

    if report.get("changed"):
        await log_event(
            action_type=ev.NAR1_CR_STATUS_CHANGED,
            event_code=ev.NAR1_CR_STATUS_CHANGED,
            old_value=report.get("previous"),
            new_value=report.get("code"),
            before_state={"cr_doc_status_code": report.get("previous")},
            after_state={
                "cr_doc_status_code": report.get("code"),
                "cr_doc_status": report.get("cr_text"),
            },
            metadata={
                "case_no": case.get("case_no"),
                "document_status": report.get("cr_text"),
                "stage_promoted": bool(report.get("stage_promoted")),
            },
            **common,
        )
