"""PBI-39 companies router — happy / 401-403 / edge + audit-write assertions.

Supabase + audit are mocked; no DB is touched. super_admin via _resolve_user
bypasses require_permission, so happy paths only mock the router's get_supabase.
"""
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

SUPER_ADMIN = {
    "id": "admin-1", "display_name": "Levi Z.",
    "role_name": "super_admin", "role_id": "role-sa",
}
REGULAR = {
    "id": "u-2", "display_name": "Staff", "role_name": "staff", "role_id": "role-x",
}
H = {"Authorization": "Bearer tok"}


def _mock_sb():
    """A supabase mock where any chain resolves; terminal .data is set per test."""
    return MagicMock()


# ---- access control ---------------------------------------------------------

def test_missing_token_returns_403():
    resp = client.get("/companies")
    assert resp.status_code == 403  # HTTPBearer: no credentials


def test_invalid_token_returns_401():
    with patch("middleware.auth._resolve_user", side_effect=HTTPException(status_code=401, detail="x")):
        resp = client.get("/companies", headers=H)
        assert resp.status_code == 401


def test_write_without_permission_returns_403():
    with patch("middleware.auth._resolve_user", return_value=REGULAR), \
         patch("middleware.auth.get_supabase") as msb:
        # role_permissions query returns no rows → insufficient
        msb.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        resp = client.post("/companies", json={"company_name": "X"}, headers=H)
        assert resp.status_code == 403


# ---- reads ------------------------------------------------------------------

