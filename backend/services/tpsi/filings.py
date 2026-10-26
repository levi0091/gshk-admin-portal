"""The filing ledger: per-attempt chain state for a TPSI submission.

Why this exists at all: CR's order is validate -> sign -> submit, and each step
consumes the previous step's CR-signed payload. Holding that chain server-side
is what makes the submit gate real — a client cannot assert "already validated"
and skip straight to the chargeable call.
"""
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from db.supabase import get_supabase
from services.tpsi import client as tpsi_client
from services.tpsi.config import FORM_FEES
from services.tpsi.errors import TpsiError
from services.tpsi.soap import extract_submission, parse_response, text_of

_TABLE = "tpsi_filings"

# The FORM status vocabulary (migration 018). Distinct from the WORKFLOW status,
# which lives on nar1_cases and answers a different question: this says where the
# document is in CR's process, not where the case is in GSHK's.
#
# Failure is split per step on purpose. "validation_failed" means fix the data
# and retry for free; "submission_failed" means CR rejected a chargeable call.
# Collapsing both into one `failed`, as the original vocabulary did, loses the
# only distinction that changes what the user should do next.
STAGE_DRAFT = "draft"
STAGE_VALIDATED = "validated"
STAGE_VALIDATION_FAILED = "validation_failed"
STAGE_SIGNED = "signed"
STAGE_SIGNING_FAILED = "signing_failed"
STAGE_SUBMITTED = "submitted"
STAGE_SUBMISSION_FAILED = "submission_failed"
STAGE_REGISTERED = "registered"
STAGE_SUPERSEDED = "superseded"
STAGE_EDRIVE = "edrive"

# THE TWO STAGES THE 2026-10-26 INCIDENT WAS MISSING (migration 056).
#
# `submitting` is a CLAIM: exactly one request has won the right to call
# submitForm for this row, and the call is in flight. `submission_unknown` is
# what a submit becomes when it ended without CR telling us what happened — a
# timeout, a dropped connection, a 5xx with no fault in it, a reply that is not
# a receipt. CR may well have lodged that return and charged for it: on PROD,
# 16 of 160 submits timed out at 60 s and CR filed most of them anyway. Before
# these existed every one of those was stored as `submission_failed`, which the
# validate -> sign -> submit chain accepts, and operators re-filed the same
# annual return two and three times.
STAGE_SUBMITTING = "submitting"
STAGE_SUBMISSION_UNKNOWN = "submission_unknown"

#: The eleven the UI reports, in lifecycle order. `edrive` is a valid stored value
#: (upload_edrive() still works) but is not offered in the UI, so it is not here.
FORM_STATUSES = (
    STAGE_DRAFT,
    STAGE_VALIDATED,
    STAGE_VALIDATION_FAILED,
    STAGE_SIGNED,
    STAGE_SIGNING_FAILED,
    STAGE_SUBMITTING,
    STAGE_SUBMITTED,
    STAGE_SUBMISSION_FAILED,
    STAGE_SUBMISSION_UNKNOWN,
    STAGE_REGISTERED,
    STAGE_SUPERSEDED,
)

#: Human labels for the form status. The UI shows these beside — never merged
#: with — the workflow status.
FORM_STATUS_LABELS = {
    STAGE_DRAFT: "Not yet sent to CR",
    STAGE_VALIDATED: "Validated by CR",
    STAGE_VALIDATION_FAILED: "Rejected at validation",
    STAGE_SIGNED: "Signed",
    STAGE_SIGNING_FAILED: "Rejected at signing",
    STAGE_SUBMITTED: "Filed with CR",
    STAGE_SUBMITTING: "Filing with CR…",
    STAGE_SUBMISSION_FAILED: "Rejected at submission",
    STAGE_SUBMISSION_UNKNOWN: "Outcome unknown — check CR",
    STAGE_REGISTERED: "Registered by CR",
    STAGE_SUPERSEDED: "Superseded by a later attempt",
    STAGE_EDRIVE: "Sent to CR e-Drive",
}

#: Stages a filing can never move on from.
TERMINAL_STAGES = (STAGE_SUBMITTED, STAGE_REGISTERED, STAGE_EDRIVE, STAGE_SUPERSEDED)

#: Stages in which CR HAS, OR MAY HAVE, this return. Nothing may re-validate,
#: re-sign, supersede or submit a filing in one of these, and while one exists
#: on a case nothing may prepare, validate, sign or submit ANOTHER filing on
#: that case either.
#:
#: Deliberately NOT folded into TERMINAL_STAGES. `submission_unknown` is not
#: terminal — an operator resolves it, to `submitted` or back to
#: `submission_failed`, once they have looked at CR — and `superseded` is
#: terminal without CR holding anything. TERMINAL_STAGES also feeds the form
#: badge's `terminal` flag and the return-year lock, which mean other things.
LOCKED_STAGES = (
    STAGE_SUBMITTING, STAGE_SUBMISSION_UNKNOWN,
    STAGE_SUBMITTED, STAGE_REGISTERED, STAGE_EDRIVE,
)

#: What `supersede` and `supersede_all_for_case` may never touch: the finished
#: stages and the ones CR may hold. Retiring a `submission_unknown` row would
#: hide a return CR may have lodged and charged for behind a fresh draft.
UNRETIRABLE_STAGES = tuple(dict.fromkeys(TERMINAL_STAGES + LOCKED_STAGES))

#: How long after the claim the background call may still START (thread-pool
#: queueing on a busy worker). `finish_submit` sends nothing once a claim is
#: older than this: a call that begins late could outlast `STALE_CLAIM_SECONDS`.
MAX_START_DELAY_SECONDS = 30

#: Slack on top of the arithmetic below.
_STALE_MARGIN_SECONDS = 30

#: How long a `submitting` claim may stand before it is read as an unknown
#: outcome -- DERIVED, not chosen. It is the longest the call can legitimately
#: take: starting late, authenticating if the client has no token (connect +
#: read), then the one submitForm post (connect + read), plus slack. There is
#: no second post -- a 401 on submitForm is not retried (client.post_form) -- so
#: the sum is a ceiling, and `tests/tpsi/test_submit_review_round1.py` fails if
#: a client timeout is raised past it.
#:
#: It used to be a literal 240, with a comment that a claim older than it "has
#: outlived any request that could still answer it". It had not: a 401 re-post
#: alone could run the call past 500 s, and a receipt that landed after the
#: sweep and a "not lodged" declaration was dropped while the retry path
#: reached CR a second time (code review 01, B1). Migration 056's view repeats
#: the number and a test keeps the two equal.
STALE_CLAIM_SECONDS = int(
    MAX_START_DELAY_SECONDS + tpsi_client.SUBMIT_WORST_CASE_SECONDS
    + _STALE_MARGIN_SECONDS)

#: A failure at any step. Kept as a tuple so callers test membership rather than
#: string-matching a suffix.
FAILURE_STAGES = (
    STAGE_VALIDATION_FAILED, STAGE_SIGNING_FAILED, STAGE_SUBMISSION_FAILED,
)


def form_status(row: dict) -> dict:
    """The FORM status — where the document is in CR's process.

    Deliberately NOT merged with the case's workflow status, which answers a
    different question (where the case is in GSHK's process) and lives on
    nar1_cases. The UI reports the two side by side; collapsing them into one
    badge loses information in both directions.
    """
    stage = row["stage"]
    error = row.get("cr_error") or {}
    status = {
        "code": stage,
        "label": FORM_STATUS_LABELS.get(stage, stage),
        "failed": stage in FAILURE_STAGES,
        "terminal": stage in TERMINAL_STAGES,
        # CR has, or may have, this return, so nothing may touch it again. The
        # screen withholds every chain control on this flag rather than keeping
        # its own copy of the list.
        "locked": stage in LOCKED_STAGES,
        # Present only on a failure, and it is the whole fault list: CR returns
        # every problem at once so one pass can fix them all.
        "faults": error.get("faults") or [],
    }
    if stage in FAILURE_STAGES:
        # A failure with NO fault list -- a refused token, a declared "not
        # lodged" -- used to leave the screen with a red badge and nothing to
        # say. `message` is what was recorded and `kind` says which sort it is
        # ("auth", "declared_not_lodged"); both only on a failure (code review
        # 01, S-7).
        status["message"] = error.get("message")
        status["kind"] = error.get("kind")
    return status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _insert(payload: dict) -> dict:
    return get_supabase().table(_TABLE).insert(payload).execute().data[0]


def _update(filing_id: str, payload: dict) -> None:
    get_supabase().table(_TABLE).update(payload).eq("id", filing_id).execute()


def get_filing(filing_id: str) -> dict:
    rows = get_supabase().table(_TABLE).select("*").eq("id", filing_id).execute().data
    if not rows:
        raise LookupError(f"no TPSI filing {filing_id}")
    return rows[0]


def supersede(filing_id: str) -> bool:
    """Retire an attempt CR has not filed. Returns whether a row moved.

    THE STAGE NOTHING EVER WROTE. `STAGE_SUPERSEDED` has existed since this
    module was written and `current_filing()` has always excluded it, but no
    caller ever set it — which is the defect migration 024's docstring records,
    and the reason `Restart verification` promised to discard the CR-signed
    snapshot and then left it in place. An operator who corrected the company
    details and restarted would re-send the client, and file, CR's OLD signed
    XML: the exact "show one document, file another" failure the verification
    gate exists to prevent.

    Conditional on the stage IN THE UPDATE, not read-then-written: a submit
    landing between a read and a write would otherwise be retired here, and the
    case would show no filing while CR held a registered return. The filter
    below can only ever match a row that is still un-filed at the moment
    Postgres applies it.
    """
    rows = (
        get_supabase().table(_TABLE)
        .update({"stage": STAGE_SUPERSEDED})
        .eq("id", filing_id)
        .not_.in_("stage", list(UNRETIRABLE_STAGES))
        .execute()
        .data
    )
    return bool(rows)


