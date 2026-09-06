from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

REGULAR_USER = {
    "id": "user-1",
    "display_name": "Staff",
    "role_name": "nar1_staff",
    "role_id": "role-1",
}


def auth_headers():
    return {"Authorization": "Bearer tok"}


def test_get_audit_trail_returns_entries():
    with patch("middleware.auth._resolve_user", return_value=REGULAR_USER), \
         patch("middleware.auth.get_supabase") as mock_perm_sb, \
         patch("routers.cases_audit.get_supabase") as mock_sb:

        # Permission check passes (role has audit_trail:read)
        # Chain: .table().select().eq(role_id).eq(module).execute()
        mock_perm_sb.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"permission": "read"}
        ]

        mock_sb.return_value.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = [
            {
                "id": "log-1",
                "created_at": "2026-06-06T10:00:00Z",
                "user_display_name": "Levi Z.",
                "action_type": "CASE_FIELD_UPDATED",
                "entity_type": "case",
                "entity_id": "case-abc",
                "before_state": {"field": "client_full_name", "old": "John"},
                "after_state": {"field": "client_full_name", "new": "John Smith"},
                "metadata": None,
            }
        ]

        # PRD-specified path: GET /cases/{case_id}/audit
        resp = client.get("/cases/case-abc/audit", headers=auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["action_type"] == "CASE_FIELD_UPDATED"


# ---- global audit log ------------------------------------------------------

SUPER_ADMIN = {"id": "a1", "display_name": "Levi Z.",
               "role_name": "super_admin", "role_id": "r1"}

LEGACY_ROW = {
    "id": "log-9", "created_at": "2026-06-18T12:07:00Z",
    "action_type": "LEGACY_VP_EVENT", "source": "viewpoint_import",
    "event_code": "OFA", "source_keycode": "ITUTORS",
    "action_label": "Statutory Officer (Director/Secretary) Appointment",
    "company_name": "iTutors Limited",
    "case_id": "e1", "created_by": "JAC", "user_display_name": "JAC",
    "old_value": None, "new_value": "Get Started HK Limited (company_secretary)",
    "metadata": {"description": "Get Started HK Limited Appointed as Secretary"},
}


def _wire(sb, rows, total=1, entities=None):
    """select() is called for the count query and the page query."""
    q = MagicMock()
    sb.table.return_value.select.return_value = q
    q.eq.return_value = q
    q.or_.return_value = q
    q.order.return_value = q
    # Every method services/table_filters may call has to CHAIN, or a filter
    # applied second lands on a different mock and the assertion for it looks
    # like the filter was never applied.
    for method in ("in_", "ilike", "gte", "lte", "lt", "is_", "neq", "not_"):
        getattr(q, method).return_value = q
    q.not_.is_.return_value = q
    q.limit.return_value.execute.return_value.count = total
    q.range.return_value.execute.return_value.data = rows
    q.in_.return_value.execute.return_value.data = entities or []


def test_global_audit_returns_denormalized_context():
    """Every row answers the same questions regardless of source: generic action,
    which company, old -> new, who. All denormalized (migration 012)."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.audit.get_supabase") as msb:
        _wire(msb.return_value, [dict(LEGACY_ROW)], total=226351)
        resp = client.get("/audit/", headers=auth_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 226351
        entry = body["entries"][0]
        assert entry["company_name"] == "iTutors Limited"
        # GENERIC action, not the per-record Viewpoint description
        assert entry["action_label"] == "Statutory Officer (Director/Secretary) Appointment"
        assert entry["event_code"] == "OFA"


def test_global_audit_filters_by_source():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.audit.get_supabase") as msb:
        sb = msb.return_value
        _wire(sb, [], total=12)
        resp = client.get("/audit/?source=g_flowdesk", headers=auth_headers())
        assert resp.status_code == 200
        assert resp.json()["total"] == 12
        q = sb.table.return_value.select.return_value
        assert ("source", "g_flowdesk") in [c.args for c in q.eq.call_args_list]


def test_global_audit_filters_to_one_company():
    """Pinning the trail to a company is how you see everything done to it."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.audit.get_supabase") as msb:
        sb = msb.return_value
        _wire(sb, [], total=7)
        resp = client.get("/audit/?company_id=e1", headers=auth_headers())
        assert resp.status_code == 200
        q = sb.table.return_value.select.return_value
        assert ("case_id", "e1") in [c.args for c in q.eq.call_args_list]


def test_global_audit_rejects_non_whitelisted_sort():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.audit.get_supabase") as msb:
        _wire(msb.return_value, [], total=0)
        assert client.get("/audit/?sort=;drop", headers=auth_headers()).status_code == 422


