"""The return year on a case, and the Data Verification viewer (Levi 2026-09-18).

Routes:
  GET   /cases/{id}/return-year           the picker: year, options, lock
  PATCH /cases/{id} {ar_period_year}      choose it (nar1:write, audited)
  POST  /cases/{id}/verification/send     fixes it before anyone is mailed
  GET   /cases/{id}/validation/comparison approved vs CR-validated, as a list
  GET   /cases/{id}/validation/preview    CR-validated PDF, changes boxed

Every collaborator is patched at the router's boundary; `hk_today` is pinned so
no assertion depends on the day the suite runs.
"""
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from services import nar1_return_year
from services.nar1_form import compare as nar1_compare

SUPER = {"id": "u1", "display_name": "Levi", "role_name": "super_admin",
         "role_id": "role-sa"}
STAFF = {"id": "u2", "display_name": "Staff", "role_name": "staff",
         "role_id": "role-x"}
H = {"Authorization": "Bearer tok"}

TODAY = date(2026, 9, 18)

CASE = {"id": "c1", "case_no": "NAR-2026-0004", "entity_id": "e1",
        "ar_period_year": None, "verification_sent_at": None,
        "client_approved": None, "client_response_at": None,
        "verification_xml": None}

#: ShoppyVerse's shape: the 2026 anniversary is three weeks after TODAY.
ENTITY = {"id": "e1", "company_name": "SHOPPYVERSE LIMITED",
          "br_number": "78908563", "incorporation_date": "2019-10-09"}


@pytest.fixture
def client():
    return TestClient(app)


def _super():
    return patch("middleware.auth._resolve_user", return_value=SUPER)


def _staff_without(module_permissions=()):
    return [patch("middleware.auth._resolve_user", return_value=STAFF),
            patch("middleware.auth._permissions_for",
                  return_value=set(module_permissions))]


def _today():
    return patch("routers.cases.nar1_return_year.hk_today", return_value=TODAY)


def _case(case=None, filing=None, entity=ENTITY):
    return [
        patch("routers.cases.nar1_cases.get_case", return_value=case or CASE),
        patch("routers.cases.nar1_cases.current_filing", return_value=filing),
        patch("routers.cases.nar1_cases.entity_for", return_value=entity),
        patch("routers.cases.nar1_cases.composite",
              side_effect=lambda cid: {"id": cid}),
    ]


class _Stack:
    def __init__(self, *managers):
        self._managers = [m for group in managers
                          for m in (group if isinstance(group, list) else [group])]

    def __enter__(self):
        return [m.__enter__() for m in self._managers]

    def __exit__(self, *exc):
        for m in reversed(self._managers):
            m.__exit__(*exc)
        return False


# ---------------------------------------------------------------------------
# GET /cases/{id}/return-year
# ---------------------------------------------------------------------------

def test_the_picker_starts_empty_with_every_year_back_to_the_first_return(client):
    """Levi 2026-09-19: "do not default the dropdown to current year... make it
    empty by default but mandatory"."""
    with _Stack(_super(), _today(), _case()):
        response = client.get("/cases/c1/return-year", headers=H)
    assert response.status_code == 200
    body = response.json()
    assert body["year"] is None and body["source"] is None
    assert body["return_date"] is None
    assert body["locked"] is False
    years = [o["year"] for o in body["options"]]
    assert years[0] == 2026 and years[-1] == 2020
    assert {2023, 2024, 2025, 2026} <= set(years)


def test_a_draft_built_under_the_old_default_does_not_preselect_its_year(client):
    draft = {"id": "f1", "stage": "draft",
             "request_xml": "<cr:yearAnnualReturn>2026</cr:yearAnnualReturn>"}
    with _Stack(_super(), _today(), _case(filing=draft)):
        body = client.get("/cases/c1/return-year", headers=H).json()
    assert body["year"] is None


