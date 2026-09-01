"""Reference lookups that drive the form dropdowns (PBI-41).

Gender, nationality, marital status and the rest were free-text inputs, which
lets the same concept in under a dozen spellings. These are the controlled
vocabularies, lifted from Viewpoint's own LookValues (see migration 013).

Read-only and identical for every user, so this is deliberately cheap: one query
for the whole set, cached in-process. The alternative — a request per category
per form — was six round trips to render one page.
"""
import time

from fastapi import APIRouter, Depends, HTTPException

from middleware.auth import require_any_permission
from db.supabase import get_supabase
from services.tpsi.forms.cr_vocabularies import (
    BUSINESS_NATURE,
    CURRENCY,
    DISTRICT_CODES,
)

router = APIRouter()

#: CR's Hong Kong District codes, served alongside Viewpoint's vocabularies but
#: NOT stored with them.
#:
#: For a HK address CR reads District as a controlled code, not free text:
#: sending "WAN CHAI" was refused live on 2026-08-27 ("Please input valid
#: District") while "WANCHAI" passed. The address form therefore needs the same
#: 125 values `nar1_mapper` validates against — and seeding them into
#: `lookup_values` would create a SECOND copy that can drift from the one that
#: decides whether a filing is accepted. One owner per vocabulary: CR owns
#: this, so it is read from CR's own set at import time.
#:
#: The label is the code. CR's codes are names with the spaces removed, and
#: "WANCHAI" cannot be turned back into "Wan Chai" reliably — inventing a
#: prettier label risks showing an operator something CR has never heard of.
_CR_DISTRICTS = [{"code": code, "label": code} for code in sorted(DISTRICT_CODES)]

#: CR's 88 business nature codes. The label IS the description, because picking
#: a code is what fills the description in — CR derives `natureDesc` from
#: `nature` after web-form validation, so the two are never independently
#: chosen. Viewpoint holds no business nature whatsoever (BusNames.BusNature is
#: empty on all 5,028 rows), so this list is the only guard against an operator
#: inventing a code.
_CR_BUSINESS_NATURE = [
    {"code": code, "label": description}
    for code, description in sorted(BUSINESS_NATURE.items())
]

#: CR's 54 currency codes, which are NOT ISO 4217 — CR wants RMB, NTD, WON and
#: NIS where ISO says CNY, TWD, KRW and ILS. `lookup_values` separately holds
#: 162 ISO codes lifted from Viewpoint; offering those on a share capital form
#: produces a filing CR refuses, so anything bound for CR reads this instead.
_CR_CURRENCY = [
    {"code": code, "label": f"{code} - {description}"}
    for code, description in sorted(CURRENCY.items())
]

# Reference data for both the company and the person forms — a role holding
# either one may read it.
require_lookup_read = require_any_permission(("companies", "read"), ("persons", "read"))

# Reference data changes when someone ships a migration, not during a session.
_TTL = 300.0
_cache: tuple[float, dict[str, list[dict]]] | None = None


def clear_cache() -> None:
    global _cache
    _cache = None


def _all() -> dict[str, list[dict]]:
    global _cache
    if _cache and time.monotonic() - _cache[0] < _TTL:
        return _cache[1]

    sb = get_supabase()
    rows = (
        sb.table("lookup_values")
        .select("category, code, label")
        .eq("is_active", True)
        .order("category").order("sort_order")
        .limit(5000)          # PostgREST caps at 1000 by default; the seed is ~660
        .execute().data
    ) or []

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["category"], []).append(
            {"code": row["code"], "label": row["label"]}
        )
    # Rides along with the Viewpoint categories so the address form costs no
    # extra round trip — the whole point of serving these in one response.
    grouped["cr_district"] = _CR_DISTRICTS
    grouped["cr_business_nature"] = _CR_BUSINESS_NATURE
    grouped["cr_currency"] = _CR_CURRENCY
    _cache = (time.monotonic(), grouped)
    return grouped


@router.get("")
async def list_lookups(user=Depends(require_lookup_read)):
    """Every category at once — the profile forms need most of them anyway."""
    return _all()


@router.get("/{category}")
async def list_lookup(category: str, user=Depends(require_lookup_read)):
    values = _all().get(category)
    if values is None:
        raise HTTPException(404, f"unknown lookup category: {category}")
    return values
