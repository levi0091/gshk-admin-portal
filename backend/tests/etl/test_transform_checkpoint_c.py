from datetime import datetime, timezone

from etl.transform.checkpoint_c import (
    transform_contact, transform_charge, transform_task, transform_address_assignment,
    transform_form_filing, parse_event_string, transform_event_log_row,
    transform_ref_status_row, transform_audit_form_filing, audit_context,
)
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


def _addr_assignment(**kw):
    base = {
        "RefCode": "E1", "SeqNr": 1, "AddrType": "RO", "AddrNr": 100,
        "Effective": "2020-01-01", "Cancelled": None,
    }
    base.update(kw)
    return base


def test_transform_address_assignment_entity_route():
    out = transform_address_assignment(
        _addr_assignment(), {"E1": "e-uuid"}, {}, {"E1": "C"}, {"100": "addr-uuid"},
        ReconciliationReport())
    assert out["vp_source_key"] == "E1:1"
    assert out["address_id"] == "addr-uuid"
    assert out["party_type"] == "entity"
    assert out["entity_id"] == "e-uuid"
    assert out["person_id"] is None
    assert out["address_role"] == "RO"
    assert out["effective_date"] == "2020-01-01"
    assert out["cancelled_date"] is None
    assert out["is_current"] is True


def test_transform_address_assignment_person_route():
    out = transform_address_assignment(
        _addr_assignment(RefCode="P1", AddrType="RA", Cancelled="2021-01-01"),
        {}, {"P1": "p-uuid"}, {"P1": "I"}, {"100": "addr-uuid"},
        ReconciliationReport())
    assert out["party_type"] == "person"
    assert out["entity_id"] is None
    assert out["person_id"] == "p-uuid"
    assert out["address_role"] == "RA"
    assert out["cancelled_date"] == "2021-01-01"
    assert out["is_current"] is False


def test_transform_address_assignment_unresolved_address_dropped_and_logged():
    report = ReconciliationReport()
    out = transform_address_assignment(
        _addr_assignment(AddrNr=999), {"E1": "e-uuid"}, {}, {"E1": "C"}, {}, report)
    assert out is None
    assert report.has_errors() is True


def test_transform_address_assignment_unresolved_party_dropped_and_logged():
    report = ReconciliationReport()
    out = transform_address_assignment(
        _addr_assignment(RefCode="GHOST"), {}, {}, {}, {"100": "addr-uuid"}, report)
    assert out is None
    assert report.has_errors() is True


def _form_filing(**kw):
    base = {
        "FQnumber": "FQ025280", "EntCode": "E1", "FormCode": "HK23NAR1",
        "DateGenerate": "2026-01-01", "DateSigned": "2026-01-02",
        "DateFiled": "2026-01-03", "DateFileDeadLine": "2026-02-01",
        "FiledROC": 1, "FieldDetails": "some field text",
    }
    base.update(kw)
    return base


def test_transform_form_filing_workflow_nar1():
    out = transform_form_filing(_form_filing(), {"E1": "e-uuid"}, ReconciliationReport())
    assert out["workflow"] == "nar1"


def test_transform_form_filing_workflow_nnc1():
    out = transform_form_filing(
        _form_filing(FormCode="HK14eNNC1"), {"E1": "e-uuid"}, ReconciliationReport())
    assert out["workflow"] == "nnc1"


def test_transform_form_filing_workflow_other_is_none():
    out = transform_form_filing(
        _form_filing(FormCode="HK23IRBR200"), {"E1": "e-uuid"}, ReconciliationReport())
    assert out["workflow"] is None


def test_transform_form_filing_status_filed_wins():
    out = transform_form_filing(_form_filing(), {"E1": "e-uuid"}, ReconciliationReport())
    assert out["status"] == "filed"


def test_transform_form_filing_status_queued_fallback():
    out = transform_form_filing(
        _form_filing(DateGenerate=None, DateSigned=None, DateFiled=None),
        {"E1": "e-uuid"}, ReconciliationReport())
    assert out["status"] == "queued"


