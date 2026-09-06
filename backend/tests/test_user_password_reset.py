"""`POST /users/{id}/reset-password` — an administrator unlocks a colleague.

The same three properties creation holds (`test_user_password_flow.py`), plus
the one that is specific to a reset:

  1. THE GENERATED PASSWORD LEAVES BY EXACTLY ONE ROUTE — the email. Not the
     API response, not a log line, not an audit row. An administrator resets an
     account; they do not learn how to sign in as it.
  2. THE ACCOUNT IS FORCED TO CHANGE IT. A reset that left the generated
     password in place would leave a credential that an administrator mailed
     working indefinitely.
  3. THE ORDER IS AUTH, FLAG, MAIL — and a failure after the Auth call NEVER
     aborts the response, because by then the user's old password is already
     gone and the mail is the only way back in.
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

TARGET = {"id": "u9", "display_name": "Roy", "email": "roy@x.com",
          "is_active": True}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_auth_cache()
    yield
    clear_auth_cache()


def _sb(target=TARGET):
    """`target=None` means the row is genuinely absent — hence the default is
    the row itself, not None, which would make "no such user" unreachable."""
    sb = MagicMock()
    table = MagicMock()
    (table.select.return_value.eq.return_value.limit.return_value
     .execute.return_value.data) = [target] if target else []
    (table.update.return_value.eq.return_value.execute.return_value
     .data) = [{"id": "u9"}]
    sb.table.return_value = table
    return sb


def _reset(client, sb=None, send=None, user=None, user_id="u9"):
    sb = sb if sb is not None else _sb()
    sender = send or MagicMock(return_value={"id": "m1", "redirected": False})
    with patch("middleware.auth._resolve_user", return_value=user or SUPER), \
         patch("routers.users.get_supabase", return_value=sb), \
         patch("routers.users.email_service.send", new=sender):
        response = client.post(f"/users/{user_id}/reset-password", headers=H)
    return response, sb, sender


def _generated(sb):
    """The password the route actually handed to Supabase Auth."""
    return sb.auth.admin.update_user_by_id.call_args[0][1]["password"]


# --------------------------------------------------------------------------- #
#  Happy path
# --------------------------------------------------------------------------- #

def test_resetting_a_password_returns_200(client):
    response, _, _ = _reset(client)
    assert response.status_code == 200


def test_the_new_password_is_generated_not_chosen(client):
    """The same generator creation uses: 20 characters, none of them confusable
    with another in some font."""
    _, sb, _ = _reset(client)
    password = _generated(sb)
    assert len(password) == 20
    assert not set(password) & set("1lIO0")


def test_the_new_password_is_never_in_the_response(client):
    """An administrator resets an account, they do not learn how to sign in as
    it — and a response body ends up in the browser's network log."""
    response, sb, _ = _reset(client)
    assert _generated(sb) not in response.text


def test_the_new_password_goes_to_the_user_by_email(client):
    _, sb, send = _reset(client)
    assert send.call_args.kwargs["to"] == ["roy@x.com"]
    assert _generated(sb) in send.call_args.kwargs["html"]


def test_the_mail_says_it_was_a_reset_and_not_a_new_account(client):
    """A person who did not ask for this has either a confused colleague or a
    compromised portal, and the message is the only thing that tells them which
    question to ask."""
    _, _, send = _reset(client)
    html = send.call_args.kwargs["html"]
    assert "has reset" in html
    assert "If you did not ask for this" in html
    assert send.call_args.kwargs["subject"] == (
        "Your G-FlowDesk password has been reset")


def test_the_user_is_forced_to_choose_their_own_password(client):
    _, sb, _ = _reset(client)
    assert sb.table.return_value.update.call_args[0][0] == {
        "must_change_password": True}


def test_the_response_names_the_address_the_mail_actually_went_to(client):
    """The screen tells the administrator which mailbox to chase. It has to be
    the address the mail was sent to, not the one they were looking at."""
    response, _, send = _reset(client)
    assert response.json()["email"] == "roy@x.com"
    assert send.call_args.kwargs["to"] == [response.json()["email"]]


def test_the_identity_cache_is_cleared(client):
    """Identities are cached for 30 seconds. Without this the user is not sent
    to the choose-a-password screen for half a minute after the reset."""
    with patch("routers.users.clear_auth_cache") as cleared:
        _reset(client)
    cleared.assert_called_once()


# --------------------------------------------------------------------------- #
#  Who may press it
# --------------------------------------------------------------------------- #

def test_resetting_someone_else_is_super_admin_only(client):
    response, _, _ = _reset(client, user=STAFF)
    assert response.status_code == 403


def test_it_needs_a_token_at_all(client):
    assert client.post("/users/u9/reset-password").status_code in (401, 403)


