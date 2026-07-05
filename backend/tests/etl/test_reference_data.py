from etl.reference_data import decode_id_type, decode_officer_role, AMBIGUOUS_OFFICER_CODES


def test_decode_id_type_known_codes():
    assert decode_id_type("PSP") == "passport"
    assert decode_id_type("IDC") == "hkid"
    assert decode_id_type("PRC") == "china_id"


def test_decode_id_type_unknown_or_null_falls_back_to_other():
    assert decode_id_type("BRN") == "other"
    assert decode_id_type(None) == "other"
    assert decode_id_type("") == "other"


def test_decode_officer_role_known_codes():
    assert decode_officer_role("DIR") == "director"
    assert decode_officer_role("SEC") == "company_secretary"


def test_decode_officer_role_ambiguous_codes_are_flagged():
    assert decode_officer_role("RPD") == "reserve_director"
    assert "RPD" in AMBIGUOUS_OFFICER_CODES
    assert "DIR" not in AMBIGUOUS_OFFICER_CODES


def test_decode_officer_role_unknown_defaults_to_director():
    assert decode_officer_role("ZZZ") == "director"
