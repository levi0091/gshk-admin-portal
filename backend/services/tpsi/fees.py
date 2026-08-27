"""The annual registration fee for a NAR1 — computed, not guessed.

SOURCE. Companies Registry, "Major Fees under the Companies Ordinance",
https://www.cr.gov.hk/en/services/fees.htm, section
**(A) Local private companies having a share capital**, read 2026-08-27:

    | Registration of annual returns                                    | HK$   |
    | If delivered                                                      |       |
    | within 42 days after the company's return date@                   |   105 |
    | more than 42 days after but within 3 months after the return date@ |   870 |
    | more than 3 months after but within 6 months after the date@      | 1,740 |
    | more than 6 months after but within 9 months after the date@      | 2,610 |
    | more than 9 months after the company's return date@               | 3,480 |
    | @ the anniversary of the company's date of incorporation          |       |

TWO THINGS THAT ARE EASY TO GET WRONG.

1. The 3/6/9-month boundaries run from the RETURN DATE, not from the end of
   the 42-day period. A return 4 months late is in the 3-6 month band
   (HK$1,740), not the 42-days-to-3-months one.
2. "the company's return date" is the anniversary of incorporation IN THE
   RETURN'S OWN YEAR (`yearAnnualReturn`), not the incorporation date and not
   today's anniversary.

VERIFIED AGAINST A REAL SUBMISSION. CR TEST, 2026-08-27: company incorporated
2022-01-01, return year 2026 (return date 2026-01-01), delivered 2026-08-27 —
238 days, inside the >6-≤9-month band. CR billed **HK$2,610** and stamped the
document `NAR1L`. This module returns 2610.00 for those inputs; see
tests/tpsi/test_fees.py, which pins that case by name.

SCOPE, AND WHAT HAPPENS OUTSIDE IT. The table above is the one for a local
**private** company **having a share capital**. A public company's return date
is tied to its accounting reference period rather than its incorporation
anniversary, and a company limited by guarantee has no share capital — for
either, this module returns an UNCERTAIN quote at the ceiling rather than a
confident wrong number. GSHK's entire book is private companies with share
capital (5,744 of 5,930 have share classes on record), so the computed path is
the normal one and the ceiling is the exception.

`python-dateutil` is deliberately NOT used: it is only a transitive dependency
here, and a fee calculation should not break because something else dropped it.
`_add_months` is the whole of what was needed.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

#: Days after the return date within which the ordinary fee applies (CO s.662).
FILING_WINDOW_DAYS = 42

ON_TIME_FEE = Decimal("105.00")

#: (months after the return date, fee if delivered within that many months).
#: Ordered, and read as "the first band the delivery date falls inside".
LATE_BANDS: tuple[tuple[int, Decimal], ...] = (
    (3, Decimal("870.00")),
    (6, Decimal("1740.00")),
    (9, Decimal("2610.00")),
)

#: Beyond the last band. Also the ceiling used when the fee cannot be computed.
MAX_FEE = Decimal("3480.00")


class FeeError(ValueError):
    """The fee cannot be computed from the data given."""


@dataclass(frozen=True)
class FeeQuote:
    amount: Decimal
    #: Human band, for the screen: "within 42 days", "more than 6 months…".
    band: str
    #: The anniversary this was measured from — shown so an operator can check
    #: it against the company record rather than trust the arithmetic.
    return_date: date | None
    #: Signed. Negative = delivered before the deadline, 0 = on the deadline.
    days_after_deadline: int | None
    #: False when the amount is a CEILING rather than the actual fee. The UI
    #: must not present an uncertain quote as "the fee".
    certain: bool
    #: Why it is uncertain. None when certain.
    reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "amount": str(self.amount),
            "band": self.band,
            "return_date": self.return_date.isoformat() if self.return_date else None,
            "days_after_deadline": self.days_after_deadline,
            "certain": self.certain,
            "reason": self.reason,
        }


def _add_months(start: date, months: int) -> date:
    """Calendar months, clamping to the end of a short month.

    31 Jan + 1 month is 28/29 Feb, not 3 March: CR's bands are calendar months
    and rolling the overflow forward would move a filing into a more expensive
    band on the last three days of a long month.
    """
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def return_date_for(incorporation_date: date, year: int) -> date:
    """The company's return date: the incorporation anniversary in `year`.

    29 February incorporations fall back to 28 February in a common year —
    the same clamp `_add_months` uses, and the reading that keeps the return
    date inside the intended month.
    """
    day = min(
        incorporation_date.day,
        calendar.monthrange(year, incorporation_date.month)[1],
    )
    return date(year, incorporation_date.month, day)


def _coerce_date(value, field: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError as exc:
            raise FeeError(f"{field} {value!r} is not a date") from exc
    raise FeeError(f"{field} is required to work out the registration fee")


def uncertain(reason: str) -> FeeQuote:
    """A ceiling, explicitly flagged. Used wherever the fee is not computable.

    The ceiling — not the on-time fee — because this value also gates the
    deposit balance, and being optimistic there means the filing fails at CR
    with the money half-spent.
    """
    return FeeQuote(
        amount=MAX_FEE,
        band=f"up to HK${MAX_FEE}",
        return_date=None,
        days_after_deadline=None,
        certain=False,
        reason=reason,
    )


def annual_return_fee(
    *,
    incorporation_date,
    year: int,
    delivered_on=None,
    private_with_share_capital: bool = True,
) -> FeeQuote:
    """The NAR1 registration fee for a return delivered on `delivered_on`.

    `delivered_on` defaults to today in Hong Kong — CR charges by the date the
    return actually reaches it, and for the first eight hours of every HK
    working day UTC is still on yesterday, which on a band boundary is a
    different fee.
    """
    if not private_with_share_capital:
        return uncertain(
            "this tariff is the one for a local private company having a share "
            "capital; a public company's return date follows its accounting "
            "reference period and a guarantee company has no share capital"
        )

    try:
        incorporated = _coerce_date(incorporation_date, "incorporation date")
    except FeeError as exc:
        return uncertain(str(exc))

    if not year:
        return uncertain("the return year is not set on this filing")

    delivered = (
        _coerce_date(delivered_on, "delivery date") if delivered_on is not None
        else _hk_today()
    )

    rd = return_date_for(incorporated, int(year))
    if delivered < rd:
        # A return cannot be delivered before the period it reports on closes.
        return uncertain(
            f"the return date ({rd.isoformat()}) is in the future — check the "
            "return year and the incorporation date on the company record"
        )

    deadline = rd + timedelta(days=FILING_WINDOW_DAYS)
    days_after = (delivered - deadline).days

    if delivered <= deadline:
        return FeeQuote(ON_TIME_FEE, f"within {FILING_WINDOW_DAYS} days of the "
                        f"return date", rd, days_after, True)

    previous = f"more than {FILING_WINDOW_DAYS} days"
    for months, fee in LATE_BANDS:
        if delivered <= _add_months(rd, months):
            return FeeQuote(fee, f"{previous} after but within {months} months "
                            "of the return date", rd, days_after, True)
        previous = f"more than {months} months"

    return FeeQuote(MAX_FEE, f"{previous} after the return date", rd,
                    days_after, True)


def _hk_today() -> date:
    from datetime import datetime, timedelta as _td, timezone

    return (datetime.now(timezone.utc) + _td(hours=8)).date()


#: Words in `entities.company_type` that put a company OUTSIDE section (A).
_NOT_PRIVATE_SHARE_CAPITAL = ("public", "guarantee", "unlimited")


def is_private_with_share_capital(entity: dict, *, has_share_capital: bool) -> bool:
    """Whether CR's section (A) tariff applies to this company.

    THE EVIDENCE, and why it is weighted this way. `entities.company_type` is
    populated on 11 of 5,930 client companies on DEV, so it cannot be the test
    — but when it IS set and says "public" or "guarantee", that is a positive
    statement and it wins.

    Otherwise the discriminator is whether the company has a share capital at
    all, which the return itself answers: a company limited by guarantee has no
    share classes and therefore no Schedule 1. That does not distinguish a
    private company from a public non-listed one, and this returns True for
    both — the honest limit of what the data supports. It is the right default
    for GSHK's book (HK private companies limited by shares) and the failure
    mode is visible: a public company's return date would not be its
    incorporation anniversary, so the quoted return date shown beside the fee
    would be wrong on its face.
    """
    declared = (entity or {}).get("company_type") or ""
    if any(word in declared.lower() for word in _NOT_PRIVATE_SHARE_CAPITAL):
        return False
    return bool(has_share_capital)
