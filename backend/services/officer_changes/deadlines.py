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


def reply_by_default(deadline: date | None, today: date) -> date:
    """`max(deadline - 5 days, today + 2 days)`; with no deadline, today + 5.

    A case with no dated change used to have no default, and the operator had
    to choose. Since Jacqueline's A1 every change may be undated when the draft
    goes out ("let us fill in the most recent date"), so "no deadline yet" is
    the common case and five days is the same lead the deadline rule gives."""
    if deadline is None:
        return today + timedelta(days=REPLY_LEAD_DAYS)
    return max(deadline - timedelta(days=REPLY_LEAD_DAYS),
               today + timedelta(days=REPLY_MIN_DAYS))


#: NAR1's filing window: an annual return is due within 42 days after the
#: incorporation anniversary. An ND2B dated to an anniversary older than this is
#: not being filed "with the NAR1", which is the whole reason for the default.
ANNIVERSARY_WINDOW_DAYS = 42


def _anniversary_in(year: int, born: date) -> date:
    try:
        return born.replace(year=year)
    except ValueError:  # 29 February in a common year
        return date(year, 2, 28)


def anniversary_default(incorporation_date, *, open_return_date=None,
                        today: date | None = None) -> date | None:
    """The effective date a new ND2B line starts with (Jacqueline B1).

    "Unless there is any special request, most of the time we will default the
    effective date to the anniversary date ... so we can submit both forms
    together." So: the return date of the company's open NAR1 when it has one,
    else its most recent anniversary when that is no more than 42 days ago (the
    NAR1 window), else None — an older anniversary would make the ND2B overdue
    the moment it was opened. Never a date after today: CR records what has
    happened."""
    today = today or hk_today()
    open_day = _as_date(open_return_date)
    if open_day is not None and open_day <= today:
        return open_day
    born = _as_date(incorporation_date)
    if born is None:
        return None
    anniversary = _anniversary_in(today.year, born)
    if anniversary > today:
        anniversary = _anniversary_in(today.year - 1, born)
    if anniversary <= born:
        return None
    return anniversary if (today - anniversary).days <= ANNIVERSARY_WINDOW_DAYS else None
