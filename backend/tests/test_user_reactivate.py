"""`PATCH /users/{id}/reactivate` — deactivation gets an undo.

Deactivation had none. The dialog claimed it "can be reversed by reassigning a
role"; `PATCH /users/{id}` writes `role_id` and `display_name` and has never
written `is_active`, and nothing lifted the Supabase Auth ban. So a deactivated
colleague was permanently locked out and the only way back was editing the
database by hand.

The properties worth holding, all of them about the SECOND half of the job:

  1. THE AUTH BAN IS LIFTED. `users.is_active` is what this portal refuses on,
     but GoTrue refuses the sign-in itself, and flipping the column does not
     touch it. A reactivation that only wrote the column would show an Active
     account that still cannot sign in.
  2. AUTH GOES FIRST, AND ITS FAILURE CHANGES NOTHING. The row keeps saying
     Inactive, which is true, and the button stays there to press again.
  3. THE IDENTITY CACHE IS CLEARED. A refusal is cached for 30 seconds along
     with the identity, so without this the user is still told their account is
     inactive well after it was restored.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from middleware.auth import clear_auth_cache

SUPER = {"id": "u1", "display_name": "Levi", "role_name": "super_admin",
         "role_id": "role-sa", "must_change_password": False}
STAFF = {"id": "u9", "display_name": "Roy", "role_name": "case_manager",
         "role_id": "role-cm", "must_change_password": False}
H = {"Authorization": "Bearer tok"}

TARGET = {"id": "u9", "display_name": "Harry Lo", "email": "harry@getstarted.hk",
          "is_active": False}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_auth_cache()
    yield
    clear_auth_cache()


def _sb(target=TARGET, update_rows=None):
    """`target=None` means the row is genuinely absent."""
    sb = MagicMock()
    table = MagicMock()
    (table.select.return_value.eq.return_value.limit.return_value
     .execute.return_value.data) = [target] if target else []
    (table.update.return_value.eq.return_value.execute.return_value
     .data) = update_rows if update_rows is not None else [{"id": "u9"}]
    sb.table.return_value = table
    return sb


def _reactivate(client, sb=None, user=None, user_id="u9"):
    sb = sb if sb is not None else _sb()
    with patch("middleware.auth._resolve_user", return_value=user or SUPER), \
         patch("routers.users.get_supabase", return_value=sb):
        response = client.patch(f"/users/{user_id}/reactivate", headers=H)
    return response, sb


def _flag_written(sb):
    """Every `is_active` value handed to the users table by this request."""
    return [call.args[0] for call in sb.table.return_value.update.call_args_list]


def test_reactivating_returns_200(client):
    response, _ = _reactivate(client)
    assert response.status_code == 200
    assert response.json()["is_active"] is True


def test_the_account_is_marked_active_again(client):
    _, sb = _reactivate(client)
    assert {"is_active": True} in _flag_written(sb)


def test_the_auth_ban_is_lifted(client):
    """THE HALF THAT ACTUALLY LETS THEM BACK IN. `deactivate` bans the account
    in GoTrue for a hundred years; the column this portal reads is a separate
    fact, and clearing only that would leave the sign-in still refused."""
    _, sb = _reactivate(client)
    sb.auth.admin.update_user_by_id.assert_called_once_with(
        "u9", {"ban_duration": "none"})


def test_the_ban_is_lifted_BEFORE_the_row_is_marked_active(client):
    """Order, not decoration. Writing the column first would put the account on
    screen as Active while GoTrue still refused it — the administrator sees a
    working account, the user sees "Invalid login credentials", and nothing on
    either screen connects the two."""
    order = []
    sb = _sb()
    sb.auth.admin.update_user_by_id.side_effect = lambda *a, **k: order.append("auth")
    sb.table.return_value.update.side_effect = lambda *a, **k: (
        order.append("flag") or MagicMock())

    with patch("middleware.auth._resolve_user", return_value=SUPER), \
         patch("routers.users.get_supabase", return_value=sb):
        client.patch("/users/u9/reactivate", headers=H)

    assert order[:2] == ["auth", "flag"]


def test_an_auth_failure_leaves_the_account_deactivated(client):
    """The safe direction. Nothing has been written yet, so the row still says
    Inactive — which is TRUE, the person still cannot sign in — and the button
    is still there to press again."""
    sb = _sb()
    sb.auth.admin.update_user_by_id.side_effect = RuntimeError("gotrue is down")
    response, sb = _reactivate(client, sb=sb)

    assert response.status_code == 502
    assert "still deactivated" in response.json()["detail"]
    assert {"is_active": True} not in _flag_written(sb)


def test_an_auth_failure_says_what_it_could_not_do(client):
    sb = _sb()
    sb.auth.admin.update_user_by_id.side_effect = RuntimeError("gotrue is down")
    response, _ = _reactivate(client, sb=sb)
    assert "gotrue is down" in response.json()["detail"]


def test_the_identity_cache_is_cleared(client):
    """A REFUSAL is cached alongside the identity for 30 seconds. Without this
    the user is still told their account is inactive after it was restored."""
    with patch("routers.users.clear_auth_cache") as cleared:
        _reactivate(client)
    cleared.assert_called_once()


def test_reactivating_an_already_active_account_is_a_no_op(client):
    """Two administrators pressing the same button is not a fault worth a 409."""
    response, sb = _reactivate(client, sb=_sb({**TARGET, "is_active": True}))
    assert response.status_code == 200
    assert response.json()["already_active"] is True
    sb.auth.admin.update_user_by_id.assert_not_called()
    assert {"is_active": True} not in _flag_written(sb)


def test_an_unknown_user_is_404_and_changes_nothing(client):
    response, sb = _reactivate(client, sb=_sb(None))
    assert response.status_code == 404
    sb.auth.admin.update_user_by_id.assert_not_called()
    assert {"is_active": True} not in _flag_written(sb)


def test_a_row_that_vanishes_between_read_and_write_is_404(client):
    response, _ = _reactivate(client, sb=_sb(update_rows=[]))
    assert response.status_code == 404


def test_reactivating_is_super_admin_only(client):
    response, sb = _reactivate(client, user=STAFF)
    assert response.status_code == 403
    sb.auth.admin.update_user_by_id.assert_not_called()


def test_it_needs_a_token_at_all(client):
    assert client.patch("/users/u9/reactivate").status_code == 403


def test_a_super_admin_on_a_generated_password_cannot_reactivate_anybody(client):
    """`_refuse_until_password_changed` runs BEFORE the super_admin bypass
    (spec §7), and this route is not one of the two exempt ones."""
    response, sb = _reactivate(
        client, user={**SUPER, "must_change_password": True})
    assert response.status_code == 409
    sb.auth.admin.update_user_by_id.assert_not_called()


def test_the_response_names_the_account_that_was_restored(client):
    """The screen reports it back by EMAIL. Two rows can carry the same display
    name, and the address is the identifier that is actually unique."""
    body = _reactivate(client)[0].json()
    assert body["email"] == "harry@getstarted.hk"
    assert body["display_name"] == "Harry Lo"
