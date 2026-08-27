"""services/nar1_cases.py — direct coverage, mocked at the get_supabase()
boundary (the tests/tpsi/test_filings.py / test_documents_service.py style),
not by mocking the functions under test. test_cases_router.py already covers
the router; it patches nar1_cases wholesale, so it proves nothing about what
this module actually does with the Supabase client.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services import nar1_case_status, nar1_cases
from services.tpsi import filings as tpsi_filings


def _sb_with(case_row: dict, filing_rows: list[dict]) -> MagicMock:
    """A get_supabase() double that answers differently for `nar1_cases` vs
    `tpsi_filings` -- composite() reads both tables through the same client,
    so a single fixed `return_value` (which cannot distinguish call args)
    would hand the filing chain's response back to the case query too.
    """
    sb = MagicMock()

    case_table = MagicMock()
    case_table.select.return_value.eq.return_value.execute.return_value.data = [case_row]

    filing_table = MagicMock()
    filing_chain = (
        filing_table.select.return_value.eq.return_value
        .neq.return_value.order.return_value.limit.return_value
    )
    filing_chain.execute.return_value.data = filing_rows

    def _table(name):
        return case_table if name == "nar1_cases" else filing_table

    sb.table.side_effect = _table
    return sb


# ---- get_case ---------------------------------------------------------


def test_get_case_returns_the_row():
    with patch("services.nar1_cases.get_supabase") as msb:
        sb = MagicMock()
        msb.return_value = sb
        sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"id": "c1"}
        ]

        row = nar1_cases.get_case("c1")

    sb.table.assert_called_with("nar1_cases")
    sb.table.return_value.select.assert_called_with("*")
    sb.table.return_value.select.return_value.eq.assert_called_with("id", "c1")
    assert row == {"id": "c1"}


def test_get_case_raises_lookup_error_when_no_row_comes_back():
    with patch("services.nar1_cases.get_supabase") as msb:
        sb = MagicMock()
        msb.return_value = sb
        sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []

        with pytest.raises(LookupError):
            nar1_cases.get_case("nope")


# ---- create_case --------------------------------------------------------


def test_create_case_rejects_a_non_nar1_form_code_before_any_db_call():
    """R1 is NAR1 only. Nothing about this check needs a client."""
    with patch("services.nar1_cases.get_supabase") as msb:
        with pytest.raises(ValueError):
            nar1_cases.create_case(entity_id="e1", form_code="Nnc1", user_id="u1")
    msb.assert_not_called()


def test_create_case_allocates_via_next_case_no_and_stores_annual_return():
    with patch("services.nar1_cases.get_supabase") as msb:
        sb = MagicMock()
        msb.return_value = sb
        sb.rpc.return_value.execute.return_value.data = "NAR-2026-0007"
        sb.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "c1", "case_no": "NAR-2026-0007"}
        ]

        row = nar1_cases.create_case(entity_id="e1", form_code="Nar1", user_id="u9")

    rpc_name, rpc_args = sb.rpc.call_args[0]
    assert rpc_name == "next_case_no"
    assert rpc_args["p_prefix"].startswith("NAR-")

    payload = sb.table.return_value.insert.call_args[0][0]
    assert payload["nar1_type"] == "annual_return"
    assert payload["case_no"] == "NAR-2026-0007"
    assert payload["entity_id"] == "e1"
    assert payload["created_by"] == "u9"
    assert payload["assigned_to"] == "u9"
    assert row["case_no"] == "NAR-2026-0007"


# ---- update_case ----------------------------------------------------------


def test_update_case_stamps_updated_at_alongside_the_patch():
    with patch("services.nar1_cases.get_supabase") as msb:
        sb = MagicMock()
        msb.return_value = sb
        sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": "c1"}
        ]

        nar1_cases.update_case("c1", {"aml_cleared": True})

    payload = sb.table.return_value.update.call_args[0][0]
    assert payload["aml_cleared"] is True
    assert payload["updated_at"] is not None
    sb.table.return_value.update.return_value.eq.assert_called_with("id", "c1")


# ---- current_filing ---------------------------------------------------


def test_current_filing_excludes_superseded_and_orders_newest_first():
    with patch("services.nar1_cases.get_supabase") as msb:
        sb = MagicMock()
        msb.return_value = sb
        chain = (
            sb.table.return_value.select.return_value.eq.return_value
            .neq.return_value.order.return_value.limit.return_value
        )
        chain.execute.return_value.data = [{"id": "f2", "stage": "signed"}]

        result = nar1_cases.current_filing("c1")

    sb.table.assert_called_with("tpsi_filings")
    sb.table.return_value.select.return_value.eq.assert_called_with("nar1_case_id", "c1")
    sb.table.return_value.select.return_value.eq.return_value.neq.assert_called_with(
        "stage", tpsi_filings.STAGE_SUPERSEDED
    )
    (
        sb.table.return_value.select.return_value.eq.return_value.neq.return_value
        .order.assert_called_with("created_at", desc=True)
    )
    (
        sb.table.return_value.select.return_value.eq.return_value.neq.return_value
        .order.return_value.limit.assert_called_with(1)
    )
    assert result == {"id": "f2", "stage": "signed"}


def test_current_filing_returns_none_when_there_are_no_rows():
    with patch("services.nar1_cases.get_supabase") as msb:
        sb = MagicMock()
        msb.return_value = sb
        chain = (
            sb.table.return_value.select.return_value.eq.return_value
            .neq.return_value.order.return_value.limit.return_value
        )
        chain.execute.return_value.data = []

        result = nar1_cases.current_filing("c1")

    assert result is None


# ---- composite ----------------------------------------------------------


def test_composite_returns_both_statuses_and_the_filing_id():
    case_row = {"id": "c1", "manual_receipt": None}
    filing_row = {"id": "f1", "stage": tpsi_filings.STAGE_VALIDATED}
    sb = _sb_with(case_row, [filing_row])

    with patch("services.nar1_cases.get_supabase", return_value=sb):
        result = nar1_cases.composite("c1")

    assert result["filing_id"] == "f1"
    assert "workflow_status" in result and result["workflow_status"]["code"]
    assert result["form_status"]["code"] == tpsi_filings.STAGE_VALIDATED


def test_composite_form_status_is_none_without_a_filing():
    case_row = {"id": "c1", "manual_receipt": None}
    sb = _sb_with(case_row, [])

    with patch("services.nar1_cases.get_supabase", return_value=sb):
        result = nar1_cases.composite("c1")

    assert result["filing_id"] is None
    assert result["form_status"] is None
    # derive() must still run with filing=None -- it does not blow up without
    # a filing row (that is the whole point of the D-6 split).
    assert result["workflow_status"]["code"] == "data_verification"


def test_composite_receipt_prefers_the_filing_receipt_over_manual():
    case_row = {"id": "c1", "manual_receipt": {"source": "manual"}}
    filing_row = {
        "id": "f1", "stage": tpsi_filings.STAGE_SUBMITTED,
        "receipt": {"source": "filing"},
    }
    sb = _sb_with(case_row, [filing_row])

    with patch("services.nar1_cases.get_supabase", return_value=sb):
        result = nar1_cases.composite("c1")

    assert result["receipt"] == {"source": "filing"}


def test_composite_receipt_falls_back_to_the_manual_receipt_without_a_filing():
    case_row = {"id": "c1", "manual_receipt": {"source": "manual"}}
    sb = _sb_with(case_row, [])

    with patch("services.nar1_cases.get_supabase", return_value=sb):
        result = nar1_cases.composite("c1")

    assert result["receipt"] == {"source": "manual"}


# ---- list_dashboard (BE-7) --------------------------------------------
#
# A hand-written PostgREST double rather than a MagicMock chain. The property
# under test is WHICH FILTER REACHED WHICH QUERY -- a MagicMock returns itself
# for every call, so it can say a filter was applied but not to what, and the
# eight count queries and the page query would be indistinguishable.

class _FakeQuery:
    """Records the PostgREST calls made against one query."""

    def __init__(self, log: dict, rows: list, count: int):
        self.log = log
        self._rows = rows
        self._count = count
        log.update({"or": None, "eq": [], "cmp": [], "not_is": [],
                    "order": None, "range": None, "limit": None})

    def or_(self, expr):
        self.log["or"] = expr
        return self

    def eq(self, col, val):
        self.log["eq"].append((col, val))
        return self

    def __getattr__(self, name):
        if name in ("lte", "gte", "gt", "lt"):
            def apply(col, val):
                self.log["cmp"].append((name, col, val))
                return self
            return apply
        raise AttributeError(name)

    @property
    def not_(self):
        outer = self

        class _Not:
            def is_(self, col, val):
                outer.log["not_is"].append((col, val))
                return outer

        return _Not()

    def order(self, col, desc=False, nullsfirst=None):
        self.log["order"] = (col, desc, nullsfirst)
        return self

    def range(self, start, end):
        self.log["range"] = (start, end)
        return self

    def limit(self, n):
        self.log["limit"] = n
        return self

    def execute(self):
        return SimpleNamespace(data=self._rows, count=self._count)


class _FakeSupabase:
    def __init__(self, rows=(), count=0):
        self.rows = list(rows)
        self.count = count
        self.queries: list[dict] = []

    def table(self, name):
        self.table_name = name
        return self

    def select(self, cols, count=None):
        log = {"cols": cols, "count_mode": count}
        self.queries.append(log)
        # Only the page query returns rows. A count query that also handed rows
        # back would hide a missing .range().
        rows = [] if count else [dict(r) for r in self.rows]
        return _FakeQuery(log, rows, self.count)

    @property
    def count_queries(self):
        return [q for q in self.queries if q["count_mode"] == "exact"]

    @property
    def page_query(self):
        return next(q for q in self.queries if q["count_mode"] is None)


def _registry_row(**over):
    row = {"id": "c1", "case_no": "NAR-2026-0041", "workflow_status": "signing",
           "workflow_off_portal": False, "workflow_overdue": False,
           "days_to_anniversary": 12}
    row.update(over)
    return row


async def test_list_dashboard_reads_the_registry_view_not_the_table():
    """nar1_cases carries no days_to_anniversary and no workflow badge. Reading
    the table would mean deriving both in Python over one page of rows, which
    sorts and filters the 50 rows the server happened to send."""
    sb = _FakeSupabase(rows=[_registry_row()], count=1)
    with patch("services.nar1_cases.get_supabase", return_value=sb):
        await nar1_cases.list_dashboard()
    assert sb.table_name == "nar1_case_registry"


async def test_list_dashboard_returns_the_badge_in_derives_shape():
    """The dashboard and the case detail must not disagree on the key names of
    the badge, let alone on its value."""
    sb = _FakeSupabase(
        rows=[_registry_row(workflow_status="completed", workflow_off_portal=True)],
        count=1,
    )
    with patch("services.nar1_cases.get_supabase", return_value=sb):
        result = await nar1_cases.list_dashboard()
    assert result["rows"][0]["workflow_status"] == {
        "code": "completed", "label": "Completed",
        "off_portal": True, "overdue": False,
    }


async def test_list_dashboard_counts_every_status_badge():
    """The filter tabs count the WHOLE filtered set, not the page: PostgREST
    caps returned rows at 1000, so counting fetched rows under-reports."""
    sb = _FakeSupabase(rows=[_registry_row()], count=3)
    with patch("services.nar1_cases.get_supabase", return_value=sb):
        result = await nar1_cases.list_dashboard()
    assert set(result["counts"]) == {"all", *nar1_case_status.WORKFLOW_STATUSES}
    assert len(sb.count_queries) == 1 + len(nar1_case_status.WORKFLOW_STATUSES)


async def test_the_status_tab_counts_ignore_the_selected_tab():
    """Applying the selected status to every count would collapse the other tabs
    to zero, and the tab bar would only ever show one number."""
    sb = _FakeSupabase(rows=[_registry_row()], count=3)
    with patch("services.nar1_cases.get_supabase", return_value=sb):
        await nar1_cases.list_dashboard(workflow_status="awaiting_client")
    filtered = [q for q in sb.count_queries
                if ("workflow_status", "awaiting_client") in q["eq"]]
    assert len(filtered) == 1


async def test_the_total_follows_the_selected_status():
    """A pager quoting the unfiltered total for a filtered list invents pages
    that render empty."""
    sb = _FakeSupabase(rows=[_registry_row()], count=7)
    with patch("services.nar1_cases.get_supabase", return_value=sb):
        result = await nar1_cases.list_dashboard(workflow_status="signing")
    assert result["total"] == result["counts"]["signing"]


async def test_the_anniversary_filter_reaches_the_count_queries_too():
    """Filtering only the page query leaves the pager and the tab counts quoting
    totals for a set the user is not looking at."""
    sb = _FakeSupabase(rows=[_registry_row()], count=1)
    with patch("services.nar1_cases.get_supabase", return_value=sb):
        await nar1_cases.list_dashboard(anniv_op="lte", anniv_days=30)
    assert all(("lte", "days_to_anniversary", 30) in q["cmp"] for q in sb.queries)
    # A company with no incorporation_date cannot answer a numeric question.
    assert all(("days_to_anniversary", "null") in q["not_is"] for q in sb.queries)


async def test_the_search_reaches_the_count_queries_too():
    sb = _FakeSupabase(rows=[_registry_row()], count=1)
    with patch("services.nar1_cases.get_supabase", return_value=sb):
        await nar1_cases.list_dashboard(search="acme")
    assert all("acme" in (q["or"] or "") for q in sb.queries)
    assert "case_no.ilike" in sb.page_query["or"]


async def test_the_default_sort_is_the_deadline_soonest_first():
    """The deadline is why this screen exists. nullsfirst=False explicitly:
    Postgres puts NULLs first on a DESC sort, which would open the list with
    every company that has no incorporation date and therefore no answer."""
    sb = _FakeSupabase(rows=[_registry_row()], count=1)
    with patch("services.nar1_cases.get_supabase", return_value=sb):
        await nar1_cases.list_dashboard()
    assert sb.page_query["order"] == ("days_to_anniversary", False, False)


async def test_paging_maps_to_a_postgrest_range():
    sb = _FakeSupabase(rows=[_registry_row()], count=1)
    with patch("services.nar1_cases.get_supabase", return_value=sb):
        await nar1_cases.list_dashboard(page=3, page_size=20)
    assert sb.page_query["range"] == (40, 59)


@pytest.mark.parametrize("kwargs", [
    {"anniv_op": "near", "anniv_days": 5},
    {"anniv_op": "lte"},
    {"anniv_days": 5},
    {"workflow_status": "nonsense"},
    {"sort": "manual_receipt"},
])
async def test_list_dashboard_refuses_arguments_the_router_would_have_rejected(kwargs):
    """The router answers 422, but the whitelists are re-checked here: anniv_op
    becomes a method name and sort becomes a PostgREST order clause, so a caller
    that skipped the router must not reach either. Same reasoning that put the
    manual-submission interlock in the service rather than the route (Task 10).
    """
    with patch("services.nar1_cases.get_supabase") as msb:
        with pytest.raises(ValueError):
            await nar1_cases.list_dashboard(**kwargs)
    msb.assert_not_called()


# ---- search is data, not filter grammar ------------------------------------

def test_search_term_with_commas_and_dots_cannot_add_filter_clauses():
    """PostgREST's or_() is a comma-separated, dot-delimited grammar, so a term
    containing either used to become MORE GRAMMAR rather than a value:
    `a,br_number.eq.X` silently adds a clause nobody asked for."""
    hostile = 'ACME,br_number.eq.SECRET'
    escaped = nar1_cases._escape_filter_value(hostile)
    # Quoted as ONE literal, so the separators inside it are inert.
    assert escaped.startswith('"%') and escaped.endswith('%"')
    assert escaped == '"%ACME,br_number.eq.SECRET%"'


def test_search_term_cannot_close_the_quote_early():
    """A double quote in the term would otherwise end the literal and let the
    rest of the term be read as grammar again."""
    assert nar1_cases._escape_filter_value('a"b') == '"%a\\"b%"'
    assert nar1_cases._escape_filter_value("a\\b") == r'"%a\\b%"'


# ---- composite() carries the company-side header ---------------------------
#
# `nar1_cases` holds only entity_id, so a case read straight off the table has
# no company name, no BR number and no anniversary -- and those are what the
# v11 case header is made of. The dashboard never showed this because it reads
# `nar1_case_registry`; the detail read did not, so the same case rendered
# fully on the list and half-empty one click later (Levi, 2026-08-27).


def _sb_with_registry(case_row: dict, filing_rows: list[dict],
                      registry_row: dict | None) -> MagicMock:
    """Like _sb_with, but answers `nar1_case_registry` too.

    Deliberately a THIRD table double rather than a widened `_sb_with`: a bare
    MagicMock answers `select().eq().limit().execute().data` with a MagicMock
    whose `keys()` yields nothing, so `{**that}` expands to {} and a broken
    merge would look exactly like a working one.
    """
    sb = _sb_with(case_row, filing_rows)
    inner = sb.table.side_effect

    registry_table = MagicMock()
    (registry_table.select.return_value.eq.return_value
     .limit.return_value.execute.return_value.data) = (
        [registry_row] if registry_row is not None else [])

    def _table(name):
        return registry_table if name == "nar1_case_registry" else inner(name)

    sb.table.side_effect = _table
    return sb


def test_composite_carries_the_company_name_brn_and_anniversary():
    sb = _sb_with_registry(
        {"id": "c1", "manual_receipt": None}, [],
        {"company_name": "Harbour Tech Ltd.", "br_number": "2100028",
         "cr_number": "3456789", "company_name_zh": "海港科技",
         "days_to_anniversary": -12, "case_type": "NAR1"},
    )
    with patch("services.nar1_cases.get_supabase", return_value=sb):
        result = nar1_cases.composite("c1")

    assert result["company_name"] == "Harbour Tech Ltd."
    assert result["br_number"] == "2100028"
    assert result["days_to_anniversary"] == -12
    assert result["case_type"] == "NAR1"


def test_composite_workflow_status_stays_the_derived_OBJECT():
    """The view carries a workflow_status STRING of its own.

    Letting it land on top of derive()'s composite object is React error #31 --
    "Objects are not valid as a React child" -- which unmounts the whole tree
    and blanks the page. That shipped once already.
    """
    sb = _sb_with_registry(
        {"id": "c1", "manual_receipt": None}, [],
        {"company_name": "Harbour Tech Ltd.", "workflow_status": "completed"},
    )
    with patch("services.nar1_cases.get_supabase", return_value=sb):
        result = nar1_cases.composite("c1")

    assert isinstance(result["workflow_status"], dict)
    assert result["workflow_status"]["code"] == "data_verification"


def test_composite_still_renders_when_the_registry_view_is_unreachable():
    """The header decorates a case that has already been read. A view outage
    should cost the company name, not the whole case detail."""
    sb = _sb_with({"id": "c1", "case_no": "NAR-2026-0041", "manual_receipt": None}, [])
    boom = MagicMock()
    boom.select.side_effect = RuntimeError("view is gone")
    inner = sb.table.side_effect
    sb.table.side_effect = lambda n: boom if n == "nar1_case_registry" else inner(n)

    with patch("services.nar1_cases.get_supabase", return_value=sb):
        result = nar1_cases.composite("c1")

    assert result["case_no"] == "NAR-2026-0041"
    assert result["workflow_status"]["code"] == "data_verification"


def test_composite_tolerates_a_case_missing_from_the_view():
    sb = _sb_with_registry({"id": "c1", "manual_receipt": None}, [], None)
    with patch("services.nar1_cases.get_supabase", return_value=sb):
        result = nar1_cases.composite("c1")
    assert result["id"] == "c1"
    assert result.get("company_name") is None
