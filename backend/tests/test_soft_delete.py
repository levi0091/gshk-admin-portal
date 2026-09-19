"""Soft delete of companies and natural persons (migration 049).

Most of these run against `FakeSB`, a small in-memory stand-in for the PostgREST
builder that actually FILTERS rows. The rules here are about which rows count --
a current role at a live company blocks, the same role at a deleted company does
not -- and a chain of MagicMocks answers every filter the same way, which is how
a rule that looks at the wrong column still passes.
"""
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from main import app
from services import soft_delete
from services.tpsi.forms import nar1_mapper

client = TestClient(app)
H = {"Authorization": "Bearer tok"}
SUPER_ADMIN = {"id": "admin-1", "display_name": "Levi Z.",
               "role_name": "super_admin", "role_id": "role-sa"}
STAFF = {"id": "u-2", "display_name": "Staff", "role_name": "staff",
         "role_id": "role-x"}
DELETED_AT = "2026-09-20T02:00:00+00:00"


# --------------------------------------------------------------------------- #
#  An in-memory PostgREST, just big enough
# --------------------------------------------------------------------------- #

class FakeSB:
    #: PostgREST's own cap on an un-ranged read, which is what makes paging
    #: necessary at all.
    MAX_ROWS = 1000

    def __init__(self, **tables):
        self.tables = {k: [dict(r) for r in v] for k, v in tables.items()}
        self.writes: list[tuple[str, str, dict]] = []
        self.in_sizes: list[int] = []

    def table(self, name):
        return _Query(self, name)


def _unlike(pattern: str) -> str:
    return re.sub(r"\\(.)", r"\1", pattern).lower()


