"""When an officer change is due at CR, and when the client is asked to answer by.

PRD §10.6: an ND2A / ND2B is due 15 days after the change it reports. A case
can report several changes, so it is due 15 days after the EARLIEST — the one
whose clock runs out first. Late filing is an offence but carries no fee, so
the deadline marks a case overdue and never refuses it (PRD E-13).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

FILING_WINDOW_DAYS = 15
#: The client is asked to answer this many days before the filing deadline...
REPLY_LEAD_DAYS = 5
#: ...but never given less than this to read the form (spec B-8, PRD AS-5).
REPLY_MIN_DAYS = 2

_HK = ZoneInfo("Asia/Hong_Kong")


def hk_today() -> date:
    """Railway and Supabase run in UTC; a change made at 01:00 in the office is
    the previous day there."""
    return datetime.now(_HK).date()


def _as_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def change_dates(entries: list[dict]) -> list[date]:
    """Every date a change on the case took effect, omitted ND2B lines excluded."""
    dates = []
    for entry in entries:
        if entry.get("kind") == "change":
            for item in entry.get("items") or []:
                if not item.get("omitted"):
                    dates.append(_as_date(item.get("effective_date")))
        else:
            dates.append(_as_date(entry.get("effective_date")))
    return [d for d in dates if d]


def filing_deadline(entries: list[dict]) -> date | None:
    """Earliest effective date among entries and non-omitted items + 15 days."""
    dates = change_dates(entries)
    return min(dates) + timedelta(days=FILING_WINDOW_DAYS) if dates else None


def reply_by_default(deadline: date | None, today: date) -> date | None:
    """`max(deadline - 5 days, today + 2 days)`; None with no deadline, when the
    operator must choose (the send refuses without one)."""
    if deadline is None:
        return None
    return max(deadline - timedelta(days=REPLY_LEAD_DAYS),
               today + timedelta(days=REPLY_MIN_DAYS))
