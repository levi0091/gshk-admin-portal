from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_me_returns_user_profile():
    with patch("middleware.auth._resolve_user") as mock_resolve, patch(
        "routers.auth.get_supabase"
    ) as mock_sb:
        mock_resolve.return_value = {
            "id": "user-123",
            "display_name": "Levi Z.",
            "role_name": "super_admin",
            "role_id": "00000000-0000-0000-0000-000000000001",
        }
        sb = MagicMock()
        mock_sb.return_value = sb
        sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"module": "nar1_data", "permission": "read"},
        ]
        resp = client.get("/auth/me", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["display_name"] == "Levi Z."
        assert data["role_name"] == "super_admin"
        assert data["permissions"] == ["nar1_data:read"]


def test_me_without_token_returns_403():
    resp = client.get("/auth/me")
    assert resp.status_code == 403
