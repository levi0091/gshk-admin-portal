"""Spec §7 — user creation without an admin-chosen password.

Two properties this file exists to hold:

  1. THE GENERATED PASSWORD LEAVES BY EXACTLY ONE ROUTE — the welcome email.
     Not the API response, not a log line, not an audit row. An administrator
     cannot read a colleague's credential, and neither can anybody reading the
     server's logs.
  2. THE FLAG IS ENFORCED IN THE MIDDLEWARE. A first-login redirect that lives
     in React is a suggestion; the API is reachable with the same token by
     anything that can type a URL.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from middleware.auth import clear_auth_cache
from routers import users as users_router

SUPER = {"id": "u1", "display_name": "Levi", "role_name": "super_admin",
         "role_id": "role-sa", "must_change_password": False}
NEW_USER = {"id": "u9", "display_name": "Roy", "role_name": "case_manager",
            "role_id": "role-cm", "must_change_password": True}
H = {"Authorization": "Bearer tok"}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_auth_cache()
    yield
    clear_auth_cache()


def _sb(created=None, role_name="Case Manager"):
    sb = MagicMock()
    sb.auth.admin.create_user.return_value = MagicMock(
        user=MagicMock(id="u9"))
    table = MagicMock()
    table.insert.return_value.execute.return_value.data = [
        created or {"id": "u9", "display_name": "Roy", "email": "roy@x.com"}]
    (table.select.return_value.eq.return_value.single.return_value
     .execute.return_value.data) = {"name": role_name}
    (table.update.return_value.eq.return_value.execute.return_value
     .data) = [{"id": "u9"}]
    sb.table.return_value = table
    return sb


# --------------------------------------------------------------------------- #
#  generate_password
# --------------------------------------------------------------------------- #

def test_the_generated_password_omits_every_confusable_character():
    """Somebody is going to read this off a screen and type it into a login
    box. `1 l I O 0` are each confusable with another character in some font,
    and every one of them is a support conversation."""
    for _ in range(200):
        assert not set(users_router.generate_password()) & set("1lIO0")


def test_the_generated_password_is_long_enough_to_be_worth_generating():
    password = users_router.generate_password()
    assert len(password) == 20
    # ~118 bits from a 60-character alphabet. Far more than a human would
    # choose, which is the point.
    assert len(set(users_router._ALPHABET)) >= 55


def test_two_generated_passwords_are_never_the_same():
    assert len({users_router.generate_password() for _ in range(500)}) == 500


def test_the_password_carries_nothing_a_shell_or_a_csv_would_mangle():
    for _ in range(200):
        assert not set(users_router.generate_password()) & set("'\"\\ ,;`$")


# --------------------------------------------------------------------------- #
#  create_user
# --------------------------------------------------------------------------- #

def _create(client, sb, send=None, body=None):
    with patch("middleware.auth._resolve_user", return_value=SUPER), \
         patch("routers.users.get_supabase", return_value=sb), \
         patch("routers.users.email_service.send",
               new=send or MagicMock(return_value={"id": "m1",
                                                   "redirected": False})) as sent:
        response = client.post("/users/", headers=H, json=body or {
            "display_name": "Roy", "email": "roy@x.com", "role_id": "role-cm"})
    return response, sent


def test_creating_a_user_no_longer_takes_a_password(client):
    response, _ = _create(client, _sb())
    assert response.status_code == 201


def test_a_password_in_the_request_is_simply_not_a_field(client):
    """Removed, not deprecated: a model that still accepted one would keep the
    old flow alive for any caller that kept sending it."""
    assert "password" not in users_router.CreateUserRequest.model_fields


def test_the_generated_password_is_never_in_the_response(client):
    """The administrator does not need it, the screen must not show it, and a
    response body ends up in the browser's network log."""
    sb = _sb()
    response, _ = _create(client, sb)
    sent_password = sb.auth.admin.create_user.call_args[0][0]["password"]
    assert sent_password                      # one WAS generated
    assert sent_password not in response.text


def test_the_generated_password_goes_to_the_new_user_by_email(client):
    sb = _sb()
    _, send = _create(client, sb)
    generated = sb.auth.admin.create_user.call_args[0][0]["password"]
    assert send.call_args.kwargs["to"] == ["roy@x.com"]
    assert generated in send.call_args.kwargs["html"]


def test_the_welcome_email_names_the_role_it_granted(client):
    _, send = _create(client, _sb(role_name="Case Manager"))
    assert "Case Manager" in send.call_args.kwargs["html"]


def test_a_role_that_cannot_be_read_omits_one_line_rather_than_failing(client):
    """A nameless role is a cosmetic problem. Refusing to create the account
    over it would be a real one."""
    sb = _sb()
    (sb.table.return_value.select.return_value.eq.return_value.single
     .return_value.execute.side_effect) = RuntimeError("boom")
    response, send = _create(client, sb)
    assert response.status_code == 201
    send.assert_called_once()


