import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.asyncio
async def test_log_event_inserts_row():
    with patch("services.audit_service.get_supabase") as mock_sb:
        sb = MagicMock()
        mock_sb.return_value = sb
        sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": "log-1"}]

        from services.audit_service import log_event
        await log_event(
            case_id="case-abc",
            user_id="user-123",
            user_display_name="Levi Z.",
            action_type="CASE_FIELD_UPDATED",
            entity_type="case",
            entity_id="case-abc",
            before_state={"field": "client_full_name", "old": "John"},
            after_state={"field": "client_full_name", "new": "John Smith"},
        )

        sb.table.assert_called_with("audit_log")
        insert_call = sb.table.return_value.insert.call_args[0][0]
        assert insert_call["action_type"] == "CASE_FIELD_UPDATED"
        assert insert_call["user_display_name"] == "Levi Z."


@pytest.mark.asyncio
async def test_log_event_scrubs_credentials_from_metadata():
    with patch("services.audit_service.get_supabase") as mock_sb:
        sb = MagicMock()
        mock_sb.return_value = sb
        sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": "log-2"}]

        from services.audit_service import log_event
        await log_event(
            case_id="case-abc",
            user_id="user-123",
            user_display_name="Levi Z.",
            action_type="TPSI_SUBMISSION_ATTEMPTED",
            entity_type="tpsi",
            entity_id="case-abc",
            metadata={
                "Authorization": "Bearer secret-token",
                "password": "secret",
                "pin": "1234",
                "endpoint": "submitFormNar1",
                "response_status": 200,
            },
        )

        insert_call = sb.table.return_value.insert.call_args[0][0]
        logged_meta = insert_call["metadata"]
        assert "Authorization" not in logged_meta
        assert "password" not in logged_meta
        assert "pin" not in logged_meta
        assert logged_meta["endpoint"] == "submitFormNar1"
        assert logged_meta["response_status"] == 200


@pytest.mark.asyncio
async def test_log_event_failure_does_not_raise():
    with patch("services.audit_service.get_supabase") as mock_sb:
        mock_sb.return_value.table.return_value.insert.return_value.execute.side_effect = Exception("DB down")

        from services.audit_service import log_event
        # Must NOT raise — wraps in try/except
        await log_event(
            case_id="case-abc",
            user_id="user-123",
            user_display_name="Levi Z.",
            action_type="CASE_STATUS_CHANGED",
            entity_type="case",
            entity_id="case-abc",
        )
