from unittest.mock import patch
from etl.run_checkpoint_c import run


@patch("etl.run_checkpoint_c.backfill_primary_addresses")
@patch("etl.run_checkpoint_c._audit_ids")
@patch("etl.run_checkpoint_c.extract_events_form")
@patch("etl.run_checkpoint_c.load_audit_form_filings", return_value=0)
@patch("etl.run_checkpoint_c.load_audit_log", return_value=0)
@patch("etl.run_checkpoint_c.extract_ref_status", return_value=[])
@patch("etl.run_checkpoint_c.extract_event_log", return_value=[])
@patch("etl.run_checkpoint_c.load_form_filings", return_value=0)
@patch("etl.run_checkpoint_c.extract_form_filings", return_value=[])
@patch("etl.run_checkpoint_c.load_address_assignments", return_value=0)
@patch("etl.run_checkpoint_c.extract_address_assignments", return_value=[])
@patch("etl.run_checkpoint_c.load_tasks", return_value=0)
@patch("etl.run_checkpoint_c.extract_tasks", return_value=[])
@patch("etl.run_checkpoint_c.load_charges", return_value=0)
@patch("etl.run_checkpoint_c.extract_charges", return_value=[])
@patch("etl.run_checkpoint_c.load_contacts", return_value=0)
@patch("etl.run_checkpoint_c.extract_contacts", return_value=[])
@patch("etl.run_checkpoint_c.extract_vp_users", return_value={})
@patch("etl.run_checkpoint_c._refcode_types", return_value={})
@patch("etl.run_checkpoint_c._vp_key_to_id", return_value={})
@patch("etl.run_checkpoint_c.get_supabase_engine")
@patch("etl.run_checkpoint_c.get_viewpoint_engine")
def test_run_dry_run_skips_audit_form_filings_and_backfill(
    mock_vp, mock_sb, mock_vpkey, mock_refcode, mock_unames,
    mock_extract_contacts, mock_load_contacts,
    mock_extract_charges, mock_load_charges,
    mock_extract_tasks, mock_load_tasks,
    mock_extract_addr, mock_load_addr,
    mock_extract_forms, mock_load_forms,
    mock_extract_event_log, mock_extract_ref_status, mock_load_audit_log,
    mock_load_aff, mock_extract_events_form, mock_audit_ids, mock_backfill,
):
    report = run(dry_run=True)
    mock_extract_events_form.assert_not_called()
    mock_audit_ids.assert_not_called()
    mock_backfill.assert_not_called()
    assert "contacts" in report.entities
    assert "audit_log" in report.entities
    assert "audit_form_filings" not in report.entities


@patch("etl.run_checkpoint_c.backfill_primary_addresses", return_value={"entities_updated": 2, "persons_updated": 3})
@patch("etl.run_checkpoint_c._audit_ids", return_value={"EL:1": "audit-uuid"})
@patch("etl.run_checkpoint_c.extract_events_form", return_value=[{"EventNr": 1.0, "FQNumber": "FQ1"}])
@patch("etl.run_checkpoint_c.load_audit_form_filings", return_value=1)
@patch("etl.run_checkpoint_c.load_audit_log", return_value=0)
@patch("etl.run_checkpoint_c.extract_ref_status", return_value=[])
@patch("etl.run_checkpoint_c.extract_event_log", return_value=[])
@patch("etl.run_checkpoint_c.load_form_filings", return_value=0)
@patch("etl.run_checkpoint_c.extract_form_filings", return_value=[])
@patch("etl.run_checkpoint_c.load_address_assignments", return_value=0)
@patch("etl.run_checkpoint_c.extract_address_assignments", return_value=[])
@patch("etl.run_checkpoint_c.load_tasks", return_value=0)
@patch("etl.run_checkpoint_c.extract_tasks", return_value=[])
@patch("etl.run_checkpoint_c.load_charges", return_value=0)
@patch("etl.run_checkpoint_c.extract_charges", return_value=[])
@patch("etl.run_checkpoint_c.load_contacts", return_value=0)
@patch("etl.run_checkpoint_c.extract_contacts", return_value=[])
@patch("etl.run_checkpoint_c.extract_vp_users", return_value={})
@patch("etl.run_checkpoint_c._refcode_types", return_value={})
@patch("etl.run_checkpoint_c._vp_key_to_id", return_value={"FQ1": "filing-uuid"})
@patch("etl.run_checkpoint_c.get_supabase_engine")
@patch("etl.run_checkpoint_c.get_viewpoint_engine")
def test_run_real_reaches_audit_form_filings_and_backfill(
    mock_vp, mock_sb, mock_vpkey, mock_refcode, mock_unames,
    mock_extract_contacts, mock_load_contacts,
    mock_extract_charges, mock_load_charges,
    mock_extract_tasks, mock_load_tasks,
    mock_extract_addr, mock_load_addr,
    mock_extract_forms, mock_load_forms,
    mock_extract_event_log, mock_extract_ref_status, mock_load_audit_log,
    mock_load_aff, mock_extract_events_form, mock_audit_ids, mock_backfill,
):
    report = run(dry_run=False)
    mock_extract_events_form.assert_called_once()
    mock_audit_ids.assert_called_once()
    mock_backfill.assert_called_once()
    assert report.entities["audit_form_filings"]["loaded_count"] == 1
    assert report.entities["entities_registered_address_backfill"]["loaded_count"] == 2
    assert report.entities["persons_residential_address_backfill"]["loaded_count"] == 3