def test_the_new_account_must_change_its_password(client):
    sb = _sb()
    _create(client, sb)
    inserted = sb.table.return_value.insert.call_args[0][0]
    assert inserted["must_change_password"] is True


def test_a_failed_welcome_email_does_NOT_undo_the_account(client):
    """The account is already in Supabase Auth. Raising would tell the
    administrator the creation failed, and their retry would then collide on
    the email address — leaving a real user who can never sign in and an
    administrator who believes no user exists."""
    response, _ = _create(
        client, _sb(),
        send=MagicMock(side_effect=RuntimeError("RESEND_API_KEY is not set")))
    assert response.status_code == 201
    body = response.json()
    assert body["welcome_email_sent"] is False
    assert "RESEND_API_KEY" in body["welcome_email_error"]


def test_a_failed_welcome_email_still_leaks_no_password(client):
    sb = _sb()
    response, _ = _create(
        client, sb, send=MagicMock(side_effect=RuntimeError("mail is down")))
    generated = sb.auth.admin.create_user.call_args[0][0]["password"]
    assert generated not in response.text


def test_creating_a_user_is_super_admin_only(client):
    with patch("middleware.auth._resolve_user", return_value=NEW_USER):
        response = client.post("/users/", headers=H, json={
            "display_name": "X", "email": "x@x.com", "role_id": "r"})
    # 409 (must change password) or 403 (not a super admin) — either way the
    # account is not created. This user is both.
    assert response.status_code in (403, 409)


# --------------------------------------------------------------------------- #
#  The must-change gate
# --------------------------------------------------------------------------- #

def test_a_user_on_a_generated_password_cannot_reach_a_business_route(client):
    with patch("middleware.auth._resolve_user", return_value=NEW_USER):
        response = client.get("/cases", headers=H)
    assert response.status_code == 409
    assert "must be replaced" in response.json()["detail"]


def test_the_refusal_is_409_and_not_403(client):
    """403 means "your role does not allow this" and would send the reader to
    an administrator for a problem they can fix themselves in ten seconds."""
    with patch("middleware.auth._resolve_user", return_value=NEW_USER):
        assert client.get("/cases", headers=H).status_code == 409


def test_even_a_SUPER_ADMIN_on_a_generated_password_is_refused(client):
    """The check runs BEFORE the super_admin bypass, on purpose: the account
    that can create other users is the one worth protecting most."""
    stuck_admin = {**SUPER, "must_change_password": True}
    with patch("middleware.auth._resolve_user", return_value=stuck_admin):
        response = client.post("/users/", headers=H, json={
            "display_name": "X", "email": "x@x.com", "role_id": "r"})
    assert response.status_code == 409


def test_auth_me_STAYS_reachable_because_it_is_how_the_flag_is_discovered(client):
    """Refusing this would leave a new user staring at a login screen that
    accepted their password and then showed them nothing."""
    sb = MagicMock()
    (sb.table.return_value.select.return_value.eq.return_value
     .execute.return_value.data) = []
    with patch("middleware.auth._resolve_user", return_value=NEW_USER), \
         patch("routers.auth.get_supabase", return_value=sb):
        response = client.get("/auth/me", headers=H)
    assert response.status_code == 200
    assert response.json()["must_change_password"] is True


def test_a_user_who_has_changed_their_password_is_not_refused(client):
    sb = MagicMock()
    (sb.table.return_value.select.return_value.eq.return_value
     .execute.return_value.data) = []
    settled = {**NEW_USER, "must_change_password": False}
    with patch("middleware.auth._resolve_user", return_value=settled), \
         patch("routers.auth.get_supabase", return_value=sb):
        assert client.get("/auth/me", headers=H).status_code == 200


# --------------------------------------------------------------------------- #
#  set_own_password
# --------------------------------------------------------------------------- #

def _set_password(client, new_password, sb=None, user=None):
    sb = sb or _sb()
    with patch("middleware.auth._resolve_user", return_value=user or NEW_USER), \
         patch("routers.users.get_supabase", return_value=sb):
        response = client.post("/users/me/password", headers=H,
                               json={"new_password": new_password})
    return response, sb


def test_choosing_a_password_clears_the_flag(client):
    response, sb = _set_password(client, "a-decent-password")
    assert response.status_code == 200
    assert response.json() == {"must_change_password": False}
    assert sb.auth.admin.update_user_by_id.call_args[0][1] == {
        "password": "a-decent-password"}
    assert sb.table.return_value.update.call_args[0][0] == {
        "must_change_password": False}


