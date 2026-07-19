import pytest
from unittest.mock import patch, MagicMock
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from middleware.auth import require_permission


def make_app(module: str, permission: str):
    app = FastAPI()

    @app.get("/test")
    def test_route(user=Depends(require_permission(module, permission))):
        return {"user_id": user["id"]}

    return TestClient(app)


def test_missing_token_returns_403():
    client = make_app("companies", "read")
    resp = client.get("/test")
    assert resp.status_code == 403  # HTTPBearer returns 403 when no creds


def test_invalid_token_returns_401():
    with patch("middleware.auth.get_supabase") as mock_sb:
        mock_sb.return_value.auth.get_user.side_effect = Exception("invalid")
        client = make_app("companies", "read")
        resp = client.get("/test", headers={"Authorization": "Bearer bad_token"})
        assert resp.status_code == 401


def test_super_admin_bypasses_permission_check():
    with patch("middleware.auth.get_supabase") as mock_sb:
        sb = MagicMock()
        mock_sb.return_value = sb

        # Auth returns a valid user
        user_obj = MagicMock()
        user_obj.id = "user-123"
        sb.auth.get_user.return_value = MagicMock(user=user_obj)

        # users table returns super_admin role
        sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "display_name": "Levi Z.",
            "is_active": True,
            "roles": {"name": "super_admin"},
        }

        client = make_app("companies", "write")
        resp = client.get("/test", headers={"Authorization": "Bearer valid_token"})
        assert resp.status_code == 200


def test_user_without_permission_returns_403():
    with patch("middleware.auth.get_supabase") as mock_sb:
        sb = MagicMock()
        mock_sb.return_value = sb

        user_obj = MagicMock()
        user_obj.id = "user-456"
        sb.auth.get_user.return_value = MagicMock(user=user_obj)

        # Use side_effect to return different mocks per table name
        users_mock = MagicMock()
        users_mock.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "display_name": "Staff User",
            "is_active": True,
            "roles": {"name": "nar1_staff"},
            "role_id": "role-789",
        }
        perms_mock = MagicMock()
        perms_mock.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

        sb.table.side_effect = lambda table_name: users_mock if table_name == "users" else perms_mock

        client = make_app("companies", "write")
        resp = client.get("/test", headers={"Authorization": "Bearer valid_token"})
        assert resp.status_code == 403