def test_transform_form_filing_field_details_wrapped():
    out = transform_form_filing(_form_filing(), {"E1": "e-uuid"}, ReconciliationReport())
    assert out["field_details"] == {"vp_field_details": "some field text"}


def test_transform_form_filing_field_details_none_when_blank():
    out = transform_form_filing(
        _form_filing(FieldDetails=None), {"E1": "e-uuid"}, ReconciliationReport())
    assert out["field_details"] is None


def test_transform_form_filing_unresolved_entity_dropped_and_logged():
    report = ReconciliationReport()
    out = transform_form_filing(_form_filing(EntCode="GHOST"), {}, report)
    assert out is None
    assert report.has_errors() is True


def test_transform_form_filing_full_happy_path():
    out = transform_form_filing(_form_filing(), {"E1": "e-uuid"}, ReconciliationReport())
    assert out["vp_source_key"] == "FQ025280"
    assert out["entity_id"] == "e-uuid"
    assert out["form_code"] == "HK23NAR1"
    assert out["generated_date"] == "2026-01-01"
    assert out["signed_date"] == "2026-01-02"
    assert out["filed_date"] == "2026-01-03"
    assert out["file_deadline"] == "2026-02-01"
    assert out["filed_with_cr"] is True
    assert out["document_id"] is None
    assert out["source"] == "viewpoint_import"


# ---------------------------------------------------------------------------
# parse_event_string
# ---------------------------------------------------------------------------

REAL_SAMPLE = (
    "{SFMG\x0cFQnumber=FQ025280\x0cFormName=NAR1 - Annual Return Private Company"
    "\x0cEntCode=OBSYDIANGR\x0cGeneratedOn=2026-06-18\x0cGeneratedBy=Jacqueline"
    "\x0c\x0c\x0cEventNr=181993\x0c}"
)


def test_parse_event_string_real_sample():
    out = parse_event_string(REAL_SAMPLE)
    assert out["FQnumber"] == "FQ025280"
    assert out["FormName"] == "NAR1 - Annual Return Private Company"
    assert out["EntCode"] == "OBSYDIANGR"
    assert out["GeneratedOn"] == "2026-06-18"
    assert out["GeneratedBy"] == "Jacqueline"
    assert out["EventNr"] == "181993"
    assert "SFMG" not in out


def test_parse_event_string_old_new_pairs():
    s = "{SFMG\x0cOldAdNrRA=6030\x0cNewAdNrRA=8029\x0cOldAdNrRC=100\x0cNewAdNrRC=200\x0c}"
    out = parse_event_string(s)
    assert out["OldAdNrRA"] == "6030"
    assert out["NewAdNrRA"] == "8029"
    assert out["OldAdNrRC"] == "100"
    assert out["NewAdNrRC"] == "200"


def test_parse_event_string_none_returns_empty():
    assert parse_event_string(None) == {}


def test_parse_event_string_empty_returns_empty():
    assert parse_event_string("") == {}


def test_parse_event_string_garbage_does_not_raise():
    assert parse_event_string("not even close to valid") == {}


def test_parse_event_string_token_without_equals_skipped():
    out = parse_event_string("{SFMG\x0cjustsometoken\x0cFoo=Bar\x0c}")
    assert "justsometoken" not in out
    assert out == {"Foo": "Bar"}


def test_parse_event_string_duplicate_key_last_wins():
    out = parse_event_string("{SFMG\x0cFoo=First\x0cFoo=Second\x0c}")
    assert out["Foo"] == "Second"


# ---------------------------------------------------------------------------
# transform_event_log_row
# ---------------------------------------------------------------------------

def _event_log_row(**kw):
    base = {
        "EventNr": 181993.0,
        "EventClass": 1,
        "KeyCode": "OBSYDIANGR",
        "DateEvent": "2026-06-18T00:00:00",
        "EventCode": "SFMG",
        "Ucode": "JAC",
        "Description": "Form generated",
        "EventString": REAL_SAMPLE,
        "RecordID": None,
    }
    base.update(kw)
    return base


