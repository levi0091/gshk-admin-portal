from etl.transform.checkpoint_b import transform_share_classes, transform_business_name, transform_entity_name_change
from etl.transform.checkpoint_b import transform_share_transaction, transform_share_certificate
from etl.reconciliation import ReconciliationReport


def _sc(entcode, shareclass, name, **kw):
    base = {
        "EntCode": entcode, "ShareClass": shareclass, "ShareClassName": name,
        "Currency": "HKD", "NomValShare": 1, "VotesPerShare": 1,
        "Issued": 100, "PaidCap": 100,
    }
    base.update(kw)
    return base


def test_transform_share_classes_basic_mapping():
    rows = [_sc("E1", "OR01", "Ordinary", NomValShare=1, VotesPerShare=1, Issued=1000, PaidCap=1000)]
    report = ReconciliationReport()
    out = transform_share_classes(rows, {"E1": "e-uuid"}, report)
    assert len(out) == 1
    r = out[0]
    assert r["vp_source_key"] == "E1:OR01"
    assert r["entity_id"] == "e-uuid"
    assert r["class_name"] == "Ordinary"
    assert r["currency"] == "HKD"
    assert r["nominal_value"] == 1
    assert r["votes_per_share"] == 1
    assert r["total_issued"] == 1000
    assert r["total_paid"] == 1000


def test_transform_share_classes_disambiguates_same_name_within_entity():
    rows = [
        _sc("E1", "OR01", "Ordinary"),
        _sc("E1", "OR02", "Ordinary"),
        _sc("E2", "OR01", "Ordinary"),  # different entity, no collision
    ]
    report = ReconciliationReport()
    out = transform_share_classes(rows, {"E1": "e1", "E2": "e2"}, report)
    names = {r["vp_source_key"]: r["class_name"] for r in out}
    # E1 has two "Ordinary" -> disambiguated by code; E2's stays plain
    assert names["E1:OR01"] == "Ordinary (OR01)"
    assert names["E1:OR02"] == "Ordinary (OR02)"
    assert names["E2:OR01"] == "Ordinary"


def test_transform_share_classes_null_name_defaults_ordinary():
    rows = [_sc("E1", "OR01", None)]
    out = transform_share_classes(rows, {"E1": "e1"}, ReconciliationReport())
    assert out[0]["class_name"] == "Ordinary"


def test_transform_share_classes_unresolved_entity_dropped_and_logged():
    rows = [_sc("GHOST", "OR01", "Ordinary")]
    report = ReconciliationReport()
    out = transform_share_classes(rows, {}, report)
    assert out == []
    assert report.has_errors() is True


def test_transform_business_name_maps_fields():
    row = {
        "EntCode": "E1", "SeqNr": 1, "BusRegNr": "12345678",
        "BusName": "Acme Trading", "ChineseBusName": "測試",
        "DateRegistration": "2020-01-01", "DateRenew": "2021-01-01",
        "DateCessation": None, "Status": None,
    }
    out = transform_business_name(row, {"E1": "e-uuid"}, ReconciliationReport())
    assert out["vp_source_key"] == "E1:1"
    assert out["entity_id"] == "e-uuid"
    assert out["br_number"] == "12345678"
    assert out["business_name"] == "Acme Trading"
    assert out["business_name_zh"] == "測試"
    assert out["registration_date"] == "2020-01-01"
    assert out["renewal_date"] == "2021-01-01"
    assert out["cessation_date"] is None


def test_transform_business_name_unresolved_entity_returns_none_and_logs():
    report = ReconciliationReport()
    row = {"EntCode": "GHOST", "SeqNr": 1, "BusRegNr": None, "BusName": None,
           "ChineseBusName": None, "DateRegistration": None, "DateRenew": None,
           "DateCessation": None, "Status": None}
    out = transform_business_name(row, {}, report)
    assert out is None
    assert report.has_errors() is True


def test_transform_entity_name_change_maps_fields():
    row = {
        "EntCode": "E1", "SeqNr": 1, "OldName": "Old Co Ltd", "OldChnsName": "舊名",
        "NewName": "New Co Ltd", "NewChnsName": "新名",
        "DateApplied": "2021-01-01", "DateConfirmed": "2021-02-01",
    }
    out = transform_entity_name_change(row, {"E1": "e-uuid"}, ReconciliationReport())
    assert out["vp_source_key"] == "E1:1"
    assert out["entity_id"] == "e-uuid"
    assert out["old_name"] == "Old Co Ltd"
    assert out["old_name_zh"] == "舊名"
    assert out["new_name"] == "New Co Ltd"
    assert out["new_name_zh"] == "新名"
    assert out["applied_date"] == "2021-01-01"
    assert out["confirmed_date"] == "2021-02-01"