def test_the_picker_shows_the_year_a_legacy_case_was_sent_for(client):
    legacy = {**CASE, "verification_sent_at": "2026-09-10T00:00:00Z",
              "verification_xml": "<cr:yearAnnualReturn>2026</cr:yearAnnualReturn>"}
    with _Stack(_super(), _today(), _case(case=legacy)):
        body = client.get("/cases/c1/return-year", headers=H).json()
    assert (body["year"], body["source"]) == (2026, "sent")
    assert body["locked"] is True


def test_the_picker_says_why_a_sent_case_cannot_change_year(client):
    sent = {**CASE, "ar_period_year": 2026,
            "verification_sent_at": "2026-09-10T00:00:00Z"}
    with _Stack(_super(), _today(), _case(case=sent)):
        body = client.get("/cases/c1/return-year", headers=H).json()
    assert body["locked"] is True
    assert "Restart verification" in body["locked_reason"]


def test_the_picker_marks_years_other_cases_already_file(client):
    held = {2025: {"case_id": "c0", "case_no": "NAR-2026-0001"}}
    with _Stack(_super(), _today(), _case(),
                patch("routers.cases.nar1_return_year.held_years",
                      return_value=held)):
        body = client.get("/cases/c1/return-year", headers=H).json()
    by_year = {o["year"]: o for o in body["options"]}
    assert by_year[2025]["held_by"]["case_no"] == "NAR-2026-0001"


def test_the_picker_requires_nar1_read(client):
    with _Stack(_staff_without(), _case()):
        assert client.get("/cases/c1/return-year", headers=H).status_code == 403


def test_the_picker_404s_an_unknown_case(client):
    with _Stack(_super(), patch("routers.cases.nar1_cases.get_case",
                                side_effect=LookupError("no case c9"))):
        assert client.get("/cases/c9/return-year", headers=H).status_code == 404


# ---------------------------------------------------------------------------
# PATCH /cases/{id} {ar_period_year}
# ---------------------------------------------------------------------------

def test_choosing_a_missed_year_stores_it_and_audits_the_change(client):
    update = MagicMock()
    log = AsyncMock()
    with _Stack(_super(), _today(), _case(),
                patch("routers.cases.nar1_cases.update_case", new=update),
                patch("routers.cases.log_event", new=log)):
        response = client.patch("/cases/c1", headers=H, json={"ar_period_year": 2023})
    assert response.status_code == 200
    assert update.call_args.args[1] == {"ar_period_year": 2023}
    [event] = [c.kwargs for c in log.call_args_list]
    assert event["action_type"] == "CASE_FIELD_UPDATED"
    assert event["new_value"] == "2023" and event["old_value"] is None
    assert event["metadata"] == {"field": "ar_period_year"}


def test_a_year_before_the_first_return_is_a_400_naming_it(client):
    update = MagicMock()
    with _Stack(_super(), _today(), _case(),
                patch("routers.cases.nar1_cases.update_case", new=update)):
        response = client.patch("/cases/c1", headers=H, json={"ar_period_year": 2019})
    assert response.status_code == 400
    assert "2020" in response.text
    update.assert_not_called()


def test_a_year_early_is_a_400(client):
    update = MagicMock()
    with _Stack(_super(), _today(), _case(),
                patch("routers.cases.nar1_cases.update_case", new=update)):
        response = client.patch("/cases/c1", headers=H, json={"ar_period_year": 2027})
    assert response.status_code == 400
    update.assert_not_called()


def test_once_sent_the_year_is_locked(client):
    update = MagicMock()
    sent = {**CASE, "ar_period_year": 2026,
            "verification_sent_at": "2026-09-10T00:00:00Z"}
    with _Stack(_super(), _today(), _case(case=sent),
                patch("routers.cases.nar1_cases.update_case", new=update)):
        response = client.patch("/cases/c1", headers=H, json={"ar_period_year": 2025})
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "return_year_locked"
    update.assert_not_called()


