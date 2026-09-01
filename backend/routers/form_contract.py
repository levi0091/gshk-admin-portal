"""What CR requires of each profile field, served to the screens.

The profile forms used to carry their own idea of which fields matter and how
long they may be, and CR's idea lived in `nar1_mapper`. The two could disagree
without anything noticing, and the way you found out was a rejected filing --
an over-long address line arrives as a ValueError out of `nar1.validate` weeks
after someone typed it, and reads as a crash.

This serves the single answer both sides use: from the generated contract, for
each profile column, the strictest length CR imposes anywhere it appears and
whether CR requires it in any context we hold.

Read-only and identical for every user, so it is computed once at import.
"""
from collections import defaultdict

from fastapi import APIRouter, Depends

from middleware.auth import require_any_permission
from services.cr_forms import contract

router = APIRouter()

require_contract_read = require_any_permission(("companies", "read"),
                                               ("persons", "read"))


def _build() -> dict[str, dict[str, dict]]:
    """table -> column -> {max_length, mandatory, cr_fields}.

    A column is reachable from several CR fields (NAR1 and NNC1 spell the same
    thing differently, and an address block repeats). The STRICTEST length wins
    -- a value that fits `indvEngOname` at 110 but not `engName` at 50 is one
    CR would refuse in the second context -- and mandatory is true if CR
    requires it anywhere, because that is the context the case may need.
    """
    grouped: dict[tuple[str, str], list] = defaultdict(list)
    for (form, path), entry in contract.FIELDS.items():
        disposition, target, mandatory, max_length = entry
        if disposition != "mapped" or "." not in target:
            continue
        table, column = target.split(".", 1)
        grouped[(table, column)].append(
            (path.rsplit("/", 1)[-1], form, mandatory, max_length))

    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for (table, column), occurrences in grouped.items():
        lengths = [length for _, _, _, length in occurrences if length]
        out[table][column] = {
            "max_length": min(lengths) if lengths else None,
            "mandatory": any(mandatory for _, _, mandatory, _ in occurrences),
            # Which CR fields this column feeds, so an operator asking "why is
            # this capped at 50?" can be answered without reading the mapper.
            "cr_fields": sorted({name for name, _, _, _ in occurrences}),
        }
    return {table: columns for table, columns in out.items()}


_CONTRACT = _build()


@router.get("")
async def get_form_contract(user=Depends(require_contract_read)):
    """CR's requirements per profile column, for the profile screens."""
    return _CONTRACT