def test_the_flag_is_cleared_only_AFTER_auth_accepted_the_new_password(client):
    """Clearing first would leave an account able to use the portal on a
    password the change did not apply."""
    sb = _sb()
    sb.auth.admin.update_user_by_id.side_effect = RuntimeError("too weak")
    response, _ = _set_password(client, "a-decent-password", sb=sb)
    assert response.status_code == 400
    sb.table.return_value.update.assert_not_called()


def test_a_short_password_is_refused_before_it_reaches_auth(client):
    sb = _sb()
    response, _ = _set_password(client, "short", sb=sb)
    assert response.status_code == 400
    assert "at least 8" in response.json()["detail"]
    sb.auth.admin.update_user_by_id.assert_not_called()


def test_a_whitespace_only_password_is_refused(client):
    response, sb = _set_password(client, "            ")
    assert response.status_code == 400
    sb.auth.admin.update_user_by_id.assert_not_called()


def test_the_refusal_never_echoes_the_password_back(client):
    sb = _sb()
    sb.auth.admin.update_user_by_id.side_effect = RuntimeError("rejected")
    response, _ = _set_password(client, "hunter2-hunter2", sb=sb)
    assert "hunter2" not in response.text


def test_setting_a_password_changes_NOTHING_else(client):
    """A route reachable by an account that has not finished authenticating
    itself must not be able to change more than it says."""
    response, sb = _set_password(client, "a-decent-password")
    assert response.status_code == 200
    written = sb.table.return_value.update.call_args[0][0]
    assert set(written) == {"must_change_password"}


def test_the_identity_cache_is_cleared_so_the_user_is_not_refused_for_30s(client):
    """Identities are cached for 30 seconds. Without this the user keeps being
    refused by every route for half a minute after doing exactly what they
    were told to do."""
    with patch("routers.users.clear_auth_cache") as cleared:
        _set_password(client, "a-decent-password")
    cleared.assert_called_once()


def test_the_set_password_route_needs_a_token_but_no_permission(client):
    """`require_user`, not `require_permission`: it is the one route a user on
    a generated password can still reach."""
    response = client.post("/users/me/password",
                           json={"new_password": "a-decent-password"})
    assert response.status_code in (401, 403)


# --------------------------------------------------------------------------- #
#  The welcome email itself
# --------------------------------------------------------------------------- #

def test_the_welcome_email_points_at_the_environment_it_was_sent_from():
    """A welcome email that sent a DEV colleague to the production portal would
    have them sign in somewhere their account does not exist."""
    from services import app_env, email_service

    with patch.dict("os.environ", {"APP_ENV": "prod"}, clear=False):
        app_env.is_production.cache_clear()
        _, html = email_service.welcome_email("Roy", "Case Manager", "pw")
        assert "https://admin.g-flowdesk.com" in html
        assert "admin-dev" not in html

    with patch.dict("os.environ", {"APP_ENV": "dev"}, clear=False):
        app_env.is_production.cache_clear()
        _, html = email_service.welcome_email("Roy", "Case Manager", "pw")
        assert "https://admin-dev.g-flowdesk.com" in html
    app_env.is_production.cache_clear()


def test_a_preview_deployment_can_override_the_portal_url():
    from services import email_service

    with patch.dict("os.environ",
                    {"ADMIN_PORTAL_URL": "https://preview.pages.dev/"},
                    clear=False):
        assert email_service.portal_url() == "https://preview.pages.dev"


def test_a_junk_override_falls_back_rather_than_mailing_a_broken_link():
    from services import app_env, email_service

    with patch.dict("os.environ", {"ADMIN_PORTAL_URL": "not a url"}, clear=False):
        app_env.is_production.cache_clear()
        assert email_service.portal_url().startswith("https://admin")
    app_env.is_production.cache_clear()


def test_the_welcome_email_survives_outlook_like_every_other_message():
    from services import email_service

    _, html = email_service.welcome_email("Roy", "Case Manager", "pw")
    assert "display:flex" not in html
    assert "display:grid" not in html
    assert "<style" not in html
    assert "class=" not in html
    assert "<table" in html


def test_the_password_is_set_in_a_monospaced_face():
    """The reader is going to read it character by character, and a proportional
    face makes l/1/I and O/0 ambiguous."""
    from services import email_service

    _, html = email_service.welcome_email("Roy", "Case Manager", "Xk7pQ2wRm9t")
    index = html.index("Xk7pQ2wRm9t")
    assert "monospace" in html[:index]


def test_a_name_carrying_markup_is_escaped():
    from services import email_service

    _, html = email_service.welcome_email("<script>x</script>", "Role", "pw")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_the_welcome_email_says_the_password_is_temporary():
    from services import email_service

    _, html = email_service.welcome_email("Roy", "Case Manager", "pw")
    assert "Temporary password" in html
    assert "choose your own password" in html