class _FakeQuery:
    """Minimal stand-in for the PostgREST query builder.

    Tracks the `status` eq-filter and which branch (pending / terminal) the page
    query took, so exact-count queries and the two ordered page queries each
    resolve to the right value. Chained MagicMocks can't express this because
    base() applies .eq('is_client') *before* count_of() adds .eq('status').
    """

    def __init__(self, counts, pend, term, status=None, branch=None):
        self._counts, self._pend, self._term = counts, pend, term
        self._status, self._branch = status, branch

    def _with(self, **kw):
        return _FakeQuery(self._counts, self._pend, self._term,
                          status=kw.get("status", self._status),
                          branch=kw.get("branch", self._branch))

    def eq(self, col, val):
        return self._with(status=val) if col == "status" else self

    def in_(self, col, vals):
        return self._with(branch="pending")

    @property
    def not_(self):
        outer = self

        class _Not:
            def in_(self, col, vals):
                return outer._with(branch="terminal")
        return _Not()

    def or_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def range(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        data = {"pending": self._pend, "terminal": self._term}.get(self._branch, [])
        count = (self._counts.get(self._status, 0) if self._status
                 else self._counts[None])
        return SimpleNamespace(data=data, count=count)


def _wire_list(sb, *, counts, pending_rows, terminal_rows):
    """counts maps status -> count; key None is the unfiltered "all" count."""
    fq = _FakeQuery(counts, pending_rows, terminal_rows)
    sb.table.return_value.select.side_effect = lambda cols, count=None: fq


def test_list_registry_returns_paginated_envelope():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb:
        _wire_list(
            msb.return_value,
            counts={None: 1},
            pending_rows=[],
            terminal_rows=[{"id": "e1", "company_name": "Acme", "is_client": True,
                            "is_corporate_party": False, "status": "live"}],
        )
        resp = client.get("/companies", headers=H)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1 and body["page"] == 1
        assert len(body["companies"]) == 1
        # registry carries the flag tab counts; dashboard tiles are absent
        assert set(body["flag_counts"]) == {"all", "client", "corporate_party", "non_client"}
        assert "tiles" not in body


def test_sort_rejects_non_whitelisted_column():
    """`sort` reaches PostgREST's order clause — it must never be free text."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb:
        _wire_list(msb.return_value, counts={None: 0}, pending_rows=[], terminal_rows=[])
        resp = client.get("/companies?sort=company_name;drop", headers=H)
        assert resp.status_code == 422


def test_sort_orders_by_the_requested_column():
    """An explicit sort replaces the pending-first grouping."""
    captured = {}

    class _Q:
        def eq(self, *a, **k): return self
        def or_(self, *a, **k): return self
        def in_(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def order(self, col, desc=False, **kw):
            captured["order"] = (col, desc)
            return self
        def range(self, *a, **k): return self
        def execute(self):
            return SimpleNamespace(data=[], count=5)

    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb:
        msb.return_value.table.return_value.select.side_effect = lambda cols, count=None: _Q()
        resp = client.get("/companies?sort=created_at&dir=desc", headers=H)
        assert resp.status_code == 200
        assert captured["order"] == ("created_at", True)


def test_registry_non_client_flag_filters_is_client_false():
    """flag=non_client must select is_client=false (the 68 corporate-party-only rows)."""
    captured = {}

    class _Q:
        def eq(self, col, val):
            captured[col] = val
            return self
        def or_(self, *a, **k): return self
        def order(self, *a, **k): return self
        def range(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def in_(self, *a, **k): return self
        @property
        def not_(self):
            outer = self

            class _N:
                def in_(self, *a, **k): return outer
            return _N()
        def execute(self):
            return SimpleNamespace(data=[], count=68)

    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb:
        msb.return_value.table.return_value.select.side_effect = lambda cols, count=None: _Q()
        resp = client.get("/companies?flag=non_client", headers=H)
        assert resp.status_code == 200
        assert captured.get("is_client") is False


def test_dashboard_returns_tiles_and_sorts_pending_first():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb:
        _wire_list(
            msb.return_value,
            counts={None: 3, "pending_aml": 1, "pending_client": 1},
            pending_rows=[
                {"id": "e2", "company_name": "AML Co", "status": "pending_aml"},
                {"id": "e3", "company_name": "Pend Co", "status": "pending_client"}],
            terminal_rows=[{"id": "e1", "company_name": "Live Co", "status": "live"}],
        )
        resp = client.get("/companies?scope=dashboard", headers=H)
        assert resp.status_code == 200
        body = resp.json()
        assert body["tiles"] == {"action_required": 1, "pending": 1}
        assert body["status_counts"]["all"] == 3
        assert body["total"] == 3
        # pending-work companies sort ahead of the terminal 'live' one
        assert body["companies"][0]["status"] != "live"
        assert body["companies"][-1]["status"] == "live"
        assert body["companies"][0]["has_pending_case"] is True
        assert body["companies"][-1]["has_pending_case"] is False


def test_get_company_includes_relations_and_cases():
    entity = {"id": "e1", "company_name": "Acme", "is_client": True}
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.document_service.list_documents", return_value=[]):
        sb = msb.return_value
        sel = sb.table.return_value.select.return_value
        sel.eq.return_value.single.return_value.execute.return_value.data = entity
        sel.eq.return_value.execute.return_value.data = []            # shareholders / BO / contacts / cases
        sel.eq.return_value.neq.return_value.execute.return_value.data = []   # officers (excl. secretary)
        sel.eq.return_value.eq.return_value.execute.return_value.data = []    # secretaries (role=company_secretary)
        resp = client.get("/companies/e1", headers=H)
        assert resp.status_code == 200
        body = resp.json()
        assert body["officers"] == [] and "cases" in body
        assert body["documents"] == [] and body["contacts"] == []


def test_get_company_omits_cases_pane_for_non_client():
    """Cases pane is client-only (§6 visibility)."""
    entity = {"id": "e3", "company_name": "Asia BC", "is_client": False,
              "is_corporate_party": True}
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.document_service.list_documents", return_value=[]):
        sb = msb.return_value
        sel = sb.table.return_value.select.return_value
        sel.eq.return_value.single.return_value.execute.return_value.data = entity
        sel.eq.return_value.execute.return_value.data = []            # shareholders / BO / contacts / cases
        sel.eq.return_value.neq.return_value.execute.return_value.data = []   # officers (excl. secretary)
        sel.eq.return_value.eq.return_value.execute.return_value.data = []    # secretaries (role=company_secretary)
        resp = client.get("/companies/e3", headers=H)
        assert resp.status_code == 200
        assert "cases" not in resp.json()


def test_create_company_creates_address_and_phone_rows():
    """Add Company's free-text address + phone land in `addresses` / `contacts`."""
    inserted = []

    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_event", new=AsyncMock()):
        sb = msb.return_value

        def table_side_effect(name):
            t = MagicMock()

            def insert(row):
                inserted.append((name, row))
                m = MagicMock()
                if name == "addresses":
                    m.execute.return_value.data = [{"id": "addr-1"}]
                elif name == "entities":
                    m.execute.return_value.data = [{"id": "e-new", **row}]
                else:
                    m.execute.return_value.data = [{"id": "c-1"}]
                return m

            t.insert.side_effect = insert
            return t

        sb.table.side_effect = table_side_effect

        resp = client.post("/companies", json={
            "company_name": "NewCo", "status": "live",
            "registered_address": "1 Harbour View St", "company_phone": "+852 3500 1234",
        }, headers=H)
        assert resp.status_code == 201

    tables = {name for name, _ in inserted}
    assert {"addresses", "entities", "contacts"} <= tables
    entity_row = next(r for n, r in inserted if n == "entities")
    # the free-text address became an addresses row the entity points at
    assert entity_row["registered_address_id"] == "addr-1"
    assert "registered_address" not in entity_row and "company_phone" not in entity_row
    contact_row = next(r for n, r in inserted if n == "contacts")
    assert contact_row["contact_type"] == "phone"
    assert contact_row["contact_value"] == "+852 3500 1234"


def test_get_company_404():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb:
        msb.return_value.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = None
        resp = client.get("/companies/missing", headers=H)
        assert resp.status_code == 404


# ---- create -----------------------------------------------------------------

def test_create_company_201_and_audits():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_event", new=AsyncMock()) as audit:
        msb.return_value.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "new-e", "company_name": "NewCo", "status": "pre_incorporation"}
        ]
        resp = client.post("/companies", json={"company_name": "NewCo"}, headers=H)
        assert resp.status_code == 201
        audit.assert_awaited_once()
        assert audit.await_args.kwargs["action_type"] == "COMPANY_CREATED"


