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


def test_cr_business_nature_is_served_with_its_description():
    """Picking a code has to fill the description in, so the label carries it.
    Viewpoint holds no business nature at all, so this dropdown is the only
    thing standing between an operator and a free-text code."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.lookups.get_supabase") as msb:
        _lookup_rows(msb)
        resp = client.get("/lookups/cr_business_nature", headers=H)

    assert resp.status_code == 200
    values = resp.json()
    assert len(values) == 88
    head_offices = next(v for v in values if v["code"] == "070")
    assert head_offices["label"].startswith("Activities of head offices")


def test_cr_currency_offers_crs_codes_and_never_the_iso_ones():
    """`lookup_values` carries 162 ISO currency codes from Viewpoint; CR takes
    54 of its own. A share class denominated in renminbi must be offered RMB,
    because CNY is a code CR has never heard of."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.lookups.get_supabase") as msb:
        _lookup_rows(msb)
        resp = client.get("/lookups/cr_currency", headers=H)

    assert resp.status_code == 200
    codes = {v["code"] for v in resp.json()}
    assert len(codes) == 54
    assert {"RMB", "NTD", "WON", "NIS"} <= codes
    assert not ({"CNY", "TWD", "KRW", "ILS"} & codes)


def test_cr_company_type_offers_exactly_crs_three():
    """PRD §7.4. CR's worksheet documents only "P - Private, N - Public"; `G`
    comes from CR's shipped NNC1G examples, and shipped XML outranks the
    worksheet. Viewpoint has no mapping, so this list is the whole vocabulary
    and a fourth value would be one an operator invented."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN),          patch("routers.lookups.get_supabase") as msb:
        _lookup_rows(msb)
        resp = client.get("/lookups/cr_company_type", headers=H)

    assert resp.status_code == 200
    values = resp.json()
    assert [v["code"] for v in values] == ["P", "N", "G"]
    assert values[0]["label"] == "Private"


def test_cr_record_type_lists_the_registers_nar1_s16_asks_about():
    """Thirteen registers -- Viewpoint's address types minus the seals and the
    company's own addresses, which are not records."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN),          patch("routers.lookups.get_supabase") as msb:
        _lookup_rows(msb)
        resp = client.get("/lookups/cr_record_type", headers=H)

    assert resp.status_code == 200
    values = resp.json()
    assert len(values) == 13
    assert {"SS", "ST", "SU", "SR", "SB"}.isdisjoint({v["code"] for v in values})
    assert next(v for v in values if v["code"] == "SM")["label"] == "Register of Members"


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


def test_cr_country_is_crs_own_list_keyed_by_what_we_store():
    """The address Country dropdown fed on `lookup_values.country` -- 270
    Viewpoint rows, 20 of which CR has no code for at all, three of them
    labelled only in Chinese ('HK-CH', 'MO-CH', 'TW-CH').

    An operator filing a Hong Kong company picked the Chinese Hong Kong, it
    stored 'HK-CH', and the return died at Data Verification with "no CR
    region code is known for country 'HK-CH'". CR's own sheet is the only
    list allowed to feed a field CR validates.

    Keyed by ISO alpha-2 because that is what `addresses.country` holds in
    all 141 of DEV's distinct non-blank values -- serving CR's three-letter
    codes instead would orphan every one of the 8,035 rows.
    """
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.lookups.get_supabase") as msb:
        _lookup_rows(msb)
        resp = client.get("/lookups/cr_country", headers=H)

    assert resp.status_code == 200
    values = resp.json()
    assert len(values) == 250
    codes = {v["code"] for v in values}
    assert {"HK", "VN", "AE", "NL", "GB"} <= codes          # what DEV stores
    assert not (codes & {"HK-CH", "MO-CH", "TW-CH", "GB-ENG", "US-DE", "ZR"})


def test_not_one_country_option_is_labelled_in_chinese():
    """Levi, 2026-09-03: "when i select the chinese words from the dropdown ..
    it is not registering with CR portal".

    Stronger than naming the three known codes above, because the defect was
    never about those three strings — it was that a Chinese-labelled option
    existed AT ALL in a list feeding a form CR reads in English. The NAR1 is
    filed with language "E"; an option nobody can file is a trap whatever it
    is keyed by.
    """
    import re

    cjk = re.compile(r"[　-鿿＀-￯]")
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.lookups.get_supabase") as msb:
        _lookup_rows(msb)
        resp = client.get("/lookups/cr_country", headers=H)

    offenders = [v for v in resp.json()
                 if cjk.search(v["label"]) or cjk.search(v["code"])]
    assert not offenders, f"Chinese-labelled country options offered: {offenders}"
    # And the English ones an operator reaches for instead are all there.
    labels = {v["code"]: v["label"] for v in resp.json()}
    assert labels["HK"] == "Hong Kong"
    assert labels["MO"] == "Macau"
    assert labels["TW"] == "Taiwan"


def test_every_cr_country_option_resolves_to_a_code_cr_accepts():
    """The dropdown must not be able to offer a value the mapper refuses --
    that is the entire defect. Asserted through the SAME resolver
    `nar1_mapper` calls, so the two cannot drift."""
    from services.tpsi.forms.cr_vocabularies import resolve_country

    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.lookups.get_supabase") as msb:
        _lookup_rows(msb)
        values = client.get("/lookups/cr_country", headers=H).json()

    assert all(resolve_country(v["code"]) is not None for v in values)


def test_to_alpha2_normalises_every_spelling_onto_a_dropdown_key():
    """251 `incorporation_place` rows held the literal "Hong Kong", which
    files perfectly well and matches no dropdown option — so the profile
    rendered "Hong Kong (not in list)". Normalising is what makes the stored
    data and the vocabulary the same set."""
    from services.tpsi.forms.cr_vocabularies import to_alpha2

    assert to_alpha2("Hong Kong") == "HK"
    assert to_alpha2("HKG") == "HK"
    assert to_alpha2("hk") == "HK"
    assert to_alpha2("CHN") == "CN"
    assert to_alpha2("France") == "FR"
    # Guernsey is CR's own GBR1, never GBR.
    assert to_alpha2("GBR1") == "GG"
    # None means CR has no code — distinguishable from "already normalised".
    assert to_alpha2("HK-CH") is None
    assert to_alpha2("") is None


def test_cr_country_labels_are_english_and_readable():
    """The complaint was that the list was not all English. CR's sheet is
    UPPERCASE; the label is title-cased for reading and the CODE is what gets
    stored, so nothing CR validates depends on the casing."""
    with patch("middleware.auth._resolve_user", return_value=SUPER_ADMIN), \
         patch("routers.lookups.get_supabase") as msb:
        _lookup_rows(msb)
        values = client.get("/lookups/cr_country", headers=H).json()

    by_code = {v["code"]: v["label"] for v in values}
    assert by_code["HK"] == "Hong Kong"
    assert by_code["US"] == "United States"
    # An apostrophe must not become "People'S" -- naive .title() does that.
    assert "'S" not in by_code["LA"]
    assert all(ch.isascii() for label in by_code.values() for ch in label)
    # Sorted by label, because that is the order someone scans.
    assert [v["label"] for v in values] == sorted(v["label"] for v in values)
