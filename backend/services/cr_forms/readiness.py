"""Can this company produce a valid return?

Answered on the profile, before a case opens, instead of at CR after a
chargeable and irreversible submit (PRD OQ-2 -- Levi chose to block rather than
warn). Measured against DEV when this shipped: 453 of 5,930 client companies
(7.6%) are blocked -- 252 with no registered-office country, 219 with no share
class, 18 in both.

THE RULE FOR WHAT MAY APPEAR HERE. Only fields CR marks **Mandatory = Y** in
its own worksheet. Business nature is the field this rule exists to keep out:
it is `M=N` on both NAR1 (`nature`) and NNC1 (`bnCode`), and Viewpoint has none
for any of its 5,028 rows, so blocking on it would freeze the entire book over
something CR does not require.

Everything else -- a field that is merely empty, or over CR's length -- is
*highlighted* on the profile rather than blocking, and that is computed from
the same contract on the front end.
"""
from typing import Optional

from services.tpsi.forms.cr_vocabularies import CURRENCY, resolve_country

#: The share-capital columns CR requires per class: clsOfShares, currency,
#: noOfShareIssuedOnThisCls, issuedCapital, paidUpCapital. All Mandatory=Y.
_SHARE_CLASS_REQUIRED = (
    ("class_name", "Class of Shares"),
    ("currency", "Currency"),
    ("total_issued", "Total Number"),
    ("issued_amount", "Total Amount"),
    ("total_paid", "Total Amount Paid up or Regarded as Paid up"),
)


def _problem(field: str, message: str) -> dict:
    return {"field": field, "message": message}


def filing_problems(company: dict) -> list[dict]:
    """Everything that stops this company filing, not just the first thing.

    Returns `[]` when the company is filable. Each problem names the field so
    the screen can link straight to it -- a disabled button with no explanation
    is the failure mode this is meant to avoid.
    """
    problems: list[dict] = []

    address: Optional[dict] = company.get("registered_address")
    country = ((address or {}).get("country") or "").strip()
    if not country:
        problems.append(_problem(
            "registered_address.country",
            "The registered office has no country or region. CR requires one "
            "on every return, and it must be HKG.",
        ))
    elif resolve_country(country) is None:
        # PRESENT IS NOT FILABLE. This gate used to ask only whether a country
        # was there, so 'HK-CH' -- Viewpoint's code for the Chinese Hong Kong,
        # which CR has never heard of -- opened a case that then died at Data
        # Verification. The gate has to ask the question the mapper will ask.
        problems.append(_problem(
            "registered_address.country",
            f"The registered office country {country!r} is not one CR has a "
            "code for, so the return cannot be built. Re-pick it from the "
            "country list on the company profile.",
        ))

    share_classes = company.get("share_classes") or []
    if not share_classes:
        problems.append(_problem(
            "share_classes",
            "No share capital is recorded. CR's section 11 requires at least "
            "one class of shares for a company having a share capital.",
        ))
    else:
        for share_class in share_classes:
            for column, label in _SHARE_CLASS_REQUIRED:
                value = share_class.get(column)
                if value is None or (isinstance(value, str) and not value.strip()):
                    problems.append(_problem(
                        f"share_classes.{column}",
                        f"A share class is missing {label}, which CR requires.",
                    ))
            # Same rule as the country: a currency that is merely present is
            # not a currency CR takes. Its list is 54 codes and four are NOT
            # ISO -- it wants RMB where ISO says CNY. One real share class in
            # DEV is denominated 'CNY' and another 'XXX'.
            currency = (share_class.get("currency") or "").strip().upper()
            if currency and currency not in CURRENCY:
                problems.append(_problem(
                    "share_classes.currency",
                    f"{currency!r} is not a currency CR accepts. Its list is "
                    "not ISO 4217 — renminbi is 'RMB', not 'CNY'. Re-pick it "
                    "on the Share Capital card.",
                ))
    return problems
