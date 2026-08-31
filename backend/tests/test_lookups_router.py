"""Reference lookups + document-type scoping (PBI-41)."""
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from routers import lookups

client = TestClient(app)

SUPER_ADMIN = {"id": "a1", "display_name": "Levi", "role_name": "super_admin", "role_id": "r-sa"}
COMPANIES_ONLY = {"id": "u2", "display_name": "Ops", "role_name": "ops", "role_id": "r-ops"}
NO_ACCESS = {"id": "u3", "display_name": "Guest", "role_name": "guest", "role_id": "r-g"}
H = {"Authorization": "Bearer tok"}

ROWS = [
    {"category": "gender", "code": "M", "label": "Male"},
    {"category": "gender", "code": "F", "label": "Female"},
    {"category": "country", "code": "HK", "label": "Hong Kong"},
]


def _lookup_rows(mock_sb):
    (mock_sb.return_value.table.return_value.select.return_value
     .eq.return_value.order.return_value.order.return_value
     .limit.return_value.execute.return_value.data) = ROWS


def setup_function():
    lookups.clear_cache()


def test_lookups_grouped_by_category():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.lookups.get_supabase") as msb:
        _lookup_rows(msb)
        resp = client.get("/lookups", headers=H)
    assert resp.status_code == 200
    body = resp.json()
    # The Viewpoint-sourced categories, exactly as seeded.
    assert body["gender"] == [{"code": "M", "label": "Male"}, {"code": "F", "label": "Female"}]
    assert body["country"] == [{"code": "HK", "label": "Hong Kong"}]
    # cr_district rides along so the address form costs no extra round trip;
    # its contents are asserted below.
    assert "cr_district" in body


def test_cr_district_comes_from_crs_vocabulary_not_the_database():
    """CR owns this list, not Viewpoint. Serving it from `lookup_values` would
    make a second copy that can drift from the one `nar1_mapper` validates
    against — so it must still be served when the lookup table is empty."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.lookups.get_supabase") as msb:
        (msb.return_value.table.return_value.select.return_value
         .eq.return_value.order.return_value.order.return_value
         .limit.return_value.execute.return_value.data) = []
        resp = client.get("/lookups/cr_district", headers=H)
    assert resp.status_code == 200
    codes = {v["code"] for v in resp.json()}
    assert "CENTRAL" in codes
    assert "WANCHAI" in codes


def test_every_cr_district_value_is_one_the_nar1_mapper_accepts():
    """The dropdown must not be able to offer a value CR would refuse. Sending
    the district NAME "WAN CHAI" was rejected live on 2026-08-27 while the code
    "WANCHAI" passed, so every option has to round-trip through the same
    resolver the mapper uses."""
    from services.tpsi.forms.cr_vocabularies import resolve_district

    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.lookups.get_supabase") as msb:
        _lookup_rows(msb)
        resp = client.get("/lookups/cr_district", headers=H)
    values = resp.json()
    assert len(values) == 125
    for v in values:
        assert resolve_district(v["code"]) == v["code"]


def test_single_category():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.lookups.get_supabase") as msb:
        _lookup_rows(msb)
        resp = client.get("/lookups/gender", headers=H)
    assert resp.status_code == 200
    assert resp.json() == [{"code": "M", "label": "Male"}, {"code": "F", "label": "Female"}]


def test_unknown_category_404s():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.lookups.get_supabase") as msb:
        _lookup_rows(msb)
        resp = client.get("/lookups/pets", headers=H)
    assert resp.status_code == 404


def test_unauthenticated_is_401():
    assert client.get("/lookups").status_code == 403  # no bearer -> HTTPBearer rejects


def test_read_on_either_module_is_enough():
    """The vocabularies serve both the company and the person form, so gating
    them on one module would lock out a role that only holds the other."""
    with patch("middleware.auth._resolve_user", return_value=COMPANIES_ONLY), \
         patch("middleware.auth._permissions_for", side_effect=
               lambda u, m: {"read"} if m == "persons" else set()), \
         patch("routers.lookups.get_supabase") as msb:
        _lookup_rows(msb)
        resp = client.get("/lookups", headers=H)
    assert resp.status_code == 200


def test_no_read_on_either_module_is_403():
    with patch("middleware.auth._resolve_user", return_value=NO_ACCESS), \
         patch("middleware.auth._permissions_for", return_value=set()):
        resp = client.get("/lookups", headers=H)
    assert resp.status_code == 403


# --- document types scoped to their owner ----------------------------------

def test_document_types_filtered_to_person():
    """A Certificate of Incorporation is not a person's document; offering it on
    a person profile only invites a miscategorised upload."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.documents.get_supabase") as msb:
        chain = msb.return_value.table.return_value.select.return_value.eq.return_value
        chain.in_.return_value.order.return_value.execute.return_value.data = [
            {"code": "id_scan", "label": "Identity Document Scan", "applies_to": "person"}]
        resp = client.get("/documents/types?owner_type=person", headers=H)

    assert resp.status_code == 200
    assert [t["code"] for t in resp.json()] == ["id_scan"]
    # "both" types must still be offered — a proof of address belongs to either
    assert chain.in_.call_args[0] == ("applies_to", ["person", "both"])


def test_document_types_unfiltered_when_no_owner_given():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.documents.get_supabase") as msb:
        chain = msb.return_value.table.return_value.select.return_value.eq.return_value
        chain.order.return_value.execute.return_value.data = []
        resp = client.get("/documents/types", headers=H)

    assert resp.status_code == 200
    chain.in_.assert_not_called()


def test_document_types_rejects_a_bogus_owner_type():
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN):
        resp = client.get("/documents/types?owner_type=alien", headers=H)
    assert resp.status_code == 400