def mark_registered(filing_id: str) -> bool:
    """CR confirmed the filing is on the register. Returns whether a row moved.

    THE SECOND STAGE NOTHING EVER WROTE. `STAGE_REGISTERED` has been in the
    vocabulary since migration 018, whose own docstring defines it as "CR
    confirmed the filing via docStatusEnquiry" — and until `nar1_cr_status`
    there was nothing doing the enquiring. `StageConfirmation` carried a comment
    saying so, and the Confirmation step sat permanently at IN PROGRESS because
    `stageDone(5)` waited on a value no code path could produce.

    Conditional on `stage = 'submitted'` INSIDE the update, not
    read-then-written, and for a sharper reason than `supersede`'s: this runs
    from a nightly job walking hundreds of cases, so the window between a read
    and a write is as long as the rest of the run. The only row this can ever
    move is one that is still `submitted` at the instant Postgres applies it.

    Never `edrive` and never a manual filing: e-Drive is finished in CR's own
    wizard and an off-portal filing has no submitted row at all. Both carry
    their CR status on the CASE (`nar1_cases.cr_doc_status_code`), which is why
    this promotion is a nicety for the FORM badge rather than the fact anything
    depends on.
    """
    rows = (
        get_supabase().table(_TABLE)
        .update({"stage": STAGE_REGISTERED})
        .eq("id", filing_id)
        .eq("stage", STAGE_SUBMITTED)
        .execute()
        .data
    )
    return bool(rows)


def supersede_all_for_case(nar1_case_id: str) -> int:
    """Retire EVERY un-filed attempt on one case. Returns how many moved.

    `supersede()` takes one filing id, and every existing caller feeds it
    `current_filing()` — the NEWEST non-superseded row. That is the right answer
    for a restart, which opens a replacement. It is the wrong answer for closing
    a case: nothing stops a second draft existing alongside the live one (see
    `nar1_cases.blocking_filing`, which exists because of exactly that), and
    retiring only the newest would leave the other live on a case that has
    ended.

    Conditional on the stage inside the UPDATE, like `supersede()`: a submit
    landing mid-flight cannot be un-filed here.
    """
    rows = (
        get_supabase().table(_TABLE)
        .update({"stage": STAGE_SUPERSEDED})
        .eq("nar1_case_id", nar1_case_id)
        .not_.in_("stage", list(UNRETIRABLE_STAGES))
        .execute()
        .data
    )
    return len(rows or [])


#: Stages whose XML may still be rebuilt from the live company record.
#:
#: Deliberately excludes STAGE_VALIDATED and everything after it. From
#: `validated` onward the case reads its own frozen snapshot -- the PDF the
#: client approves, the signature and the filing are all built from it -- and
#: rewriting it under them is the "show one document, file another" failure the
#: verification gate exists to prevent. `Restart verification` is the sanctioned
#: way to discard a snapshot, and it supersedes the row rather than editing it.
REBUILDABLE_STAGES = (STAGE_DRAFT, STAGE_VALIDATION_FAILED)


def rebuild_draft(filing_id: str, form_xml: str) -> dict | None:
    """Point an un-validated filing at freshly built XML. Returns the refreshed row, or None.

    THE CORRECTION THAT NEVER REACHED CR. `validate()` re-sends
    `filing["request_xml"]` verbatim, and the workflow screen re-validates the
    filing the case already has. So an operator who fixed an address, or chose a
    different signing capacity, and pressed Validate again sent CR the *same
    bytes* -- and read CR's identical answer as "my correction did not work".

    Observed on case NAR-2026-0065: the case carried
    `signatory_capacity='Company Secretary'` while its stored request_xml still
    declared `selectCapacityDesc` 'Director' from the first prepare.

    Conditional on the stage IN THE UPDATE, not read-then-written: a validate
    landing between a read and a write would otherwise have the snapshot it just
    froze discarded by a rebuild that read the row while it was still a draft.

    `cr_error` is cleared with the XML it belongs to. Leaving it would render a
    stale refusal beside a form CR has not been shown yet.

    The UPDATE already returns the row it changed, so the caller gets the fresh
    filing without a second round trip -- and cannot be handed a row that a
    concurrent validate moved out from under the guard.
    """
    rows = (
        get_supabase().table(_TABLE)
        .update(
            {
                "request_xml": form_xml,
                "stage": STAGE_DRAFT,
                "cr_error": None,
                "validated_xml": None,
                "validated_at": None,
            }
        )
        .eq("id", filing_id)
        .in_("stage", list(REBUILDABLE_STAGES))
        .execute()
        .data
    )
    return rows[0] if rows else None


def create_filing(
    *,
    entity_id: str,
    form_code: str,
    form_xml: str,
    user_id: str,
    nar1_case_id: str | None = None,
    form_filing_id: str | None = None,
) -> dict:
    """Open a filing attempt. Rejects an unknown form code before any CR call.

    A NAR1 MUST BELONG TO A CASE (code review 01, S-5). Both locks -- the
    application's and migration 056's index -- are keyed on `nar1_case_id`, so a
    case-less NAR1 sits outside them: a second return for the same company and
    year could be validated, signed and submitted through the raw API.
    """
    FORM_FEES[form_code]  # KeyError here beats a 400 from CR later
    if form_code.lower() == "nar1" and not nar1_case_id:
        raise ValueError(
            "a NAR1 filing must belong to a case: opening one without a case "
            "would put it outside the lock that stops one annual return being "
            "filed twice. Open it from the case.")
    return _insert(
        {
            "entity_id": entity_id,
            "form_code": form_code,
            "request_xml": form_xml,
            "presenter_user_id": user_id,
            "nar1_case_id": nar1_case_id,
            "form_filing_id": form_filing_id,
            "stage": STAGE_DRAFT,
        }
    )


def validate(client, filing_id: str) -> dict:
    """validateForm{Code}. No charge, no CR-side effect.

    On success CR returns the form with its own XML signature over it. That
    payload is carried forward VERBATIM — request and response share one
    namespace convention, so no rewriting is needed or wanted.

    Stage guard: refuses signed, and every stage CR has or may have
    (`LOCKED_STAGES`). This is the money invariant. The double-charge guards are
    the conditional claim in `_claim` (`signed -> submitting`, settled inside
    Postgres BEFORE CR is called) and `uq_tpsi_filings_case_locked`
    (migration 056), one locked filing per case. The older
    `uq_tpsi_filings_submitted` (016) is only written after CR has answered, so
    it never stopped a double click reaching CR -- its own comment said so and
    was wrong. Walking a locked row's stage back to 'validated' would let it be
    claimed again, so it must be impossible to reach from here, not just
    unlikely given call order. Re-validating a draft or an already-validated
    filing is legitimate (a user fixing field errors and retrying) and stays
    allowed.
    """
    from services.tpsi.soap import build_submission

    filing = get_filing(filing_id)
    # Before the stage check, so a filing CR may hold is refused by name. The
    # stage check alone let `submission_failed` through, and on 2026-10-26 that
    # was every submit that had merely timed out.
    _refuse_if_locked(filing, "re-validating it")
    if filing["stage"] in (STAGE_SIGNED,) + TERMINAL_STAGES:
        raise ValueError(
            f"filing is already {filing['stage']} and cannot be re-validated"
        )
    submission = build_submission(filing["request_xml"])

    try:
        raw = client.post_form("validateForm", filing["form_code"], submission)
        validated = extract_submission(raw)
    except TpsiError as exc:
        _update(
            filing_id,
            {
                "stage": STAGE_VALIDATION_FAILED,
                "cr_error": {"faults": getattr(exc, "faults", []), "message": str(exc)},
            },
        )
        raise

    _update(
        filing_id,
        {
            "stage": STAGE_VALIDATED,
            "validated_xml": validated,
            "validated_at": _now(),
            "cr_error": None,
        },
    )
    return get_filing(filing_id)


def _extract_eform(submission_xml: str) -> str:
    """The overall signature signs the <EForm> element, not the whole document.

    Sliced as text, prefix discovered from the document: the digest is over
    these exact bytes, so it must not be re-serialised.
    """
    import re as _re

    from services.tpsi.soap import CR_NS

    open_match = _re.search(r"<(\w+:)?EForm[\s>]", submission_xml)
    if not open_match:
        raise TpsiError("no <EForm> in the validated payload")
    prefix = open_match.group(1) or ""
    close = f"</{prefix}EForm>"
    end = submission_xml.find(close)
    if end == -1:
        raise TpsiError("unterminated <EForm> in the validated payload")
    sliced = submission_xml[open_match.start() : end + len(close)]

    # ...but the slice alone is NOT what CR digests. Its reference program does
    #     xml2String(xmlObj.getElementsByTagName('cr:EForm')[0])
    # i.e. XMLSerializer over the parsed subtree, and a serializer re-emits the
    # namespace declaration for every prefix the subtree uses. CR declares
    # xmlns:cr on the RESPONSE element, not on EForm, so the raw slice carries
    # no declaration and hashes to something CR never computes.
    # Injected as text rather than actually re-serialising, because everything
    # else about these bytes must survive untouched.
    if prefix and f"xmlns:{prefix[:-1]}=" not in sliced.split(">", 1)[0]:
        sliced = _re.sub(
            rf"^<{prefix}EForm\b",
            f'<{prefix}EForm xmlns:{prefix[:-1]}="{CR_NS}"',
            sliced,
            count=1,
        )
    return sliced


# ---------------------------------------------------------------------------
# The off-portal (wet-signature) interlock — BE-6
# ---------------------------------------------------------------------------
#
# nar1_cases.manual_conflict() guards the manual path against a live filing, but
# only in one direction. It deliberately allows a manual completion while a
# filing sits at 'validated' (the client changed their mind mid-chain), and
# 'validated' -> 'signed' -> 'submitted' is then free of any check that knows the
# case has already been filed on paper. That is one chargeable, IRREVERSIBLE
# call away from lodging the same statutory return with CR twice.
#
# So the interlock is two-way: every step of the e-Sign chain that puts a form in
# front of CR refuses a case whose return is already filed off-portal. It is read
# from the database on every call rather than cached, and it FAILS CLOSED — if
# the case cannot be read, the chargeable call does not happen.


class SubmitGateError(Exception):
    """A guard on the chargeable, irreversible submit refused.

    Defined here rather than in the Submit section below because
    ManualCompletionInterlock subclasses it and `sign` raises that.
    """


class ManualCompletionInterlock(SubmitGateError):
    """The case behind this filing was already filed off-portal.

    A SubmitGateError so `submit_filing` refuses, audits (TPSI_SUBMISSION_FAILED)
    and 409s it exactly like every other guard on the chargeable call. `sign` and
    `upload_edrive` raise it too and their routes handle it explicitly, so the
    refusal surfaces before the signature rather than at the charge.
    """