def test_transform_event_log_row_happy_path():
    out = transform_event_log_row(
        _event_log_row(), {"OBSYDIANGR": "e-uuid"}, {"JAC": "Jacqueline Tan"})
    assert out["vp_source_key"] == "EL:181993"
    assert out["created_at"] == "2026-06-18T00:00:00"
    assert out["event_code"] == "SFMG"
    assert out["source_keycode"] == "OBSYDIANGR"
    assert out["case_id"] == "e-uuid"
    assert out["entity_type"] == "1"
    assert out["entity_id"] == "OBSYDIANGR"
    assert out["user_display_name"] == "Jacqueline Tan"
    assert out["created_by"] == "JAC"
    assert out["actioned_by"] == "JAC"
    assert out["action_type"] == "LEGACY_VP_EVENT"
    assert out["source"] == "viewpoint_import"
    assert out["form_type"] == "na"
    assert out["user_id"] is None
    assert out["metadata"]["FQnumber"] == "FQ025280"
    assert out["metadata"]["description"] == "Form generated"
    # A form generation changes nothing, so there is no diff to show — but
    # "Form Generated" with no form is exactly the useless entry we set out to
    # fix. It reports WHICH form instead.
    assert out["changed_fields"] == [
        {"field": "FormName", "label": "FormName", "old": None,
         "new": "NAR1 - Annual Return Private Company"},
        {"field": "FQnumber", "label": "FQnumber", "old": None, "new": "FQ025280"},
    ]
    assert out["before_state"] is None
    assert out["after_state"] == {
        "FormName": "NAR1 - Annual Return Private Company",
        "FQnumber": "FQ025280",
    }
    assert out["old_value"] is None
    assert "NAR1 - Annual Return Private Company" in out["new_value"]


def test_transform_event_log_row_old_new_lifted():
    row = _event_log_row(
        EventString="{SFMG\x0cOldAdNrRA=6030\x0cNewAdNrRA=8029\x0cOldAdNrRC=100\x0cNewAdNrRC=200\x0c}",
        Description=None,
    )
    out = transform_event_log_row(row, {}, {})
    assert out["before_state"] == {"AdNrRA": "6030", "AdNrRC": "100"}
    assert out["after_state"] == {"AdNrRA": "8029", "AdNrRC": "200"}
    assert out["old_value"] == "AdNrRA: 6030; AdNrRC: 100"
    assert out["new_value"] == "AdNrRA: 8029; AdNrRC: 200"


def test_transform_event_log_row_decodes_pipe_as_new_old():
    """Viewpoint's own convention: "Field=new|old". It is where most changes
    hide — reading only the explicit Old/New pairs missed them, which is why
    the imported trail looked empty."""
    row = _event_log_row(
        EventCode="CMA",
        EventString="{CMA\x0cEntCode=HKHWLI\x0cDateLastAnRe=2025-07-21|2024-07-21"
                    "\x0cConfidential=False|False\x0cDIxchkD=1|0\x0c}",
        Description=None,
    )
    out = transform_event_log_row(
        row, {}, {}, field_labels={"DateLastAnRe": "Last Annual Return"})

    # the real change, labelled
    assert out["changed_fields"] == [
        {"field": "DateLastAnRe", "label": "Last Annual Return",
         "old": "2024-07-21", "new": "2025-07-21"},
    ]
    # Confidential=False|False is context written in change form, not a change.
    # DIxchkD is a Viewpoint internal checklist flag — noise, never shown.
    assert out["old_value"] == "2024-07-21"
    assert out["new_value"] == "2025-07-21"


