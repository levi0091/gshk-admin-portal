"""Beneficial-owner vocabularies: what kind of controller, and how control is held.

Both lists are the portal's own, NOT CR's -- neither NAR1 nor NNC1 carries a
single `beneficial_owners.*` field (check `contract.py`: nothing maps to that
table). They come from the Companies Ordinance Part 12 Division 2A, which is
what the Significant Controllers Register the portal keeps is FOR.

They live here rather than in `lookup_values` for the same reason CR's own
vocabularies do (see `tpsi/forms/cr_vocabularies.py`): the list that decides
whether a write is accepted must be the same object the dropdown is drawn from.
A seeded copy is a second list, and a second list drifts.

WHY THE STORED VALUES ARE CODES AND NOT THE SENTENCES. `nature_of_control`
holds `over_25_percent`, never the 63-character sentence -- the wording of
s.653D condition (b) is the legislature's and it has been amended before. A row
that stored the prose would have to be rewritten by a migration when the prose
changes; a row that stores the code just renders differently.

GRANDFATHERING, as everywhere else in this repo. `owner_type` has carried free
text since the Viewpoint ETL. `validate` accepts a value already on the row so a
legacy record can be edited without first being corrected, and refuses only a
NEW value outside the list -- the same rule `company_type` and the HKID check
digit follow.
"""
from typing import Optional

from fastapi import HTTPException

#: What kind of controller this party is. Order is render order.
OWNER_TYPES: list[tuple[str, str]] = [
    ("ubo", "Ultimate Beneficial Owner"),
    ("significant_controller", "Significant Controller"),
]

#: HOW control is held -- Companies Ordinance s.653D, the two conditions GSHK
#: records. Order is render order.
NATURE_OF_CONTROL: list[tuple[str, str]] = [
    ("over_25_percent",
     "Holds more than 25% of the issued shares of the company"),
    ("significant_influence",
     "Has the right to exercise, or actually exercises, significant influence "
     "or control over the company"),
]

OWNER_TYPE_CODES = {code for code, _ in OWNER_TYPES}
NATURE_OF_CONTROL_CODES = {code for code, _ in NATURE_OF_CONTROL}

#: Viewpoint spellings that mean one of ours. Mapped rather than grandfathered
#: because these are the SAME fact under another name -- leaving them as free
#: text would put two codes for one concept in the dropdown.
_OWNER_TYPE_ALIASES = {
    "ubo": "ubo",
    "ultimate beneficial owner": "ubo",
    "beneficial owner": "ubo",
    "significant controller": "significant_controller",
    "registrable person": "significant_controller",
    "sc": "significant_controller",
}


def normalise_owner_type(value: Optional[str]) -> Optional[str]:
    """A stored owner type as a code, or the value unchanged if unrecognised."""
    if not value:
        return value
    text = str(value).strip()
    return _OWNER_TYPE_ALIASES.get(text.lower(), text)


def validate(field: str, value: Optional[str], current: Optional[str] = None) -> Optional[str]:
    """Refuse a NEW value outside the list; always allow back what is stored.

    `field` is the column name, so the refusal names the field the operator is
    looking at rather than a variable name from in here.
    """
    if value in (None, ""):
        return None
    allowed, options = (
        (OWNER_TYPE_CODES, OWNER_TYPES) if field == "owner_type"
        else (NATURE_OF_CONTROL_CODES, NATURE_OF_CONTROL)
    )
    text = normalise_owner_type(value) if field == "owner_type" else str(value).strip()
    if text in allowed or text == (current or ""):
        return text
    raise HTTPException(
        status_code=422,
        detail=(f"{value!r} is not a value {field} accepts. It takes "
                + ", ".join(f"{code} ({label})" for code, label in options) + "."),
    )
