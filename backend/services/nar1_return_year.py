"""Which annual return a case is for — CR's `yearAnnualReturn` — and which it may be.

THE ONE FIELD CR TAKES, AND THE ONLY LEVER THERE IS (Levi 2026-09-18). Every
source CR publishes agrees:

  * the parameter worksheet embedded in `TPSI API Interface v1.0.14.docx`:
        yearAnnualReturn | Integer | Mandatory Y | 4 | "Year of annual return
        to be filed (Private Company)"
        dateReturnMadeUp | String  | Mandatory N | 10 | "Date to which this
        Return is Made Up. To be filled in by system after Web-Form validation
        (6.6)"
  * CR's own `validate_NAR1(Private Company, Schedule 1).xml` sends
    `<cr:yearAnnualReturn>2020</cr:yearAnnualReturn>` and no date at all;
  * CR's `submit_NAR1.xml` — the same company, BR 00000001, after validation —
    carries `yearAnnualReturn 2020` AND the `dateReturnMadeUp 31/10/2020` CR
    wrote itself.

So a return is identified by its YEAR, and CR derives the made-up date from its
own register: the anniversary of incorporation in that year. There is no date to
send. Until this module existed every build passed no year and got
`nar1_prepare.hk_year()` — so every NAR1 G-FlowDesk ever prepared was the
current calendar year's, and a company four years behind could only ever file
this one. (On DEV, 50 of 50 filings carry 2026.)

WHERE IT LIVES: `nar1_cases.ar_period_year`. The column has existed since the
PBI-38 schema (migration 003) and was never written; the case header and the
public approval page already read it. One case is one return, so the year is a
fact about the case, chosen at Client Verification — the first stage, and the
one where the client is shown the return they will be asked to approve.

RESOLUTION, in this order, so no case in flight changes under anybody:

  1. `ar_period_year`, once somebody chose it or a send/prepare fixed it;
  2. the year already in the case's filing XML — every legacy case, whose
     return was built with `hk_year()` before this existed;
  3. the default: the current year in Hong Kong, clamped into the range below.
     That is what `hk_year()` always was, and it is the same year the
     dashboard's `days_to_anniversary` is measured to (migration 033), so a
     case reading "in 22 days" is for the return due in 22 days.

THE RANGE. From the first return (the year after incorporation — the first
anniversary) to the NEXT return that falls due on or after today. Every year in
it is either already due, and filable now, or the upcoming one: GSHK sends the
return to the client ahead of the anniversary (Levi 2026-09-17), so the upcoming
year has to be choosable at stage 1 even though CR will not validate it until
its return date. Nothing later is: that is a year early, and no client should
be asked to approve it.

A company with no incorporation date on record has no first year and no return
dates. It is offered the last `UNKNOWN_BACKLOG_YEARS` years up to this one and
told why the dates are missing; CR, which has the date, remains the check.

ONE LIVE CASE PER COMPANY PER YEAR. Four missed years are four cases (2023,
2024, 2025, 2026), and nothing stops a company holding several open cases — two
outstanding returns is normal. Two cases for the SAME year is a return filed
twice. `held_years` answers it here and migration 047's partial unique index
settles the race in Postgres. A closed case holds nothing: closing is how a
mistaken case gives its year back.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from db.supabase import get_supabase
from services.tpsi import fees
from services.tpsi import filings as tpsi_filings

_TABLE = "nar1_cases"

#: How far back a company with NO incorporation date may reach. There is no
#: first return to anchor on, and an unbounded list is not a choice anybody can
#: make. Ten years is well beyond any backlog GSHK files; CR checks the real
#: date either way.
UNKNOWN_BACKLOG_YEARS = 10

#: Where the resolved year came from. The screen says which, because "you chose
#: 2024" and "we assumed 2026" are different statements to be looking at.
SOURCE_CASE = "case"
SOURCE_FILING = "filing"
SOURCE_DEFAULT = "default"

#: `yearAnnualReturn` in a stored fragment. The fragments carry undeclared
#: prefixes (`cr:`), so a regex on the local name is sturdier than a parse that
#: has to wrap the fragment first — and this is the only element read.
_YEAR_IN_XML = re.compile(r"<(?:[\w.-]+:)?yearAnnualReturn>\s*(\d{4})\s*<")


class YearRefused(ValueError):
    """The year cannot be set on this case. `.status` is the HTTP answer.

    400 for a year outside the range (the request is wrong), 409 for a case that
    is locked or a year another case already holds (the request is fine; the
    state is not).
    """

    def __init__(self, message: str, *, status: int = 400,
                 held_by: dict | None = None):
        super().__init__(message)
        self.status = status
        self.held_by = held_by


def hk_today() -> date:
    """Today in Hong Kong — the day CR counts in, not Railway's UTC day."""
    return fees._hk_today()


