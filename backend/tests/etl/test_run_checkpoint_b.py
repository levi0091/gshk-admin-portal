from unittest.mock import patch
from etl.run_checkpoint_b import run


@patch("etl.run_checkpoint_b.load_shareholdings", return_value=0)
@patch("etl.run_checkpoint_b.derive_shareholdings", return_value=[])
@patch("etl.run_checkpoint_b.load_share_certificates", return_value=0)
@patch("etl.run_checkpoint_b.extract_share_certificates", return_value=[])
@patch("etl.run_checkpoint_b.load_share_transactions", return_value=0)
@patch("etl.run_checkpoint_b.extract_share_transactions", return_value=[])
@patch("etl.run_checkpoint_b.load_entity_name_changes", return_value=0)
@patch("etl.run_checkpoint_b.extract_entity_name_changes", return_value=[])
@patch("etl.run_checkpoint_b.load_business_names", return_value=0)
@patch("etl.run_checkpoint_b.extract_business_names", return_value=[])
@patch("etl.run_checkpoint_b.load_share_classes", return_value=0)
@patch("etl.run_checkpoint_b.transform_share_classes", return_value=[])
@patch("etl.run_checkpoint_b.extract_share_capital", return_value=[])
@patch("etl.run_checkpoint_b._refcode_types", return_value={})
@patch("etl.run_checkpoint_b._vp_key_to_id", return_value={})
@patch("etl.run_checkpoint_b.get_supabase_engine")
@patch("etl.run_checkpoint_b.get_viewpoint_engine")
def test_run_dry_run_short_circuits_before_detail_tables(
    mock_vp, mock_sb, mock_vpkey, mock_refcode,
    mock_extract_sc, mock_transform_sc, mock_load_sc,
    mock_extract_bn, mock_load_bn, mock_extract_nc, mock_load_nc,
    mock_extract_tx, mock_load_tx, mock_extract_cert, mock_load_cert,
    mock_derive_sh, mock_load_sh,
):
    report = run(dry_run=True)
    # share-detail tables (need share_class_id from this run's write) skipped in dry-run
    mock_extract_tx.assert_not_called()
    mock_derive_sh.assert_not_called()
    # independent tables were processed
    assert "share_classes" in report.entities
    assert "business_names" in report.entities
    assert "entity_name_changes" in report.entities


@patch("etl.run_checkpoint_b.load_shareholdings", return_value=3)
@patch("etl.run_checkpoint_b.derive_shareholdings", return_value=[{"x": 1}] * 3)
@patch("etl.run_checkpoint_b.load_share_certificates", return_value=0)
@patch("etl.run_checkpoint_b.extract_share_certificates", return_value=[])
@patch("etl.run_checkpoint_b.load_share_transactions", return_value=0)
@patch("etl.run_checkpoint_b.extract_share_transactions", return_value=[])
@patch("etl.run_checkpoint_b.load_entity_name_changes", return_value=0)
@patch("etl.run_checkpoint_b.extract_entity_name_changes", return_value=[])
@patch("etl.run_checkpoint_b.load_business_names", return_value=0)
@patch("etl.run_checkpoint_b.extract_business_names", return_value=[])
@patch("etl.run_checkpoint_b.load_share_classes", return_value=0)
@patch("etl.run_checkpoint_b.transform_share_classes", return_value=[])
@patch("etl.run_checkpoint_b.extract_share_capital", return_value=[])
@patch("etl.run_checkpoint_b._refcode_types", return_value={})
@patch("etl.run_checkpoint_b._vp_key_to_id", return_value={})
@patch("etl.run_checkpoint_b.get_supabase_engine")
@patch("etl.run_checkpoint_b.get_viewpoint_engine")
def test_run_real_reaches_shareholdings(
    mock_vp, mock_sb, mock_vpkey, mock_refcode,
    mock_extract_sc, mock_transform_sc, mock_load_sc,
    mock_extract_bn, mock_load_bn, mock_extract_nc, mock_load_nc,
    mock_extract_tx, mock_load_tx, mock_extract_cert, mock_load_cert,
    mock_derive_sh, mock_load_sh,
):
    report = run(dry_run=False)
    mock_derive_sh.assert_called_once()
    assert report.entities["shareholdings"]["source_count"] == 3