def test_create_company_rejects_non_create_status():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase"):
        resp = client.post("/companies", json={"company_name": "X", "status": "ceased"}, headers=H)
        assert resp.status_code == 422


# ---- update (field diff audit) ---------------------------------------------

def test_update_company_audits_only_changed_fields():
    current = {"id": "e1", "company_name": "Old", "case_notes": "same"}
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_events", new=AsyncMock()) as audit:
        sb = msb.return_value
        sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = current
        sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": "e1", "company_name": "New", "case_notes": "same"}
        ]
        resp = client.patch("/companies/e1", json={"company_name": "New", "case_notes": "same"}, headers=H)
        assert resp.status_code == 200
        # one entry per CHANGED field, batched into a single insert
        events = audit.await_args.args[0]
        assert len(events) == 1                       # case_notes was unchanged
        assert events[0]["action_type"] == "CASE_FIELD_UPDATED"
        assert events[0]["old_value"] == "Old" and events[0]["new_value"] == "New"
        assert events[0]["event_code"] == "ADC"       # Viewpoint's master-file code


def test_update_company_no_fields_400():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase"):
        resp = client.patch("/companies/e1", json={}, headers=H)
        assert resp.status_code == 400


def test_flags_update_audits_flag_changed():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_event", new=AsyncMock()) as audit:
        sb = msb.return_value
        sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "is_client": True, "is_corporate_party": False}
        sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": "e1", "is_corporate_party": True}]
        resp = client.patch("/companies/e1/flags", json={"is_corporate_party": True}, headers=H)
        assert resp.status_code == 200
        assert audit.await_args.kwargs["action_type"] == "COMPANY_FLAG_CHANGED"


# ---- party linking ----------------------------------------------------------

def test_link_party_requires_exactly_one_party():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase"):
        # both set → 422
        resp = client.post("/companies/e1/officers",
                           json={"person_id": "p1", "corporate_entity_id": "c1"}, headers=H)
        assert resp.status_code == 422
        # neither set → 422
        resp = client.post("/companies/e1/officers", json={"role": "director"}, headers=H)
        assert resp.status_code == 422


def test_link_officer_201_and_audits():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_event", new=AsyncMock()) as audit:
        msb.return_value.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "lnk-1", "entity_id": "e1", "person_id": "p1"}]
        resp = client.post("/companies/e1/officers",
                           json={"person_id": "p1", "role": "director"}, headers=H)
        assert resp.status_code == 201
        assert audit.await_args.kwargs["action_type"] == "PARTY_LINKED"


def test_link_secretary_forces_company_secretary_role():
    """`secretaries` is entity_officers scoped to role='company_secretary'.

    The role is fixed server-side, so a secretary can never be created as a
    plain director even if the client sends a different role.
    """
    captured = {}
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_event", new=AsyncMock()) as audit:
        sb = msb.return_value

        def insert(row):
            captured.update(row)
            m = MagicMock()
            m.execute.return_value.data = [{"id": "sec-1", **row}]
            return m

        sb.table.return_value.insert.side_effect = insert

        resp = client.post("/companies/e1/secretaries",
                           json={"corporate_entity_id": "gshk-1", "role": "director"},
                           headers=H)
        assert resp.status_code == 201

    assert captured["role"] == "company_secretary"   # client's "director" overridden
    assert captured["party_type"] == "corporate"
    assert captured["corporate_entity_id"] == "gshk-1"
    assert audit.await_args.kwargs["action_type"] == "PARTY_LINKED"