def incorporated(entity: dict | None) -> date | None:
    """`entities.incorporation_date` as a date, or None. Never raises."""
    value = (entity or {}).get("incorporation_date")
    if not value:
        return None
    try:
        return fees._coerce_date(value, "incorporation date")
    except fees.FeeError:
        return None


def year_in_xml(xml: str | None) -> int | None:
    """The `yearAnnualReturn` a stored fragment carries, or None."""
    match = _YEAR_IN_XML.search(xml or "")
    return int(match.group(1)) if match else None


def filing_year(filing: dict | None) -> int | None:
    """The year a filing was built for — CR's copy first, it is what is filed."""
    filing = filing or {}
    return (year_in_xml(filing.get("validated_xml"))
            or year_in_xml(filing.get("request_xml")))


def return_date(inc: date | None, year: int) -> date | None:
    """The anniversary of incorporation in `year` — the date CR makes it up to.

    `fees.return_date_for` is the one implementation of that (29 February
    included), shared with the fee, the submit gate and the renderer's section
    4, so none of them can disagree about which day a return is for.
    """
    if inc is None:
        return None
    return fees.return_date_for(inc, int(year))


def first_year(inc: date | None) -> int | None:
    """The first annual return a company files: its first anniversary's year."""
    return inc.year + 1 if inc else None


def earliest_year(inc: date | None, today: date) -> int:
    first = first_year(inc)
    return first if first is not None else today.year - UNKNOWN_BACKLOG_YEARS


def latest_year(inc: date | None, today: date) -> int:
    """The next return that falls due on or after today.

    This year's, if its anniversary has not passed; next year's if it has. A
    company whose first anniversary is still ahead gets that first year.
    Without an incorporation date there is no anniversary to measure, so the
    ceiling is this calendar year.
    """
    if inc is None:
        return today.year
    this_year = return_date(inc, today.year)
    latest = today.year if this_year >= today else today.year + 1
    return max(latest, first_year(inc))


def default_year(inc: date | None, today: date) -> int:
    """This year in Hong Kong, clamped into the range — what `hk_year()` was."""
    return min(max(today.year, earliest_year(inc, today)),
               latest_year(inc, today))


def resolve(case: dict | None, filing: dict | None, entity: dict | None = None,
            today: date | None = None) -> tuple[int, str]:
    """(year, source) for this case. See the module docstring for the order."""
    stored = (case or {}).get("ar_period_year")
    if stored:
        return int(stored), SOURCE_CASE
    built = filing_year(filing)
    if built:
        return built, SOURCE_FILING
    today = today or hk_today()
    return default_year(incorporated(entity), today), SOURCE_DEFAULT


def check_range(year, inc: date | None, today: date,
                company_name: str | None = None) -> int:
    """The year as an int, or YearRefused saying why it cannot be chosen."""
    try:
        year = int(year)
    except (TypeError, ValueError):
        raise YearRefused(f"{year!r} is not a year")
    earliest = earliest_year(inc, today)
    latest = latest_year(inc, today)
    who = company_name or "this company"
    if year < earliest:
        if inc is not None:
            raise YearRefused(
                f"{who} was incorporated on {_hk(inc)}, so its first annual "
                f"return is for {earliest} (made up to {_hk(return_date(inc, earliest))}). "
                f"There is no {year} return to file.")
        raise YearRefused(
            f"{year} is more than {UNKNOWN_BACKLOG_YEARS} years ago. {who} has "
            f"no incorporation date on record, so the portal cannot tell which "
            f"returns exist — record the incorporation date on the company "
            f"profile to reach earlier years.")
    if year > latest:
        if inc is not None:
            raise YearRefused(
                f"the {year} return is made up to {_hk(return_date(inc, year))}, "
                f"which is more than a year away. The latest return that can be "
                f"prepared is {latest} (made up to "
                f"{_hk(return_date(inc, latest))}).")
        raise YearRefused(
            f"{year} is in the future. {who} has no incorporation date on "
            f"record, so {latest} is the latest year that can be chosen.")
    return year


