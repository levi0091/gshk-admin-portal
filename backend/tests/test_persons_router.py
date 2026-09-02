"""PBI-39 persons router — happy / 401-403 / edge + audit-write assertions."""
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, AsyncMock

from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

SUPER_ADMIN = {"id": "admin-1", "display_name": "Levi Z.", "role_name": "super_admin", "role_id": "role-sa"}
REGULAR = {"id": "u-2", "display_name": "Staff", "role_name": "staff", "role_id": "role-x"}
H = {"Authorization": "Bearer tok"}


def test_missing_token_returns_403():
    assert client.get("/persons").status_code == 403


def test_invalid_token_returns_401():
    with patch("middleware.auth._resolve_user", side_effect=HTTPException(status_code=401, detail="x")):
        assert client.get("/persons", headers=H).status_code == 401


def test_create_without_permission_returns_403():
    with patch("middleware.auth._resolve_user", return_value=REGULAR), \
         patch("middleware.auth.get_supabase") as msb:
        msb.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        resp = client.post("/persons", json={"full_name": "Jane"}, headers=H)
        assert resp.status_code == 403


class _FakeQuery:
    """Stands in for the person_registry view query builder.

    `log` records the predicates a column filter puts on the query, so a test
    can assert they reached the COUNT queries as well as the page — filtering
    only the page would leave the role tabs and the pager describing a wider
    set than the rows come from.
    """

    def __init__(self, counts, rows, flag=None, log=None):
        self._counts, self._rows, self._flag = counts, rows, flag
        self.log = [] if log is None else log

    def _rec(self, name, *args):
        self.log.append((name, *args))
        return self

    def eq(self, col, val):
        return _FakeQuery(self._counts, self._rows, flag=col, log=self.log)

    def ilike(self, col, val):
        return self._rec("ilike", col, val)

    def in_(self, col, vals):
        return self._rec("in_", col, list(vals))

    def neq(self, col, val):
        return self._rec("neq", col, val)

    def is_(self, col, val):
        return self._rec("is_", col, val)

    def lte(self, col, val):
        return self._rec("lte", col, val)

    def gte(self, col, val):
        return self._rec("gte", col, val)

    def lt(self, col, val):
        return self._rec("lt", col, val)

    @property
    def not_(self):
        outer = self

        class _Not:
            def is_(self, col, val):
                return outer._rec("not_is", col, val)
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
        count = self._counts.get(self._flag, 0) if self._flag else self._counts[None]
        return SimpleNamespace(data=self._rows, count=count)


def _wire_registry(sb, counts, rows):
    fq = _FakeQuery(counts, rows)
    sb.table.return_value.select.side_effect = lambda cols, count=None: fq
    return fq.log


def test_list_persons_returns_role_counts_and_page():
    rows = [{"id": "p1", "full_name": "Jane Doe", "is_director": True}]
    counts = {None: 6850, "is_director": 6259, "is_shareholder": 6447,
              "is_secretary": 13, "is_beneficial_owner": 3}
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase") as msb:
        _wire_registry(msb.return_value, counts, rows)
        resp = client.get("/persons", headers=H)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 6850
        assert body["role_counts"] == {
            "all": 6850, "director": 6259, "shareholder": 6447,
            "secretary": 13, "beneficial_owner": 3,
        }
        assert len(body["persons"]) == 1


def test_list_persons_role_filter_uses_view_flag():
    """Filtering by role must count DISTINCT persons, not link-table rows."""
    counts = {None: 6850, "is_director": 6259}
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase") as msb:
        _wire_registry(msb.return_value, counts, [])
        resp = client.get("/persons?role=director", headers=H)
        assert resp.status_code == 200
        assert resp.json()["total"] == 6259


def test_list_persons_rejects_non_whitelisted_sort():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase"):
        assert client.get("/persons?sort=;drop", headers=H).status_code == 422


def test_list_persons_rejects_unknown_role():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase"):
        assert client.get("/persons?role=wizard", headers=H).status_code == 422


# ---- per-column header filters ---------------------------------------------

def _list(url):
    counts = {None: 6850, "is_director": 6259}
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase") as msb:
        log = _wire_registry(msb.return_value, counts, [])
        return client.get(url, headers=H), log


def test_a_column_filter_reaches_the_count_queries_too():
    """The role tabs and the pager must count the set the rows are drawn from."""
    resp, log = _list("/persons?filter=full_name:contains:jane")
    assert resp.status_code == 200
    applied = [e for e in log if e[0] == "ilike"]
    assert len(applied) >= 6            # page query + the 5 concurrent counts
    assert all(e == ("ilike", "full_name", "%jane%") for e in applied)


def test_identity_type_filters_as_an_enum():
    resp, log = _list("/persons?filter=primary_id_type:in:hkid,passport")
    assert resp.status_code == 200
    assert ("in_", "primary_id_type", ["hkid", "passport"]) in log


def test_persons_with_no_nationality_are_reachable():
    """Nationality has no Viewpoint lookup and is free text, so blanks are
    common and finding them is the point of the filter."""
    resp, log = _list("/persons?filter=nationality:empty:")
    assert resp.status_code == 200
    assert resp.json()["total"] == 6850


def test_a_filter_on_an_unlisted_column_is_refused():
    resp, _log = _list("/persons?filter=residential_address_id:contains:x")
    assert resp.status_code == 422
    assert "residential_address_id" in resp.json()["detail"]


def test_an_unknown_identity_type_is_refused():
    resp, _log = _list("/persons?filter=primary_id_type:in:drivers_licence")
    assert resp.status_code == 422


def test_get_person_profile_includes_rollup_and_docs():
    person = {"id": "p1", "full_name": "Jane", "residential_address_id": None}
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase") as msb, \
         patch("routers.persons.document_service.list_documents", return_value=[]) as docs:
        sb = msb.return_value
        sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = person
        sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        resp = client.get("/persons/p1", headers=H)
        assert resp.status_code == 200
        body = resp.json()
        assert "role_rollup" in body and body["documents"] == []
        docs.assert_called_once()


def test_get_person_404():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase") as msb:
        msb.return_value.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = None
        assert client.get("/persons/missing", headers=H).status_code == 404


def test_create_person_201_and_audits():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase") as msb, \
         patch("routers.persons.log_event", new=AsyncMock()) as audit:
        msb.return_value.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "p-new", "full_name": "Jane"}]
        resp = client.post("/persons", json={"full_name": "Jane"}, headers=H)
        assert resp.status_code == 201
        assert audit.await_args.kwargs["action_type"] == "PERSON_CREATED"


def test_create_person_requires_full_name():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase"):
        assert client.post("/persons", json={}, headers=H).status_code == 422


def test_update_person_audits_per_changed_field():
    current = {"id": "p1", "email": "old@e.com", "phone": "123"}
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase") as msb, \
         patch("routers.persons.log_events", new=AsyncMock()) as audit:
        sb = msb.return_value
        sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = current
        sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": "p1", "email": "new@e.com", "phone": "123"}]
        resp = client.patch("/persons/p1", json={"email": "new@e.com", "phone": "123"}, headers=H)
        assert resp.status_code == 200
        events = audit.await_args.args[0]
        assert len(events) == 1                       # phone was unchanged
        assert events[0]["action_type"] == "PERSON_FIELD_UPDATED"


def test_update_person_no_fields_400():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.persons.get_supabase"):
        assert client.patch("/persons/p1", json={}, headers=H).status_code == 400