class CaseClosedInterlock(SubmitGateError):
    """The case behind this filing was permanently closed.

    A SubmitGateError for the same reason ManualCompletionInterlock is: it makes
    `submit_filing` refuse, audit (TPSI_SUBMISSION_FAILED) and 409 exactly like
    every other guard on the chargeable call, with no new branch. `sign` and
    `upload_edrive` raise it too and their routes handle it explicitly, so the
    refusal surfaces before CR is contacted rather than at the charge.
    """


class DriftDetected(SubmitGateError):
    """The stored return no longer matches the company record (spec §6).

    A SubmitGateError so `submit_filing` refuses, audits TPSI_SUBMISSION_FAILED
    and 409s it like every other guard on the chargeable call — but it carries
    `differences`, because the remedy depends on WHICH field moved and a bare
    "the data differs" leaves the operator to diff a nine-page statutory form
    by eye.
    """

    def __init__(self, differences: list):
        self.differences = differences
        count = len(differences)
        super().__init__(
            f"the validated form no longer matches the company record "
            f"({count} field{'' if count == 1 else 's'} changed since it was "
            f"validated). Restart verification to rebuild and re-validate the "
            f"return."
        )


class BeforeReturnDate(SubmitGateError):
    """The return date has not arrived yet, so there is no return to file.

    A SubmitGateError so `submit_filing` refuses, audits TPSI_SUBMISSION_FAILED
    and 409s it exactly like every other guard on the chargeable call. It
    carries the two dates because the remedy is arithmetic the operator has to
    be able to check: either they are simply early, or the return YEAR on the
    filing is wrong, and only the pair of dates distinguishes those.
    """

    def __init__(self, return_date, today):
        self.return_date = return_date
        self.today = today
        days = (return_date - today).days
        super().__init__(
            f"this company's return date is {return_date.isoformat()}, which is "
            f"{days} day{'' if days == 1 else 's'} away — an annual return "
            f"cannot be delivered before the anniversary it reports on. Nothing "
            f"was sent to CR and nothing was charged. If this looks wrong, check "
            f"the return year on the filing and the incorporation date on the "
            f"company record."
        )


class RecordCheckFailed(SubmitGateError):
    """The drift comparison could not be made, so nothing was filed.

    Split out of the plain SubmitGateError it used to be (Levi 2026-09-03) for
    one reason: it can carry `problems`. When the rebuild failed because the
    COMPANY RECORD is no longer filable, the mapper already knows exactly what
    is wrong with it and which party each fault belongs to — and joining that
    list into the exception message threw the structure away one line before
    the screen needed it.

    `reason` separates the two cases, because they send the operator to
    different places:

      record_unusable — someone edited the company into a state CR would
                        reject. Fixable on the profile, then restart
                        verification.
      check_failed    — the comparison itself broke (the graph would not load,
                        the stored XML would not parse). Restarting cannot fix
                        that, so the screen must not suggest it.
    """

    def __init__(self, message: str, problems: list | None = None,
                 reason: str = "check_failed"):
        self.problems = list(problems or [])
        self.reason = reason
        super().__init__(message)


def _refuse_if_drifted(filing: dict) -> None:
    """Spec §6. Runs before ANY CR call and before any charge.

    A DriftError — the comparison could not be made at all — is deliberately
    NOT swallowed. It becomes a refusal too: this gate sits in front of an
    irreversible chargeable call, and "we could not check" is not a reason to
    proceed. It is raised as a plain SubmitGateError so the message says the
    check failed, rather than sending the operator to restart verification for
    a problem restarting cannot fix.
    """
    from services.tpsi import drift

    # NAR1 ONLY. `submit` is generic over form codes and the comparator rebuilds
    # through `nar1_mapper`; pointing it at an NNC1 would fail to map and refuse
    # a filing it knows nothing about. A form with no rebuilder is not checked —
    # which is the state everything was in before this gate existed, not a
    # regression — and NNC1 has no client-approval snapshot to drift from yet.
    if (filing.get("form_code") or "").lower() != "nar1":
        return

    try:
        differences = drift.differences_for(filing)
    except drift.DriftError as exc:
        # The headline stays a sentence an operator can read on its own; the
        # faults ride alongside it as a LIST rather than spliced into it.
        # `problems` is populated only when the mapper refused the record,
        # which is also the only case where restarting verification is the
        # remedy — hence the two reasons and the two headlines.
        if exc.problems:
            raise RecordCheckFailed(
                f"{exc}, so it was not submitted",
                problems=exc.problems, reason="record_unusable",
            ) from exc
        raise RecordCheckFailed(
            f"the return could not be checked against the company record "
            f"before filing, so it was not submitted: {exc}"
        ) from exc
    if differences:
        raise DriftDetected(differences)


def case_of(filing: dict) -> dict:
    """The nar1_cases row behind this filing, or {}.

    ONE query, read by BOTH interlocks below. It replaced a narrower
    `manual_completion()` when case closure arrived: two functions each doing
    their own SELECT is two round trips on every signature and every submit, and
    — the reason that matters — a second un-patched database reader is exactly
    how a test goes green locally and red in CI, having quietly talked to DEV.

    A filing with no `nar1_case_id` (NNC1, or a bare TPSI filing) has no case at
    all, so there is nothing to read and nothing to refuse.
    """
    case_id = filing.get("nar1_case_id")
    if not case_id:
        return {}
    rows = (
        get_supabase().table("nar1_cases")
        .select("id,case_no,manual_receipt,manual_submitted_at,closed_at,"
                "closed_reason")
        .eq("id", case_id)
        .limit(1)
        .execute()
        .data
    )
    return (rows or [None])[0] or {}


def _refuse_if_case_finished(filing: dict, action: str) -> None:
    """Refuse anything that would put this form in front of CR after the case
    behind it has ended — by a paper filing, or by being closed.

    CLOSURE IS CHECKED FIRST. A closed case is over whatever else is true of it,
    and naming the closure is what tells the operator that no amount of fixing
    the filing will help.

    THE SECOND LOCK, NOT THE ONLY ONE. `POST /cases/{id}/close` supersedes every
    live filing on the way out, so this normally never fires — the stage gates
    refuse first. It exists because that cleanup is best-effort and is allowed
    to fail (the case is closed the instant its UPDATE lands, and a 500 there
    would report a failed close over a case that is genuinely shut). A signed
    filing left live on a closed case is one chargeable, irreversible call from
    lodging a return the client cancelled, which is not a state to leave
    guarded by a button.
    """
    case = case_of(filing)

    if case.get("closed_at"):
        raise CaseClosedInterlock(
            f"case {case.get('case_no') or case.get('id')} was closed and is "
            f"not proceeding — {action} would lodge an annual return the "
            "client cancelled, and charge the deposit account for it. Closing "
            "cannot be undone; open a new case if the return is going ahead "
            "after all."
        )

    if case.get("manual_receipt"):
        raise ManualCompletionInterlock(
            f"case {case.get('case_no') or case.get('id')} was already filed "
            f"off-portal (wet signature, receipt recorded "
            f"{case.get('manual_submitted_at') or 'earlier'}) — {action} would "
            "lodge the same annual return with CR a second time and charge the "
            "deposit account for it"
        )


class FilingLocked(SubmitGateError):
    """CR has, or may have, this return — through this filing or another one
    on the same case — so nothing may put it in front of CR again.

    A SubmitGateError so `submit_filing` refuses, audits and 409s it like every
    other guard on the chargeable call. `filing` is the row holding the lock,
    which is not always the one the request named: the case-level lock exists
    because a second filing on the same case would put a second copy of the
    same annual return in front of CR just as surely as re-submitting the first.
    """

    def __init__(self, filing: dict, action: str, *, own: bool):
        self.filing = filing
        self.own = own
        stage = filing.get("stage")
        label = FORM_STATUS_LABELS.get(stage, stage)
        which = "this filing" if own else "another filing on this case"
        if stage == STAGE_SUBMITTING:
            remedy = ("It is being filed with CR right now. Wait for that to "
                      "finish; the case updates when CR answers.")
        elif stage == STAGE_SUBMISSION_UNKNOWN:
            remedy = ("CR may have filed it and charged the deposit account. "
                      "Check CR e-Services (Document Submission > Enquire "
                      "Submitted Documents) and record what CR shows before "
                      "anything else.")
        else:
            remedy = "CR already holds this return."
        super().__init__(
            f"{which} is '{label}', so {action} is refused — it would put a "
            f"second copy of this annual return in front of CR. {remedy}"
        )

    def detail(self) -> dict:
        """The 409 body every route answers with, so the three routes that
        refuse a locked filing cannot word it three ways (code review 01, N-1)."""
        return {"message": str(self), "reason": "filing_locked",
                "stage": (self.filing or {}).get("stage")}


def locked_filing_on_case(nar1_case_id: str | None,
                          exclude_id: str | None = None) -> dict | None:
    """A filing on this case that CR has, or may have — other than `exclude_id`.

    The read half of the case-level lock. The write half is migration 056's
    partial unique index on `tpsi_filings(nar1_case_id)`, which is what settles
    a race this read cannot: two requests can both read "nothing locked" and
    both go on to claim, and only Postgres can refuse the second.
    """
    if not nar1_case_id:
        return None
    rows = (
        get_supabase().table(_TABLE)
        .select("id,stage,nar1_case_id,submit_started_at")
        .eq("nar1_case_id", nar1_case_id)
        .in_("stage", list(LOCKED_STAGES))
        .execute()
        .data
    ) or []
    for row in rows:
        if row.get("id") != exclude_id and row.get("stage") in LOCKED_STAGES:
            return row
    return None


def _refuse_if_locked(filing: dict, action: str) -> None:
    """Refuse anything that would put this return in front of CR again."""
    if filing.get("stage") in LOCKED_STAGES:
        raise FilingLocked(filing, action, own=True)
    other = locked_filing_on_case(filing.get("nar1_case_id"),
                                  exclude_id=filing.get("id"))
    if other:
        raise FilingLocked(other, action, own=False)


