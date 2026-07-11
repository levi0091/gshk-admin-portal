from typing import Optional

from fastapi import APIRouter, Depends, Query

from middleware.auth import require_permission
from db.supabase import get_supabase

router = APIRouter()

_DEFAULT_PAGE_SIZE = 100
_MAX_PAGE_SIZE = 500


@router.get("/")
async def get_global_audit(
    limit: int = Query(default=_DEFAULT_PAGE_SIZE, le=_MAX_PAGE_SIZE),
    page: int = Query(default=1, ge=1),
    source: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    user=Depends(require_permission("audit_trail", "read")),
):
    """Global audit log, newest first. Requires audit_trail:read.

    Resolves each entry's case to a company name. `audit_log.case_id` has no FK
    (migration 002 declares it as a bare UUID), so PostgREST cannot embed it —
    the names are looked up in one extra query and attached per page.

    `source` filters 'g_flowdesk' (native events) vs 'viewpoint_import' (the
    226k rows imported from the Viewpoint EventLog by PBI-38).
    """
    sb = get_supabase()

    def base(cols: str, count: Optional[str] = None):
        q = (sb.table("audit_log").select(cols, count=count) if count
             else sb.table("audit_log").select(cols))
        if source:
            q = q.eq("source", source)
        if search:
            q = q.or_(
                f"metadata->>description.ilike.%{search}%,"
                f"event_code.ilike.%{search}%,"
                f"action_type.ilike.%{search}%,"
                f"user_display_name.ilike.%{search}%"
            )
        return q

    # 'estimated', not 'exact': an exact count scans all 226k+ audit rows and
    # intermittently trips the Postgres statement timeout. PostgREST's estimated
    # strategy uses the planner estimate for large result sets and falls back to
    # an exact count for small ones (so a filtered view still reports precisely).
    total = base("id", count="estimated").limit(1).execute().count or 0

    offset = (page - 1) * limit
    rows = (
        base("*").order("created_at", desc=True)
        .range(offset, offset + limit - 1).execute().data
    ) or []

    case_ids = {r["case_id"] for r in rows if r.get("case_id")}
    if case_ids:
        ents = (
            sb.table("entities").select("id, company_name, vp_source_key")
            .in_("id", list(case_ids)).execute().data
        ) or []
        by_id = {e["id"]: e for e in ents}
        for r in rows:
            if r.get("case_id"):
                r["company"] = by_id.get(r["case_id"])

    return {"entries": rows, "total": total, "page": page, "page_size": limit}
