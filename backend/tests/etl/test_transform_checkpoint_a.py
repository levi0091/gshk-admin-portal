from etl.transform.checkpoint_a import transform_address, transform_entity, transform_person, transform_identity_document, transform_entity_officer
from etl.reconciliation import ReconciliationReport


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


def _entity_row(**overrides):
    base = {
        "EntCode": "FACTORALIM",
        "CompName": "Xactoro Limited",
        "Name": "Xactoro Limited",
        "IncorpNr": "1234567",
        "IncorpDate": "2020-01-15",
        "IncorpPlace": "HK",
        "Status": "0",
        "DateLastAnRe": None, "DateNextAnRe": None, "DateDueAnRe": None,
        "DateNextAGM": None,
        "MA_DirMin": 1, "MA_DirMax": 10, "MA_AgmWaived": False,
        "PrevEntName": None, "DateNameChanged": None,
        "Note": "Internal note", "AccountNote": None,
    }
    base.update(overrides)
    return base


def test_transform_entity_defaults_to_live_status():
    result = transform_entity(_entity_row(), bus_name=None)
    assert result["status"] == "live"
    assert result["vp_source_key"] == "FACTORALIM"
    assert result["company_name"] == "Xactoro Limited"
    assert result["cr_number"] == "1234567"


def test_transform_entity_ceased_when_status_code_c():
    result = transform_entity(_entity_row(Status="C"), bus_name=None)
    assert result["status"] == "ceased"


def test_transform_entity_ceased_when_bus_name_has_cessation_date():
    bus_name = {"BusRegNr": "12345678", "ChineseBusName": None, "DateCessation": "2023-05-01"}
    result = transform_entity(_entity_row(), bus_name=bus_name)
    assert result["status"] == "ceased"


def test_transform_entity_takes_br_number_from_bus_name():
    bus_name = {"BusRegNr": "87654321", "ChineseBusName": "測試", "DateCessation": None}
    result = transform_entity(_entity_row(), bus_name=bus_name)
    assert result["br_number"] == "87654321"
    assert result["company_name_zh"] == "測試"


def test_transform_entity_assigned_to_is_always_none():
    result = transform_entity(_entity_row(), bus_name=None)
    assert result["assigned_to"] is None


def test_transform_identity_document_resolves_person_id():
    person_ids = {"LEUNGP": "11111111-1111-1111-1111-111111111111"}
    vp_row = {
        "RefCode": "LEUNGP", "SeqNr": 1, "IdType": "PSP", "IdCode": "K1234567",
        "Country": "HK", "FromDate": "2018-01-01", "ToDate": "2028-01-01",
    }
    result = transform_identity_document(vp_row, person_ids)
    assert result is not None
    assert result["person_id"] == "11111111-1111-1111-1111-111111111111"
    assert result["id_type"] == "passport"
    assert result["id_number"] == "K1234567"
    assert result["vp_source_key"] == "LEUNGP:1"


def test_transform_identity_document_returns_none_when_person_missing():
    vp_row = {
        "RefCode": "GHOST", "SeqNr": 1, "IdType": "PSP", "IdCode": "X1",
        "Country": None, "FromDate": None, "ToDate": None,
    }
    result = transform_identity_document(vp_row, {})
    assert result is None


def test_transform_entity_officer_maps_director():
    entity_ids = {"FACTORALIM": "e-uuid-1"}
    person_ids = {"LEUNGP": "p-uuid-1"}
    report = ReconciliationReport()
    vp_row = {
        "EntCode": "FACTORALIM", "SeqNr": 1, "AddrCode": "LEUNGP",
        "OfficerType": "DIR", "Position": None,
        "DateAppoint": "2020-01-15", "DateResign": None, "ReasonResign": None,
    }
    result = transform_entity_officer(vp_row, entity_ids, person_ids, report)
    assert result["entity_id"] == "e-uuid-1"
    assert result["person_id"] == "p-uuid-1"
    assert result["role"] == "director"
    assert result["is_current"] is True
    assert report.has_errors() is False


def test_transform_entity_officer_resigned_is_not_current():
    entity_ids = {"E1": "e-uuid"}
    person_ids = {"P1": "p-uuid"}
    report = ReconciliationReport()
    vp_row = {
        "EntCode": "E1", "SeqNr": 2, "AddrCode": "P1", "OfficerType": "DIR",
        "Position": None, "DateAppoint": "2019-01-01",
        "DateResign": "2021-01-01", "ReasonResign": "R",
    }
    result = transform_entity_officer(vp_row, entity_ids, person_ids, report)
    assert result["is_current"] is False
    assert result["resigned_date"] == "2021-01-01"


def test_transform_entity_officer_ambiguous_role_is_logged():
    entity_ids = {"E1": "e-uuid"}
    person_ids = {"P1": "p-uuid"}
    report = ReconciliationReport()
    vp_row = {
        "EntCode": "E1", "SeqNr": 3, "AddrCode": "P1", "OfficerType": "RPD",
        "Position": None, "DateAppoint": None, "DateResign": None, "ReasonResign": None,
    }
    transform_entity_officer(vp_row, entity_ids, person_ids, report)
    assert report.has_errors() is True
    assert "RPD" in report.errors[0]["message"]


def test_transform_entity_officer_missing_entity_returns_none_and_logs():
    report = ReconciliationReport()
    vp_row = {
        "EntCode": "GHOST", "SeqNr": 1, "AddrCode": "P1", "OfficerType": "DIR",
        "Position": None, "DateAppoint": None, "DateResign": None, "ReasonResign": None,
    }
    result = transform_entity_officer(vp_row, {}, {"P1": "p-uuid"}, report)
    assert result is None
    assert report.has_errors() is True


def test_transform_entity_officer_missing_person_returns_dict_with_none_person_id():
    entity_ids = {"E1": "e-uuid"}
    report = ReconciliationReport()
    vp_row = {
        "EntCode": "E1", "SeqNr": 4, "AddrCode": "GHOSTPERSON", "OfficerType": "DIR",
        "Position": None, "DateAppoint": None, "DateResign": None, "ReasonResign": None,
    }
    result = transform_entity_officer(vp_row, entity_ids, {}, report)
    assert result is not None
    assert result["entity_id"] == "e-uuid"
    assert result["person_id"] is None
    assert result["role"] == "director"
    assert report.has_errors() is True
    assert "GHOSTPERSON" in report.errors[0]["message"]


def test_transform_company_secretary_from_entity_officer_row():
    from etl.transform.checkpoint_a import transform_company_secretary

    entity_officer_row = {
        "vp_source_key": "E1:2",
        "entity_id": "e-uuid",
        "person_id": "p-uuid",
        "role": "company_secretary",
        "appointed_date": "2020-01-01",
        "is_current": True,
    }
    result = transform_company_secretary(entity_officer_row)
    assert result == {
        "vp_source_key": "E1:2",
        "entity_id": "e-uuid",
        "is_gshk": True,
        "secretary_name": "Get Started HK Limited",
        "tcsp_number": "TC000807",
        "person_id": "p-uuid",
        "appointed_date": "2020-01-01",
        "is_current": True,
    }
