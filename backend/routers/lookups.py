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
from services.cr_forms.record_types import RECORD_TYPES
from services.tpsi.forms.cr_vocabularies import (
    BUSINESS_NATURE,
    COMPANY_TYPE,
    COUNTRY_OPTIONS,
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

#: CR's three company types. Deliberately NOT sorted — Private first, because
#: it is what 5,711 of the 5,930 companies in the book are.
#:
#: `entities.company_type` held free text before this (Viewpoint's own
#: descriptions, e.g. "Private company limited by shares"). Those values are
#: not dropped: `optionsFor` on the front end always offers the stored value
#: back, flagged, so a legacy record renders rather than silently blanking on
#: the next save.
_CR_COMPANY_TYPE = [{"code": code, "label": label} for code, label in COMPANY_TYPE]

#: The registers NAR1 s16 asks a company to locate, in render order.
_CR_RECORD_TYPE = [{"code": code, "label": label} for code, label in RECORD_TYPES]

#: CR's Country & Region sheet, for every field CR validates a country on:
#: an address's `ctryRegion` and a passport's `indvPptIssCtry`.
#:
#: `lookup_values.country` is NOT usable for these. It carries 270 Viewpoint
#: rows, 20 of which resolve to no CR code at all -- US states, UK constituent
#: countries, Labuan, Zaire, and three labelled only in Chinese. Picking the
#: Chinese Hong Kong stored 'HK-CH' and killed the return at Data
#: Verification. Same rule as the district and currency lists above: the
#: vocabulary that decides whether a filing is accepted owns the dropdown.
#:
#: `lookup_values.country` stays for `place_of_birth` and the other fields CR
#: never sees.
_CR_COUNTRY = [{"code": code, "label": label} for code, label in COUNTRY_OPTIONS]

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
    grouped["cr_company_type"] = _CR_COMPANY_TYPE
    grouped["cr_record_type"] = _CR_RECORD_TYPE
    grouped["cr_country"] = _CR_COUNTRY
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