def test_asking_a_locked_case_for_the_year_it_already_has_is_a_no_op(client):
    update = MagicMock()
    log = AsyncMock()
    sent = {**CASE, "ar_period_year": 2026,
            "verification_sent_at": "2026-09-10T00:00:00Z"}
    with _Stack(_super(), _today(), _case(case=sent),
                patch("routers.cases.nar1_cases.update_case", new=update),
                patch("routers.cases.log_event", new=log)):
        response = client.patch("/cases/c1", headers=H, json={"ar_period_year": 2026})
    assert response.status_code == 200
    update.assert_not_called()
    log.assert_not_awaited()


def test_restart_and_a_new_year_in_one_request_is_allowed(client):
    """The natural way to move a case sent for the wrong year: the restart
    lifts the lock the year change would otherwise hit."""
    update = MagicMock()
    sent = {**CASE, "ar_period_year": 2026,
            "verification_sent_at": "2026-09-10T00:00:00Z",
            "verification_xml": "<mailed/>"}
    with _Stack(_super(), _today(), _case(case=sent),
                patch("routers.cases.tpsi_filings.supersede", return_value=False),
                patch("routers.cases.nar1_approvals.supersede_outstanding"),
                patch("routers.cases.nar1_cases.update_case", new=update),
                patch("routers.cases.log_event", new=AsyncMock())):
        response = client.patch("/cases/c1", headers=H, json={
            "restart_verification": True, "ar_period_year": 2025})
    assert response.status_code == 200
    written = update.call_args.args[1]
    assert written["ar_period_year"] == 2025
    assert written["verification_sent_at"] is None


def test_a_year_another_case_files_is_a_409_naming_that_case(client):
    update = MagicMock()
    held = {2024: {"case_id": "c0", "case_no": "NAR-2026-0001"}}
    with _Stack(_super(), _today(), _case(),
                patch("routers.cases.nar1_return_year.held_years", return_value=held),
                patch("routers.cases.nar1_cases.update_case", new=update)):
        response = client.patch("/cases/c1", headers=H, json={"ar_period_year": 2024})
    assert response.status_code == 409
    assert response.json()["detail"]["held_by"]["case_no"] == "NAR-2026-0001"
    update.assert_not_called()


def test_losing_the_race_to_the_unique_index_is_a_409_not_a_500(client):
    class Duplicate(Exception):
        code = "23505"

    with _Stack(_super(), _today(), _case(),
                patch("routers.cases.nar1_cases.update_case",
                      side_effect=Duplicate("duplicate key value")),
                patch("routers.cases.log_event", new=AsyncMock())):
        response = client.patch("/cases/c1", headers=H, json={"ar_period_year": 2024})
    assert response.status_code == 409
    assert "2024" in response.text


def test_choosing_a_year_requires_nar1_write(client):
    update = MagicMock()
    with _Stack(_staff_without({"read"}), _today(), _case(),
                patch("routers.cases.nar1_cases.update_case", new=update)):
        response = client.patch("/cases/c1", headers=H, json={"ar_period_year": 2024})
    assert response.status_code == 403
    update.assert_not_called()


# ---------------------------------------------------------------------------
# The send fixes the year before anybody is mailed
# ---------------------------------------------------------------------------

def _send_patches(case, *, claim):
    return [
        patch("routers.cases.nar1_cases.get_case", return_value=case),
        patch("routers.cases.nar1_cases.current_filing", return_value=None),
        patch("routers.cases.nar1_cases.default_recipients", return_value=[]),
        patch("routers.cases.nar1_cases.recipient_email",
              return_value="client@example.com"),
        patch("routers.cases.nar1_cases.entity_for", return_value=ENTITY),
        patch("routers.cases.nar1_cases.composite", return_value={"id": "c1"}),
        patch("routers.cases.nar1_cases.update_case"),
        patch("routers.cases.nar1_prepare.build_form_xml",
              new=AsyncMock(return_value="<built/>")),
        patch("routers.cases.tpsi_filings.create_filing",
              return_value={"id": "f1", "stage": "draft",
                            "request_xml": "<built/>"}),
        patch("routers.cases.nar1_form_fill.render", return_value=b"%PDF-1.4"),
        # One token per recipient, echoing the deadline — the shape the real
        # `issue` returns (see test_cases_verification's fixture).
        patch("routers.cases.nar1_approvals.issue",
              side_effect=lambda *, case_id, recipients, sent_at=None,
              expires_at=None: [{**r, "token": f"tok-{i}",
                                 "expires_at": expires_at}
                                for i, r in enumerate(recipients)]),
        patch("routers.cases.nar1_approvals.supersede_outstanding"),
        patch("routers.cases.nar1_return_year.claim", **claim),
    ]


