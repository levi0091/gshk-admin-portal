"""Editing share capital — the thing the Share Capital card could not do.

Block 5 shipped the card read-only, complete with a "1 to fix" badge on a
company whose Total Amount was missing. There was no way to fix it: no edit
control, and no endpoint behind one. 219 client companies have no share class
at all and could not create one either, which is exactly what stops them
filing.

Everything here is CR's section 11, so every value is validated against CR's
own vocabulary rather than merely stored.
"""
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

SUPER_ADMIN = {"id": "admin-1", "display_name": "Levi Z.",
               "role_name": "super_admin", "role_id": "role-sa"}
H = {"Authorization": "Bearer tok"}

EXISTING = {
    "id": "sc1", "entity_id": "e1", "class_name": "Ordinary",
    "currency": "HKD", "total_issued": 100, "issued_amount": None,
    "total_paid": 100,
}


def _sb(msb, current=EXISTING, company={"id": "e1", "company_name": "Acme"}):
    sb = msb.return_value
    sel = sb.table.return_value.select.return_value
    sel.eq.return_value.single.return_value.execute.return_value.data = company
    sel.eq.return_value.eq.return_value.single.return_value.execute.return_value.data = current
    (sb.table.return_value.update.return_value.eq.return_value
     .execute.return_value.data) = [{**(current or {}), "id": "sc1"}]
    sb.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "sc9", "entity_id": "e1"}]
    return sb


# --- editing -------------------------------------------------------------

def test_the_missing_total_amount_can_be_filled_in():
    """The literal case in the screenshot: Total Amount is blank, the card
    says one thing to fix, and until now nothing could fix it."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_events", new=AsyncMock()):
        sb = _sb(msb)
        resp = client.patch("/companies/e1/share-classes/sc1", headers=H,
                            json={"issued_amount": "100"})

    assert resp.status_code == 200
    assert sb.table.return_value.update.call_args.args[0]["issued_amount"] == "100"


def test_a_currency_cr_does_not_accept_is_refused():
    """CR's list is 54 codes and is NOT ISO 4217: renminbi is RMB. A share
    class stored as CNY is refused by CR after the fee is taken."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb:
        _sb(msb)
        resp = client.patch("/companies/e1/share-classes/sc1", headers=H,
                            json={"currency": "CNY"})

    assert resp.status_code == 422
    assert "RMB" in resp.text


def test_crs_own_renminbi_code_is_accepted():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_events", new=AsyncMock()):
        _sb(msb)
        resp = client.patch("/companies/e1/share-classes/sc1", headers=H,
                            json={"currency": "RMB"})

    assert resp.status_code == 200


def test_a_figure_longer_than_cr_accepts_is_refused():
    """Capped in CHARACTERS, not magnitude — and at the STRICTER of the two
    forms. NAR1 gives `issuedCapital` 16, NNC1 gives `issuedShareCapital` 14,
    and the same company may need both; `form_contract` takes `min(lengths)`
    across forms for exactly this reason. 14 characters is a hundred trillion
    dollars, so nothing real is being turned away."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb:
        _sb(msb)
        resp = client.patch("/companies/e1/share-classes/sc1", headers=H,
                            json={"issued_amount": "1" * 15})

    assert resp.status_code == 422
    assert "14" in resp.text


def test_a_figure_that_is_not_a_number_is_refused():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb:
        _sb(msb)
        resp = client.patch("/companies/e1/share-classes/sc1", headers=H,
                            json={"total_issued": "one hundred"})

    assert resp.status_code == 422


def test_a_negative_figure_is_refused():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb:
        _sb(msb)
        resp = client.patch("/companies/e1/share-classes/sc1", headers=H,
                            json={"total_issued": "-5"})

    assert resp.status_code == 422


def test_zero_paid_up_is_allowed_because_it_is_an_answer():
    """Nil paid up is a real state of a real company, and `if not value`
    would have called it missing."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_events", new=AsyncMock()):
        _sb(msb)
        resp = client.patch("/companies/e1/share-classes/sc1", headers=H,
                            json={"total_paid": "0"})

    assert resp.status_code == 200


def test_a_class_name_longer_than_cr_accepts_is_refused():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb:
        _sb(msb)
        resp = client.patch("/companies/e1/share-classes/sc1", headers=H,
                            json={"class_name": "O" * 101})

    assert resp.status_code == 422


def test_editing_a_share_class_is_audited_field_by_field():
    logged = AsyncMock()
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_events", new=logged):
        _sb(msb)
        client.patch("/companies/e1/share-classes/sc1", headers=H,
                     json={"issued_amount": "100", "class_name": "Ordinary"})

    entries = logged.await_args.args[0]
    # class_name is unchanged, so only the one real change is recorded.
    assert [e["new_value"] for e in entries] == ["100"]
    assert entries[0]["action_type"] == "CASE_FIELD_UPDATED"


def test_a_share_class_of_another_company_is_not_reachable():
    """The id is in the path; without scoping to the company, a share class
    belonging to someone else could be edited through this route."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb:
        _sb(msb, current=None)
        resp = client.patch("/companies/e1/share-classes/sc1", headers=H,
                            json={"issued_amount": "100"})

    assert resp.status_code == 404


# --- creating ------------------------------------------------------------

def test_a_company_with_no_share_capital_can_be_given_some():
    """219 client companies have no share class at all, which is what stops
    them filing. Editing alone would never unblock one of them."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb, \
         patch("routers.companies.log_event", new=AsyncMock()):
        sb = _sb(msb)
        resp = client.post("/companies/e1/share-classes", headers=H, json={
            "class_name": "Ordinary", "currency": "HKD",
            "total_issued": "100", "issued_amount": "100", "total_paid": "100"})

    assert resp.status_code == 201
    written = sb.table.return_value.insert.call_args.args[0]
    assert written["entity_id"] == "e1"
    assert written["class_name"] == "Ordinary"


def test_a_new_share_class_is_validated_the_same_way():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb:
        _sb(msb)
        resp = client.post("/companies/e1/share-classes", headers=H, json={
            "class_name": "Ordinary", "currency": "CNY",
            "total_issued": "100", "issued_amount": "100", "total_paid": "100"})

    assert resp.status_code == 422


def test_a_new_share_class_must_carry_everything_cr_requires():
    """Creating a half-filled class would just move the block, not clear it."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.companies.get_supabase") as msb:
        _sb(msb)
        resp = client.post("/companies/e1/share-classes", headers=H, json={
            "class_name": "Ordinary", "currency": "HKD"})

    assert resp.status_code == 422


# --- permissions ---------------------------------------------------------

def test_editing_share_capital_needs_companies_write():
    reader = {**SUPER_ADMIN, "role_name": "case_manager", "role_id": "role-cm"}
    with patch("middleware.auth._resolve_user", return_value=reader), \
         patch("middleware.auth.get_supabase") as msb:
        (msb.return_value.table.return_value.select.return_value.eq.return_value
         .eq.return_value.execute.return_value.data) = []
        resp = client.patch("/companies/e1/share-classes/sc1", headers=H,
                            json={"issued_amount": "100"})

    assert resp.status_code == 403
