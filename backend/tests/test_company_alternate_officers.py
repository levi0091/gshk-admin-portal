"""The company profile's officers accept an alternate director (PBI-70 revived,
Jacqueline 2026-11-04): a role `alternate_director` with the director it acts for.

`_validate_alternate` is the same rule `cases._check_alternate_to` applies on an
ND2A appointment, so the profile and the form cannot disagree.
"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app
from routers import companies
from tests.officer_changes.fakes import FakeSupabase
from tests.test_companies_router import H, SUPER_ADMIN

client = TestClient(app)


@pytest.fixture
def sb():
    return FakeSupabase({"entity_officers": [
        {"id": "O1", "entity_id": "E1", "person_id": "P1", "role": "director",
         "is_current": True},
        {"id": "O2", "entity_id": "E1", "person_id": "P2", "role": "company_secretary",
         "is_current": True},
        {"id": "OX", "entity_id": "OTHER", "person_id": "P3", "role": "director",
         "is_current": True},
        {"id": "OF", "entity_id": "E1", "person_id": "P4", "role": "director",
         "is_current": False},
    ]})


def _create(sb, **over):
    out = {"entity_id": "E1", "person_id": "P9", "role": "alternate_director",
           "alternate_to_officer_id": "O1", **over}
    companies._validate_alternate(sb, out, None)
    return out


def test_an_alternate_with_a_current_director_of_this_company_is_accepted(sb):
    assert _create(sb)["alternate_to_officer_id"] == "O1"


@pytest.mark.parametrize("link, message", [
    (None, "choose which one"),
    ("O2", "current director of this company"),    # a secretary
    ("OX", "current director of this company"),    # another company's director
    ("OF", "current director of this company"),    # a director who has left
    ("NOPE", "current director of this company"),
])
def test_the_director_must_be_chosen_and_must_be_current_here(sb, link, message):
    with pytest.raises(HTTPException) as caught:
        _create(sb, alternate_to_officer_id=link)
    assert caught.value.status_code == 422 and message in caught.value.detail


def test_a_director_cannot_be_their_own_alternate(sb):
    with pytest.raises(HTTPException) as caught:
        _create(sb, person_id="P1")
    assert "own alternate" in caught.value.detail


def test_a_stray_link_on_a_director_is_dropped(sb):
    out = {"entity_id": "E1", "person_id": "P9", "role": "director",
           "alternate_to_officer_id": "O1"}
    companies._validate_alternate(sb, out, None)
    assert out["alternate_to_officer_id"] is None


def test_changing_an_alternate_to_a_director_clears_the_link(sb):
    held = {"id": "OA", "entity_id": "E1", "person_id": "P9", "role": "alternate_director",
            "alternate_to_officer_id": "O1"}
    out = {"role": "director"}
    companies._validate_alternate(sb, out, held)
    assert out["alternate_to_officer_id"] is None


def test_an_edit_that_touches_neither_field_is_grandfathered(sb):
    # The director has since left; renaming the position must still work.
    held = {"id": "OA", "entity_id": "E1", "person_id": "P9", "role": "alternate_director",
            "alternate_to_officer_id": "OF"}
    out = {"position": "Chair's alternate"}
    companies._validate_alternate(sb, out, held)
    assert out == {"position": "Chair's alternate"}


def test_repointing_an_existing_alternate_is_validated(sb):
    held = {"id": "OA", "entity_id": "E1", "person_id": "P9", "role": "alternate_director",
            "alternate_to_officer_id": "O1"}
    with pytest.raises(HTTPException):
        companies._validate_alternate(sb, {"alternate_to_officer_id": "OX"}, held)


def test_the_endpoint_refuses_an_alternate_with_no_director():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase"), \
         patch("routers.companies.log_event", new=AsyncMock()) as audit:
        resp = client.post("/companies/e1/officers",
                           json={"person_id": "p1", "role": "alternate_director"}, headers=H)
        assert resp.status_code == 422
        assert "alternate to a director" in resp.json()["detail"]
        audit.assert_not_awaited()


def test_the_link_is_a_writable_officer_field():
    assert "alternate_to_officer_id" in companies._RELATIONS["officers"]["fields"]
    assert "alternate_to_officer_id" not in companies._RELATIONS["secretaries"]["fields"]