def test_transform_entity_name_change_unresolved_entity_returns_none_and_logs():
    report = ReconciliationReport()
    row = {"EntCode": "GHOST", "SeqNr": 1, "OldName": None, "OldChnsName": None,
           "NewName": None, "NewChnsName": None, "DateApplied": None, "DateConfirmed": None}
    out = transform_entity_name_change(row, {}, report)
    assert out is None
    assert report.has_errors() is True


def _st(**kw):
    base = {
        "EntCode": "E1", "IssueNr": 5, "ShareClass": "OR01", "AddrCode": "P1",
        "TransType": "IS", "TransDate": "2020-01-01", "NrShare": 100,
        "BalanceShare": 100, "IssuePrice": 1, "CertificateNr": 7,
    }
    base.update(kw)
    return base


def test_transform_share_transaction_individual_holder():
    out = transform_share_transaction(
        _st(), {"E1": "e-uuid"}, {"P1": "p-uuid"}, {"P1": "I"},
        {"E1:OR01": "sc-uuid"}, ReconciliationReport())
    assert out["vp_source_key"] == "E1:5"
    assert out["entity_id"] == "e-uuid"
    assert out["share_class_id"] == "sc-uuid"
    assert out["person_id"] == "p-uuid"
    assert out["transaction_type"] == "IS"
    assert out["shares"] == 100
    assert out["balance"] == 100
    assert out["issue_price"] == 1
    assert out["certificate_no"] == "7"


def test_transform_share_transaction_issue_row_has_no_person():
    out = transform_share_transaction(
        _st(AddrCode="ISSUE"), {"E1": "e-uuid"}, {}, {},
        {"E1:OR01": "sc-uuid"}, ReconciliationReport())
    assert out["person_id"] is None


def test_transform_share_transaction_corporate_holder_no_person_no_error():
    report = ReconciliationReport()
    out = transform_share_transaction(
        _st(AddrCode="C1"), {"E1": "e-uuid"}, {}, {"C1": "C"},
        {"E1:OR01": "sc-uuid"}, report)
    assert out["person_id"] is None
    assert report.has_errors() is False


def test_transform_share_transaction_orphan_class_null_share_class_id():
    out = transform_share_transaction(
        _st(ShareClass="ZZ99"), {"E1": "e-uuid"}, {"P1": "p-uuid"}, {"P1": "I"},
        {}, ReconciliationReport())
    assert out["share_class_id"] is None


def test_transform_share_transaction_unresolved_entity_returns_none_and_logs():
    report = ReconciliationReport()
    out = transform_share_transaction(
        _st(EntCode="GHOST"), {}, {}, {}, {}, report)
    assert out is None
    assert report.has_errors() is True


def _cert(**kw):
    base = {
        "SeqNr": 42, "EntCode": "E1", "AddrCode": "P1", "ShareClass": "OR01",
        "IssueDate": "2020-01-01", "CertificateNr": 7, "NrShare": 100,
        "CancelDate": None,
    }
    base.update(kw)
    return base


def test_transform_share_certificate_individual_holder():
    out = transform_share_certificate(
        _cert(), {"E1": "e-uuid"}, {"P1": "p-uuid"}, {"P1": "I"},
        {"E1:OR01": "sc-uuid"}, ReconciliationReport())
    assert out["vp_source_key"] == "42"
    assert out["entity_id"] == "e-uuid"
    assert out["share_class_id"] == "sc-uuid"
    assert out["person_id"] == "p-uuid"
    assert out["certificate_no"] == "7"
    assert out["shares"] == 100
    assert out["issue_date"] == "2020-01-01"
    assert out["cancelled_date"] is None
    assert out["document_id"] is None


def test_transform_share_certificate_corporate_holder_no_person_no_error():
    report = ReconciliationReport()
    out = transform_share_certificate(
        _cert(AddrCode="C1"), {"E1": "e-uuid"}, {}, {"C1": "C"},
        {"E1:OR01": "sc-uuid"}, report)
    assert out["person_id"] is None
    assert report.has_errors() is False


def test_transform_share_certificate_unresolved_entity_returns_none_and_logs():
    report = ReconciliationReport()
    out = transform_share_certificate(
        _cert(EntCode="GHOST"), {}, {}, {}, {}, report)
    assert out is None
    assert report.has_errors() is True


