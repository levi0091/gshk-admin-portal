from etl.transform.checkpoint_a import transform_address, transform_person


def test_transform_address_maps_core_fields():
    vp_row = {
        "AddrNr": 4021,
        "Address": "Room 501, 5/F",
        "Address2": "ABC Tower",
        "Address3": "123 Nathan Road",
        "Address4": None,
        "Address5": None,
        "City": "Kowloon",
        "State": None,
        "Country": "HK",
        "PostalCode": None,
        "AddressLoc1": "香港九龍",
        "AddressLoc2": None,
        "CityLoc": "九龍",
    }
    result = transform_address(vp_row)
    assert result == {
        "vp_source_key": "4021",
        "line1": "Room 501, 5/F",
        "line2": "ABC Tower",
        "line3": "123 Nathan Road",
        "city": "Kowloon",
        "state_region": None,
        "country": "HK",
        "postal_code": None,
        "line1_zh": "香港九龍",
        "line2_zh": None,
        "city_zh": "九龍",
        "is_hk_address": True,
    }


def test_transform_address_collapses_overflow_lines_into_line3():
    vp_row = {
        "AddrNr": 1, "Address": "L1", "Address2": "L2", "Address3": "L3",
        "Address4": "L4", "Address5": "L5", "City": None, "State": None,
        "Country": None, "PostalCode": None, "AddressLoc1": None,
        "AddressLoc2": None, "CityLoc": None,
    }
    result = transform_address(vp_row)
    assert result["line3"] == "L3, L4, L5"


def test_transform_address_non_hk_country_is_not_hk_address():
    vp_row = {
        "AddrNr": 2, "Address": None, "Address2": None, "Address3": None,
        "Address4": None, "Address5": None, "City": None, "State": None,
        "Country": "SG", "PostalCode": None, "AddressLoc1": None,
        "AddressLoc2": None, "CityLoc": None,
    }
    result = transform_address(vp_row)
    assert result["is_hk_address"] is False


def test_transform_person_maps_core_fields():
    vp_row = {
        "RefCode": "LEUNGP",
        "Name": "LEUNG Siu Ming",
        "ChnsName": "梁小明",
        "GivenNames": "Siu Ming",
        "FormerName": None,
        "FormerGivenNames": None,
        "Email": "siuming@example.com",
        "BirthDate": None,
        "Gender": "M",
        "Nationality": "Chinese",
        "NationalityCode": "CHN",
        "Occupation": "Director",
        "PlaceBirth": "Hong Kong",
        "MaritalStatus": "M",
        "DateDeath": None,
    }
    result = transform_person(vp_row)
    assert result["vp_source_key"] == "LEUNGP"
    assert result["full_name"] == "LEUNG Siu Ming"
    assert result["full_name_zh"] == "梁小明"
    assert result["given_names"] == "Siu Ming"
    assert result["email"] == "siuming@example.com"
    assert result["nationality"] == "Chinese"
    assert result["residential_address_id"] is None


def test_transform_person_falls_back_to_search_name_when_name_blank():
    vp_row = {
        "RefCode": "X1", "Name": None, "ChnsName": None, "GivenNames": None,
        "FormerName": None, "FormerGivenNames": None, "Email": None,
        "BirthDate": None, "Gender": None, "Nationality": None,
        "NationalityCode": None, "Occupation": None, "PlaceBirth": None,
        "MaritalStatus": None, "DateDeath": None, "SearchName": "FALLBACK NAME",
    }
    result = transform_person(vp_row)
    assert result["full_name"] == "FALLBACK NAME"


def test_transform_person_merges_aliases_into_former_name():
    vp_row = {
        "RefCode": "X2", "Name": "Jane Doe", "ChnsName": None,
        "GivenNames": "Jane", "FormerName": None, "FormerGivenNames": None,
        "Email": None, "BirthDate": None, "Gender": None, "Nationality": None,
        "NationalityCode": None, "Occupation": None, "PlaceBirth": None,
        "MaritalStatus": None, "DateDeath": None, "Aliases": "Jane Smith",
    }
    result = transform_person(vp_row)
    assert result["former_name"] == "Jane Smith"