class _Query:
    def __init__(self, sb, name):
        self.sb, self.name = sb, name
        self.filters, self.op, self.values, self.one = [], "select", None, False
        self.window = (0, FakeSB.MAX_ROWS - 1)

    def select(self, *_a, **_k):
        return self

    def update(self, values):
        self.op, self.values = "update", values
        return self

    def eq(self, col, val):
        self.filters.append(lambda r: r.get(col) == val)
        return self

    def neq(self, col, val):
        self.filters.append(lambda r: r.get(col) != val)
        return self

    def in_(self, col, vals):
        vals = set(vals)
        self.sb.in_sizes.append(len(vals))
        self.filters.append(lambda r: r.get(col) in vals)
        return self

    def is_(self, col, val):
        assert val == "null"
        self.filters.append(lambda r: r.get(col) is None)
        return self

    def ilike(self, col, pattern):
        target = _unlike(pattern)
        self.filters.append(lambda r: (r.get(col) or "").lower() == target)
        return self

    @property
    def not_(self):
        query = self

        class _Not:
            def is_(self, col, val):
                assert val == "null"
                query.filters.append(lambda r: r.get(col) is not None)
                return query
        return _Not()

    def or_(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def range(self, start, end):
        self.window = (start, min(end, start + FakeSB.MAX_ROWS - 1))
        return self

    def limit(self, *_a, **_k):
        return self

    def single(self):
        self.one = True
        return self

    def execute(self):
        rows = [r for r in self.sb.tables.get(self.name, [])
                if all(f(r) for f in self.filters)]
        if self.op == "update":
            for r in rows:
                r.update(self.values)
            self.sb.writes.append((self.name, "update", dict(self.values)))
        total = len(rows)
        if self.op == "select":
            rows = rows[self.window[0]:self.window[1] + 1]
        data = [dict(r) for r in rows]
        if self.one:
            data = data[0] if data else None
        return SimpleNamespace(data=data, count=total)


def _company(cid, name, **kw):
    return {"id": cid, "company_name": name, "br_number": f"BR-{cid}",
            "deleted_at": None, "is_client": True, **kw}


def _person(pid, name, **kw):
    return {"id": pid, "full_name": name, "deleted_at": None, **kw}


# --------------------------------------------------------------------------- #
#  services/soft_delete
# --------------------------------------------------------------------------- #

def test_is_deleted_only_for_a_row_that_carries_a_deletion():
    sb = FakeSB(entities=[_company("a", "A LTD"),
                          _company("b", "B LTD", deleted_at=DELETED_AT)])
    assert soft_delete.is_deleted(sb, "entities", "b") is True
    assert soft_delete.is_deleted(sb, "entities", "a") is False
    assert soft_delete.is_deleted(sb, "entities", "missing") is False


def test_a_mock_that_is_not_a_list_is_not_a_deletion():
    """Every router test hands queries a MagicMock; its truthy attributes must
    not read as 'this record was deleted'."""
    assert soft_delete.is_deleted(MagicMock(), "entities", "x") is False


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_a_deletion_needs_a_reason(raw):
    with pytest.raises(ValueError, match="why"):
        soft_delete.clean_reason(raw)


def test_a_reason_is_trimmed_and_capped():
    assert soft_delete.clean_reason("  duplicate  ") == "duplicate"
    with pytest.raises(ValueError, match=str(soft_delete.REASON_MAX)):
        soft_delete.clean_reason("x" * (soft_delete.REASON_MAX + 1))


def _person_links_sb():
    return FakeSB(
        entities=[_company("live", "LIVE LTD"),
                  _company("gone", "GONE LTD", deleted_at=DELETED_AT),
                  _company("other", "OTHER LTD")],
        entity_officers=[
            {"entity_id": "live", "person_id": "p1", "role": "director", "is_current": True},
            {"entity_id": "gone", "person_id": "p1", "role": "director", "is_current": True},
            {"entity_id": "other", "person_id": "p1", "role": "director", "is_current": False},
        ],
        shareholdings=[
            {"entity_id": "live", "person_id": "p1", "is_current": True},
        ],
        beneficial_owners=[],
        company_secretaries=[
            {"entity_id": "other", "person_id": "p1", "is_current": True},
        ],
    )


def test_a_person_is_blocked_by_each_current_role_at_a_live_company():
    blockers = soft_delete.person_blockers(_person_links_sb(), "p1")
    assert blockers["cases"] == []
    assert blockers["links"] == [
        {"company_id": "live", "company_name": "LIVE LTD",
         "br_number": "BR-live", "roles": ["Director", "Shareholder"]},
        # From the ETL's secretary register, where the officer row is not current.
        {"company_id": "other", "company_name": "OTHER LTD",
         "br_number": "BR-other", "roles": ["Company secretary"]},
    ]


def test_a_role_at_a_deleted_company_or_a_former_role_does_not_block():
    sb = _person_links_sb()
    sb.tables["shareholdings"] = []
    sb.tables["company_secretaries"] = []
    sb.tables["entity_officers"] = [r for r in sb.tables["entity_officers"]
                                    if r["entity_id"] != "live"]
    assert soft_delete.has_blockers(soft_delete.person_blockers(sb, "p1")) is False


def _company_sb(**overrides):
    tables = dict(
        entities=[_company("gshk", "Get Started HK Limited"),
                  _company("client", "CLIENT LTD"),
                  _company("client2", "CLIENT TWO LTD")],
        entity_officers=[
            {"entity_id": "client", "corporate_entity_id": "gshk",
             "role": "company_secretary", "is_current": True},
        ],
        shareholdings=[], beneficial_owners=[],
        company_secretaries=[
            {"entity_id": "client2", "person_id": None, "is_current": True,
             "secretary_name": "GET STARTED HK LIMITED"},
        ],
        nar1_case_registry=[],
    )
    tables.update(overrides)
    return FakeSB(**tables)


def test_a_company_is_blocked_by_its_roles_elsewhere_including_the_register():
    sb = _company_sb()
    blockers = soft_delete.company_blockers(sb, sb.tables["entities"][0])
    assert [(e["company_id"], e["roles"]) for e in blockers["links"]] == [
        ("client", ["Company secretary"]), ("client2", ["Company secretary"])]


def test_the_company_secretary_of_thousands_is_counted_not_listed():
    """GSHK's own entity is the current secretary of ~5,600 companies.

    Every one of them must COUNT -- past PostgREST's 1,000-row page -- while
    only SHOWN_LINKS are named, and no request may carry thousands of ids in
    its URL, which is what asking for all their names at once would do.
    """
    clients = [_company(f"c{i:05d}", f"CLIENT {i:05d} LTD") for i in range(2500)]
    clients[7]["deleted_at"] = DELETED_AT        # a deleted one does not count
    sb = _company_sb(
        entities=[_company("gshk", "Get Started HK Limited"), *clients],
        entity_officers=[{"entity_id": c["id"], "corporate_entity_id": "gshk",
                          "role": "company_secretary", "is_current": True}
                         for c in clients],
        company_secretaries=[])
    blockers = soft_delete.company_blockers(sb, sb.tables["entities"][0])

    assert blockers["links_total"] == 2499
    assert len(blockers["links"]) == soft_delete.SHOWN_LINKS
    assert max(sb.in_sizes) <= soft_delete.SHOWN_LINKS
    assert "and 2494 more" in soft_delete.describe(blockers)


def test_a_register_name_does_not_block_when_a_live_twin_would_still_resolve_it():
    """Two live companies with one name is already ambiguous for nar1_source;
    deleting one is what fixes that, so the register must not refuse it."""
    sb = _company_sb(entity_officers=[])
    sb.tables["entities"].append(_company("twin", "Get Started HK Limited"))
    blockers = soft_delete.company_blockers(sb, sb.tables["entities"][0])
    assert blockers["links"] == []


@pytest.mark.parametrize("status, blocks", [
    ("client_verification", True), ("awaiting_client", True),
    ("data_verification", True), ("cr_pending", True), ("cr_rejected", True),
    ("cr_registered", False), ("closed", False),
])
def test_a_case_blocks_until_it_is_closed_or_cr_registered_it(status, blocks):
    sb = _company_sb(entity_officers=[], company_secretaries=[],
                     nar1_case_registry=[{"id": "k1", "entity_id": "gshk",
                                          "case_no": "NAR-2026-0001",
                                          "workflow_status": status}])
    blockers = soft_delete.company_blockers(sb, sb.tables["entities"][0])
    assert bool(blockers["cases"]) is blocks


def test_the_refusal_names_what_has_to_happen_first():
    text = soft_delete.describe({
        "links": [{"company_id": "c", "company_name": "CLIENT LTD"}],
        "cases": [{"case_id": "k", "case_no": "NAR-2026-0001"}]})
    assert "CLIENT LTD" in text and "NAR-2026-0001" in text
    assert text.startswith("Cannot delete")


def test_deleting_twice_only_succeeds_once():
    sb = FakeSB(persons=[_person("p1", "A")])
    first = soft_delete.mark_deleted(sb, "persons", "p1", user_id="u", reason="dup")
    second = soft_delete.mark_deleted(sb, "persons", "p1", user_id="u", reason="again")
    assert first["deleted_reason"] == "dup" and second is None
    assert sb.tables["persons"][0]["deleted_reason"] == "dup"


def test_restoring_clears_all_three_and_only_for_a_deleted_row():
    sb = FakeSB(persons=[_person("p1", "A", deleted_at=DELETED_AT,
                                 deleted_by="u", deleted_reason="dup")])
    assert soft_delete.restore(sb, "persons", "p1")["deleted_at"] is None
    assert sb.tables["persons"][0]["deleted_reason"] is None
    assert soft_delete.restore(sb, "persons", "p1") is None


# --------------------------------------------------------------------------- #
#  Every by-id route refuses a deleted record -- the sweep
# --------------------------------------------------------------------------- #

#: The only routes on a `{company_id}` / `{person_id}` path allowed to reach a
#: DELETED record: the profile (read-only, to a role that may restore it) and
#: restore itself.
_ALLOWED = {
    ("GET", "/companies/{company_id}"), ("POST", "/companies/{company_id}/restore"),
    ("GET", "/persons/{person_id}"), ("POST", "/persons/{person_id}/restore"),
}


def _guards(dependant):
    for dep in dependant.dependencies:
        yield getattr(dep.call, "refuses_deleted", None)
        yield from _guards(dep)


def test_every_route_on_a_company_or_person_id_refuses_a_deleted_one():
    """A route added later with a plain require_permission fails here."""
    seen, unguarded = 0, []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for param, table in (("{company_id}", "entities"), ("{person_id}", "persons")):
            if param not in route.path:
                continue
            for method in route.methods:
                seen += 1
                if (method, route.path) in _ALLOWED:
                    continue
                if table not in set(_guards(route.dependant)):
                    unguarded.append(f"{method} {route.path}")
    assert seen > 20
    assert unguarded == []


# --------------------------------------------------------------------------- #
#  Routes
# --------------------------------------------------------------------------- #

def _as(user, perms=frozenset()):
    """Log in as `user` holding `perms` ({"companies:delete", ...})."""
    def permissions_for(_user, module):
        return {p.split(":")[1] for p in perms if p.split(":")[0] == module}
    return (patch("middleware.auth._resolve_user", return_value=user),
            patch("middleware.auth._permissions_for", side_effect=permissions_for))


class _Session:
    def __init__(self, user, perms, sb):
        self.patches = [*_as(user, perms),
                        patch("routers.companies.get_supabase", return_value=sb),
                        patch("routers.persons.get_supabase", return_value=sb),
                        patch("routers.companies.log_event", new_callable=AsyncMock),
                        patch("routers.persons.log_event", new_callable=AsyncMock)]

    def __enter__(self):
        mocks = [p.start() for p in self.patches]
        return SimpleNamespace(company_audit=mocks[4], person_audit=mocks[5])

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()


@pytest.mark.parametrize("perms", [
    frozenset(), frozenset({"companies:read"}),
    frozenset({"companies:read", "companies:write"}),
    frozenset({"persons:delete"}),
])
def test_deleting_a_company_takes_companies_delete_and_nothing_less(perms):
    sb = _company_sb(entity_officers=[], company_secretaries=[])
    with _Session(STAFF, perms, sb):
        resp = client.post("/companies/gshk/delete", json={"reason": "dup"}, headers=H)
    assert resp.status_code == 403
    assert sb.writes == []


def test_a_company_with_nothing_holding_it_is_deleted_and_audited():
    sb = _company_sb(entity_officers=[], company_secretaries=[])
    with _Session(STAFF, {"companies:delete"}, sb) as s:
        resp = client.post("/companies/gshk/delete",
                           json={"reason": "  duplicate of the ETL profile "},
                           headers=H)
    assert resp.status_code == 200, resp.text
    row = sb.tables["entities"][0]
    assert row["deleted_reason"] == "duplicate of the ETL profile"
    assert row["deleted_by"] == "u-2" and row["deleted_at"]
    audit = s.company_audit.await_args.kwargs
    assert audit["event_code"] == "GF_COMPANY_DELETED"
    assert audit["action_type"] == "COMPANY_DELETED"
    assert audit["subject_id"] == "gshk" and audit["subject_ref"] == "BR-gshk"


def test_a_company_still_somebodys_secretary_is_refused_with_409():
    sb = _company_sb()
    with _Session(SUPER_ADMIN, set(), sb) as s:
        resp = client.post("/companies/gshk/delete", json={"reason": "x"}, headers=H)
    assert resp.status_code == 409
    assert "CLIENT LTD" in resp.json()["detail"]
    assert sb.writes == [] and not s.company_audit.await_count


def test_a_blank_reason_is_a_422_and_changes_nothing():
    sb = _company_sb(entity_officers=[], company_secretaries=[])
    with _Session(SUPER_ADMIN, set(), sb):
        resp = client.post("/companies/gshk/delete", json={"reason": "  "}, headers=H)
    assert resp.status_code == 422 and sb.writes == []


def test_the_dialog_is_told_what_blocks_before_anyone_types_a_reason():
    sb = _company_sb()
    with _Session(SUPER_ADMIN, set(), sb):
        body = client.get("/companies/gshk/deletion-check", headers=H).json()
    assert body["can_delete"] is False
    assert [e["company_name"] for e in body["links"]] == ["CLIENT LTD", "CLIENT TWO LTD"]


def _deleted_company_sb():
    return _company_sb(entities=[_company("gone", "GONE LTD", deleted_at=DELETED_AT,
                                          deleted_by="admin-1",
                                          deleted_reason="duplicate",
                                          is_client=False)],
                       users=[{"id": "admin-1", "display_name": "Levi Z."}])


@pytest.mark.parametrize("method, path, body", [
    ("patch", "/companies/gone", {"company_name": "X"}),
    ("patch", "/companies/gone/flags", {"is_client": True}),
    ("post", "/companies/gone/officers", {"person_id": "p1"}),
    ("get", "/companies/gone/documents", None),
    ("post", "/companies/gone/delete", {"reason": "again"}),
])
def test_a_deleted_company_is_a_404_to_every_route_but_its_profile(method, path, body):
    sb = _deleted_company_sb()
    with _Session(SUPER_ADMIN, set(), sb):
        resp = getattr(client, method)(path, headers=H,
                                       **({"json": body} if body else {}))
    assert resp.status_code == 404
    assert sb.writes == []


def test_a_deleted_company_profile_is_a_404_without_the_delete_grant():
    with _Session(STAFF, {"companies:read", "companies:write"}, _deleted_company_sb()):
        resp = client.get("/companies/gone", headers=H)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Company not found"


def test_a_deleted_company_profile_says_who_and_why_to_a_role_that_can_restore():
    with _Session(STAFF, {"companies:read", "companies:delete"}, _deleted_company_sb()), \
         patch("routers.companies.document_service.list_documents", return_value=[]):
        resp = client.get("/companies/gone", headers=H)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted_at"] == DELETED_AT
    assert body["deleted_reason"] == "duplicate"
    assert body["deleted_by_name"] == "Levi Z."


def test_the_deleted_list_is_for_the_delete_grant_only():
    sb = _deleted_company_sb()
    with _Session(STAFF, {"companies:read", "companies:write"}, sb):
        assert client.get("/companies/deleted", headers=H).status_code == 403
    with _Session(STAFF, {"companies:delete"}, sb):
        body = client.get("/companies/deleted", headers=H).json()
    assert [c["company_name"] for c in body["companies"]] == ["GONE LTD"]
    assert body["companies"][0]["deleted_by_name"] == "Levi Z."


def test_restoring_a_company_brings_it_back_and_is_audited():
    sb = _deleted_company_sb()
    with _Session(STAFF, {"companies:delete"}, sb) as s:
        resp = client.post("/companies/gone/restore", headers=H)
        again = client.post("/companies/gone/restore", headers=H)
    assert resp.status_code == 200 and again.status_code == 409
    assert sb.tables["entities"][0]["deleted_at"] is None
    assert s.company_audit.await_args.kwargs["event_code"] == "GF_COMPANY_RESTORED"


@pytest.mark.parametrize("field, table", [("person_id", "persons"),
                                          ("corporate_entity_id", "entities")])
def test_a_deleted_party_cannot_be_given_a_role(field, table):
    sb = _company_sb(persons=[_person("pgone", "GONE", deleted_at=DELETED_AT)])
    sb.tables["entities"].append(_company("pgone", "GONE CO", deleted_at=DELETED_AT))
    with _Session(SUPER_ADMIN, set(), sb):
        resp = client.post("/companies/client/officers",
                           json={field: "pgone", "role": "director"}, headers=H)
    assert resp.status_code == 422
    assert "deleted" in resp.json()["detail"]


# ---- persons ---------------------------------------------------------------

def test_a_person_with_no_current_role_is_deleted_and_audited():
    sb = _person_links_sb()
    for t in ("entity_officers", "shareholdings", "company_secretaries"):
        sb.tables[t] = []
    sb.tables["persons"] = [_person("p1", "Chan Tai Man")]
    sb.tables["person_identity_documents"] = []
    with _Session(STAFF, {"persons:delete"}, sb) as s:
        resp = client.post("/persons/p1/delete", json={"reason": "test record"},
                           headers=H)
    assert resp.status_code == 200, resp.text
    assert sb.tables["persons"][0]["deleted_reason"] == "test record"
    audit = s.person_audit.await_args.kwargs
    assert audit["event_code"] == "GF_PERSON_DELETED"
    assert audit["company_name"] == "Chan Tai Man"


def test_a_sitting_director_cannot_be_deleted():
    sb = _person_links_sb()
    sb.tables["persons"] = [_person("p1", "Chan Tai Man")]
    with _Session(SUPER_ADMIN, set(), sb):
        resp = client.post("/persons/p1/delete", json={"reason": "x"}, headers=H)
    assert resp.status_code == 409
    assert "LIVE LTD" in resp.json()["detail"]


def test_deleting_a_person_takes_persons_delete():
    sb = FakeSB(persons=[_person("p1", "A")])
    with _Session(STAFF, {"persons:read", "persons:write", "companies:delete"}, sb):
        resp = client.post("/persons/p1/delete", json={"reason": "x"}, headers=H)
    assert resp.status_code == 403


def test_a_deleted_person_is_a_404_to_edits_and_to_a_profile_reader():
    sb = FakeSB(persons=[_person("p1", "A", deleted_at=DELETED_AT,
                                 deleted_reason="dup")])
    with _Session(STAFF, {"persons:read", "persons:write"}, sb):
        assert client.patch("/persons/p1", json={"full_name": "B"},
                            headers=H).status_code == 404
        assert client.get("/persons/p1", headers=H).status_code == 404
    assert sb.writes == []


def test_a_role_at_a_deleted_company_leaves_the_person_profile():
    from routers.persons import _role_rollup

    rollup = _role_rollup(_person_links_sb(), "p1")
    assert {r["company_name"] for r in rollup} == {"LIVE LTD", "OTHER LTD"}


def test_the_persons_deleted_list_is_for_the_delete_grant_only():
    sb = FakeSB(persons=[_person("p1", "A", deleted_at=DELETED_AT,
                                 deleted_reason="dup")], users=[])
    with _Session(STAFF, {"persons:read"}, sb):
        assert client.get("/persons/deleted", headers=H).status_code == 403
    with _Session(STAFF, {"persons:delete"}, sb):
        body = client.get("/persons/deleted", headers=H).json()
    assert [p["full_name"] for p in body["persons"]] == ["A"]


# ---- the company profile, when a party was deleted --------------------------

def _profile_sb(officer_current: bool):
    sb = MagicMock()
    entity = _company("c1", "CLIENT LTD", is_client=False)
    officer = {"id": "o1", "entity_id": "c1", "person_id": "p9", "role": "director",
               "is_current": officer_current,
               "persons": _person("p9", "Gone Person", deleted_at=DELETED_AT)}
    sel = sb.table.return_value.select.return_value
    sel.eq.return_value.single.return_value.execute.return_value.data = entity
    sel.eq.return_value.execute.return_value.data = []
    sel.eq.return_value.neq.return_value.execute.return_value.data = [officer]
    sel.eq.return_value.eq.return_value.execute.return_value.data = []
    return sb


@pytest.mark.parametrize("current", [True, False])
def test_a_deleted_party_is_left_off_the_profile(current):
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase", return_value=_profile_sb(current)), \
         patch("routers.companies.document_service.list_documents", return_value=[]):
        body = client.get("/companies/c1", headers=H).json()
    assert body["officers"] == []
    problems = [p["message"] for p in body["filing_problems"] if p["field"] == "parties"]
    # A CURRENT one cannot just vanish: the return would still carry them.
    assert bool(problems) is current
    if current:
        assert "Gone Person" in problems[0]


# ---- cases -----------------------------------------------------------------

def test_no_case_can_be_opened_for_a_deleted_company():
    from services import nar1_cases

    sb = FakeSB(entities=[_company("gone", "GONE", deleted_at=DELETED_AT)])
    with patch("services.nar1_cases.get_supabase", return_value=sb):
        with pytest.raises(ValueError, match="deleted"):
            nar1_cases.create_case(entity_id="gone", form_code="Nar1", user_id="u")


def test_the_case_route_refuses_a_deleted_company_with_a_400():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("services.nar1_cases.get_supabase",
               return_value=FakeSB(entities=[_company("gone", "G",
                                                      deleted_at=DELETED_AT)])):
        resp = client.post("/cases", json={"entity_id": "gone"}, headers=H)
    assert resp.status_code == 400
    assert "deleted" in resp.json()["detail"]


@pytest.mark.parametrize("flag, status", [(True, 404), (False, 200)])
def test_a_case_of_a_deleted_company_is_gone_with_it(flag, status):
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.cases.nar1_cases.composite",
               return_value={"id": "k1", "company_deleted": flag}):
        assert client.get("/cases/k1", headers=H).status_code == status