def test_transform_event_log_row_resolves_address_cards():
    """Viewpoint records an address change as a change of card NUMBER.
    "Business Address: 6030 -> 8029" tells a reader nothing."""
    row = _event_log_row(
        EventCode="ADC",
        EventString="{ADC\x0cOldAdNrBA=6030\x0cNewAdNrBA=8029\x0c}",
        Description=None,
    )
    out = transform_event_log_row(
        row, {}, {},
        field_labels={"AdNrBA": "Business Address"},
        address_labels={"6030": "Old Road, ZA", "8029": "Unit 301, Illovo Towers, ZA"},
    )
    assert out["changed_fields"] == [{
        "field": "AdNrBA", "label": "Business Address",
        "old": "Old Road, ZA", "new": "Unit 301, Illovo Towers, ZA",
    }]


def test_transform_event_log_row_eventnr_float_to_int():
    out = transform_event_log_row(_event_log_row(EventNr=42.0), {}, {})
    assert out["vp_source_key"] == "EL:42"


def test_transform_event_log_row_ucode_none_falls_back_to_viewpoint():
    out = transform_event_log_row(_event_log_row(Ucode=None), {}, {})
    assert out["user_display_name"] == "viewpoint"
    assert out["created_by"] is None
    assert out["actioned_by"] is None


def test_transform_event_log_row_ucode_unresolved_falls_back_to_ucode():
    out = transform_event_log_row(_event_log_row(Ucode="ZZZ"), {}, {})
    assert out["user_display_name"] == "ZZZ"


def test_transform_event_log_row_recordid_and_keycode_none_is_unknown():
    out = transform_event_log_row(_event_log_row(RecordID=None, KeyCode=None), {}, {})
    assert out["entity_id"] == "unknown"


def test_transform_event_log_row_recordid_preferred_over_keycode():
    out = transform_event_log_row(_event_log_row(RecordID="REC1"), {}, {})
    assert out["entity_id"] == "REC1"


def test_transform_event_log_row_eventclass_none_is_vp():
    out = transform_event_log_row(_event_log_row(EventClass=None), {}, {})
    assert out["entity_type"] == "vp"


def test_transform_event_log_row_date_event_none_uses_sentinel():
    out = transform_event_log_row(_event_log_row(DateEvent=None), {}, {})
    assert out["created_at"] == datetime(1970, 1, 1)
    assert out["metadata"]["vp_date_missing"] is True


def test_transform_event_log_row_no_description_no_metadata_key():
    out = transform_event_log_row(
        _event_log_row(EventString=None, Description=None), {}, {})
    assert out["metadata"] is None


# ---------------------------------------------------------------------------
# transform_ref_status_row
# ---------------------------------------------------------------------------

def _ref_status_row(**kw):
    base = {
        "RefCode": "OBSYDIANGR", "SeqNr": 3.0, "SType": "AR",
        "OldStat": "Pending", "NewStat": "Active",
        "DateChange": "2026-06-18T00:00:00", "Ucode": "JAC",
        "CDescr": "Status update",
    }
    base.update(kw)
    return base


def test_transform_ref_status_row_happy_path():
    out = transform_ref_status_row(
        _ref_status_row(), {"OBSYDIANGR": "e-uuid"}, {"JAC": "Jacqueline Tan"})
    assert out["vp_source_key"] == "RS:OBSYDIANGR:3"
    assert out["event_code"] == "STATUS"
    assert out["old_value"] == "Pending"
    assert out["new_value"] == "Active"
    assert out["created_at"] == "2026-06-18T00:00:00"
    assert out["case_id"] == "e-uuid"
    assert out["source_keycode"] == "OBSYDIANGR"
    assert out["entity_type"] == "status"
    assert out["entity_id"] == "OBSYDIANGR"
    assert out["metadata"] == {"stype": "AR", "descr": "Status update"}
    assert out["user_display_name"] == "Jacqueline Tan"
    assert out["created_by"] == "JAC"
    assert out["actioned_by"] == "JAC"
    assert out["action_type"] == "LEGACY_VP_EVENT"
    assert out["source"] == "viewpoint_import"
    assert out["form_type"] == "na"
    assert out["user_id"] is None
    assert out["before_state"] is None
    assert out["after_state"] is None


