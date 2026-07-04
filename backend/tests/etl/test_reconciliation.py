import json
from etl.reconciliation import ReconciliationReport


def test_record_entity_and_save(tmp_path):
    report = ReconciliationReport()
    report.record_entity("addresses", source_count=8023, loaded_count=8023)
    report.record_entity("persons", source_count=6850, loaded_count=6840)

    out_file = tmp_path / "report.json"
    report.save(str(out_file))

    saved = json.loads(out_file.read_text())
    assert saved["entities"]["addresses"] == {
        "source_count": 8023, "loaded_count": 8023, "discrepancy": 0,
    }
    assert saved["entities"]["persons"]["discrepancy"] == 10


def test_record_error_collects_into_report(tmp_path):
    report = ReconciliationReport()
    report.record_error("entities", vp_source_key="0000000123", message="ambiguous status code 'G'")

    out_file = tmp_path / "report.json"
    report.save(str(out_file))
    saved = json.loads(out_file.read_text())

    assert saved["errors"] == [
        {"entity": "entities", "vp_source_key": "0000000123", "message": "ambiguous status code 'G'"}
    ]


def test_has_errors():
    report = ReconciliationReport()
    assert report.has_errors() is False
    report.record_error("entities", "X", "boom")
    assert report.has_errors() is True
