from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from middleware.auth import require_permission
from db.supabase import get_supabase
from services import audit_subject
from services import table_filters as tf

router = APIRouter()

_DEFAULT_PAGE_SIZE = 100
_MAX_PAGE_SIZE = 500

# Whitelisted — `sort` reaches PostgREST's order clause.
_SORTABLE = {
    "created_at", "action_label", "event_code", "company_name",
    "old_value", "new_value", "user_display_name", "case_id",
    "module", "subject_kind", "subject_ref",
}

#: Columns the per-column header filters may narrow on
#: (services/table_filters). A separate whitelist from `_SORTABLE`, and it also
#: fixes each column's KIND, which decides the ops it will accept.
#:
#: THE ENUMS ARE CLOSED, and closed against the same tuples the writers use, so
#: a filter option can never name a value no row can hold.
#:
#: `subject_id` is a uuid and is declared as one. Declaring a uuid column as
#: text resolves `eq` to `ilike`, Postgres has no `uuid ~~* unknown` operator,
#: and the whole listing 500s — the browser reports that as a bare "Failed to
#: fetch", naming neither the column nor the filter.
#: `subject_kind` is DELIBERATELY ABSENT, and it is not an oversight.
#:
#: Measured on DEV: two enum filters ANDed together is the pathological shape
#: for this table. PostgREST compiles `in.()` to `= ANY(array)`, which the
#: planner will not resolve against the composite index (migration 035) — so it
#: walks all 226k rows in date order and times out, and a pair that matches
#: NOTHING is the worst case because there is no early exit. `module` alone is
#: fine (0.5s, index-backed); so is `module` with any text or date filter.
#:
#: Nothing on the screen sends it — the Module filter already answers "show me
#: only person changes" — so offering it through the API buys one unaskable
#: question at the price of a combination that returns 500. If a subject-kind
#: control is ever wanted, add it together with the `btree_gin` index that makes
#: the pair safe, not before.
_FILTERABLE = {
    "created_at": tf.timestamp(),
    "module": tf.enum(audit_subject.MODULES),
    "company_name": tf.text(),
    "subject_ref": tf.text(),
    "subject_id": tf.uuid(),
    "action_label": tf.text(),
    "event_code": tf.text(),
    "user_display_name": tf.text(),
    "new_value": tf.text(),
    "old_value": tf.text(),
    "source": tf.enum({"g_flowdesk", "viewpoint_import"}),
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
    filter_: list[str] = Query(
        default_factory=list, alias="filter",
        description="repeatable column:op:value — see services/table_filters",
    ),
    sort: Optional[str] = Query(default=None),
    dir: str = Query(default="desc"),
    user=Depends(require_permission("audit_trail", "read")),
):
    """Global audit log. Requires audit_trail:read.

    Every entry — Viewpoint-imported or native — carries the same context: WHICH
    MODULE the change belongs to, WHICH RECORD it is about (subject kind, id,
    name and the reference a human quotes), the generic action, old -> new, and
    the actor. All of it is denormalized onto the row (migrations 012 and 034),
    so search, sort and the per-column filters are plain column operations
    rather than joins over 226k+ rows.

    `search` matches the subject's name and reference, the action, the event
    code, the actor and the changed values. `company_id` pins the trail to one
    company, which is how you see everything that ever happened to it.

    FILTERING HAPPENS IN THE DATABASE, like every other listing in this portal.
    This one paginates 100 rows at a time out of 226k: narrowing the page the
    server happened to send would look right, narrow nothing, and quietly answer
    a different question.
    """
    if sort and sort not in _SORTABLE:
        raise HTTPException(status_code=422, detail=f"Cannot sort by '{sort}'")

    try:
        col_filters = tf.parse(filter_, _FILTERABLE)
    except tf.FilterError as exc:
        # 422 naming the column, never a silently dropped filter: a filter the
        # server drops looks exactly like a filter that matched everything.
        raise HTTPException(status_code=422, detail=str(exc))

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
                f"subject_ref.ilike.%{search}%,"
                f"action_label.ilike.%{search}%,"
                f"event_code.ilike.%{search}%,"
                f"user_display_name.ilike.%{search}%,"
                f"created_by.ilike.%{search}%,"
                f"old_value.ilike.%{search}%,"
                f"new_value.ilike.%{search}%"
            )
        # Applied to BOTH queries below. Filtering only the page query leaves
        # the pager quoting a total for a set nobody is looking at.
        return tf.apply(q, col_filters)

    # 'estimated', not 'exact': an exact count scans all 226k+ rows and trips the
    # statement timeout. PostgREST falls back to an exact count for small results.
    total = base("id", count="estimated").limit(1).execute().count or 0

    offset = (page - 1) * limit
    rows = (
        base("*").order(sort or "created_at", desc=(dir == "desc"))
        .range(offset, offset + limit - 1).execute().data
    ) or []

    return {"entries": rows, "total": total, "page": page, "page_size": limit}