def test_transform_ref_status_row_seqnr_float_to_int():
    out = transform_ref_status_row(_ref_status_row(SeqNr=7.0), {}, {})
    assert out["vp_source_key"] == "RS:OBSYDIANGR:7"


def test_transform_ref_status_row_metadata_none_dropping():
    out = transform_ref_status_row(
        _ref_status_row(SType=None, CDescr=None), {}, {})
    assert out["metadata"] is None


def test_transform_ref_status_row_date_change_none_uses_sentinel():
    out = transform_ref_status_row(_ref_status_row(DateChange=None), {}, {})
    assert out["created_at"] == datetime(1970, 1, 1)


def _events_form(**kw):
    base = {"EventNr": 181993.0, "FQNumber": "FQ025280"}
    base.update(kw)
    return base


def test_transform_audit_form_filing_both_resolve():
    report = ReconciliationReport()
    out = transform_audit_form_filing(
        _events_form(),
        {"EL:181993": "audit-uuid"},
        {"FQ025280": "filing-uuid"},
        report,
    )
    assert out["vp_source_key"] == "181993:FQ025280"
    assert out["audit_log_id"] == "audit-uuid"
    assert out["form_filing_id"] == "filing-uuid"
    assert out["vp_event_nr"] == "181993"
    assert out["vp_fq_number"] == "FQ025280"
    assert report.has_errors() is False


def test_transform_audit_form_filing_one_side_missing_returned_and_logged():
    report = ReconciliationReport()
    out = transform_audit_form_filing(
        _events_form(), {}, {"FQ025280": "filing-uuid"}, report)
    assert out is not None
    assert out["audit_log_id"] is None
    assert out["form_filing_id"] == "filing-uuid"
    assert report.has_errors() is True

    report2 = ReconciliationReport()
    out2 = transform_audit_form_filing(
        _events_form(), {"EL:181993": "audit-uuid"}, {}, report2)
    assert out2 is not None
    assert out2["audit_log_id"] == "audit-uuid"
    assert out2["form_filing_id"] is None
    assert report2.has_errors() is True


def test_transform_audit_form_filing_both_missing_dropped_and_logged():
    report = ReconciliationReport()
    out = transform_audit_form_filing(_events_form(), {}, {}, report)
    assert out is None
    assert report.has_errors() is True


def test_transform_audit_form_filing_float_event_nr_normalized():
    report = ReconciliationReport()
    out = transform_audit_form_filing(
        _events_form(EventNr=181993.0),
        {"EL:181993": "audit-uuid"},
        {"FQ025280": "filing-uuid"},
        report,
    )
    assert out["vp_source_key"] == "181993:FQ025280"
    assert out["vp_event_nr"] == "181993"
    assert "181993.0" not in out["vp_source_key"]


# ---- audit context (migration 012) ----------------------------------------

def test_collapse_uniform_kv_collapses_identical_values():
    """Viewpoint packs a whole field map into one string. When every field got
    the same value it is ONE change, not fifteen."""
    from etl.transform.checkpoint_c import collapse_uniform_kv
    blob = "AdNrS1=2311; AdNrS2=2311; AdNrS3=2311; AdNrSU=2311"
    assert collapse_uniform_kv(blob) == "2311"


def test_collapse_uniform_kv_leaves_real_multi_value_strings_alone():
    from etl.transform.checkpoint_c import collapse_uniform_kv
    blob = "CapAmt=Nil; CapCur=HKD"
    assert collapse_uniform_kv(blob) == blob
    assert collapse_uniform_kv(None) is None
    assert collapse_uniform_kv("plain") == "plain"


