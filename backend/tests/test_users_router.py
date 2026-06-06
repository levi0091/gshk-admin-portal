from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

SUPER_ADMIN_USER = {
    "id": "admin-1",
    "display_name": "Levi Z.",
    "role_name": "super_admin",
    "role_id": "00000000-0000-0000-0000-000000000001",
}


def auth_headers():
    return {"Authorization": "Bearer tok"}


def test_list_users_returns_list():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN_USER), \
         patch("routers.users.get_supabase") as mock_sb:
        mock_sb.return_value.table.return_value.select.return_value.order.return_value.execute.return_value.data = [
            {"id": "u1", "display_name": "Alice", "email": "a@e.com",
             "is_active": True, "roles": {"name": "nar1_staff"}}
        ]
        resp = client.get("/users/", headers=auth_headers())
        assert resp.status_code == 200
        assert len(resp.json()) == 1


def test_create_user_returns_201():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN_USER), \
         patch("routers.users.get_supabase") as mock_sb:
        sb = MagicMock()
        mock_sb.return_value = sb
        created_auth_user = MagicMock()
        created_auth_user.id = "new-user-id"
        sb.auth.admin.create_user.return_value = MagicMock(user=created_auth_user)
        sb.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "new-user-id", "display_name": "Bob", "email": "bob@e.com",
             "role_id": "role-1", "is_active": True}
        ]
        payload = {"display_name": "Bob", "email": "bob@e.com",
                   "role_id": "role-1", "password": "TempPass123!"}
        resp = client.post("/users/", json=payload, headers=auth_headers())
        assert resp.status_code == 201


def test_deactivate_user_returns_200():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN_USER), \
         patch("routers.users.get_supabase") as mock_sb:
        sb = MagicMock()
        mock_sb.return_value = sb
        sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": "u1", "is_active": False}
        ]
        resp = client.patch("/users/u1/deactivate", headers=auth_headers())
        assert resp.status_code == 200
