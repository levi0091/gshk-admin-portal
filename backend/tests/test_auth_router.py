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
            {"module": "companies", "permission": "read"},
        ]
        resp = client.get("/auth/me", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["display_name"] == "Levi Z."
        assert data["role_name"] == "super_admin"
        assert data["permissions"] == ["companies:read"]


def test_me_works_for_a_user_with_no_module_permissions():
    """The identity bootstrap must not be gated on a business module — otherwise
    a role that only holds, say, persons access could never load the page that
    would have told it what it can do. Any authenticated, active user gets /me."""
    with patch("middleware.auth._resolve_user") as mock_resolve, patch(
        "routers.auth.get_supabase"
    ) as mock_sb:
        mock_resolve.return_value = {
            "id": "user-9",
            "display_name": "New Staff",
            "role_name": "onboarding",  # not super_admin
            "role_id": "role-onboarding",
        }
        sb = MagicMock()
        mock_sb.return_value = sb
        sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        resp = client.get("/auth/me", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200
        assert resp.json()["permissions"] == []


def test_me_without_token_returns_403():
    resp = client.get("/auth/me")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# The TEST environment badge (Levi 2026-08-30)
# ---------------------------------------------------------------------------
#
# The header pill is driven from here rather than from a Vite build-time
# variable, so it describes the API the browser is actually talking to. A
# frontend built for dev and pointed at the prod API would otherwise wear a
# TEST badge while filing real returns.
#
# Levi chose APP_ENV — the deployment — over the CR/TPSI environment. During
# the planned PROD-on-TPSI-test pilot this badge will read PRODUCTION while
# filings still go to CR test; that is the decision, not a bug.


def _me_with_env(app_env_value):
    """Drive /auth/me with APP_ENV set to `app_env_value` (None = unset)."""
    import os

    env = {k: v for k, v in os.environ.items() if k != "APP_ENV"}
    if app_env_value is not None:
        env["APP_ENV"] = app_env_value

    with patch.dict(os.environ, env, clear=True), patch(
        "middleware.auth._resolve_user"
    ) as mock_resolve, patch("routers.auth.get_supabase") as mock_sb:
        mock_resolve.return_value = {
            "id": "user-123",
            "display_name": "Levi Z.",
            "role_name": "super_admin",
            "role_id": "role-1",
        }
        sb = MagicMock()
        mock_sb.return_value = sb
        sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        return client.get("/auth/me", headers={"Authorization": "Bearer tok"}).json()


def test_me_reports_a_test_environment_on_dev():
    assert _me_with_env("dev")["is_test_env"] is True


def test_me_does_not_report_a_test_environment_on_prod():
    assert _me_with_env("prod")["is_test_env"] is False


def test_me_reports_a_test_environment_when_app_env_is_unset():
    """An unconfigured deployment wears the badge. Showing TEST on a machine
    that turns out to be production is a wasted glance; hiding it on a machine
    that turns out to be test is how someone files for real by accident."""
    assert _me_with_env(None)["is_test_env"] is True
