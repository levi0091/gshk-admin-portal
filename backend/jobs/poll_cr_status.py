"""Ask CR what it did with every return it is still deciding about.

Levi 2026-09-16: "we should only check for things after submission and not yet
confirmed or rejected with CR."

    python -m jobs.poll_cr_status

    PROD   */15 * * * *        every 15 minutes, around the clock
    DEV    */15 0-8 * * 1-5    every 15 minutes, 08:00–16:45 Hong Kong,
                               weekdays (Levi 2026-09-16)

EVERY 15 MINUTES IS AFFORDABLE, AND THAT IS A PROPERTY OF THIS JOB, NOT A
GUESS. `docStatusEnquiry` is free (§6.5.1, "No Charge required"); the query
below returns nothing once the book has settled, and a run with nothing to do
costs no CR login at all; and `services/tpsi/tokens.py` keeps one token for 30
minutes in Postgres, so the runs that DO have work share a login rather than
making 96 a day. What it is NOT affordable in is audit rows — see `record_run`.

DEV STOPS AT WEEKENDS AND EVENINGS because CR's TEST service answers the form
APIs only between 10:00 and 16:00 Hong Kong. A run outside that window is a
login spent to be refused. The requested window is 08:00–17:00 and cron cannot
express "up to and including 17:00" in one expression, so the last run is at
16:45; the useful part of it on DEV is 10:00–15:45 regardless.

WHY A CRON SERVICE AND NOT AN IN-PROCESS SCHEDULER — the same reason
`auto_approve_nar1` gives, plus one of its own. An in-process timer fires once
per replica, so the moment Railway scales the API past one instance every case
is polled twice; `docStatusEnquiry` is free, but CR issues ONE TOKEN PER ACCOUNT
AT A TIME and two replicas logging in as the shared presenter would invalidate
each other's session mid-run.

ONE LOGIN, MANY ENQUIRIES. The client is built once and reused: tokens are
cached for 30 minutes (`services/tpsi/tokens.py`), so a run over a few hundred
cases costs one authentication. That matters beyond politeness — repeated CR
auth failures LOCK the account, so the fewer logins a job makes, the smaller the
blast radius when a password expires mid-run.

WHAT IT WILL NOT TOUCH, AND WHY EACH EXCLUSION MATTERS. The full list lives in
`nar1_cr_status.due_for_check`; the query below pre-filters for the two that can
be expressed in SQL, and the service re-checks all of them per case.

  not filed          there is nothing at CR to ask about
  already decided    CR said Registered or Rejected; it will not change its mind
                     and every further enquiry is a CR round trip for nothing
  closed             nobody is waiting for the answer
  no CR case number  there is no key `docStatusEnquiry` will match on

IDEMPOTENT. A second run the same hour re-asks CR and writes the same answer;
the only new row is the run's own heartbeat, which is what it is for.

PER-CASE ISOLATION. One case that fails does not abandon the rest — each is
asked on its own and the run reports how many were checked, changed, skipped and
failed. A job that stopped at the first CR fault would leave the rest of the
book unpolled until somebody noticed.

A TRANSPORT FAILURE ENDS THE RUN, and that is deliberate: if CR is unreachable
or the shared credential has expired, the next 300 cases will fail identically,
and 300 stack traces is a worse report than one. The exit code says so and the
next scheduled run picks up where this stopped.
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone

from db.supabase import get_supabase
from services import audit_events as ev
from services import nar1_cases, nar1_cr_status
from services.audit_service import log_event
from services.tpsi import doc_status as ds
from services.tpsi import shared_credentials
from services.tpsi.client import TpsiClient
from services.tpsi.errors import TpsiUnavailableError

#: Who the trail says did this. Matches `auto_approve_nar1`'s wording, because
#: an operator reading the audit log should not have to learn two names for
#: "the portal did this by itself".
ACTOR = "G-FlowDesk (automatic)"

#: How many cases one run will look at.
#:
#: EXPLICIT, because PostgREST applies its OWN ceiling when a query does not
#: (Supabase's default is 1,000) and returns the truncated page with no error
#: and no marker. A silent cap here would poll the first thousand and leave the
#: rest looking, from the log, exactly like a run with nothing left to do.
#: Stated here, the cap is visible, and `run` says when it was reached.
CASE_LIMIT = 1_000

#: The columns the service needs. `SELECT *` would work and is what
#: `nar1_cases.get_case` does, but this query runs over the whole filed book on
#: a schedule and `manual_receipt` is the only jsonb in it that is ever large.
_COLS = (
    "id, case_no, entity_id, closed_at, manual_receipt, "
    "cr_doc_status, cr_doc_status_code, cr_status_checked_at, cr_document_ref_no"
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def open_cases(limit: int = CASE_LIMIT) -> list[dict]:
    """Cases CR may still have something new to say about.

    Filtered in the DATABASE, not in Python: the book is ~5,900 companies and a
    scan that pulled every case to decide in the loop would grow with history
    rather than with what is actually outstanding.

    LEAST-RECENTLY-CHECKED FIRST, nulls first. A run that does hit the ceiling
    then clears the cases nobody has asked about at all before re-asking ones
    checked an hour ago, and the next run takes the remainder. Ordering by
    creation date instead would re-poll the same oldest thousand every time and
    never reach the newest case in the book.

    It does NOT filter on "is filed" — that needs the filing row, and joining
    tpsi_filings through PostgREST to express it would make this query a second
    definition of a rule `nar1_cr_status.is_filed` already owns. The service
    re-checks per case and the unfiled ones come back as skips.

    `or_(... is.null, ... not.in ...)` AND NOT A BARE `not_.in_`. In SQL,
    `col NOT IN ('a','b')` evaluates to NULL when `col` is NULL, and a NULL
    predicate excludes the row — so the bare form would filter out EVERY case in
    the book, all of which carry NULL here until the first successful check. The
    job would have run clean, reported "nothing to do", and never polled
    anything. The `is.null` arm is the whole query.
    """
    terminal = ",".join(ds.TERMINAL_CODES)
    return (
        get_supabase().table("nar1_cases")
        .select(_COLS)
        .is_("closed_at", None)
        .or_(f"cr_doc_status_code.is.null,"
             f"cr_doc_status_code.not.in.({terminal})")
        .order("cr_status_checked_at", desc=False, nullsfirst=True)
        .limit(limit)
        .execute()
        .data
        or []
    )


def build_client() -> TpsiClient:
    """The SHARED presenter account — there is no user in a cron run.

    Everything GSHK files, it files under one CR identity (BE-5/W-6), so this is
    the same credential the portal itself uses rather than a service account
    invented for the job.
    """
    credential = shared_credentials.load_for_use()
    return TpsiClient(credential.account_id, credential.tpsi_password)


async def run(limit: int = CASE_LIMIT, client: TpsiClient | None = None) -> dict:
    """One pass. Returns counts plus the reasons behind them."""
    started = _now()
    cases = open_cases(limit)
    truncated = len(cases) >= limit

    report = {
        "ran_at": started.isoformat(),
        "looked_at": len(cases),
        "checked": 0,
        "changed": [],
        "skipped": [],
        "failed": [],
        "truncated": truncated,
        "unavailable": None,
    }
    if not cases:
        return report

    # Built AFTER the query, so a run with nothing to do costs no CR login at
    # all — which is most runs once the book has settled.
    try:
        client = client or build_client()
    except Exception as exc:  # noqa: BLE001 — no credential is not a per-case fault
        report["unavailable"] = f"the shared CR credential could not be used: {exc}"
        await record_run(report)
        return report

    for case in cases:
        case_id = case.get("id")
        try:
            filing = nar1_cases.current_filing(case_id)
        except Exception as exc:  # noqa: BLE001 — an unreadable ledger is a reason
            report["failed"].append((case_id, f"the filing ledger could not be read ({exc})"))
            continue

        try:
            result = nar1_cr_status.refresh(client, case, filing)
        except TpsiUnavailableError as exc:
            # CR is not usable. The next 300 cases will fail identically, and
            # 300 stack traces is a worse report than one sentence.
            report["unavailable"] = str(exc)
            break
        except Exception as exc:  # noqa: BLE001 — one bad case must not abandon
            report["failed"].append((case_id, str(exc)))   # the rest of the book
            traceback.print_exc(file=sys.stderr)
            continue

        if result.get("skipped"):
            report["skipped"].append((case.get("case_no") or case_id, result["skipped"]))
            continue

        report["checked"] += 1
        if result.get("changed"):
            report["changed"].append((
                case.get("case_no") or case_id,
                result.get("previous"), result.get("code"), result.get("cr_text"),
            ))

        try:
            # `heartbeat=False`: the run writes ONE of those, at the end. See
            # `record_run`.
            await nar1_cr_status.record(result, case, user_id=None,
                                        user_display_name=ACTOR, heartbeat=False)
        except Exception:  # noqa: BLE001 — the trail must not undo the work
            traceback.print_exc(file=sys.stderr)

    await record_run(report)
    return report


async def record_run(report: dict) -> None:
    """One `TPSI_DOC_STATUS_CHECKED` row for the whole run.

    THE HEARTBEAT MOVED FROM THE CASE TO THE RUN when the schedule became every
    15 minutes (Levi 2026-09-16). A row per case per run is 96 times a day
    multiplied by the filed book: DEV's ten cases alone come to ~350,000 rows a
    year, more than the entire Viewpoint import, on a table whose search needed
    trigram indexes to answer at all. What the heartbeat is FOR survives the
    move intact — it exists so that its absence is noticed, and one row every 15
    minutes is a far clearer pulse than a thousand.

    What is NOT lost: `NAR1_CR_STATUS_CHANGED` still fires per case on every
    move, which is the row anybody actually goes looking for, and the Check-now
    button still writes a per-case heartbeat because a person did that to that
    case.

    A RUN THAT ASKED CR NOTHING WRITES NOTHING. Once the book has settled most
    runs have no outstanding case at all, and 96 rows a day saying "there was
    nothing to poll" is not a heartbeat, it is the noise that makes an audit
    trail unsearchable — and CLAUDE.md already keeps read-only no-ops out of it.
    Liveness for the quiet case is Railway's own cron log, which is where
    anybody asking "did it run?" looks first. The moment there IS something
    outstanding, every run says so.

    Never raises. The work is already done and committed by the time this runs;
    a Supabase hiccup writing the trail must not make a successful run report
    failure — the same discipline `log_event` itself keeps.
    """
    if not (report.get("checked") or report.get("failed")
            or report.get("unavailable")):
        return
    try:
        await log_event(
            action_type=ev.TPSI_DOC_STATUS_CHECKED,
            event_code=ev.TPSI_DOC_STATUS_CHECKED,
            entity_type="tpsi",
            entity_id="poll_cr_status",
            user_id=None,
            user_display_name=ACTOR,
            metadata={
                "job": "poll_cr_status",
                "looked_at": report.get("looked_at"),
                "checked": report.get("checked"),
                # The COUNTS here and the case numbers in the per-case
                # NAR1_CR_STATUS_CHANGED rows — a summary that repeated the
                # detail would be the volume problem again in one row.
                "changed": len(report.get("changed") or []),
                "skipped": len(report.get("skipped") or []),
                "failed": len(report.get("failed") or []),
                "truncated": bool(report.get("truncated")),
                "unavailable": report.get("unavailable"),
            },
        )
    except Exception:  # noqa: BLE001 — the trail must not undo the work
        traceback.print_exc(file=sys.stderr)


def main() -> int:
    import asyncio

    report = asyncio.run(run())
    # stdout, because Railway's cron log is the only place anybody will look.
    # Counts first, then the detail: a run that skipped everything and a run
    # with nothing to do look identical from the counts alone.
    print(f"[poll_cr_status] {report['ran_at']}: looked at {report['looked_at']}, "
          f"checked {report['checked']}, changed {len(report['changed'])}, "
          f"skipped {len(report['skipped'])}, failed {len(report['failed'])}")
    for case_no, before, after, cr_text in report["changed"]:
        print(f"  CHANGED {case_no}: {before} -> {after} (CR said {cr_text!r})")
    for case_no, reason in report["skipped"]:
        print(f"  skipped {case_no}: {reason}")
    for case_id, reason in report["failed"]:
        print(f"  FAILED  {case_id}: {reason}", file=sys.stderr)
    if report.get("truncated"):
        print(f"  NOTE: the page was full ({CASE_LIMIT} rows) — there may be "
              f"more outstanding cases. They are the most recently checked and "
              f"the next run will take them.", file=sys.stderr)
    if report.get("unavailable"):
        print(f"  CR WAS NOT USABLE: {report['unavailable']}", file=sys.stderr)

    # Non-zero on a failure OR on an unusable CR. A run with nothing due is a
    # success, and a cron service that alerted on it would train everyone to
    # ignore it — but a run that could not reach CR at all did not do its job,
    # and that has to be distinguishable from one that found nothing to do.
    return 1 if (report["failed"] or report["unavailable"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