SEND = {"to": ["client@example.com"], "respond_by": "2099-12-31"}


def test_the_send_builds_and_fixes_the_year_the_case_names(client):
    log = AsyncMock()
    case = {**CASE, "ar_period_year": 2024}
    mail = MagicMock(return_value={"id": "m1", "to": ["client@example.com"],
                                   "intended_to": ["client@example.com"],
                                   "redirected": False})
    with _Stack(_super(), _today(), _send_patches(case, claim={"return_value": False}),
                patch("routers.cases.email_service.send", new=mail),
                patch("routers.cases.log_event", new=log)) as entered:
        response = client.post("/cases/c1/verification/send", headers=H, json=SEND)
    assert response.status_code == 200, response.text
    build = [m for m in entered if isinstance(m, AsyncMock)
             and m.await_args and "year" in m.await_args.kwargs]
    assert build and build[0].await_args.kwargs["year"] == 2024
    sent = [c.kwargs for c in log.call_args_list
            if c.kwargs.get("action_type") == "EMAIL_SENT"]
    assert sent[0]["metadata"]["return_year"] == 2024


#: A case mailed before the year existed, being RE-sent: no stored year, but
#: the return it was sent is for one — the only way a send can still meet a
#: case whose year is not written down.
LEGACY_SENT = {**CASE, "verification_sent_at": "2026-09-10T00:00:00Z",
               "verification_xml": "<cr:yearAnnualReturn>2026</cr:yearAnnualReturn>"}


def test_a_case_with_no_year_is_refused_before_anything_is_built(client):
    """MANDATORY (Levi 2026-09-19). Nobody is asked to approve "a" return."""
    build = AsyncMock(return_value="<built/>")
    mail = MagicMock()
    claim = MagicMock()
    with _Stack(_super(), _today(), _send_patches(dict(CASE), claim={"new": claim}),
                patch("routers.cases.nar1_prepare.build_form_xml", new=build),
                patch("routers.cases.email_service.send", new=mail),
                patch("routers.cases.log_event", new=AsyncMock())):
        response = client.post("/cases/c1/verification/send", headers=H, json=SEND)
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "return_year_required"
    build.assert_not_awaited()
    mail.assert_not_called()
    claim.assert_not_called()


def test_the_stage_one_preview_asks_for_the_year_instead_of_guessing(client):
    build = AsyncMock(return_value="<built/>")
    with _Stack(_super(), _today(), _case(),
                patch("routers.cases.nar1_prepare.build_form_xml", new=build)):
        response = client.get("/cases/c1/verification/preview", headers=H)
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "return_year_required"
    build.assert_not_awaited()


def test_a_year_another_case_holds_refuses_the_send_before_any_mail(client):
    refused = nar1_return_year.YearRefused(
        "case NAR-2026-0001 is already filing this company's 2026 annual return",
        status=409, held_by={"case_id": "c0", "case_no": "NAR-2026-0001"})
    mail = MagicMock()
    with _Stack(_super(), _today(),
                _send_patches(dict(LEGACY_SENT), claim={"side_effect": refused}),
                patch("routers.cases.email_service.send", new=mail),
                patch("routers.cases.log_event", new=AsyncMock())):
        response = client.post("/cases/c1/verification/send", headers=H, json=SEND)
    assert response.status_code == 409
    assert "NAR-2026-0001" in response.text
    mail.assert_not_called()