def test_composite_asks_about_the_company_only_when_the_view_hid_the_case():
    from services import nar1_cases

    with patch.object(nar1_cases, "get_case", return_value={"id": "k1", "entity_id": "gone"}), \
         patch.object(nar1_cases, "current_filing", return_value=None), \
         patch.object(nar1_cases, "_company_deleted", return_value=True) as asked:
        with patch.object(nar1_cases, "_company_header", return_value={"company_name": "X"}):
            assert nar1_cases.composite("k1")["company_deleted"] is False
        asked.assert_not_called()
        with patch.object(nar1_cases, "_company_header", return_value={}):
            assert nar1_cases.composite("k1")["company_deleted"] is True
        asked.assert_called_once_with("gone")


# ---- the return ------------------------------------------------------------

def test_the_mapper_refuses_a_return_that_still_names_a_deleted_party():
    from tests.tpsi.test_nar1_mapper import graph, mapped

    mapped(graph())  # the fixture maps cleanly on its own
    with pytest.raises(nar1_mapper.MappingError) as exc:
        mapped(graph(deleted_parties=["Gone Person"]))
    assert any("Gone Person" in p and "deleted" in p for p in exc.value.problems)


def test_the_mapper_refuses_a_deleted_company():
    from tests.tpsi.test_nar1_mapper import graph, mapped

    g = graph()
    g["entity"] = {**g["entity"], "deleted_at": DELETED_AT}
    with pytest.raises(nar1_mapper.MappingError) as exc:
        mapped(g)
    assert any("has been deleted" in p for p in exc.value.problems)


def test_a_deleted_namesake_is_nobodys_secretary():
    from services.tpsi.forms import nar1_source

    live = {"id": "live", "company_name": "Payward Limited"}
    gone = {"id": "gone", "company_name": "Payward Limited", "deleted_at": DELETED_AT}
    index = nar1_source._index_by_name([live, gone])
    assert index == {nar1_source._normalise_name("Payward Limited"): [live]}