def test_secretary_link_not_reachable_via_officers_route():
    """officers/{id} must not resolve a secretary row (they share entity_officers)."""
    captured = {}

    class _Q:
        def select(self, *a, **k): return self
        def eq(self, col, val):
            captured.setdefault("eq", []).append((col, val))
            return self
        def neq(self, col, val):
            captured["neq"] = (col, val)
            return self
        def single(self): return self
        def execute(self): return SimpleNamespace(data=None)

    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb:
        msb.return_value.table.return_value = _Q()
        resp = client.delete("/companies/e1/officers/sec-1", headers=H)
        assert resp.status_code == 404

    # the officers route explicitly excludes company_secretary rows
    assert captured["neq"] == ("role", "company_secretary")


def test_link_shareholder_requires_share_class():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase"):
        resp = client.post("/companies/e1/shareholders",
                           json={"person_id": "p1", "shares_held": 100}, headers=H)
        assert resp.status_code == 422


def test_unknown_relation_404():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase"):
        resp = client.post("/companies/e1/frenemies", json={"person_id": "p1"}, headers=H)
        assert resp.status_code == 404


def test_update_link_audits_party_updated():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_events", new=AsyncMock()) as audit:
        sb = msb.return_value
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "id": "lnk-1", "entity_id": "e1", "position": "old"}
        sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": "lnk-1", "position": "new"}]
        resp = client.patch("/companies/e1/officers/lnk-1", json={"position": "new"}, headers=H)
        assert resp.status_code == 200
        events = audit.await_args.args[0]
        assert events[0]["action_type"] == "PARTY_UPDATED"
        assert events[0]["event_code"] == "OFC"       # Viewpoint's officer-change code


def test_unlink_audits_party_unlinked():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_event", new=AsyncMock()) as audit:
        sb = msb.return_value
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "id": "lnk-1", "entity_id": "e1", "person_id": "p1", "corporate_entity_id": None}
        resp = client.delete("/companies/e1/officers/lnk-1", headers=H)
        assert resp.status_code == 200
        assert audit.await_args.kwargs["action_type"] == "PARTY_UNLINKED"


# ---- R3 · days-to-anniversary (migration 019 view) --------------------------