def test_a_held_year_is_refused_before_anything_is_built(client):
    """The read-only check at the top: nothing is prepared, no draft filing is
    opened for a year another case already files."""
    held = {2026: {"case_id": "c0", "case_no": "NAR-2026-0001"}}
    build = AsyncMock(return_value="<built/>")
    mail = MagicMock()
    with _Stack(_super(), _today(),
                _send_patches(dict(LEGACY_SENT), claim={"return_value": False}),
                patch("routers.cases.nar1_return_year.held_years", return_value=held),
                patch("routers.cases.nar1_prepare.build_form_xml", new=build),
                patch("routers.cases.email_service.send", new=mail),
                patch("routers.cases.log_event", new=AsyncMock())):
        response = client.post("/cases/c1/verification/send", headers=H, json=SEND)
    assert response.status_code == 409
    assert response.json()["detail"]["held_by"]["case_no"] == "NAR-2026-0001"
    build.assert_not_awaited()
    mail.assert_not_called()


def test_a_send_refused_for_a_missing_deadline_does_not_fix_the_year(client):
    """The year is stored only once the mail is about to go. A send refused
    on a cheap check must not leave "fixed by the send" in the trail."""
    claim = MagicMock(return_value=True)
    with _Stack(_super(), _today(),
                _send_patches(dict(LEGACY_SENT), claim={"new": claim}),
                patch("routers.cases.email_service.send"),
                patch("routers.cases.log_event", new=AsyncMock())):
        response = client.post("/cases/c1/verification/send", headers=H,
                               json={"to": ["client@example.com"]})
    assert response.status_code == 422
    claim.assert_not_called()


def test_a_legacy_cases_year_written_down_by_the_send_is_audited(client):
    log = AsyncMock()
    mail = MagicMock(return_value={"id": "m1", "to": ["client@example.com"],
                                   "intended_to": ["client@example.com"],
                                   "redirected": False})
    with _Stack(_super(), _today(),
                _send_patches(dict(LEGACY_SENT), claim={"return_value": True}),
                patch("routers.cases.email_service.send", new=mail),
                patch("routers.cases.log_event", new=log)):
        response = client.post("/cases/c1/verification/send", headers=H, json=SEND)
    assert response.status_code == 200, response.text
    fixed = [c.kwargs for c in log.call_args_list
             if c.kwargs.get("action_type") == "CASE_FIELD_UPDATED"]
    assert fixed and fixed[0]["new_value"] == "2026"
    assert fixed[0]["metadata"] == {"field": "ar_period_year",
                                    "fixed_by": "verification_send",
                                    "resolved_from": "sent"}


# ---------------------------------------------------------------------------
# Data Verification — the validated form, and what moved
# ---------------------------------------------------------------------------

VALIDATED = {"id": "f1", "form_code": "Nar1", "stage": "validated",
             "request_xml": "<request/>", "validated_xml": "<validated/>",
             "validated_at": "2026-10-10T03:00:00+00:00", "signed_at": None}

APPROVED_CASE = {**CASE, "ar_period_year": 2026,
                 "verification_sent_at": "2026-09-10T02:00:00+00:00",
                 "client_approved": True,
                 "client_response_at": "2026-09-11T02:00:00+00:00",
                 "verification_xml": "<approved/>"}

CHANGE = {"section": "Director — CHAN Tai Man", "field": "Address — building",
          "approved": "Old Tower", "validated": "New Tower", "note": None,
          "pages": [5]}


def _comparing(changes=(CHANGE,), highlight=frozenset({(4, "fill_11_P.5")})):
    return patch("routers.cases.nar1_form_compare.compare",
                 return_value=nar1_compare.Comparison(changes=list(changes),
                                                      highlight=highlight))


def test_the_comparison_lists_what_moved_since_the_client_approved(client):
    with _Stack(_super(), _case(case=APPROVED_CASE, filing=VALIDATED),
                _comparing()) as entered:
        response = client.get("/cases/c1/validation/comparison", headers=H)
    assert response.status_code == 200
    body = response.json()
    assert body["compared"] is True
    assert body["changes"] == [CHANGE]
    assert body["validated_at"] == VALIDATED["validated_at"]
    assert body["client_response_at"] == APPROVED_CASE["client_response_at"]
    compare = entered[-1]
    # The APPROVED bytes against CR's copy — never the request against itself.
    assert compare.call_args.args == ("<approved/>", "<validated/>")
    assert compare.call_args.kwargs["incorporated_on"] == "2019-10-09"


