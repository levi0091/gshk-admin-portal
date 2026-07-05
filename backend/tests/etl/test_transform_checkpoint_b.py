from etl.transform.checkpoint_b import transform_share_classes
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
