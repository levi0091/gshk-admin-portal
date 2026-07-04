from unittest.mock import patch, MagicMock

from services.documents_service import (
    Document,
    DocumentCreate,
    DocumentVersionCreate,
    add_version,
    insert_document,
    list_document_types,
    set_document_status,
)


def _sb():
    sb = MagicMock()
    return sb


def test_list_document_types_active_only_orders_by_sort():
    with patch("services.documents_service.get_supabase") as msb:
        sb = _sb()
        msb.return_value = sb
        chain = sb.table.return_value.select.return_value.eq.return_value.order.return_value
        chain.execute.return_value.data = [{"code": "nar1"}, {"code": "nnc1"}]

        rows = list_document_types()

        sb.table.assert_called_with("document_types")
        sb.table.return_value.select.return_value.eq.assert_called_with("is_active", True)
        assert [r["code"] for r in rows] == ["nar1", "nnc1"]


def test_insert_document_strips_none_and_returns_row():
    with patch("services.documents_service.get_supabase") as msb:
        sb = _sb()
        msb.return_value = sb
        sb.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "doc-1", "storage_path": "entities/e1/nar1/x.pdf"}
        ]

        row = insert_document(
            DocumentCreate(
                document_type_code="nar1",
                storage_path="entities/e1/nar1/x.pdf",
                entity_id="e1",
                title=None,  # must be stripped so DB defaults apply
            )
        )

        payload = sb.table.return_value.insert.call_args[0][0]
        assert "title" not in payload
        assert payload["storage_path"] == "entities/e1/nar1/x.pdf"
        assert payload["document_type_code"] == "nar1"
        assert row["id"] == "doc-1"


def test_insert_document_raises_when_no_row():
    with patch("services.documents_service.get_supabase") as msb:
        sb = _sb()
        msb.return_value = sb
        sb.table.return_value.insert.return_value.execute.return_value.data = []
        try:
            insert_document({"storage_path": "p"})
            assert False, "expected RuntimeError"
        except RuntimeError:
            pass


def test_add_version_inserts_and_bumps_current_version():
    with patch("services.documents_service.get_supabase") as msb:
        sb = _sb()
        msb.return_value = sb
        sb.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "ver-2", "version_number": 2}
        ]

        add_version(
            DocumentVersionCreate(
                document_id="doc-1", version_number=2, storage_path="entities/e1/nar1/v2.pdf"
            )
        )

        # version inserted
        ins = sb.table.return_value.insert.call_args[0][0]
        assert ins["version_number"] == 2
        # documents.current_version advanced to the new version
        upd = sb.table.return_value.update.call_args[0][0]
        assert upd == {"current_version": 2}
        sb.table.return_value.update.return_value.eq.assert_called_with("id", "doc-1")


def test_set_document_status_rejects_invalid():
    try:
        set_document_status("doc-1", "bogus")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_document_model_round_trip():
    row = {
        "id": "doc-1",
        "document_type_code": "id_scan",
        "storage_path": "unassigned/id_scan/abc",
        "storage_bucket": "gflowdesk-documents",
        "entity_id": None,
        "current_version": 1,
        "status": "active",
        "is_generated": False,
        "checksum_sha256": "deadbeef",
    }
    doc = Document(**row)
    assert doc.id == "doc-1"
    assert doc.document_type_code == "id_scan"
    assert doc.status == "active"
    assert doc.model_dump(exclude_none=True)["checksum_sha256"] == "deadbeef"