class _RecordingQuery:
    """Records every filter/order call so a test can assert what reached PostgREST.

    Separate from _FakeQuery on purpose: that one models the pending/terminal
    branch split, this one only cares which predicates were applied and to which
    queries (the count queries and the page query must agree, or the pager
    quotes a total for a set the user is not looking at).
    """

    def __init__(self, log, rows, count):
        self.log, self._rows, self._count = log, rows, count

    def _rec(self, name, *args):
        self.log.append((name, *args))
        return self

    def eq(self, c, v):
        return self._rec("eq", c, v)

    def lte(self, c, v):
        return self._rec("lte", c, v)

    def gte(self, c, v):
        return self._rec("gte", c, v)

    def in_(self, c, v):
        return self._rec("in_", c)

    def ilike(self, c, v):
        return self._rec("ilike", c, v)

    def neq(self, c, v):
        return self._rec("neq", c, v)

    def is_(self, c, v):
        return self._rec("is_", c, v)

    @property
    def not_(self):
        outer = self

        class _Not:
            def in_(self, c, v):
                return outer._rec("not_in", c)

            def is_(self, c, v):
                return outer._rec("not_is", c, v)
        return _Not()

    def or_(self, *a, **k):
        return self

    def order(self, col, **kw):
        return self._rec("order", col, kw.get("desc"), kw.get("nullsfirst"))

    def range(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return SimpleNamespace(data=self._rows, count=self._count)


def _wire_recording(sb, rows=(), row_count=0):
    """`count` on select() is PostgREST's "exact" flag, NOT a number — feeding it
    through as the row count made the tile sums add ints to strings."""
    log = []
    sb.table.return_value.select.side_effect = (
        lambda cols, count=None: _RecordingQuery(log, list(rows), row_count)
    )
    return log


def _get(url):
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb:
        log = _wire_recording(msb.return_value)
        return client.get(url, headers=H), log, msb.return_value


def test_list_reads_the_company_registry_view_not_entities():
    """days_to_anniversary is computed by the view; entities has no such column."""
    resp, _log, sb = _get("/companies")
    assert resp.status_code == 200
    assert "company_registry" in {c.args[0] for c in sb.table.call_args_list}
    assert "entities" not in {c.args[0] for c in sb.table.call_args_list}


def test_days_to_anniversary_is_sortable():
    resp, log, _ = _get("/companies?sort=days_to_anniversary&dir=asc")
    assert resp.status_code == 200
    assert ("order", "days_to_anniversary", False, False) in log


def test_descending_anniversary_sort_keeps_undated_companies_last():
    """Postgres puts NULLs FIRST on DESC; the 473 undated rows must not lead."""
    _resp, log, _ = _get("/companies?sort=days_to_anniversary&dir=desc")
    orders = [e for e in log if e[0] == "order"]
    assert orders and orders[0] == ("order", "days_to_anniversary", True, False)


def test_anniversary_filter_reaches_the_count_queries_too():
    """Filtering only the page query would make the pager quote the wrong total."""
    resp, log, _ = _get("/companies?anniv_op=lte&anniv_days=60")
    assert resp.status_code == 200
    applied = [e for e in log if e[0] == "lte"]
    # one page query + the 7 concurrent exact-count queries
    assert len(applied) >= 8
    assert all(e == ("lte", "days_to_anniversary", 60) for e in applied)


def test_anniversary_filter_excludes_companies_with_no_incorporation_date():
    _resp, log, _ = _get("/companies?anniv_op=gte&anniv_days=0")
    assert ("not_is", "days_to_anniversary", "null") in log


def test_negative_day_count_is_accepted():
    """Signed: -12 means 12 days past the anniversary, still inside the window."""
    resp, log, _ = _get("/companies?anniv_op=gte&anniv_days=-42")
    assert resp.status_code == 200
    assert ("gte", "days_to_anniversary", -42) in log


def test_unfiltered_list_applies_no_anniversary_predicate():
    _resp, log, _ = _get("/companies")
    assert not [e for e in log if e[0] in ("lte", "gte", "not_is")]


def test_unknown_comparison_is_rejected():
    resp, _log, _ = _get("/companies?anniv_op=like&anniv_days=60")
    assert resp.status_code == 422
    assert "like" in resp.json()["detail"]


def test_comparison_without_a_day_count_is_rejected():
    resp, _log, _ = _get("/companies?anniv_op=lte")
    assert resp.status_code == 422


def test_day_count_without_a_comparison_is_rejected():
    resp, _log, _ = _get("/companies?anniv_days=60")
    assert resp.status_code == 422


# ---- per-column header filters ---------------------------------------------

def test_a_column_filter_reaches_the_count_queries_too():
    """Same rule the anniversary filter follows. The flag tabs and the pager
    have to count the set the rows are drawn from, not a wider one."""
    resp, log, _ = _get("/companies?filter=company_name:contains:acme")
    assert resp.status_code == 200
    applied = [e for e in log if e[0] == "ilike"]
    assert len(applied) >= 8         # page query + the concurrent exact counts
    assert all(e == ("ilike", "company_name", "%acme%") for e in applied)


def test_two_filters_on_one_column_make_a_range():
    """Upper and lower bound, which is how the registry opens: -42 keeps the
    companies already past the anniversary and still inside the 42-day filing
    window, 60 reaches the ones coming up."""
    resp, log, _ = _get("/companies?filter=days_to_anniversary:gte:-42"
                        "&filter=days_to_anniversary:lte:60")
    assert resp.status_code == 200
    assert ("gte", "days_to_anniversary", -42) in log
    assert ("lte", "days_to_anniversary", 60) in log


def test_an_enum_filter_becomes_an_in_list():
    resp, log, _ = _get("/companies?filter=status:in:live,ceased")
    assert resp.status_code == 200
    assert ("in_", "status") in log


def test_a_filter_on_an_unlisted_column_is_refused():
    """422, not ignored: a dropped filter looks exactly like one that matched
    every row, and on a 5,930-row paginated list nobody can tell."""
    resp, _log, _ = _get("/companies?filter=case_notes:contains:secret")
    assert resp.status_code == 422
    assert "case_notes" in resp.json()["detail"]


def test_an_out_of_domain_status_is_refused():
    resp, _log, _ = _get("/companies?filter=status:in:dissolved")
    assert resp.status_code == 422


def test_every_real_entity_status_is_filterable():
    """The tabs show six statuses; the column can hold eleven. Offering only the
    six would make `live` and `ceased` — which is all 5,930 real rows —
    unreachable from the header."""
    for status in ("live", "ceased", "pre_incorporation", "client_approved"):
        resp, _log, _ = _get(f"/companies?filter=status:in:{status}")
        assert resp.status_code == 200, status


def test_no_filter_applies_no_predicate():
    # `in_` is excluded on purpose: the unfiltered listing already splits
    # pending from terminal rows with one (`_PENDING`), and that is the default
    # ordering, not a filter anybody asked for.
    _resp, log, _ = _get("/companies")
    assert not [e for e in log if e[0] in ("ilike", "neq", "is_")]
