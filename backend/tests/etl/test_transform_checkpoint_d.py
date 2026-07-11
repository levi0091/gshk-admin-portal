from datetime import datetime

from etl.transform.checkpoint_d import (
    pick_current_address_nr, transform_nonclient_corporate, _resolve_name,
)
from etl.reconciliation import ReconciliationReport


def _corp(**kw):
    base = {"RefCode": "ASIABC", "Name": "Asia BC Ltd", "CompName": None,
            "SearchName": "ASIABCLTD", "ChnsName": None}
    base.update(kw)
    return base


# --- name resolution --------------------------------------------------------

def test_resolve_name_prefers_name_over_compname():
    assert _resolve_name(_corp(Name="Real Name", CompName="Comp")) == "Real Name"


def test_resolve_name_falls_back_when_name_blank():
    assert _resolve_name(_corp(Name="   ", CompName="Comp Co")) == "Comp Co"
    assert _resolve_name(_corp(Name=None, CompName=None, SearchName="SN")) == "SN"


def test_resolve_name_unknown_when_all_blank():
    assert _resolve_name(_corp(Name=None, CompName=None, SearchName=None)) == "UNKNOWN"


# --- current-address selection ---------------------------------------------

def test_pick_current_address_none_when_empty():
    assert pick_current_address_nr([]) is None


def test_pick_current_address_prefers_not_cancelled():
    rows = [
        {"AddrNr": 1, "Effective": datetime(2020, 1, 1), "Cancelled": datetime(2021, 1, 1)},
        {"AddrNr": 2, "Effective": datetime(2019, 1, 1), "Cancelled": None},
    ]
    assert pick_current_address_nr(rows) == 2  # active beats a newer cancelled one


def test_pick_current_address_latest_effective_among_active():
    rows = [
        {"AddrNr": 1, "Effective": datetime(2019, 1, 1), "Cancelled": None},
        {"AddrNr": 2, "Effective": datetime(2022, 1, 1), "Cancelled": None},
    ]
    assert pick_current_address_nr(rows) == 2


# --- entity row transform ---------------------------------------------------

def test_transform_sets_flags_and_key():
    out = transform_nonclient_corporate(
        _corp(), 55, {"55": "addr-uuid"}, {"ASIABC"}, ReconciliationReport())
    assert out["vp_source_key"] == "ASIABC"
    assert out["company_name"] == "Asia BC Ltd"
    assert out["is_client"] is False
    assert out["is_corporate_party"] is True          # ASIABC is in the party set
    assert out["status"] == "live"
    assert out["registered_address_id"] == "addr-uuid"


def test_transform_unreferenced_orphan_not_flagged_as_party():
    out = transform_nonclient_corporate(
        _corp(RefCode="ORPHAN"), None, {}, {"ASIABC"}, ReconciliationReport())
    assert out["is_corporate_party"] is False         # not referenced anywhere
    assert out["is_client"] is False
    assert out["registered_address_id"] is None


def test_transform_missing_address_logs_but_does_not_drop():
    report = ReconciliationReport()
    out = transform_nonclient_corporate(
        _corp(), 999, {}, {"ASIABC"}, report)          # AddrNr 999 not in addresses map
    assert out["registered_address_id"] is None
    assert len(report.errors) == 1
    assert report.errors[0]["vp_source_key"] == "ASIABC"


def test_transform_chinese_name_trimmed_or_none():
    assert transform_nonclient_corporate(
        _corp(ChnsName="  亞洲  "), None, {}, set(), ReconciliationReport())["company_name_zh"] == "亞洲"
    assert transform_nonclient_corporate(
        _corp(ChnsName="   "), None, {}, set(), ReconciliationReport())["company_name_zh"] is None
