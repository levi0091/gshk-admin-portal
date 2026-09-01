"""Approve a NAR1 the client never answered, 14 days after it was sent.

Spec §5. Run from a Railway cron service:

    python -m jobs.auto_approve_nar1        at  0 16 * * *   (00:00 Hong Kong)

WHY A CRON SERVICE AND NOT AN IN-PROCESS SCHEDULER. An in-process timer fires
once per replica, so the moment Railway scales the API past one instance every
overdue case would be approved twice — and `audit_log` is insert-only, so the
second row could never be taken back. A GitHub Actions schedule was the other
option and was rejected for needing a service credential in repo secrets and
firing at whichever URL it happened to be configured with.

WHAT IT WILL NOT TOUCH, AND WHY EACH EXCLUSION MATTERS.

  already answered      an approval or a rejection is the client's own decision
                        and this job has no standing to overwrite it
  never sent            a case with no verification_sent_at was never asked, so
                        there is no silence to interpret
  filed at CR           approving a return the register already holds would put
                        a client decision in the trail AFTER the filing it
                        supposedly authorised
  filed off-portal      the same fact arrived at differently (manual_receipt)
  superseded tokens     the document those links approve was discarded when
                        verification was restarted; the client's silence about
                        a withdrawn request is not consent to the new one

IDEMPOTENT. A second run the same night finds every case it approved already
carrying `client_approved`, and changes nothing.

PER-CASE ISOLATION. One case that fails does not abandon the rest: each is
written on its own and the run reports how many were approved, skipped and
failed. A job that stopped at the first bad row would leave the rest of the
book unprocessed until somebody noticed.
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone

from db.supabase import get_supabase
from services import audit_events as ev, nar1_approvals, nar1_cases
from services.audit_service import log_event

#: Read once per run, so every case in one run gets the same reading of "now"
#: and a case cannot be judged against a clock that moved mid-loop.
def _now() -> datetime:
    return datetime.now(timezone.utc)


def due_tokens(now: datetime | None = None) -> list[dict]:
    """Outstanding approval links whose 14 days have run out.

    Filtered in the DATABASE, not in Python: the book is ~5,900 companies and a
    scan that pulled every token to decide in the loop would grow with history
    rather than with what is actually due.
    """
    moment = (now or _now()).isoformat()
    return (
        get_supabase().table("nar1_client_approvals")
        .select("id,nar1_case_id,recipient_email,recipient_name,expires_at")
        .is_("outcome", None)
        .lt("expires_at", moment)
        .order("expires_at")
        .execute()
        .data
        or []
    )


def skip_reason(case: dict) -> str | None:
    """Why this case must not be auto-approved, or None.

    Returned as text rather than a boolean so the run's report says WHICH
    exclusion applied — "skipped 41" tells an operator nothing they can act on.
    """
    if case.get("client_approved") is not None:
        return "the client already answered"
    if not case.get("verification_sent_at"):
        return "no verification was ever sent"
    if case.get("manual_receipt") or case.get("manual_submitted_at"):
        return "already filed off-portal"
    try:
        filing = nar1_cases.blocking_filing(case["id"])
    except Exception as exc:  # noqa: BLE001 — an unreadable ledger is a reason
        return f"the filing ledger could not be read ({exc})"  # to skip, not to approve
    if filing and filing.get("stage") in nar1_cases.CR_FILED_STAGES:
        return "the Companies Registry already holds this return"
    return None


async def approve(case: dict, token_row: dict, now: datetime) -> None:
    """Record the timeout approval on one case, and say so in the trail."""
    stamp = now.isoformat()
    nar1_cases.update_case(case["id"], {
        "client_approved": True,
        "client_response_at": stamp,
        "client_approval_source": nar1_approvals.SOURCE_SYSTEM_TIMEOUT,
        # NO person and NO name. Nobody approved this. Writing the last
        # recipient's name here would produce exactly the sentence spec §5
        # forbids — a director who never answered appearing to have agreed.
        "client_approval_person_id": None,
        "client_approval_name": None,
    })
    # The links stop working the moment the case is decided, for the same
    # reason a first approval supersedes the others: one return, one decision.
    nar1_approvals.supersede_outstanding(case["id"])

    await log_event(
        user_id=None,
        user_display_name="G-FlowDesk (automatic)",
        action_type=ev.CLIENT_APPROVAL_AUTO_APPROVED,
        event_code=ev.CLIENT_APPROVAL_AUTO_APPROVED,
        # audit_log.case_id holds the ENTITY id — routers/cases.py::_audit_target.
        case_id=case.get("entity_id"),
        entity_type="nar1_case",
        entity_id=case["id"],
        new_value="approved",
        metadata={
            "case_no": case.get("case_no"),
            "channel": "system_timeout",
            "window_days": nar1_approvals.APPROVAL_WINDOW_DAYS,
            "verification_sent_at": case.get("verification_sent_at"),
            "expired_at": token_row.get("expires_at"),
            # Who was asked and did not answer. The fact being recorded is a
            # SILENCE, and a silence is only meaningful if you can say whose.
            "last_recipient": token_row.get("recipient_email"),
        },
    )


async def run(now: datetime | None = None) -> dict:
    """One pass. Returns {"approved": n, "skipped": n, "failed": n, ...}."""
    moment = now or _now()
    approved, skipped, failed = 0, [], []
    seen: set = set()

    for token_row in due_tokens(moment):
        case_id = token_row.get("nar1_case_id")
        # A board of three produced three tokens for one case. The first decides
        # it; the rest are already superseded by then, but the guard here means
        # the ordering of the query cannot produce three attempts either.
        if not case_id or case_id in seen:
            continue
        seen.add(case_id)

        try:
            case = nar1_cases.get_case(case_id)
        except LookupError:
            skipped.append((case_id, "the case no longer exists"))
            continue
        except Exception as exc:  # noqa: BLE001
            failed.append((case_id, str(exc)))
            continue

        reason = skip_reason(case)
        if reason:
            skipped.append((case_id, reason))
            continue

        try:
            await approve(case, token_row, moment)
            approved += 1
        except Exception as exc:  # noqa: BLE001 — one bad case must not abandon
            failed.append((case_id, str(exc)))   # the rest of the book
            traceback.print_exc(file=sys.stderr)

    report = {
        "ran_at": moment.isoformat(),
        "approved": approved,
        "skipped": len(skipped),
        "failed": len(failed),
        "skipped_detail": skipped,
        "failed_detail": failed,
    }
    return report


def main() -> int:
    import asyncio

    report = asyncio.run(run())
    # stdout, because Railway's cron log is the only place anybody will look.
    # Counts first, then the reasons: a run that skipped everything and a run
    # with nothing to do look identical from the counts alone.
    print(f"[auto_approve_nar1] {report['ran_at']}: "
          f"approved {report['approved']}, skipped {report['skipped']}, "
          f"failed {report['failed']}")
    for case_id, reason in report["skipped_detail"]:
        print(f"  skipped {case_id}: {reason}")
    for case_id, reason in report["failed_detail"]:
        print(f"  FAILED  {case_id}: {reason}", file=sys.stderr)
    # Non-zero ONLY on a failure. A run with nothing due is a success, and a
    # cron service that alerted on it would train everyone to ignore it.
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