def test_a_super_admin_on_a_generated_password_cannot_reset_anybody(client):
    """The must-change gate runs before the super_admin bypass. The account
    that can reset other people's passwords is the one worth protecting most."""
    stuck = {**SUPER, "must_change_password": True}
    response, _, _ = _reset(client, user=stuck)
    assert response.status_code == 409


# --------------------------------------------------------------------------- #
#  Refusals
# --------------------------------------------------------------------------- #

def test_an_unknown_user_is_404_and_changes_no_password(client):
    sb = _sb(target=None)
    response, sb, send = _reset(client, sb=sb)
    assert response.status_code == 404
    sb.auth.admin.update_user_by_id.assert_not_called()
    send.assert_not_called()


def test_a_database_failure_is_NOT_reported_as_a_missing_user():
    """The reason the lookup uses `.limit(1)` and not `.single()`: the latter
    raises on no rows, so not-found would need a bare `except` — and that same
    `except` would turn an outage into "User not found", sending the
    administrator hunting for a user who is sitting right there in the table.

    The outage is now answered as a 500 by `services/api_errors.py` rather than
    escaping the app — which is the point of that middleware, and does not
    change what this test is protecting: whatever the administrator is told, it
    must not be that the user does not exist. `raise_server_exceptions=False`
    because the question is what the BROWSER receives.
    """
    error_client = TestClient(app, raise_server_exceptions=False)
    sb = _sb()
    (sb.table.return_value.select.return_value.eq.return_value.limit
     .return_value.execute.side_effect) = RuntimeError("supabase is down")

    response, _, send = _reset(error_client, sb=sb)

    assert response.status_code == 500
    assert "not found" not in response.text.lower()
    send.assert_not_called()


def test_a_deactivated_account_is_refused(client):
    """It is banned in Auth. Mailing it a working-looking password would put a
    live credential in a mailbox for an account that cannot sign in, and tell
    the administrator the opposite of the truth."""
    response, sb, send = _reset(client, sb=_sb({**TARGET, "is_active": False}))
    assert response.status_code == 409
    assert "deactivated" in response.json()["detail"]
    sb.auth.admin.update_user_by_id.assert_not_called()
    send.assert_not_called()


def test_an_account_with_no_email_is_refused_before_anything_changes(client):
    """The password leaves by one route. No route, no reset — and crucially,
    no password change either, which would lock them out permanently."""
    response, sb, _ = _reset(client, sb=_sb({**TARGET, "email": None}))
    assert response.status_code == 409
    sb.auth.admin.update_user_by_id.assert_not_called()


def test_an_auth_refusal_is_a_400_that_does_not_echo_the_password(client):
    sb = _sb()
    sb.auth.admin.update_user_by_id.side_effect = RuntimeError("rejected")
    response, sb, send = _reset(client, sb=sb)
    assert response.status_code == 400
    assert _generated(sb) not in response.text
    send.assert_not_called()


# --------------------------------------------------------------------------- #
#  Everything after the Auth call is best-effort and REPORTED
# --------------------------------------------------------------------------- #

def test_a_failed_email_does_NOT_abort_the_reset(client):
    """By this point the old password is already gone. Raising would tell the
    administrator the reset failed while the user was in fact locked out — the
    worst of both. Railway DEV has no RESEND_API_KEY, so this is the likely
    path, not the exotic one."""
    response, _, _ = _reset(
        client, send=MagicMock(side_effect=RuntimeError("RESEND_API_KEY is not set")))
    assert response.status_code == 200
    body = response.json()
    assert body["reset_email_sent"] is False
    assert "RESEND_API_KEY" in body["reset_email_error"]


def test_a_failed_email_still_leaks_no_password(client):
    response, sb, _ = _reset(
        client, send=MagicMock(side_effect=RuntimeError("mail is down")))
    assert _generated(sb) not in response.text


def test_a_redirected_email_is_reported_as_redirected(client):
    """The test-environment lock sends every message to four hardcoded
    mailboxes. The reset is real and the old password is gone, so unless this
    user is one of those four they are now locked out — and nothing else on the
    screen would say why."""
    response, _, _ = _reset(
        client, send=MagicMock(return_value={"id": "m1", "redirected": True}))
    assert response.json()["reset_email_redirected"] is True


def test_a_flag_write_that_fails_still_sends_the_mail(client):
    """The password has already changed. Aborting here would leave a real
    person locked out over a flag."""
    sb = _sb()
    sb.table.return_value.update.return_value.eq.return_value.execute \
        .side_effect = RuntimeError("column missing")
    response, _, send = _reset(client, sb=sb)
    assert response.status_code == 200
    send.assert_called_once()
    # And it says so, rather than claiming a forced change that is not set.
    assert response.json()["must_change_password"] is False


def test_a_successful_reset_reports_the_forced_change(client):
    response, _, _ = _reset(client)
    assert response.json()["must_change_password"] is True
