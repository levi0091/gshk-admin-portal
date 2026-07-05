from etl.transform.checkpoint_c import transform_contact, transform_charge, transform_task
from etl.reconciliation import ReconciliationReport


def _contact(**kw):
    base = {
        "RefCode": "E1", "SeqNr": 1, "cType": "Email",
        "cText": "info@acme.com", "Preferred": 1,
    }
    base.update(kw)
    return base


def test_transform_contact_entity_route():
    out = transform_contact(
        _contact(), {"E1": "e-uuid"}, {}, {"E1": "C"}, ReconciliationReport())
    assert out["vp_source_key"] == "E1:1"
    assert out["entity_id"] == "e-uuid"
    assert out["person_id"] is None
    assert out["contact_type"] == "Email"
    assert out["contact_value"] == "info@acme.com"
    assert out["is_preferred"] is True


def test_transform_contact_person_route():
    out = transform_contact(
        _contact(RefCode="P1", Preferred=0), {}, {"P1": "p-uuid"}, {"P1": "I"}, ReconciliationReport())
    assert out["vp_source_key"] == "P1:1"
    assert out["entity_id"] is None
    assert out["person_id"] == "p-uuid"
    assert out["is_preferred"] is False


def test_transform_contact_unresolved_dropped_and_logged():
    report = ReconciliationReport()
    out = transform_contact(
        _contact(RefCode="GHOST"), {}, {}, {}, report)
    assert out is None
    assert report.has_errors() is True


def _charge(**kw):
    base = {
        "EntCode": "E1", "ChargeNr": 1, "ChargeRef": "CH-001",
        "ChargeType": "Mortgage", "MortgageeAddrCode": "M1",
        "MortgageeDescr": "Big Bank Ltd", "DateRegistration": "2020-01-01",
        "DateDischarge": None, "PropertyDescr": "123 Main St", "Currency": "HKD",
    }
    base.update(kw)
    return base


def test_transform_charge_maps_fields():
    out = transform_charge(_charge(), {"E1": "e-uuid"}, ReconciliationReport())
    assert out["vp_source_key"] == "E1:1"
    assert out["entity_id"] == "e-uuid"
    assert out["charge_ref"] == "CH-001"
    assert out["charge_type"] == "Mortgage"
    assert out["mortgagee"] == "Big Bank Ltd"
    assert out["registration_date"] == "2020-01-01"
    assert out["discharge_date"] is None
    assert out["property_description"] == "123 Main St"
    assert out["currency"] == "HKD"


def test_transform_charge_mortgagee_falls_back_to_addr_code():
    out = transform_charge(
        _charge(MortgageeDescr=None), {"E1": "e-uuid"}, ReconciliationReport())
    assert out["mortgagee"] == "M1"


def test_transform_charge_unresolved_entity_dropped_and_logged():
    report = ReconciliationReport()
    out = transform_charge(_charge(EntCode="GHOST"), {}, report)
    assert out is None
    assert report.has_errors() is True


def _task(**kw):
    base = {
        "RefCode": "E1", "SeqNr": 1, "ToDoCode": "T1",
        "DueDate": "2026-01-01", "Remark": "call client", "IsDone": 0,
        "Description": "Follow up",
    }
    base.update(kw)
    return base


def test_transform_task_entity_route_with_remark_appended():
    out = transform_task(
        _task(), {"E1": "e-uuid"}, {}, {"E1": "C"}, ReconciliationReport())
    assert out["vp_source_key"] == "E1:1"
    assert out["entity_id"] == "e-uuid"
    assert out["person_id"] is None
    assert out["task_code"] == "T1"
    assert out["description"] == "Follow up — call client"
    assert out["due_date"] == "2026-01-01"
    assert out["is_done"] is False
    assert out["completed_date"] is None
    assert out["assigned_to"] is None


def test_transform_task_person_route_no_remark():
    out = transform_task(
        _task(RefCode="P1", Remark=None, IsDone=1), {}, {"P1": "p-uuid"}, {"P1": "I"}, ReconciliationReport())
    assert out["entity_id"] is None
    assert out["person_id"] == "p-uuid"
    assert out["description"] == "Follow up"
    assert out["is_done"] is True


def test_transform_task_both_description_and_remark_blank_is_none():
    out = transform_task(
        _task(Description=None, Remark=None), {"E1": "e-uuid"}, {}, {"E1": "C"}, ReconciliationReport())
    assert out["description"] is None


def test_transform_task_unresolved_dropped_and_logged():
    report = ReconciliationReport()
    out = transform_task(_task(RefCode="GHOST"), {}, {}, {}, report)
    assert out is None
    assert report.has_errors() is True