class SignatoryMismatch(Exception):
    """The return names one signatory and a different account is signing it.

    Only reachable on the natural-person path. CR's worksheet says
    selectPersonId is "Empty if sign by Body Corporate", so for a company whose
    secretary is a body corporate — every real GSHK client — the return names
    the corporate secretary and carries no person id at all, and the e-Service
    credential in the PinSign block is the ONLY thing identifying the human who
    signed. There is nothing to disagree with, and this never fires.

    Where the return DOES name a person, the two must be the same person. A
    NAR1 declaring that A signed it, carrying B's signature, is a false
    statutory declaration whether or not CR's own checks happen to catch it.
    """


#: The two elements that can name the human who signs, in the order they are
#: consulted. A return signed for a BODY CORPORATE carries no selectPersonId at
#: all -- CR refuses one there ("the signatory is not an individual user",
#: verified 2026-09-16) -- and names the signer in associatedPersonId instead.
#: Reading only the first would make this function return None for every real
#: GSHK client, and the mismatch guard below is only as good as what it reads.
_SIGNATORY_ELEMENTS = ("selectPersonId", "associatedPersonId")


def declared_signatory_id(validated_xml: str | None) -> str | None:
    """The e-Service account this return names as its signer, or None.

    Read by regex rather than parsed: validated_xml is a bare fragment with
    undeclared prefixes (see _extract_eform), so an XML parser needs it wrapped
    first, and these are optional leaf values.

    WIDENED to associatedPersonId (2026-09-16). It used to read selectPersonId
    only, on the reasoning that a body-corporate return "names no person and
    these guards never fire". That was true while the body-corporate path
    emitted nothing identifying a human -- which is also why CR rejected every
    such return. Now that the path names the signer, a guard that still looked
    only at selectPersonId would go blind on the ONE path every real GSHK
    client uses, and a NAR1 declaring that A signed it while carrying B's
    signature is a false statutory declaration whether or not CR notices.
    """
    import re as _re

    if not validated_xml:
        return None
    for element in _SIGNATORY_ELEMENTS:
        found = _re.search(
            rf"<(?:\w+:)?{element}>([^<]*)</(?:\w+:)?{element}>", validated_xml
        )
        value = (found.group(1) if found else "").strip()
        if value:
            return value
    return None


def sign(client, filing_id: str, signatory_user_id: str, eservice_password: str) -> dict:
    """verifyPinSigning{Code}. No charge.

    NAR1 carries ONE overall signature by a single authorised individual — a
    director OR the company secretary. No consent signatures (spec D2).

    `signatory_user_id` is the signer's own CR e-Service account. Since Q1
    (Levi 2026-08-30) the only account a route may pass here is the logged-in
    user's stored one; nothing accepts a signatory from the request any more.
    """
    from services.tpsi.crypto import build_pin_sign, signing_public_key_pem
    from services.tpsi.soap import append_to_signatures

    filing = get_filing(filing_id)
    # First, and before the stage check: a signature on a case already filed on
    # paper is the step that arms the chargeable one. Naming the real obstacle
    # here beats letting it surface a step later, at the charge.
    _refuse_if_case_finished(filing, "signing this filing")
    _refuse_if_locked(filing, "signing it")
    if filing["stage"] != STAGE_VALIDATED:
        raise ValueError("filing must be validated before it can be signed")

    validated = filing["validated_xml"]
    # Guarded here rather than in the router so a script, a test harness or a
    # future route cannot sign a return in someone else's name by going round
    # the HTTP layer.
    declared = declared_signatory_id(validated)
    if declared and declared.casefold() != (signatory_user_id or "").casefold():
        raise SignatoryMismatch(
            f"this return names e-Service account '{declared}' as its "
            f"signatory, but you are signing as '{signatory_user_id}'. A NAR1 "
            "is a statutory declaration by the person it names — either that "
            "person signs it, or the return is prepared again naming you"
        )
    pin_sign = build_pin_sign(
        _extract_eform(validated),
        signatory_user_id,
        eservice_password,
        # The certificate CR signed THIS response with — not
        # config.cr_public_key_pem, which is the change-password key. See
        # crypto.signing_public_key_pem.
        signing_public_key_pem(validated),
    )
    # CR: the overall signature goes inside EFormSignatures, BELOW its own.
    signed = append_to_signatures(validated, pin_sign)

    try:
        raw = client.post_form("verifyPinSigning", filing["form_code"], signed)
        element = parse_response(raw, "verifyPinSigningResponse")
        result = text_of(element, "result") or ""
    except TpsiError as exc:
        _update(
            filing_id,
            {"stage": STAGE_SIGNING_FAILED,
             "cr_error": {"faults": getattr(exc, "faults", []), "message": str(exc)}},
        )
        raise

    _update(
        filing_id,
        {"stage": STAGE_SIGNED, "signed_xml": signed,
         "signed_at": _now(), "cr_error": None},
    )
    return {"filing_id": filing_id, "result": result}


def upload_edrive(client, filing_id: str) -> dict:
    """uploadToEdriveForm{Code}. No charge.

    Terminal for TPSI: CR states the form is "inconvertible to TPSI format after
    submitting to e-Drive" — it must be finished in the Web Guided Wizard, so
    this filing can never go on to submitForm.
    """
    filing = get_filing(filing_id)
    # e-Drive is a lodgement channel, not a preview: STAGE_EDRIVE is one of
    # nar1_cases.CR_FILED_STAGES precisely because CR holds the return after it.
    # Blocking only sign/submit would leave this door open from 'validated'.
    _refuse_if_case_finished(filing, "sending it to CR e-Drive")
    _refuse_if_locked(filing, "sending it to CR e-Drive")
    if filing["stage"] not in (STAGE_VALIDATED, STAGE_SIGNED):
        raise ValueError("filing must be validated before it can go to e-Drive")

    payload = filing.get("signed_xml") or filing["validated_xml"]
    raw = client.post_form("uploadToEdriveForm", filing["form_code"], payload)
    element = parse_response(raw, "uploadToEdriveResponse")
    result = text_of(element, "result") or ""

    _update(filing_id, {"stage": STAGE_EDRIVE})
    return {"filing_id": filing_id, "result": result}


# ---------------------------------------------------------------------------
# Submit — CHARGEABLE AND IRREVERSIBLE
# ---------------------------------------------------------------------------

#: The receipt vocabulary CR returns from submitForm. PUBLIC because the manual
#: (off-portal) path in services/nar1_cases.py validates a hand-entered receipt
#: against this same tuple — the Confirmation screen renders one template for
#: both paths, so the two shapes must not be allowed to drift apart (BE-6).
RECEIPT_FIELDS = (
    "caseNo", "brNo", "accNo", "chiCoyName", "engCoyName",
    "docCodesWithBarcode", "pymtNo", "pymtRefNo", "pymtMtd",
    "transactionDate", "transactionTime", "totalAmount", "refNo",
)
RECEIPT_LINE_FIELDS = ("rcptNo", "revCode", "docShtFrm", "revDesc", "amtChrg")


def parse_receipt(xml_bytes: bytes) -> dict:
    """CR's submitForm receipt — the only proof the filing landed."""
    from services.tpsi.soap import find_all

    element = parse_response(xml_bytes, "submitFormResponse")
    receipt = {f: text_of(element, f) for f in RECEIPT_FIELDS}
    receipt["paymentRcptList"] = [
        {f: text_of(line, f) for f in RECEIPT_LINE_FIELDS}
        for line in find_all(element, "paymentRcptList")
    ]
    return receipt


def _check_gate(filing: dict, confirm: bool, balance, quote) -> None:
    """The four conditions, in CR's own order. Server-side, always.

    Every one is checked against state this service holds, never against
    something the caller asserted — a client must not be able to claim it
    already validated and jump straight to the charge.
    """
    if filing["stage"] != STAGE_SIGNED:
        raise SubmitGateError(
            f"filing is '{filing['stage']}' — it must be signed "
            "(validate then sign, in that order) before it can be submitted"
        )
    if not filing.get("signed_xml"):
        raise SubmitGateError("no signed payload stored for this filing")
    # Checked against the fee THIS return will actually attract, computed from
    # the company's return date (services/tpsi/fees.py) -- and against the
    # HK$3,480 ceiling when that cannot be computed. Never against the flat
    # on-time fee: a NAR1 quoted at HK$105 was billed HK$2,610 on the test
    # environment, and comparing with HK$105 let a filing through that the
    # account could not cover. The failure then happened at CR, mid-charge.
    if balance < quote.amount:
        detail = (
            f"the fee for this return is HK${quote.amount} "
            f"({quote.band})"
            if quote.certain else
            f"this return could cost up to HK${quote.amount} ({quote.reason})"
        )
        raise SubmitGateError(
            f"deposit balance {balance} does not cover it: {detail}. "
            "Top up the deposit account before filing."
        )
    if confirm is not True:
        raise SubmitGateError("explicit confirmation is required to submit")


def preview(client, filing_id: str, deposit_account: str) -> dict:
    """Fee and live balance, with nothing sent to CR.

    Audited separately from the confirm, per CLAUDE.md — the preview and the
    decision to spend are two distinct events in the trail.
    """
    from services.tpsi import fees, reads
    from services.tpsi.fees import MAX_FEE, ON_TIME_FEE

    filing = get_filing(filing_id)
    # ONE read of the company record, two answers off it (see `assess`).
    #
    # The fee is the COMPUTED one for THIS company's return date, not the flat
    # on-time figure: a return seven months late costs HK$2,610, and quoting
    # HK$105 both misinformed the operator and let the balance gate pass a
    # filing the account could not cover.
    #
    # The return date is the gate reported rather than raised (Levi
    # 2026-09-07). `submit` refuses it independently and is the authority;
    # saying it here is what lets the screen withhold the Submit button and
    # print the reason, instead of arming an irreversible-looking control whose
    # only outcome is a 409. Same shape as `sufficient` below, and for the same
    # reason.
    quote, return_date = assess(filing)
    balance = reads.check_balance(client, deposit_account)

    today = fees._hk_today()
    too_early = bool(return_date and today < return_date)

    return {
        "filing_id": filing_id,
        "form_code": filing["form_code"],
        "stage": filing["stage"],
        "fee": str(quote.amount),
        # ISO, or None when it could not be worked out. None is NOT "not early"
        # — it is "unknown", which is why `too_early` is its own boolean rather
        # than something the screen re-derives by comparing dates itself.
        "return_date": return_date.isoformat() if return_date else None,
        "too_early": too_early,
        "days_until_return_date": (
            (return_date - today).days if too_early else None
        ),
        # The whole quote, so the screen can show the band and the return date
        # it was measured from. An operator can check those against the company
        # record; they cannot check a bare number.
        "fee_detail": quote.as_dict(),
        "fee_is_certain": quote.certain,
        "on_time_fee": str(ON_TIME_FEE),
        "max_fee": str(MAX_FEE),
        "balance": str(balance),
        "sufficient": balance >= quote.amount,
        "ready": filing["stage"] == STAGE_SIGNED and bool(filing.get("signed_xml")),
    }


