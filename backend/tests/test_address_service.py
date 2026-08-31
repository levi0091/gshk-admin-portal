"""Copy-on-write address writes (PBI address editing).

The service's job is to refuse exactly what `nar1_mapper._address` would later
refuse, and to never mutate an address row that more than one record points at.
"""
import pytest

from services import address_service as svc


def _payload(**overrides):
    p = {
        "line1": "Suite C, Level 7",
        "line2": "World Trust Tower",
        "line3": "50 Stanley Street",
        "city": "CENTRAL",
        "state_region": None,
        "postal_code": None,
        "country": "HK",
    }
    p.update(overrides)
    return p


# ---- validation: the same limits CR enforces --------------------------------

def test_a_line_over_sixty_is_refused_and_the_field_is_named():
    with pytest.raises(svc.AddressError) as exc:
        svc.validate(_payload(line2="x" * 61))
    assert "line2" in str(exc.value)


def test_a_line_of_exactly_sixty_is_accepted():
    """CR's cap is inclusive. Refusing 60 would reject addresses it accepts."""
    svc.validate(_payload(line1="x" * 60))


def test_every_line_is_checked_not_just_the_first():
    with pytest.raises(svc.AddressError) as exc:
        svc.validate(_payload(line3="y" * 99))
    assert "line3" in str(exc.value)


def test_a_district_crs_vocabulary_does_not_know_at_all_is_refused():
    """CR refused "WAN CHAI" live on 2026-08-27 with "Please input valid
    District". Catching an unknown district here saves a round trip and names
    the value."""
    with pytest.raises(svc.AddressError) as exc:
        svc.validate(_payload(city="Atlantis"))
    assert "Atlantis" in str(exc.value)


def test_a_real_hong_kong_district_code_is_accepted():
    svc.validate(_payload(city="WANCHAI"))


def test_a_district_written_the_human_way_is_normalised_to_crs_code():
    """CR's code is the name with its spaces removed, so "Wan Chai" IS
    resolvable — refusing it would make the operator guess CR's spelling.
    Store what CR wants, accept what a person types."""
    assert svc.normalise(_payload(city="Wan Chai"))["city"] == "WANCHAI"


def test_normalisation_leaves_a_non_hong_kong_district_alone():
    """Outside HK the district is free text and there is no code to resolve
    to — uppercasing "Nicosia" would corrupt it."""
    assert svc.normalise(_payload(city="Nicosia", country="CY"))["city"] == "Nicosia"


def test_free_text_district_is_accepted_outside_hong_kong():
    """Only HK treats District as a controlled code. Elsewhere it really is
    city/state/postcode free text, and validating it against CR's HK list
    would reject every overseas director."""
    svc.validate(_payload(city="Nicosia", country="CY"))


def test_a_blank_country_is_refused():
    """The mapper already treats a missing country as a problem; refusing it
    at the door means the operator finds out now, not at validation."""
    with pytest.raises(svc.AddressError) as exc:
        svc.validate(_payload(country=""))
    assert "country" in str(exc.value).lower()


# ---- the copy-on-write decision ---------------------------------------------

def test_an_address_only_this_record_uses_is_edited_in_place():
    assert svc.plan(reference_count=1) == "update"


def test_a_shared_address_is_copied_rather_than_rewritten():
    """4,446 companies share GSHK's registered office. Editing that row in
    place would change the registered office of every one of them."""
    assert svc.plan(reference_count=4446) == "copy"


def test_a_record_with_no_address_yet_gets_a_new_row():
    assert svc.plan(reference_count=0) == "copy"