from etl.transform.checkpoint_b import derive_shareholdings


def _tx(entcode, addr, cls, bal, paid=1, posted=1):
    return {
        "EntCode": entcode, "AddrCode": addr, "ShareClass": cls,
        "BalanceShare": bal, "Paid": paid, "Posted": posted,
        "IssueNr": 1,  # ignored by the aggregation
    }


def test_derive_shareholdings_aggregates_and_flags_current():
    txs = [
        _tx("E1", "P1", "OR01", 60),
        _tx("E1", "P1", "OR01", 40),   # same member/class -> summed to 100
        _tx("E1", "P2", "OR01", 0),    # net zero -> is_current False
    ]
    out = derive_shareholdings(
        txs, {"E1": "e-uuid"}, {"P1": "p1", "P2": "p2"},
        {"P1": "I", "P2": "I"}, {"E1:OR01": "sc-uuid"}, ReconciliationReport())
    by_key = {r["vp_source_key"]: r for r in out}
    assert by_key["E1:P1:OR01"]["shares_held"] == 100
    assert by_key["E1:P1:OR01"]["is_current"] is True
    assert by_key["E1:P1:OR01"]["person_id"] == "p1"
    assert by_key["E1:P1:OR01"]["party_type"] == "individual"
    assert by_key["E1:P1:OR01"]["share_class_id"] == "sc-uuid"
    assert by_key["E1:P2:OR01"]["is_current"] is False


def test_derive_shareholdings_excludes_issue_and_unposted():
    txs = [
        _tx("E1", "ISSUE", "OR01", 100),   # ISSUE side excluded
        _tx("E1", "P1", "OR01", 50, posted=0),  # unposted excluded
    ]
    out = derive_shareholdings(
        txs, {"E1": "e-uuid"}, {"P1": "p1"}, {"P1": "I"},
        {"E1:OR01": "sc-uuid"}, ReconciliationReport())
    assert out == []


def test_derive_shareholdings_corporate_member():
    txs = [_tx("E1", "C1", "OR01", 100)]
    report = ReconciliationReport()
    out = derive_shareholdings(
        txs, {"E1": "e-uuid"}, {}, {"C1": "C"}, {"E1:OR01": "sc-uuid"}, report)
    assert out[0]["party_type"] == "corporate"
    assert out[0]["person_id"] is None
    assert out[0]["corporate_name"] == "C1"
    assert report.has_errors() is False


def test_derive_shareholdings_unresolved_share_class_dropped_and_logged():
    txs = [_tx("E1", "P1", "ZZ99", 100)]
    report = ReconciliationReport()
    out = derive_shareholdings(
        txs, {"E1": "e-uuid"}, {"P1": "p1"}, {"P1": "I"}, {}, report)
    assert out == []
    assert report.has_errors() is True


def test_derive_shareholdings_unresolved_entity_dropped_and_logged():
    txs = [_tx("GHOST", "P1", "OR01", 100)]
    report = ReconciliationReport()
    out = derive_shareholdings(txs, {}, {"P1": "p1"}, {"P1": "I"}, {"GHOST:OR01": "x"}, report)
    assert out == []
    assert report.has_errors() is True


def test_transform_share_classes_residual_collision_guard():
    # Pathological: a lone class literally named like another pair's suffixed form.
    rows = [
        _sc("E1", "OR01", "Ordinary"),
        _sc("E1", "OR02", "Ordinary"),            # pair -> "Ordinary (OR01/02)"
        _sc("E1", "OR05", "Ordinary (OR02)"),     # literal name collides with suffixed form
    ]
    report = ReconciliationReport()
    out = transform_share_classes(rows, {"E1": "e1"}, report)
    names = [r["class_name"] for r in out]
    assert len(names) == len(set(names))  # UNIQUE(entity_id, class_name) preserved
    assert report.has_errors() is True    # residual collision is logged, not silent


def test_derive_shareholdings_blank_addr_posted_row_logged():
    txs = [{
        "EntCode": "E1", "AddrCode": None, "ShareClass": "OR01",
        "BalanceShare": 100, "Paid": 1, "Posted": 1, "IssueNr": 9,
    }]
    report = ReconciliationReport()
    out = derive_shareholdings(txs, {"E1": "e1"}, {}, {}, {"E1:OR01": "sc"}, report)
    assert out == []
    assert report.has_errors() is True
    assert "blank AddrCode" in report.errors[0]["message"]
