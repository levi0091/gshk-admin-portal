from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

REGULAR_USER = {
    "id": "user-1",
    "display_name": "Staff",
    "role_name": "nar1_staff",
    "role_id": "role-1",
}


def auth_headers():
    return {"Authorization": "Bearer tok"}


def test_get_audit_trail_returns_entries():
    with patch("middleware.auth._resolve_user", return_value=REGULAR_USER), \
         patch("middleware.auth.get_supabase") as mock_perm_sb, \
         patch("routers.cases_audit.get_supabase") as mock_sb:

        # Permission check passes (nar1_staff has read on nar1_data)
        # Chain: .table().select().eq(role_id).eq(module).execute()
        mock_perm_sb.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"permission": "read"}
        ]

        mock_sb.return_value.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = [
            {
                "id": "log-1",
                "created_at": "2026-06-06T10:00:00Z",
                "user_display_name": "Levi Z.",
                "action_type": "CASE_FIELD_UPDATED",
                "entity_type": "case",
                "entity_id": "case-abc",
                "before_state": {"field": "client_full_name", "old": "John"},
                "after_state": {"field": "client_full_name", "new": "John Smith"},
                "metadata": None,
            }
        ]

        # PRD-specified path: GET /cases/{case_id}/audit
        resp = client.get("/cases/case-abc/audit", headers=auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["action_type"] == "CASE_FIELD_UPDATED"