def _nar1_fee_inputs(filing: dict) -> tuple[dict, int | None, bool]:
    """(entity, return year, has share capital) for a NAR1 filing.

    Extracted so the fee quote and the return-date gate read the SAME two
    values out of the same places. They answer different questions off one pair
    of facts, and deriving them twice is how the fee ends up measured from one
    return date while the gate checks another.

    Raises nothing the callers do not expect: a company record that will not
    read raises, and each caller decides what that means for it.
    """
    from services.tpsi.forms import nar1_summary

    entity = _entity_for_fee(filing.get("entity_id"))

    year = None
    has_share_capital = False
    xml = filing.get("validated_xml") or filing.get("request_xml")
    if xml:
        try:
            summary = nar1_summary.summarise(xml)
            year = summary.get("year")
            has_share_capital = bool(summary.get("share_classes"))
        except Exception:  # noqa: BLE001
            pass

    return entity or {}, year, has_share_capital


def return_date_from(entity: dict, year) -> date | None:
    """The CR return date for already-resolved inputs. NO I/O.

    The return date is the anniversary of incorporation IN THE RETURN'S OWN
    YEAR (`yearAnnualReturn`) — not the incorporation date and not this year's
    anniversary. `fees.return_date_for` is the one implementation of that
    clamp, including the 29 February fallback, and is reused here rather than
    re-derived: a gate that computed the date differently from the fee would
    refuse a filing on one anniversary and price it from another.

    Returns None rather than guessing. It sits in front of a chargeable call,
    so its callers have to be able to tell "this is early" from "we do not know
    when this is due" — those are different answers and only one is a refusal.
    """
    from services.tpsi import fees

    if not year:
        return None
    incorporated = (entity or {}).get("incorporation_date")
    if not incorporated:
        return None
    try:
        incorporated = fees._coerce_date(incorporated, "incorporation date")
    except fees.FeeError:
        return None
    return fees.return_date_for(incorporated, int(year))


def assess(filing: dict):
    """(fee quote, return date) for one filing, from ONE read of the company.

    THE TWO ANSWERS COME OFF THE SAME FACTS and are produced together on
    purpose. They used to be two public entry points that each did their own
    `_entity_for_fee` — two Supabase round trips on every preview and every
    submit, and (the reason that actually matters) two readings of a record
    that could in principle differ, so the gate could refuse against one
    anniversary while the fee was measured from another.

    NEVER RAISES. It is on the path to a chargeable call: an unreadable company
    record degrades the fee to the HK$3,480 ceiling and leaves the return date
    unknown, which is not the same as "not early" — see the gate below.
    """
    from services.tpsi import fees

    if filing.get("form_code") != "Nar1":
        from services.tpsi.config import fee_for
        flat = fee_for(filing["form_code"])
        # Only an annual return HAS a return date; nothing else may be dragged
        # through this arithmetic.
        return fees.FeeQuote(flat, "fixed fee", None, None, True), None

    try:
        entity, year, has_share_capital = _nar1_fee_inputs(filing)
    except Exception:  # noqa: BLE001
        return fees.uncertain("the company record could not be read"), None

    quote = fees.annual_return_fee(
        incorporation_date=(entity or {}).get("incorporation_date"),
        year=year,
        private_with_share_capital=fees.is_private_with_share_capital(
            entity, has_share_capital=has_share_capital),
    )
    return quote, return_date_from(entity, year)


def return_date_of(filing: dict):
    """This filing's CR return date, or None. Convenience over `assess`."""
    return assess(filing)[1]


def before_return_date(filing: dict):
    """(return date, today) when this NAR1's return date is still ahead, else None.

    For the VALIDATE route, which answers before CR does: CR refuses to
    validate a return made up to a future date. None for anything that is not
    a NAR1 and whenever either date is unknown — the same fail-open rule as
    `_refuse_if_before_return_date` below, for the same reason.
    """
    from services.tpsi import fees

    if (filing or {}).get("form_code") != "Nar1":
        return None
    return_date = return_date_of(filing)
    if return_date is None:
        return None
    today = fees._hk_today()
    return (return_date, today) if today < return_date else None


def _refuse_if_before_return_date(filing: dict, return_date=None) -> None:
    """An annual return cannot be filed before the year it reports on has closed.

    Levi 2026-09-07. CR's own fee table measures every band from the return
    date, and `fees.annual_return_fee` already treated a future return date as
    uninterpretable — but "uninterpretable" only downgraded the quote to the
    HK$3,480 ceiling, and the submit went ahead anyway. So a case opened a year
    early could be validated, signed and filed, and the first thing to notice
    would have been CR, after the charge.

    It runs before ANY CR traffic, including the free balance read, exactly
    where the drift and manual-completion interlocks run.

    IT FAILS OPEN WHEN THE DATE IS UNKNOWN, deliberately, and this is the one
    place in this file that does. A missing incorporation date or an
    unreadable return year is not evidence that a return is early; refusing on
    it would block a filing that is due today over a blank field, and the fee
    quote already degrades to the ceiling for exactly these filings so nothing
    is being spent optimistically. CR remains the backstop for the case nobody
    here can compute.

    `return_date` is passed in by callers that have already run `assess`, so
    the company record is read once per submit rather than once per question.
    """
    from services.tpsi import fees

    if return_date is None:
        return_date = return_date_of(filing)
    if return_date is None:
        return
    today = fees._hk_today()
    if today < return_date:
        raise BeforeReturnDate(return_date, today)


def fee_quote_for(filing: dict):
    """The registration fee CR will charge for this filing.

    Computed from the company's return date and today's date (see
    services/tpsi/fees.py), which is what CR itself charges on. Returns an
    UNCERTAIN quote at the HK$3,480 ceiling whenever the inputs do not support
    a confident answer — never a confident wrong number, and never the on-time
    fee as a stand-in, because this value also gates the deposit balance.

    Never raises: it is called on the path to a chargeable submit, and a
    lookup failure must degrade to the ceiling rather than block a filing that
    is otherwise ready.

    Convenience over `assess`, kept because "what does this cost" is a question
    plenty of callers ask on its own. A caller that ALSO needs the return date
    should call `assess` and read both, rather than paying for two reads.
    """
    return assess(filing)[0]


def _entity_for_fee(entity_id: str | None) -> dict:
    if not entity_id:
        return {}
    rows = (
        get_supabase().table("entities")
        .select("id,company_type,incorporation_date")
        .eq("id", entity_id).limit(1).execute().data or []
    )
    return rows[0] if rows else {}


def _charged_amount(receipt: dict, predicted) -> str:
    """What CR billed, falling back to our prediction only if the receipt is silent.

    `totalAmount` is the receipt's own figure and is the only authority on what
    left the deposit account. Falls back rather than raising: the money has
    already moved by the time this runs, and refusing to record a successful
    irreversible filing over a missing field would be the worse failure.
    """
    total = (receipt or {}).get("totalAmount")
    if total in (None, ""):
        return str(predicted)
    try:
        return str(Decimal(str(total)))
    except (InvalidOperation, ValueError):
        return str(predicted)


class AlreadyFiling(SubmitGateError):
    """Another request claimed this filing first, so this one sent nothing."""


@dataclass
class SubmitClaim:
    """What `begin_submit` hands to `finish_submit`: the row it claimed, the
    exact bytes to send, and the figures the receipt is reconciled against."""
    filing: dict
    body: str
    quote: object
    balance: Decimal
    started_at: str


@dataclass
class SubmitOutcome:
    """How a claimed submit ended. `stage` is the one that was decided.

    `sent` is False when the call to CR never began (the claim was lost, or
    the task started too late); then nothing was charged and nothing is in
    flight. `stored` is False when CR DID answer with a receipt that could not
    be written to the row -- the one outcome the audit row must then carry in
    full, because it is the only proof the return landed.
    """
    stage: str
    receipt: dict | None = None
    error: Exception | None = None
    waited_seconds: float = 0.0
    sent: bool = True
    stored: bool = True
    #: Why a receipt was not stored, when it was not.
    reason: str | None = None


class NotSent(Exception):
    """The call to CR was not made. Nothing was sent, so nothing was charged."""


def is_refusal(exc: Exception) -> bool:
    """Did CR ANSWER, and say no, without processing the form?

    THE WHOLE FIX TURNS ON THIS QUESTION, and the answer is narrow on purpose.
    Only two things prove CR did not lodge the return:

      * a SOAP fault carrying fault beans — CR's business rules refused it
        (TpsiValidationError, TpsiSignatureError); and
      * a refused token (TpsiAuthError) — CR never looked at the form.

    Everything else happened AFTER the request may have left the building: a
    timeout, a dropped connection, a 5xx with no fault in it, a body that is
    not a receipt, a bug in our own parsing. CR may have filed and charged in
    every one of those, and on PROD it usually had. So they are NOT refusals,
    and the caller records an unknown outcome — never a failure, because a
    failure is what the retry path accepts.
    """
    from services.tpsi.errors import (TpsiAuthError, TpsiSignatureError,
                                      TpsiValidationError)

    return isinstance(exc, (TpsiValidationError, TpsiSignatureError, TpsiAuthError))


def _is_case_lock_violation(exc: Exception) -> bool:
    """PostgREST's report of migration 056's index refusing a claim. Named by
    index, so an unrelated unique violation is not mistaken for the lock."""
    text = str(exc)
    unique = getattr(exc, "code", None) == "23505" or "23505" in text
    return unique and CASE_LOCK_INDEX in text


#: Migration 056's partial unique index: at most one filing per case in a stage
#: where CR has, or may have, the return.
CASE_LOCK_INDEX = "uq_tpsi_filings_case_locked"


