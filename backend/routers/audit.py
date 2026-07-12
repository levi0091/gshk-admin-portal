from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from middleware.auth import require_permission
from db.supabase import get_supabase

router = APIRouter()

_DEFAULT_PAGE_SIZE = 100
_MAX_PAGE_SIZE = 500

# Whitelisted — `sort` reaches PostgREST's order clause.
_SORTABLE = {
    "created_at", "action_label", "event_code", "company_name",
    "old_value", "new_value", "user_display_name", "case_id",
}


@router.get("/types")
async def list_event_types(
    user=Depends(require_permission("audit_trail", "read")),
):
    """The event-type registry (migration 012) — the shared action vocabulary.

    Viewpoint codes plus the G-FlowDesk-only ones. This is the maintainable list:
    new G-FlowDesk actions are added here as the workflow grows.
    """
    sb = get_supabase()
    return (
        sb.table("audit_event_types").select("*")
        .eq("is_active", True).order("name").execute().data
    ) or []


@router.get("/")
async def get_global_audit(
    limit: int = Query(default=_DEFAULT_PAGE_SIZE, le=_MAX_PAGE_SIZE),
    page: int = Query(default=1, ge=1),
    source: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    company_id: Optional[str] = Query(default=None),
    event_code: Optional[str] = Query(default=None),
    sort: Optional[str] = Query(default=None),
    dir: str = Query(default="desc"),
    user=Depends(require_permission("audit_trail", "read")),
):
    """Global audit log. Requires audit_trail:read.

    Every entry — Viewpoint-imported or native — carries the same context:
    company (id + name), the generic action, old -> new, and the actor. That
    context is denormalized onto the row (migration 012), so search and sort are
    plain column operations rather than joins.

    `search` matches the company name, the action, the event code, the actor and
    the changed values. `company_id` pins the trail to one company, which is how
    you see everything that ever happened to it.
    """
    if sort and sort not in _SORTABLE:
        raise HTTPException(status_code=422, detail=f"Cannot sort by '{sort}'")

    sb = get_supabase()

    def base(cols: str, count: Optional[str] = None):
        q = (sb.table("audit_log").select(cols, count=count) if count
             else sb.table("audit_log").select(cols))
        if source:
            q = q.eq("source", source)
        if company_id:
            q = q.eq("case_id", company_id)
        if event_code:
            q = q.eq("event_code", event_code)
        if search:
            q = q.or_(
                f"company_name.ilike.%{search}%,"
                f"action_label.ilike.%{search}%,"
                f"event_code.ilike.%{search}%,"
                f"user_display_name.ilike.%{search}%,"
                f"created_by.ilike.%{search}%,"
                f"old_value.ilike.%{search}%,"
                f"new_value.ilike.%{search}%"
            )
        return q

    # 'estimated', not 'exact': an exact count scans all 226k+ rows and trips the
    # statement timeout. PostgREST falls back to an exact count for small results.
    total = base("id", count="estimated").limit(1).execute().count or 0

    offset = (page - 1) * limit
    rows = (
        base("*").order(sort or "created_at", desc=(dir == "desc"))
        .range(offset, offset + limit - 1).execute().data
    ) or []

    return {"entries": rows, "total": total, "page": page, "page_size": limit}
