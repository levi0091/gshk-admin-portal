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
         patch("routers.companies.log_event", new=AsyncMock()) as audit:
        sb = msb.return_value
        sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = current
        sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": "e1", "company_name": "New", "case_notes": "same"}
        ]
        resp = client.patch("/companies/e1", json={"company_name": "New", "case_notes": "same"}, headers=H)
        assert resp.status_code == 200
        # only company_name changed → exactly one audit entry
        audit.assert_awaited_once()
        assert audit.await_args.kwargs["action_type"] == "CASE_FIELD_UPDATED"


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
         patch("routers.companies.log_event", new=AsyncMock()) as audit:
        sb = msb.return_value
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "id": "lnk-1", "entity_id": "e1", "position": "old"}
        sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": "lnk-1", "position": "new"}]
        resp = client.patch("/companies/e1/officers/lnk-1", json={"position": "new"}, headers=H)
        assert resp.status_code == 200
        assert audit.await_args.kwargs["action_type"] == "PARTY_UPDATED"


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