def _claim(filing: dict, started_at: str) -> None:
    """Take the right to call submitForm for this row. Exactly one request can.

    THE REAL DOUBLE-CHARGE GUARD. Migration 016 commented its partial unique
    index `uq_tpsi_filings_submitted` "A double-clicked submit hits this, not
    CR" — but that index is only written AFTER CR has answered, which is after
    the charge, so a double click reached CR twice before it could object.
    What settles it is this conditional UPDATE: `signed -> submitting`, inside
    Postgres, so of two requests that both passed every gate on a `signed`
    row, the second matches no row and is refused before CR is contacted.
    Migration 056 adds the case-level index that refuses a claim while another
    filing on the same case holds the lock.
    """
    try:
        rows = (
            get_supabase().table(_TABLE)
            .update({"stage": STAGE_SUBMITTING, "submit_started_at": started_at,
                     "cr_error": None})
            .eq("id", filing["id"])
            .eq("stage", STAGE_SIGNED)
            .execute()
            .data
        )
    except Exception as exc:  # noqa: BLE001 — only the lock is translated
        if _is_case_lock_violation(exc):
            other = locked_filing_on_case(filing.get("nar1_case_id"),
                                          exclude_id=filing.get("id"))
            raise FilingLocked(other or {"stage": STAGE_SUBMITTING},
                               "submitting it", own=False) from exc
        raise
    if not rows:
        raise AlreadyFiling(
            "this return is already being filed — another request claimed it "
            "a moment ago. Nothing more was sent to CR; the case updates when "
            "CR answers the first one."
        )


def begin_submit(client, filing_id: str, confirm: bool,
                 deposit_account: str) -> SubmitClaim:
    """Every gate, then the claim. Nothing chargeable happens here.

    Split from `finish_submit` so the route can answer the operator the moment
    the claim lands and make the CR call after the response (Levi 2026-10-26):
    submitForm normally takes 25-56 s and the edge in front of the API gives up
    at 100 s, so a wait long enough to be safe cannot happen inside a request.
    """
    from services.tpsi import reads
    from services.tpsi.soap import append_deposit_account

    filing = get_filing(filing_id)
    # BEFORE any CR traffic at all, including the free balance read: this is the
    # chargeable, irreversible one, and a case already filed on paper must never
    # get as far as a request that could spend.
    _refuse_if_case_finished(filing, "submitting it to CR")
    # A filing CR has, or may have — this one, or another on the same case.
    _refuse_if_locked(filing, "submitting it")
    # ONE read of the company record for both the gate and the price — see
    # `assess`. No CR traffic yet: this is a Supabase read and some arithmetic.
    quote, return_date = assess(filing)
    # Levi 2026-09-07. Before any CR traffic too, and before the drift check —
    # a return that is not due yet is not a return whose particulars are worth
    # diffing, and "the data moved" would be a confusing answer to "you are
    # eleven months early".
    _refuse_if_before_return_date(filing, return_date)
    # Spec §6. Also before any CR traffic, including the free balance read: the
    # client approved the document as it stood, and a return whose particulars
    # have moved since is not the one they approved.
    _refuse_if_drifted(filing)
    balance = reads.check_balance(client, deposit_account)  # LIVE, never cached
    _check_gate(filing, confirm, balance, quote)

    signed = filing["signed_xml"]
    body = (
        signed
        if "depositAccountNo" in signed
        else append_deposit_account(signed, deposit_account)
    )

    # LAST, after every gate: a claim is a promise that CR is about to be
    # called, and a gate refusing after it would leave a row claiming a call
    # that never happened.
    started_at = _now()
    _claim(filing, started_at)
    return SubmitClaim(filing=filing, body=body, quote=quote, balance=balance,
                       started_at=started_at)


#: The stages a FAILURE or UNKNOWN outcome may be written over. `submission_unknown`
#: is included because the stale-claim sweep can get there first on a call that
#: is in fact still running; anything else means somebody has already decided.
_OUTCOME_FROM = (STAGE_SUBMITTING, STAGE_SUBMISSION_UNKNOWN)

#: The stages a RECEIPT may be written over: everything except the stages that
#: already hold one (`submitted`, `registered`) and a retired attempt. CR's
#: receipt is the truth, so it overrides `submission_unknown`, a declared
#: `submission_failed`, and anything the retry path has reached since the claim
#: -- the opposite rule from a failure, which must never overwrite an answer
#: (code review 01, B1.4).
_RECEIPT_OVERWRITES = tuple(
    s for s in dict.fromkeys(FORM_STATUSES + (STAGE_EDRIVE,))
    if s not in (STAGE_SUBMITTED, STAGE_REGISTERED, STAGE_EDRIVE,
                 STAGE_SUPERSEDED))

#: How much of an unreadable CR reply is kept on the row, for the operator and
#: for whoever has to work out what CR sent.
RAW_REPLY_BYTES = 2048


def _update_where(filing_id: str, payload: dict, stages,
                  started_at: str | None = None) -> bool:
    """`_update`, conditional on the stage inside the UPDATE -- and, when
    `started_at` is given, on the CLAIM too (`submit_started_at`), so a late
    answer to one submit can never be written over a different submit's row.
    Returns whether a row moved."""
    query = (
        get_supabase().table(_TABLE).update(payload)
        .eq("id", filing_id).in_("stage", list(stages))
    )
    if started_at is not None:
        query = query.eq("submit_started_at", started_at)
    return bool(query.execute().data)


ALREADY_RECORDED = "already recorded by an operator"


def _why_not_stored(filing_id: str) -> str:
    """The receipt's write moved no row. Say which of two things that means: the
    row already holds a receipt (an operator recorded one, or the 056-era
    resolve did) or the claim is no longer this submit's."""
    try:
        stage = get_filing(filing_id).get("stage")
    except Exception:  # noqa: BLE001
        stage = None
    if stage in (STAGE_SUBMITTED, STAGE_REGISTERED, STAGE_EDRIVE):
        return ALREADY_RECORDED
    return "the row no longer holds this claim"


def _claim_is_ours(claim: SubmitClaim) -> bool:
    """Is the row still `submitting`, under THIS claim?

    A read, immediately before the post. The sweep needs a claim older than
    `STALE_CLAIM_SECONDS` and the start-delay check below has just ruled that
    out, so nothing can change the answer between this read and the post.
    """
    rows = (
        get_supabase().table(_TABLE).select("id")
        .eq("id", claim.filing["id"]).eq("stage", STAGE_SUBMITTING)
        .eq("submit_started_at", claim.started_at)
        .execute().data
    )
    return bool(rows)


def _raw_text(raw) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    return str(raw)[:RAW_REPLY_BYTES]


def _require_receipt(receipt: dict) -> None:
    """A reply is a receipt only if it names a case.

    `parse_receipt` reads whatever fields are there, so a body such as
    `<cr:submitFormResponse/>` yields a dict of Nones. Stored as `submitted`,
    that is a filing nobody can prove: no case number for the CR-status poll to
    ask about, and `resolve` refuses it because the stage is not unknown. When
    in doubt, unknown (code review 01, B2).
    """
    from services.tpsi.errors import TpsiUnavailableError

    if not str((receipt or {}).get("caseNo") or "").strip():
        raise TpsiUnavailableError(
            "CR's reply to the submission carried no case number, so it cannot "
            "be taken as a receipt", kind="no_receipt")


def _decide_not_to_send(claim: SubmitClaim, now: datetime) -> SubmitOutcome | None:
    """The two reasons to make no call at all, or None to go ahead.

    1. THE CLAIM IS NOT OURS ANY MORE -- swept, resolved, or re-claimed while
       this task waited for a worker thread. The stage is left exactly as it
       is: whoever moved it decided.
    2. THE CALL WOULD START TOO LATE. A call beginning after
       `MAX_START_DELAY_SECONDS` could outlast `STALE_CLAIM_SECONDS`, which is
       the only thing keeping a sweep from overlapping a live call. Nothing has
       been sent, so this is an ordinary refusal and the retry stays open.
    """
    try:
        ours = _claim_is_ours(claim)
    except Exception as exc:  # noqa: BLE001 — cannot verify: send nothing
        # The row stays `submitting` and the sweep will read it as unknown. CR
        # was never called, so that is conservative -- the safe direction.
        return SubmitOutcome(
            stage=STAGE_SUBMISSION_UNKNOWN, sent=False,
            error=NotSent(f"the claim could not be verified before sending "
                          f"({exc}); nothing was sent"))
    if not ours:
        return SubmitOutcome(
            stage=STAGE_SUBMISSION_UNKNOWN, sent=False,
            error=NotSent("claim lost before sending; nothing was sent"))

    started = _parse_instant(claim.started_at)
    if started is not None and (now - started).total_seconds() > MAX_START_DELAY_SECONDS:
        message = (f"the submission could not start within "
                   f"{MAX_START_DELAY_SECONDS} s of being claimed (the server "
                   "was busy), so nothing was sent to CR and nothing was "
                   "charged. Submit again.")
        try:
            _update_where(
                claim.filing["id"],
                {"stage": STAGE_SUBMISSION_FAILED,
                 "cr_error": {"faults": [], "kind": "not_sent",
                              "message": message}},
                (STAGE_SUBMITTING,), claim.started_at)
        except Exception as exc:  # noqa: BLE001
            print(f"[tpsi.filings] ERROR: could not record that filing "
                  f"{claim.filing['id']} was never sent: {exc}", file=sys.stderr)
        return SubmitOutcome(stage=STAGE_SUBMISSION_FAILED, sent=False,
                             error=NotSent(message))
    return None