def test_event_log_row_carries_generic_action_and_subject_name():
    """A re-run of the ETL must produce the same shape the app now expects:
    the GENERIC action name, never the per-record description."""
    from etl.transform.checkpoint_c import transform_event_log_row
    row = {
        "EventNr": 1, "EventCode": "ADC", "KeyCode": "ACME",
        "RecordID": "r1", "Ucode": "JAC", "EventClass": "C",
        "DateEvent": None, "EventString": None,
        "Description": "Master File Details of Miss Ilze TSERKEZIS Changed",
    }
    out = transform_event_log_row(
        row, {"ACME": "e1"}, {},
        label_by_code={"ADC": "Change Master File Details"},
        subject_by_vp_key={"ACME": "Acme Limited"},
    )
    assert out["action_label"] == "Change Master File Details"
    assert out["company_name"] == "Acme Limited"
    assert out["event_code"] == "ADC"
    # the per-record description is retained in metadata, not used as the action
    assert out["metadata"]["description"].startswith("Master File Details of")


# ---------------------------------------------------------------------------
# audit_context -- WHICH RECORD an imported row is about (migration 034)
#
# A Viewpoint KeyCode resolves to an entity OR a person. Resolving it against
# `entities` alone is what left every person-scoped event printing a raw
# RefCode nobody can read.
# ---------------------------------------------------------------------------

_COMPANY = {"kind": "company", "id": "e-uuid",
            "name": "Obsydian Group Limited", "ref": "69123456"}
_PERSON = {"kind": "person", "id": "p-uuid",
           "name": "Ilze TSERKEZIS", "ref": "A123456(7)"}


def test_audit_context_names_a_company_and_its_brn():
    out = audit_context("ADC", "OBSYDIANGR", {"ADC": "Change Master File Details"},
                        {"OBSYDIANGR": _COMPANY})
    assert out["action_label"] == "Change Master File Details"
    assert out["company_name"] == "Obsydian Group Limited"
    assert out["subject_kind"] == "company"
    assert out["subject_id"] == "e-uuid"
    assert out["subject_ref"] == "69123456"
    assert out["module"] == "body_corporate"


def test_audit_context_names_a_person_and_their_identity_document():
    out = audit_context("CPC", "TSERKEZIS", {}, {"TSERKEZIS": _PERSON})
    assert out["company_name"] == "Ilze TSERKEZIS"
    assert out["subject_kind"] == "person"
    assert out["subject_id"] == "p-uuid"
    assert out["subject_ref"] == "A123456(7)"
    assert out["module"] == "natural_person"


def test_audit_context_invents_no_module_for_an_unresolved_key():
    """Viewpoint recorded no NAR1 workflow, no document store and no CR filing.
    A NULL module renders as a dash, which is the truth."""
    out = audit_context("ADC", "NOBODY", {}, {})
    assert out["subject_kind"] is None
    assert out["subject_id"] is None
    assert out["module"] is None
    assert out["company_name"] is None


def test_audit_context_still_accepts_a_plain_name_map():
    """A caller holding only RefCode -> name produces a valid, barer row rather
    than a crash."""
    out = audit_context("ADC", "OBSYDIANGR", {}, {"OBSYDIANGR": "Obsydian Group"})
    assert out["company_name"] == "Obsydian Group"
    assert out["subject_kind"] is None


def test_event_log_row_carries_the_subject_through():
    out = transform_event_log_row(
        _event_log_row(), {"OBSYDIANGR": "e-uuid"}, {"JAC": "Jacqueline Tan"},
        None, {"OBSYDIANGR": _COMPANY})
    assert out["subject_kind"] == "company"
    assert out["subject_ref"] == "69123456"
    assert out["module"] == "body_corporate"


def test_ref_status_row_carries_the_subject_through():
    out = transform_ref_status_row(
        {"RefCode": "TSERKEZIS", "SeqNr": 3, "Ucode": "JAC",
         "DateChange": "2026-06-18T00:00:00", "OldStat": 0, "NewStat": 8,
         "SType": "C", "CDescr": "Active"},
        {}, {"JAC": "Jacqueline Tan"}, None, {"TSERKEZIS": _PERSON})
    assert out["subject_kind"] == "person"
    assert out["module"] == "natural_person"
    assert out["company_name"] == "Ilze TSERKEZIS"