def held_years(entity_id: str, *, excluding_case_id: str | None = None) -> dict:
    """{year: {case_id, case_no}} for every OTHER live case of this company.

    Only a STORED year counts. A case that has never chosen or fixed one holds
    nothing yet, and fixes it at its first send or prepare — where the same
    question is asked again (`claim`). Closed cases hold nothing.
    """
    rows = (
        get_supabase().table(_TABLE)
        .select("id, case_no, ar_period_year")
        .eq("entity_id", entity_id)
        .is_("closed_at", "null")
        .not_.is_("ar_period_year", "null")
        .execute()
        .data
    ) or []
    held = {}
    for row in rows:
        if excluding_case_id and row.get("id") == excluding_case_id:
            continue
        held[int(row["ar_period_year"])] = {
            "case_id": row.get("id"), "case_no": row.get("case_no")}
    return held


def refuse_if_held(entity_id: str, case_id: str, year: int) -> None:
    """YearRefused (409) when another live case of the company has this year."""
    other = held_years(entity_id, excluding_case_id=case_id).get(int(year))
    if other:
        raise YearRefused(
            f"case {other.get('case_no') or other.get('case_id')} is already "
            f"filing this company's {year} annual return. One return per year: "
            f"choose a different year, or close that case first if it was "
            f"opened by mistake.",
            status=409, held_by=other)


def lock_reason(case: dict, filing: dict | None, year: int) -> str | None:
    """Why the year on this case can no longer be changed, or None.

    FIXED THE MOMENT THE CLIENT IS ASKED. What a director approves is the
    return for one year; filing another year under that approval is filing
    something nobody agreed to. `Restart verification` clears the send and
    supersedes the filing, which is exactly what unlocks it — and is the one
    sanctioned way back to stage 1.

    A validated snapshot locks it for the same reason in the other direction:
    CR has checked the return for that year, and the frozen XML must not be
    rebuilt under it.
    """
    stage = (filing or {}).get("stage")
    if case.get("closed_at"):
        return "this case is closed"
    if (case.get("manual_submitted_at") or case.get("manual_receipt")
            or stage in tpsi_filings.TERMINAL_STAGES):
        return f"the {year} return has already been filed"
    if case.get("verification_sent_at"):
        return (f"the {year} return has been sent to the client. Restart "
                f"verification to choose a different year — the client has to "
                f"approve the return for the year that is filed")
    if filing and stage not in tpsi_filings.REBUILDABLE_STAGES:
        return (f"CR has validated the {year} return. Restart verification to "
                f"choose a different year")
    return None


def claim(case: dict, year: int) -> bool:
    """Store `year` on a case that has none yet. Returns whether it wrote.

    Called by the send and by prepare, so a case whose year was only ever the
    default gets it fixed at the moment it starts to matter: the email names it
    and the filing is built for it. Refuses (409) a year another live case
    already holds — the default can collide as easily as a choice can.
    """
    if case.get("ar_period_year"):
        return False
    refuse_if_held(case["entity_id"], case["id"], year)
    (get_supabase().table(_TABLE)
     .update({"ar_period_year": int(year)})
     .eq("id", case["id"])
     .is_("ar_period_year", "null")
     .execute())
    return True


def _fee(inc: date | None, year: int, today: date) -> dict | None:
    """What CR would charge for this year's return delivered today, or None.

    None for a return not yet due: there is no band to be in, and quoting the
    on-time fee for a return CR will not accept yet would be a number with no
    meaning.
    """
    rd = return_date(inc, year)
    if rd is None or rd > today:
        return None
    quote = fees.annual_return_fee(incorporation_date=inc, year=year,
                                   delivered_on=today)
    return quote.as_dict()


def options(inc: date | None, today: date, held: dict | None = None) -> list:
    """Every choosable year, newest first, each with what the operator needs.

    `due` is None when there is no incorporation date — "we cannot say", which
    the screen must not render as "not due".
    """
    held = held or {}
    out = []
    for year in range(latest_year(inc, today), earliest_year(inc, today) - 1, -1):
        rd = return_date(inc, year)
        out.append({
            "year": year,
            "return_date": rd.isoformat() if rd else None,
            # The 42nd day after — the last on which the HK$105 fee applies.
            "deadline": (rd + timedelta(days=fees.FILING_WINDOW_DAYS)).isoformat()
                        if rd else None,
            "due": (rd <= today) if rd else None,
            # Signed, like the dashboard's figure turned round: positive means
            # the return date has passed by that many days.
            "days_since_return_date": (today - rd).days if rd else None,
            "fee": _fee(inc, year, today),
            "held_by": held.get(year),
        })
    return out


def _hk(value: date | None) -> str:
    """DD/MM/YYYY — the way CR and the printed form write a date."""
    return value.strftime("%d/%m/%Y") if value else "an unknown date"
