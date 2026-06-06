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


def test_list_roles_returns_list():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN_USER), \
         patch("routers.roles.get_supabase") as mock_sb:
        mock_sb.return_value.table.return_value.select.return_value.order.return_value.execute.return_value.data = [
            {"id": "r1", "name": "super_admin", "role_permissions": []},
            {"id": "r2", "name": "nar1_staff", "role_permissions": [
                {"module": "nar1_data", "permission": "read"}
            ]},
        ]
        resp = client.get("/roles/", headers=auth_headers())
        assert resp.status_code == 200
        assert len(resp.json()) == 2


def test_create_role_returns_201():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN_USER), \
         patch("routers.roles.get_supabase") as mock_sb:
        sb = MagicMock()
        mock_sb.return_value = sb
        sb.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "new-role", "name": "reviewer"}
        ]
        sb.table.return_value.delete.return_value.eq.return_value.execute.return_value.data = []
        resp = client.post(
            "/roles/",
            json={"name": "reviewer", "permissions": []},
            headers=auth_headers(),
        )
        assert resp.status_code == 201


def test_update_role_permissions():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN_USER), \
         patch("routers.roles.get_supabase") as mock_sb:
        sb = MagicMock()
        mock_sb.return_value = sb
        sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": "r2", "name": "nar1_staff"}
        ]
        sb.table.return_value.delete.return_value.eq.return_value.execute.return_value.data = []
        sb.table.return_value.insert.return_value.execute.return_value.data = []
        resp = client.patch(
            "/roles/r2",
            json={"permissions": [{"module": "nar1_data", "permission": "read"}]},
            headers=auth_headers(),
        )
        assert resp.status_code == 200