def test_global_audit_requires_audit_trail_read():
    with patch("middleware.auth._resolve_user", return_value=REGULAR_USER), \
         patch("middleware.auth.get_supabase") as msb:
        msb.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        assert client.get("/audit/", headers=auth_headers()).status_code == 403


# ---- WHICH module, WHICH record (migration 034) ----------------------------

SUBJECT_ROW = {
    "id": "log-11", "created_at": "2026-09-04T09:00:00Z",
    "action_type": "CASE_STATUS_CHANGED", "source": "g_flowdesk",
    "event_code": "CASE_STATUS_CHANGED", "action_label": "Case Status Changed",
    "module": "post_incorporation", "subject_kind": "case",
    "subject_id": "c1", "subject_ref": "NAR1-2026-0042",
    "company_name": "Kanenas Holding Limited",
    "case_id": "e1", "user_display_name": "Levi Z.",
    "old_value": None, "new_value": "Client Verification",
}


def test_global_audit_returns_module_and_subject():
    """The row says which surface the change belongs to and which record it is
    about \u2014 the two things a reader could not previously get."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.audit.get_supabase") as msb:
        _wire(msb.return_value, [dict(SUBJECT_ROW)], total=1)
        entry = client.get("/audit/", headers=auth_headers()).json()["entries"][0]
        assert entry["module"] == "post_incorporation"
        assert entry["subject_kind"] == "case"
        assert entry["subject_ref"] == "NAR1-2026-0042"
        assert entry["subject_id"] == "c1"


def test_module_filter_reaches_postgrest():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.audit.get_supabase") as msb:
        sb = msb.return_value
        _wire(sb, [], total=0)
        resp = client.get("/audit/?filter=module:in:natural_person",
                          headers=auth_headers())
        assert resp.status_code == 200
        q = sb.table.return_value.select.return_value
        assert ("module", ["natural_person"]) in [c.args for c in q.in_.call_args_list]


def test_module_filter_refuses_a_value_no_row_can_hold():
    """A closed enum. An option the column cannot contain would look like a
    filter that simply matched nothing."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.audit.get_supabase") as msb:
        _wire(msb.return_value, [], total=0)
        resp = client.get("/audit/?filter=module:in:accounting",
                          headers=auth_headers())
        assert resp.status_code == 422
        assert "module" in resp.json()["detail"]


def test_unknown_filter_column_is_a_422_not_a_silent_drop():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.audit.get_supabase") as msb:
        _wire(msb.return_value, [], total=0)
        resp = client.get("/audit/?filter=secret:contains:x", headers=auth_headers())
        assert resp.status_code == 422


def test_subject_name_filter_narrows_on_the_denormalized_name():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.audit.get_supabase") as msb:
        sb = msb.return_value
        _wire(sb, [], total=0)
        assert client.get("/audit/?filter=company_name:contains:kanenas",
                          headers=auth_headers()).status_code == 200
        q = sb.table.return_value.select.return_value
        assert ("company_name", "%kanenas%") in [c.args for c in q.ilike.call_args_list]


def test_a_date_range_filter_is_accepted_on_created_at():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.audit.get_supabase") as msb:
        sb = msb.return_value
        _wire(sb, [], total=0)
        resp = client.get(
            "/audit/?filter=created_at:gte:2026-09-01&filter=created_at:lte:2026-09-04",
            headers=auth_headers())
        assert resp.status_code == 200
        q = sb.table.return_value.select.return_value
        # `lte` on a timestamptz means "to the end of that day", or picking the
        # same date twice returns nothing at all.
        assert q.gte.called and q.lt.called


def test_module_and_subject_kind_are_sortable():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.audit.get_supabase") as msb:
        _wire(msb.return_value, [], total=0)
        for column in ("module", "subject_kind", "subject_ref"):
            assert client.get(f"/audit/?sort={column}",
                              headers=auth_headers()).status_code == 200


def test_search_also_matches_the_subject_reference():
    """Typing a BRN or a case number into the search box has to find the row."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.audit.get_supabase") as msb:
        sb = msb.return_value
        _wire(sb, [], total=0)
        client.get("/audit/?search=69123456", headers=auth_headers())
        q = sb.table.return_value.select.return_value
        assert any("subject_ref.ilike.%69123456%" in c.args[0]
                   for c in q.or_.call_args_list)


def test_filters_narrow_the_count_query_too():
    """Filtering only the page query leaves the pager quoting a total for a set
    nobody is looking at."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.audit.get_supabase") as msb:
        sb = msb.return_value
        _wire(sb, [], total=0)
        client.get("/audit/?filter=module:in:cr_filing", headers=auth_headers())
        q = sb.table.return_value.select.return_value
        # Once for the count query, once for the page query.
        assert len([c for c in q.in_.call_args_list if c.args[0] == "module"]) == 2