def finish_submit(client, claim: SubmitClaim) -> SubmitOutcome:
    """submitForm{Code} — CHARGEABLE AND IRREVERSIBLE. Never raises.

    Called only by the request that claimed the row. Its outcome is CLASSIFIED,
    not caught: a receipt is `submitted`; CR's own refusal is
    `submission_failed`, retryable exactly as before; and everything else is
    `submission_unknown`, which nothing can retry (see `is_refusal`).

    BEFORE THE POST it checks that it still holds the claim and has not been
    waiting for a thread longer than `MAX_START_DELAY_SECONDS`; if either fails
    it sends nothing (`_decide_not_to_send`).

    A RECEIPT IS ALWAYS KEPT. The success write is keyed to this claim and may
    overwrite any stage that does not already hold a receipt, so an answer that
    lands after the sweep and a "not lodged" declaration still ends the row at
    `submitted`. If even that write moves no row, the receipt is printed whole
    and `outcome.stored` is False, so the caller puts it in the audit trail.

    NEVER RAISES, because by the time it runs nobody is waiting for an
    exception — it runs after the response. A write that fails here leaves the
    row at `submitting`, and the stale-claim sweep reads that as an unknown
    outcome: the safe direction.
    """
    import time

    from services.tpsi.errors import TpsiAuthError

    filing_id = claim.filing["id"]
    skipped = _decide_not_to_send(claim, datetime.now(timezone.utc))
    if skipped is not None:
        return skipped

    began = time.monotonic()
    raw = None
    try:
        raw = client.post_form("submitForm", claim.filing["form_code"], claim.body)
        receipt = parse_receipt(raw)
        _require_receipt(receipt)
    except Exception as exc:  # noqa: BLE001 — classified below, never swallowed
        waited = round(time.monotonic() - began, 1)
        refusal = is_refusal(exc)
        stage = STAGE_SUBMISSION_FAILED if refusal else STAGE_SUBMISSION_UNKNOWN
        error = {"faults": getattr(exc, "faults", []), "message": str(exc),
                 "kind": ("auth" if isinstance(exc, TpsiAuthError)
                          else "refused" if refusal
                          else getattr(exc, "kind", None) or type(exc).__name__)}
        text = _raw_text(raw)
        if text is not None:
            error["raw"] = text
        try:
            _update_where(filing_id, {"stage": stage, "cr_error": error},
                          _OUTCOME_FROM, claim.started_at)
        except Exception as write_exc:  # noqa: BLE001 — see docstring
            print(f"[tpsi.filings] ERROR: could not record the {stage} outcome "
                  f"of filing {filing_id}: {write_exc}", file=sys.stderr)
        return SubmitOutcome(stage=stage, error=exc, waited_seconds=waited)

    waited = round(time.monotonic() - began, 1)
    try:
        stored = _update_where(
            filing_id,
            {
                "stage": STAGE_SUBMITTED,
                "receipt": receipt,
                # WHAT CR ACTUALLY CHARGED, not what we predicted. A late
                # annual return is charged HK$870-HK$3,480 and CR decides which
                # tier applies (measured on CR TEST 2026-08-27: HK$2,610, revenue
                # code 16, document NAR1L). The receipt is the authority.
                "fee_amount": _charged_amount(receipt, claim.quote.amount),
                "balance_at_submit": str(claim.balance),
                "submitted_at": _now(),
                "cr_error": None,
            },
            _RECEIPT_OVERWRITES, claim.started_at,
        )
        reason = None if stored else _why_not_stored(filing_id)
    except Exception as exc:  # noqa: BLE001 — the money has moved; keep the receipt
        stored, reason = False, str(exc)
    if not stored:
        # The receipt is the only proof the return landed. It survives in the
        # platform log AND, because the caller audits it in full, in the
        # insert-only trail.
        if reason == ALREADY_RECORDED:
            # Not a failure: an operator recorded this receipt while CR's own
            # answer was still on its way. Keep it, but say what it is (review
            # 02, N-10) rather than log an ERROR that reads as lost data.
            print(f"[tpsi.filings] NOTE: CR's receipt for filing {filing_id} "
                  f"arrived after it was {reason}; receipt={receipt}",
                  file=sys.stderr)
        else:
            print(f"[tpsi.filings] ERROR: CR filed {filing_id} but the receipt "
                  f"could not be stored ({reason}); receipt={receipt}",
                  file=sys.stderr)
    else:
        _write_back_receipt(claim.filing, receipt)
    return SubmitOutcome(stage=STAGE_SUBMITTED, receipt=receipt,
                         waited_seconds=waited, stored=stored, reason=reason)


def submit(client, filing_id: str, confirm: bool, deposit_account: str) -> dict:
    """Gates, claim and submitForm in one call, for callers that can wait.

    The route does not use this — it answers after the claim and finishes in
    the background — but it is the same two halves in the same order, so a
    script or a test exercises exactly what the route does. Raises the
    exception CR's outcome carried when the return was not filed.
    """
    claim = begin_submit(client, filing_id, confirm, deposit_account)
    outcome = finish_submit(client, claim)
    if outcome.stage != STAGE_SUBMITTED:
        raise outcome.error
    return {"filing_id": filing_id, "receipt": outcome.receipt}


# ---------------------------------------------------------------------------
# An outcome nobody recorded, and an operator recording it
# ---------------------------------------------------------------------------


