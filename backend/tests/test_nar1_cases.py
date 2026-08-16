"""services/nar1_cases.py — direct coverage, mocked at the get_supabase()
boundary (the tests/tpsi/test_filings.py / test_documents_service.py style),
not by mocking the functions under test. test_cases_router.py already covers
the router; it patches nar1_cases wholesale, so it proves nothing about what
this module actually does with the Supabase client.
"""
from unittest.mock import MagicMock, patch

import pytest

from services import nar1_cases
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
