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

router = APIRouter()

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