def test_a_user_with_no_role_still_gets_a_usable_email():
    from services import email_service

    subject, html = email_service.welcome_email("Roy", None, "pw")
    assert subject
    assert "Your role" not in html
    assert "Sign in to G-FlowDesk" in html


# --------------------------------------------------------------------------- #
#  The deploy-before-migrate gap — the 2026-09-01 DEV outage
# --------------------------------------------------------------------------- #
#
# Railway redeploys the API the moment `dev` is pushed; alembic is run by hand
# afterwards. Between the two the new column DOES NOT EXIST, and PostgREST
# answers a select naming it with 42703 rather than ignoring it.
#
# Adding `must_change_password` to the identity select therefore 500'd EVERY
# authenticated request on DEV — `/auth/me` included, so the portal could not
# even say what was wrong. These tests reproduce that state.

import middleware.auth as auth_module

_MISSING_COLUMN = Exception(
    '{"code":"42703","message":"column users.must_change_password does not exist"}')


def _users_table(*, missing_column: bool, row=None):
    """A `users` table that refuses the new column the way PostgREST does."""
    table = MagicMock()

    def select(columns):
        if missing_column and "must_change_password" in columns:
            chain = MagicMock()
            chain.eq.return_value.single.return_value.execute.side_effect = \
                _MISSING_COLUMN
            return chain
        chain = MagicMock()
        chain.eq.return_value.single.return_value.execute.return_value = \
            MagicMock(data=row or {"display_name": "Roy", "is_active": True,
                                   "role_id": "role-cm",
                                   "roles": {"name": "case_manager", "id": "role-cm"}})
        return chain

    table.select.side_effect = select
    return table


@pytest.fixture(autouse=True)
def _reset_column_probe():
    """The fallback is remembered per process, so one test must not decide the
    next one's behaviour."""
    auth_module._profile_columns_ok = None
    yield
    auth_module._profile_columns_ok = None


def _resolve_with(table):
    sb = MagicMock()
    sb.auth.get_user.return_value = MagicMock(
        user=MagicMock(id="u9", email="roy@x.com"))
    sb.table.return_value = table
    with patch("middleware.auth.get_supabase", return_value=sb):
        return auth_module._resolve_user("tok")


def test_a_deployment_ahead_of_its_migrations_still_authenticates():
    """THE OUTAGE. Before this, every route 500'd until somebody ran alembic."""
    user = _resolve_with(_users_table(missing_column=True))
    assert user["display_name"] == "Roy"
    assert user["role_name"] == "case_manager"


def test_the_flag_reads_as_unset_when_the_column_is_not_there_yet():
    """Not a guess — it is the state of the database. Before migration 031 no
    account can be flagged, so reading it as unset is the truth, and it is the
    safe direction: nobody is locked out of a portal by a column that does not
    exist."""
    assert _resolve_with(_users_table(missing_column=True))[
        "must_change_password"] is False


def test_the_column_is_read_normally_once_the_migration_has_run():
    table = _users_table(missing_column=False, row={
        "display_name": "Roy", "is_active": True, "role_id": "role-cm",
        "must_change_password": True,
        "roles": {"name": "case_manager", "id": "role-cm"}})
    assert _resolve_with(table)["must_change_password"] is True


def test_the_fallback_is_remembered_rather_than_retried_every_request():
    """Identity resolution is on every request. Paying a failed round trip each
    time would double the latency of the whole portal during the gap."""
    table = _users_table(missing_column=True)
    for _ in range(5):
        _resolve_with(table)
    attempted = [c.args[0] for c in table.select.call_args_list
                 if "must_change_password" in c.args[0]]
    assert len(attempted) == 1


def test_a_real_database_fault_is_NOT_swallowed_as_a_missing_column():
    """Otherwise this turns every database fault into a silently degraded
    identity — a dropped connection would read as "no flag" and let a user
    straight past a control that is supposed to stop them."""
    table = MagicMock()
    table.select.return_value.eq.return_value.single.return_value \
        .execute.side_effect = RuntimeError("connection reset by peer")
    with pytest.raises(RuntimeError, match="connection reset"):
        _resolve_with(table)


def test_an_inactive_account_is_still_refused_during_the_gap():
    """The fallback must not become a way past the checks that were already
    there."""
    table = _users_table(missing_column=True, row={
        "display_name": "Roy", "is_active": False, "role_id": "role-cm",
        "roles": {"name": "case_manager", "id": "role-cm"}})
    with pytest.raises(Exception) as exc:
        _resolve_with(table)
    assert getattr(exc.value, "status_code", None) == 403