def _parse_instant(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def is_stale_claim(row: dict | None, now: datetime | None = None) -> bool:
    """A `submitting` claim no live request can still answer."""
    if (row or {}).get("stage") != STAGE_SUBMITTING:
        return False
    started = _parse_instant(row.get("submit_started_at"))
    if started is None:
        return True
    now = now or datetime.now(timezone.utc)
    return (now - started).total_seconds() > STALE_CLAIM_SECONDS


def expire_stale_claim(row: dict | None) -> dict | None:
    """Turn a stale `submitting` claim into `submission_unknown`. Returns the
    updated row, or None when nothing moved.

    A worker restarted mid-call (a deploy, a crash) leaves the row claimed
    forever and nothing will write CR's answer. Every read of a filing calls
    this, and the conditional UPDATE — still `submitting`, still older than the
    cut-off — means a reader racing the real answer can never overwrite it.
    """
    if not is_stale_claim(row):
        return None

    cutoff = (datetime.now(timezone.utc)
              - timedelta(seconds=STALE_CLAIM_SECONDS)).isoformat()
    query = (
        get_supabase().table(_TABLE)
        .update({"stage": STAGE_SUBMISSION_UNKNOWN,
                 "cr_error": {"faults": [], "message": (
                     "no answer recorded: the submit was sent to CR but its "
                     "outcome was never stored (the worker may have restarted "
                     "mid-call)"), "kind": "no_answer_recorded"}})
        .eq("id", row["id"])
        .eq("stage", STAGE_SUBMITTING)
    )
    if row.get("submit_started_at"):
        query = query.lt("submit_started_at", cutoff)
    rows = query.execute().data
    return rows[0] if rows else None


#: Who a repair made by a READ is attributed to. The reader did not cause it.
SYSTEM_ACTOR = "G-FlowDesk (automatic)"


async def settle_stale_claim(row: dict | None, observed_by: dict | None) -> dict | None:
    """Every read of a filing comes through here (2026-10-26).

    A `submitting` claim older than `STALE_CLAIM_SECONDS` belongs to a request
    that can no longer answer -- the worker restarted mid-call -- so it becomes
    `submission_unknown` and is audited as one, with the reason that nothing
    was ever recorded. Returns the row as it now stands. Never raises: it
    decorates a read, and a read must not fail because a repair could not be
    written.

    A WRITE UNDER A READ PERMISSION, deliberately: the ticket asks for it ("any
    read ... a conditional UPDATE makes it so"), and CLAUDE.md records it so the
    next reviewer does not take it for a breach. The audit row is the SYSTEM's
    (`SYSTEM_ACTOR`), with the reader in `metadata.observed_by` -- they looked,
    they did not do it (code review 01, S-1). Lives here, not in a router, so
    the case route and the filing route settle it one way (S-2).

    The registry VIEW (migration 056) also reads a stale claim as unknown, but
    never writes it: only these reads do (N-6).
    """
    if not is_stale_claim(row):
        return row
    waited = claim_age_seconds(row)
    try:
        moved = expire_stale_claim(row)
    except Exception as exc:  # noqa: BLE001 — see docstring
        print(f"[tpsi.filings] WARN: could not expire the stale submit claim on "
              f"filing {row.get('id')}: {exc}", file=sys.stderr)
        return {**row, "stage": STAGE_SUBMISSION_UNKNOWN}
    if moved is None:
        # Somebody else moved it first -- the real answer, or another reader.
        try:
            return get_filing(row["id"])
        except Exception:  # noqa: BLE001
            return row

    from services import audit_events as ev
    from services.audit_service import log_event
    from services.tpsi import audit_context

    await log_event(
        user_id=None, user_display_name=SYSTEM_ACTOR,
        action_type=ev.TPSI_SUBMISSION_UNKNOWN,
        event_code=ev.TPSI_SUBMISSION_UNKNOWN,
        entity_type="tpsi_filing", entity_id=row["id"],
        **audit_context.filing_subject(row),
        metadata={"reason": "no answer recorded", "waited_seconds": waited,
                  "observed_by": (observed_by or {}).get("display_name")},
    )
    return {**row, **moved}


def claim_age_seconds(row: dict | None) -> float | None:
    started = _parse_instant((row or {}).get("submit_started_at"))
    if started is None:
        return None
    return round((datetime.now(timezone.utc) - started).total_seconds(), 1)


def not_lodged_after(row: dict | None) -> str | None:
    """When "CR does not have it" may first be declared for this filing, or None.

    The instant after which no call made under the claim can still be with CR
    (`claim started + STALE_CLAIM_SECONDS`). Declaring a return not lodged
    re-opens validate, sign and submit, so while an answer could still arrive
    the declaration is refused: a receipt landing after it would meet a retry
    already on its way (code review 01, B1.3). None for a row with no claim
    time -- the ones migration 056's repair moved, which are days old.
    """
    started = _parse_instant((row or {}).get("submit_started_at"))
    if started is None:
        return None
    return (started + timedelta(seconds=STALE_CLAIM_SECONDS)).isoformat()


def _in_flight_refusal(row: dict) -> "ResolveRefused | None":
    from zoneinfo import ZoneInfo

    after = _parse_instant(not_lodged_after(row))
    if after is None or datetime.now(timezone.utc) > after:
        return None
    clock = after.astimezone(ZoneInfo(_HK)).strftime("%H:%M")
    return ResolveRefused(
        409, f"A submit may still be with CR until {clock} HKT, and a receipt "
             "arriving after you declared this return not lodged would meet a "
             f"second submit already on its way. Check again after {clock} HKT.",
        reason="may_be_in_flight", not_lodged_after=after.isoformat())


class ResolveRefused(Exception):
    """A resolution that cannot be recorded. `status` is the HTTP answer."""

    def __init__(self, status: int, message: str, **extra):
        self.status = status
        self.extra = extra
        super().__init__(message)


#: CR prints the transaction in Hong Kong time, and `submitted_at` is UTC.
_HK = "Asia/Hong_Kong"


def receipt_instant(receipt: dict) -> str:
    """CR's transactionDate + transactionTime, read as Hong Kong time, in UTC.

    It feeds `nar1_cases.filed_on` and therefore the Date printed beside the
    signature, so it must be the day CR received the return — not the day an
    operator got round to recording it. Raises ValueError on a shape CR does
    not print; `nar1_cases.validate_receipt` has already refused those.
    """
    from zoneinfo import ZoneInfo

    day = str(receipt.get("transactionDate") or "").strip()
    clock = str(receipt.get("transactionTime") or "").strip()
    if len(clock) == 5:
        clock += ":00"
    local = datetime.strptime(f"{day} {clock}", "%d/%m/%Y %H:%M:%S")
    return (local.replace(tzinfo=ZoneInfo(_HK))
            .astimezone(timezone.utc).isoformat())


def _full_receipt(receipt: dict, source: str) -> dict:
    """The stored receipt, with every key a real submitFormNar1 receipt has.

    `parse_receipt` yields every RECEIPT_FIELDS key (None when CR omitted it),
    and Confirmation renders one template for both, so a recorded receipt that
    lacked a key would render a blank box that looks like missing data.
    """
    out = {f: receipt.get(f) for f in RECEIPT_FIELDS}
    out["paymentRcptList"] = [
        {f: (line or {}).get(f) for f in RECEIPT_LINE_FIELDS}
        for line in (receipt.get("paymentRcptList") or [])
    ]
    out["source"] = source
    return out


def _same_br(a, b) -> bool:
    left = str(a or "").strip().lstrip("0")
    right = str(b or "").strip().lstrip("0")
    return bool(left) and left == right


CASE_NO_SHAPE = r"^\d{6,12}$"


def hk_date_of(row_or_value) -> date | None:
    """The Hong Kong calendar day of a stored instant, or None."""
    from zoneinfo import ZoneInfo

    started = _parse_instant(row_or_value)
    return started.astimezone(ZoneInfo(_HK)).date() if started else None


def _cr_date(text) -> date | None:
    """CR prints dates dd/mm/yyyy (a time may follow). None when it cannot be read."""
    try:
        return datetime.strptime(str(text or "").strip()[:10], "%d/%m/%Y").date()
    except ValueError:
        return None


def check_receipt_not_before_claim(filing: dict, receipt: dict) -> None:
    """A receipt cannot be dated before the submit it claims to answer.

    The transaction date feeds `submitted_at` and therefore the Date printed
    beside the signature, and a receipt for last year's return typed against
    this year's case is the mistake this catches. Skipped for a legacy row with
    no claim time. Raises ResolveRefused(422, reason="before_claim").
    """
    claimed = hk_date_of(filing.get("submit_started_at"))
    dated = _cr_date(receipt.get("transactionDate"))
    if claimed and dated and dated < claimed:
        raise ResolveRefused(
            422, f"the receipt is dated {dated.strftime('%d/%m/%Y')}, before "
                 f"this submit was made ({claimed.strftime('%d/%m/%Y')}), so it "
                 "cannot be this return's receipt. Check the case number and "
                 "date on CR's receipt; nothing was recorded.",
            reason="before_claim")


#: What CR answers when a case number is not one it holds. Measured on CR's TEST
#: and PRODUCTION environments on 2026-09-17 (`999999999`, `wddw`) and again on
#: TEST on 2026-10-27: a fault with a bean, `Case no does not exist.` -- never an
#: empty list. A case CR does know, but has not listed yet, comes back as an
#: EMPTY list. Matched case-insensitively and by substring, because the wording
#: is all CR specifies and a trailing full stop is not worth refusing over.
CASE_NOT_FOUND_FAULT = "case no does not exist"

#: What `verify_lodged` found, recorded on the TPSI_SUBMISSION_RESOLVED row.
CR_CHECK_LISTED = "listed"          # CR listed documents under this BR number
CR_CHECK_EMPTY = "known_unlisted"   # CR knows the case and has listed nothing
CR_CHECK_SKIPPED = "skipped"        # CR could not be asked, or said nothing usable


def _says_case_not_found(exc: Exception) -> bool:
    words = " ".join(m for _c, m in (getattr(exc, "faults", None) or [])) or str(exc)
    return CASE_NOT_FOUND_FAULT in words.lower()


def verify_lodged(client, case_no: str, br_no: str | None) -> dict:
    """Ask CR (free, `docStatusEnquiry`) whether this case number is a real one.

    A CHECK FOR A TYPO, NOT A PROOF OF FILING (Levi 2026-10-27). CR has said
    `docStatusEnquiry` is unreliable, and it is not what decides whether a return
    was lodged -- the operator, reading CR e-Services, does that. So it can
    REFUSE in exactly two cases, both of which are CR positively saying "no":

      422 case_no_unknown -- the fault `Case no does not exist.`
      422 br_mismatch     -- CR lists documents under the number, all of them for
                             a DIFFERENT BR number: a real case, another company's.

    Everything else passes and says so in the returned `cr_check`:

      listed         CR listed documents under this company's BR number
      known_unlisted an EMPTY list -- CR knows the case and has listed nothing,
                     which is routine for hours after a return is filed
      skipped        CR could not be asked (timeout, 5xx, auth, any other fault,
                     a reply that did not parse): nothing is proved, nothing is
                     refused, and the audit row records that the check did not run

    It no longer reads `documentName` or `submissionDate`. Those checks (last
    year's NAR1, an ND2A under the same number) depended on wording CR does not
    specify and refused a genuine return once already (code review 02, B3); the
    receipt's own date is still held against the claim by
    `check_receipt_not_before_claim`, which needs no call to CR.

    The order is `{"cr_check": ..., "reason": ...}`; `reason` is set when skipped.
    """
    from services.tpsi import reads

    try:
        rows = reads.case_status(client, case_no=case_no)
    except Exception as exc:  # noqa: BLE001 -- see "skipped" above
        if _says_case_not_found(exc):
            raise ResolveRefused(
                422, f"CR does not recognise case number {case_no}: "
                     f"{'; '.join(m for _c, m in (getattr(exc, 'faults', None) or [])) or exc}. "
                     "Check the number on CR's receipt; nothing was recorded.",
                reason="case_no_unknown") from exc
        return {"cr_check": CR_CHECK_SKIPPED,
                "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}

    listed = [r for r in rows if r.get("brNo")]
    if listed and not any(_same_br(r.get("brNo"), br_no) for r in listed):
        raise ResolveRefused(
            422, f"CR lists case number {case_no} under BR number "
                 f"{listed[0].get('brNo')}, not this company's ({br_no}). "
                 "Check the number on CR's receipt; nothing was recorded.",
            reason="br_mismatch")
    return {"cr_check": CR_CHECK_LISTED if listed else CR_CHECK_EMPTY}


def resolve_lodged(filing_id: str, receipt: dict) -> dict:
    """CR has the return: record its receipt. Conditional on the stage.

    `receipt` has already been shaped (`nar1_cases.with_derived_fields`),
    checked (`validate_receipt`) and verified against CR (`verify_lodged`).
    """
    stored = _full_receipt(receipt, "operator_after_timeout")
    moved = _update_where(
        filing_id,
        {
            "stage": STAGE_SUBMITTED,
            "receipt": stored,
            "fee_amount": _charged_amount(stored, stored.get("totalAmount") or "0"),
            "submitted_at": receipt_instant(stored),
        },
        (STAGE_SUBMISSION_UNKNOWN,),
    )
    if not moved:
        raise ResolveRefused(409, "this filing's outcome is no longer unknown — "
                                  "reload the case to see what it is now")
    filing = get_filing(filing_id)
    # CR's day, not today's: the form_filings mirror says when the return was
    # FILED, and an operator may record it days after (code review 01, N-4).
    filed = _cr_date(stored.get("transactionDate"))
    _write_back_receipt(filing, stored, filed_date=filed.isoformat() if filed else None)
    return filing


def resolve_not_lodged(filing_id: str, *, actor: str) -> dict:
    """CR does not have it: reopen the ordinary retry. Conditional on the stage.

    REFUSED WHILE A CALL COULD STILL BE WITH CR (`not_lodged_after`), here and
    not only in the route, so a script cannot skip it. Legacy rows with no
    claim time are allowed.
    """
    refusal = _in_flight_refusal(get_filing(filing_id))
    if refusal is not None:
        raise refusal
    when = _now()
    moved = _update_where(
        filing_id,
        {"stage": STAGE_SUBMISSION_FAILED,
         "cr_error": {"faults": [], "kind": "declared_not_lodged",
                      "message": (f"{actor} checked CR e-Services on {when} "
                                  "and declared this return not lodged after "
                                  "a submit that had no answer from CR.")}},
        (STAGE_SUBMISSION_UNKNOWN,),
    )
    if not moved:
        raise ResolveRefused(409, "this filing's outcome is no longer unknown — "
                                  "reload the case to see what it is now")
    return get_filing(filing_id)


def claimed_today_in_hk(row: dict) -> bool:
    """Was this filing's submit claimed today, Hong Kong time? CR can take
    hours to list a return filed today, so 'not listed' means less then."""
    from zoneinfo import ZoneInfo

    from services.tpsi import fees

    started = _parse_instant(row.get("submit_started_at"))
    if started is None:
        return False
    return started.astimezone(ZoneInfo(_HK)).date() == fees._hk_today()


def _write_back_receipt(filing: dict, receipt: dict,
                        filed_date: str | None = None) -> None:
    """Mirror the receipt onto the existing form_filings row.

    The case UI already reads form_filings, so the receipt lands where it is
    already looked for — no new columns on nar1_cases. Never raises: the filing
    has been submitted and charged by this point, and a bookkeeping failure must
    not turn a successful, irreversible submission into an error response.
    """
    if not filing.get("form_filing_id"):
        return
    try:
        get_supabase().table("form_filings").update(
            {
                "filed_with_cr": True,
                "filed_date": filed_date or _now()[:10],
                "field_details": {"receipt": receipt},
            }
        ).eq("id", filing["form_filing_id"]).execute()
    except Exception as exc:  # noqa: BLE001 - see docstring
        print(
            f"[tpsi.filings] WARN: receipt write-back failed for filing "
            f"{filing.get('id')}: {exc}",
            file=sys.stderr,
        )