def test_a_case_with_no_mailed_copy_says_it_cannot_compare(client):
    """Never sent, or sent before migration 046 kept the bytes. "Cannot say" —
    which the screen must not render as "nothing changed"."""
    with _Stack(_super(), _case(case={**CASE, "ar_period_year": 2026},
                                filing=VALIDATED), _comparing()) as entered:
        body = client.get("/cases/c1/validation/comparison", headers=H).json()
    assert body["compared"] is False and body["changes"] == []
    entered[-1].assert_not_called()


@pytest.mark.parametrize("filing", [
    None,
    {**VALIDATED, "stage": "draft", "validated_xml": None},
    # A re-validation that failed keeps the OLD validated_xml on the row; it is
    # not the form CR accepted any more and must not be shown as if it were.
    {**VALIDATED, "stage": "validation_failed"},
])
def test_before_cr_has_validated_there_is_nothing_to_show(client, filing):
    with _Stack(_super(), _case(case=APPROVED_CASE, filing=filing)):
        for path in ("comparison", "preview"):
            response = client.get(f"/cases/c1/validation/{path}", headers=H)
            assert response.status_code == 409
            assert response.json()["detail"]["reason"] == "not_validated"


def test_the_validated_preview_is_crs_copy_with_the_changes_boxed(client):
    render = MagicMock(return_value=b"%PDF-1.4 validated")
    highlight = frozenset({(4, "fill_11_P.5")})
    with _Stack(_super(), _case(case=APPROVED_CASE, filing=VALIDATED),
                _comparing(highlight=highlight),
                patch("routers.cases.nar1_form_fill.render", new=render)):
        response = client.get("/cases/c1/validation/preview", headers=H)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert render.call_args.args[0] == "<validated/>"
    assert render.call_args.kwargs["highlight"] == highlight
    assert render.call_args.kwargs["incorporated_on"] == "2019-10-09"


def test_the_clean_copy_carries_no_highlight(client):
    render = MagicMock(return_value=b"%PDF-1.4")
    with _Stack(_super(), _case(case=APPROVED_CASE, filing=VALIDATED),
                _comparing(), patch("routers.cases.nar1_form_fill.render",
                                    new=render)) as entered:
        response = client.get("/cases/c1/validation/preview?highlight=false",
                              headers=H)
    assert response.status_code == 200
    assert render.call_args.kwargs["highlight"] is None
    entered[-2].assert_not_called()   # no comparison computed for a clean copy


def test_the_validated_preview_is_dated_the_day_cr_signing_succeeded(client):
    render = MagicMock(return_value=b"%PDF-1.4")
    signed = {**VALIDATED, "stage": "signed", "signed_at": "2026-10-12T02:00:00Z"}
    with _Stack(_super(), _case(case=APPROVED_CASE, filing=signed), _comparing(),
                patch("routers.cases.nar1_form_fill.render", new=render)):
        client.get("/cases/c1/validation/preview", headers=H)
    assert render.call_args.kwargs["signed_on"] == "2026-10-12T02:00:00Z"


@pytest.mark.parametrize("path", ["comparison", "preview"])
def test_the_validated_form_requires_nar1_read(client, path):
    with _Stack(_staff_without(), _case(case=APPROVED_CASE, filing=VALIDATED)):
        assert client.get(f"/cases/c1/validation/{path}", headers=H).status_code == 403


def test_an_unrenderable_validated_form_is_a_422_not_a_500(client):
    from services.nar1_form import fill
    with _Stack(_super(), _case(case=APPROVED_CASE, filing=VALIDATED),
                patch("routers.cases.nar1_form_compare.compare",
                      side_effect=fill.FormFillError("five share classes"))):
        response = client.get("/cases/c1/validation/comparison", headers=H)
    assert response.status_code == 422
    assert "five share classes" in response.text
