"""`GET /auth/super-admins` — who the login screen tells you to write to.

The properties this file exists to hold:

  1. IT IS REACHABLE WITHOUT A TOKEN. That is the whole point — the login
     screen is the one screen with no session, and it is exactly where somebody
     needs to know who to ask.
  2. IT RETURNS SUPER ADMINS AND NOTHING ELSE. Not the rest of the user list,
     not a role id, not an account id, not `must_change_password`. This is the
     second unauthenticated route in the API and its exposure has to stay
     exactly as wide as it was argued to be.
  3. A FAILURE IS AN EMPTY LIST, NOT A 500. The login form has to render
     whether or not this resolves.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from routers import auth as auth_router


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_cache():
    auth_router.clear_contacts_cache()
    yield
    auth_router.clear_contacts_cache()


def _sb(roles=None, users=None):
    """A Supabase double whose two `.table()` calls answer differently.

    `roles` resolves the super_admin role id; `users` is filtered on it. They
    are separate queries on purpose (see the route's docstring), so the double
    has to keep them apart or the test proves nothing about either.
    """
    sb = MagicMock()
    roles_tbl, users_tbl = MagicMock(), MagicMock()
    (roles_tbl.select.return_value.eq.return_value.execute.return_value
     .data) = roles if roles is not None else [{"id": "role-sa"}]
    (users_tbl.select.return_value.in_.return_value.eq.return_value
     .order.return_value.execute.return_value.data) = users or []
    sb.table.side_effect = lambda name: (
        roles_tbl if name == "roles" else users_tbl)
    return sb


def _get(client, sb):
    with patch("routers.auth.get_supabase", return_value=sb):
        return client.get("/auth/super-admins")


# --------------------------------------------------------------------------- #
#  Reachable with no token
# --------------------------------------------------------------------------- #

def test_the_login_screen_can_read_it_without_a_token(client):
    """No Authorization header at all. The one screen that needs this list is
    the one screen that has no session to send."""
    response = _get(client, _sb(users=[
        {"display_name": "Brian Yiu", "email": "brian@getstarted.hk"}]))
    assert response.status_code == 200
    assert response.json() == {"super_admins": [
        {"display_name": "Brian Yiu", "email": "brian@getstarted.hk"}]}


def test_a_junk_token_does_not_turn_it_into_a_401(client):
    """It has no auth dependency, so there is nothing for a bad token to fail
    against. Asserted because a stray `Depends(require_user)` added later would
    break the login screen and nothing else — the least visible failure there
    is."""
    with patch("routers.auth.get_supabase", return_value=_sb()):
        response = client.get("/auth/super-admins",
                              headers={"Authorization": "Bearer nonsense"})
    assert response.status_code == 200


# --------------------------------------------------------------------------- #
#  Exactly this much, and no more
# --------------------------------------------------------------------------- #

def test_only_ACTIVE_super_admins_are_asked_for(client):
    """A deactivated administrator cannot help anybody, and naming them sends
    the locked-out user to a mailbox that will not answer."""
    sb = _sb(users=[{"display_name": "Vanis", "email": "vanis@getstarted.hk"}])
    _get(client, sb)
    users_tbl = sb.table("users")
    users_tbl.select.return_value.in_.assert_called_once_with(
        "role_id", ["role-sa"])
    (users_tbl.select.return_value.in_.return_value.eq
     .assert_called_once_with("is_active", True))


def test_it_returns_a_name_and_an_address_and_nothing_else(client):
    """The rest of the user row — id, role_id, is_active,
    must_change_password — is exactly what an unauthenticated route must not
    hand out."""
    sb = _sb(users=[{"display_name": "Vanis", "email": "vanis@getstarted.hk"}])
    _get(client, sb)
    selected = sb.table("users").select.call_args[0][0]
    assert selected == "display_name, email"


def test_a_super_admin_with_no_email_is_not_a_contact(client):
    """An address is the entire point of the list. A row without one is not
    somebody you can write to."""
    response = _get(client, _sb(users=[
        {"display_name": "Harry Lo", "email": None},
        {"display_name": "Blank", "email": "   "},
        {"display_name": "Vanis", "email": "vanis@getstarted.hk"}]))
    assert [c["email"] for c in response.json()["super_admins"]] == [
        "vanis@getstarted.hk"]


def test_every_active_super_admin_is_listed_not_just_the_first(client):
    """The screen names all of them. One address that happens to be on leave is
    the failure this replaces."""
    response = _get(client, _sb(users=[
        {"display_name": "Brian Yiu", "email": "brian@getstarted.hk"},
        {"display_name": "Levi Z.", "email": "levi@zenexflow.com"},
        {"display_name": "Vanis", "email": "vanis@getstarted.hk"}]))
    assert len(response.json()["super_admins"]) == 3


def test_no_super_admin_role_yields_an_empty_list_not_an_error(client):
    """MASTER/PROD was bootstrapped with no `super_admin` role at all. The
    login screen still has to render there."""
    response = _get(client, _sb(roles=[]))
    assert response.status_code == 200
    assert response.json() == {"super_admins": []}


# --------------------------------------------------------------------------- #
#  Failure is empty, never a 500
# --------------------------------------------------------------------------- #

def test_a_database_failure_is_an_empty_list_not_a_500(client):
    """The login form must render whether or not this resolves. The screen
    carries a fallback line for exactly this case."""
    sb = MagicMock()
    sb.table.side_effect = RuntimeError("supabase is down")
    response = _get(client, sb)
    assert response.status_code == 200
    assert response.json() == {"super_admins": []}


def test_the_failure_does_not_leak_the_reason_to_the_caller(client):
    """It goes to stderr. An unauthenticated route that reports the database's
    own error text is a route that describes the database to anybody."""
    sb = MagicMock()
    sb.table.side_effect = RuntimeError("password authentication failed")
    response = _get(client, sb)
    assert "password authentication failed" not in response.text


# --------------------------------------------------------------------------- #
#  The cache
# --------------------------------------------------------------------------- #

def test_a_second_request_does_not_ask_the_database_again(client):
    """Reloading the login screen must not be a query generator."""
    sb = _sb(users=[{"display_name": "Vanis", "email": "v@getstarted.hk"}])
    _get(client, sb)
    calls_after_first = sb.table.call_count
    _get(client, sb)
    assert sb.table.call_count == calls_after_first


def test_the_cached_answer_is_the_same_answer(client):
    sb = _sb(users=[{"display_name": "Vanis", "email": "v@getstarted.hk"}])
    first = _get(client, sb).json()
    assert _get(client, sb).json() == first


def test_a_failure_is_not_cached_as_an_empty_list(client):
    """A five-minute outage must not silence the screen for five minutes after
    the database comes back."""
    broken = MagicMock()
    broken.table.side_effect = RuntimeError("down")
    assert _get(client, broken).json() == {"super_admins": []}

    working = _sb(users=[{"display_name": "Vanis", "email": "v@getstarted.hk"}])
    assert _get(client, working).json()["super_admins"] != []
