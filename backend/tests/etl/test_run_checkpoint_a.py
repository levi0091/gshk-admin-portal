from unittest.mock import patch
from etl.run_checkpoint_a import run


@patch("etl.run_checkpoint_a.load_beneficial_owners", return_value=0)
@patch("etl.run_checkpoint_a.extract_beneficial_owners", return_value=[])
@patch("etl.run_checkpoint_a.load_company_secretaries", return_value=0)
@patch("etl.run_checkpoint_a.load_entity_officers", return_value=0)
@patch("etl.run_checkpoint_a.extract_officers", return_value=[])
@patch("etl.run_checkpoint_a.load_identity_documents", return_value=0)
@patch("etl.run_checkpoint_a.extract_identity_documents", return_value=[])
@patch("etl.run_checkpoint_a.load_entities", return_value=0)
@patch("etl.run_checkpoint_a.extract_principal_business_names", return_value={})
@patch("etl.run_checkpoint_a.extract_entities", return_value=[])
@patch("etl.run_checkpoint_a.load_persons", return_value=0)
@patch("etl.run_checkpoint_a.extract_persons", return_value=[])
@patch("etl.run_checkpoint_a.load_addresses", return_value=0)
@patch("etl.run_checkpoint_a.extract_addresses", return_value=[])
@patch("etl.run_checkpoint_a._refcode_types", return_value={})
@patch("etl.run_checkpoint_a._vp_key_to_id", return_value={})
@patch("etl.run_checkpoint_a.get_supabase_engine")
@patch("etl.run_checkpoint_a.get_viewpoint_engine")
def test_run_dry_run_touches_no_fk_resolution(
    mock_vp_engine, mock_sb_engine, mock_vp_key_to_id, mock_refcode_types, *_mocks
):
    report = run(dry_run=True)
    mock_vp_key_to_id.assert_not_called()
    mock_refcode_types.assert_not_called()
    assert "addresses" in report.entities
    assert "entities" in report.entities
