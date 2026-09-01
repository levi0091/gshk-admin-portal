from etl.transform.checkpoint_a import transform_address, transform_entity, transform_person, transform_identity_document, transform_entity_officer
from etl.transform.checkpoint_a import transform_beneficial_owner
from etl.transform.checkpoint_a import transform_compliance_identity_documents
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


def _address_row(**overrides):
    """A Viewpoint Addresses row with every column present and empty."""
    row = {
        "AddrNr": 1, "Address": None, "Address2": None, "Address3": None,
        "Address4": None, "Address5": None, "City": None, "State": None,
        "Country": None, "PostalCode": None, "AddressLoc1": None,
        "AddressLoc2": None, "CityLoc": None,
    }
    row.update(overrides)
    return row


def test_transform_address_compacts_leading_empty_source_lines():
    """The 861-row shape: Viewpoint's Address/Address2 are empty and the
    content starts at Address3. Collapsing 3+4+5 into line3 put all of it in
    one 60-char slot and left line1 and line2 empty, which is what made most
    of the book unfilable. The lines must move up instead."""
    result = transform_address(_address_row(
        Address3="Cakilli Sokak Oypas Ev Yani Hane 3",
        Address4="Gonyeli Yenikent",
        Address5="Nicosia",
    ))
    assert result["line1"] == "Cakilli Sokak Oypas Ev Yani Hane 3"
    assert result["line2"] == "Gonyeli Yenikent"
    assert result["line3"] == "Nicosia"


def test_transform_address_keeps_three_source_lines_one_to_one():
    """Three lines fit three slots, so nothing is merged."""
    result = transform_address(_address_row(
        Address="Flat A", Address2="Tower 3", Address3="18 Kings Road",
    ))
    assert [result["line1"], result["line2"], result["line3"]] == [
        "Flat A", "Tower 3", "18 Kings Road",
    ]


def test_transform_address_merges_the_smallest_adjacent_pair_when_over_three():
    """Four source lines must become three. The pair with the smallest
    combined length is merged, because minimising the longest resulting line
    is what keeps the address inside CR's 60-char cap."""
    result = transform_address(_address_row(
        Address="Flat A", Address2="Tower 3",
        Address3="18 Kings Road", Address4="North Point",
    ))
    assert [result["line1"], result["line2"], result["line3"]] == [
        "Flat A, Tower 3", "18 Kings Road", "North Point",
    ]


def test_transform_address_never_truncates_a_long_source_line():
    """A single Viewpoint line already over 60 is written whole. Trimming a
    statutory address to fit is worse than loading one a later validation
    names — 25 rows in the real book are this shape."""
    long_line = "M. Floor House-15, 16, Sultan Bin Khalifa Al Habtoor Bldg, 127-44C ST DM.65"
    assert len(long_line) > 60
    result = transform_address(_address_row(Address=long_line, Address2="Dubai"))
    assert result["line1"] == long_line


def test_transform_address_unused_lines_are_none():
    result = transform_address(_address_row(Address="Sole line"))
    assert result["line1"] == "Sole line"
    assert result["line2"] is None
    assert result["line3"] is None


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


def test_transform_person_keeps_alias_separate_from_former_name():
    """REPLACES test_transform_person_merges_aliases_into_former_name, whose
    behaviour was `FormerName or Aliases` -- one column for two different
    facts. CR asks for them separately (indvPrevEngName vs indvAlsEngName) and
    they mean different things: a previous name is one you no longer use, an
    alias is one you also use. Merging them files a person's current alias as
    a name they have abandoned."""
    vp_row = {
        "RefCode": "X2", "Name": "Jane Doe", "ChnsName": None,
        "GivenNames": "Jane", "FormerName": None, "FormerGivenNames": None,
        "Email": None, "BirthDate": None, "Gender": None, "Nationality": None,
        "NationalityCode": None, "Occupation": None, "PlaceBirth": None,
        "MaritalStatus": None, "DateDeath": None, "Aliases": "Jane Smith",
    }

    result = transform_person(vp_row)

    assert result["alias_en"] == "Jane Smith"
    assert result["former_name"] is None


def test_transform_person_carries_both_names_in_chinese_too():
    """CR wants Previous Names and Alias in Chinese as well as English."""
    vp_row = {
        "RefCode": "X3", "Name": "Jane Doe", "ChnsName": None,
        "GivenNames": "Jane", "FormerName": "Jane Roe",
        "FormerGivenNames": None, "Email": None, "BirthDate": None,
        "Gender": None, "Nationality": None, "NationalityCode": None,
        "Occupation": None, "PlaceBirth": None, "MaritalStatus": None,
        "DateDeath": None, "Aliases": "JD",
        "ChnsFormerName": "前名", "ChnsAliases": "別名",
    }

    result = transform_person(vp_row)

    assert result["former_name"] == "Jane Roe"
    assert result["former_name_zh"] == "前名"
    assert result["alias_en"] == "JD"
    assert result["alias_zh"] == "別名"


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
    report = ReconciliationReport()
    vp_row = {
        "RefCode": "LEUNGP", "SeqNr": 1, "IdType": "PSP", "IdCode": "K1234567",
        "Country": "HK", "FromDate": "2018-01-01", "ToDate": "2028-01-01",
    }
    result = transform_identity_document(vp_row, person_ids, report)
    assert result is not None
    assert result["person_id"] == "11111111-1111-1111-1111-111111111111"
    assert result["id_type"] == "passport"
    assert result["id_number"] == "K1234567"
    assert result["vp_source_key"] == "LEUNGP:1"
    assert report.has_errors() is False


def test_transform_identity_document_returns_none_when_person_missing():
    report = ReconciliationReport()
    vp_row = {
        "RefCode": "GHOST", "SeqNr": 1, "IdType": "PSP", "IdCode": "X1",
        "Country": None, "FromDate": None, "ToDate": None,
    }
    result = transform_identity_document(vp_row, {}, report)
    assert result is None
    assert report.has_errors() is True


def test_transform_identity_document_returns_none_when_id_number_missing():
    person_ids = {"LEUNGP": "11111111-1111-1111-1111-111111111111"}
    report = ReconciliationReport()
    vp_row = {
        "RefCode": "LEUNGP", "SeqNr": 2, "IdType": "PSP", "IdCode": None,
        "Country": "HK", "FromDate": None, "ToDate": None,
    }
    result = transform_identity_document(vp_row, person_ids, report)
    assert result is None
    assert report.has_errors() is True
    assert "id_number" in report.errors[0]["message"]


def test_transform_compliance_identity_documents_returns_passport_and_hkid():
    person_ids = {"LEUNGP": "11111111-1111-1111-1111-111111111111"}
    report = ReconciliationReport()
    vp_row = {
        "AddrCode": "LEUNGP",
        "PassportNr": "K1234567",
        "PasPlaceIssue": "Hong Kong",
        "PasDateIssue": "2018-01-01",
        "PasDateExpire": "2028-01-01",
        "IDcardNr": "A1234567",
        "IDcardDateIssue": "2015-06-01",
    }
    result = transform_compliance_identity_documents(vp_row, person_ids, set(), report)
    assert len(result) == 2
    passport = next(r for r in result if r["id_type"] == "passport")
    hkid = next(r for r in result if r["id_type"] == "hkid")
    assert passport["person_id"] == "11111111-1111-1111-1111-111111111111"
    assert passport["id_number"] == "K1234567"
    assert passport["issuing_country"] == "Hong Kong"
    assert passport["issue_date"] == "2018-01-01"
    assert passport["expiry_date"] == "2028-01-01"
    assert passport["vp_source_key"] == "LEUNGP:compliance-passport"
    assert passport["is_primary"] is False
    assert passport["scan_document_id"] is None
    assert hkid["person_id"] == "11111111-1111-1111-1111-111111111111"
    assert hkid["id_number"] == "A1234567"
    assert hkid["issuing_country"] is None
    assert hkid["issue_date"] == "2015-06-01"
    assert hkid["expiry_date"] is None
    assert hkid["vp_source_key"] == "LEUNGP:compliance-hkid"
    assert report.has_errors() is False


def test_transform_compliance_identity_documents_passport_only():
    person_ids = {"LEUNGP": "p-uuid"}
    report = ReconciliationReport()
    vp_row = {
        "AddrCode": "LEUNGP",
        "PassportNr": "K1234567",
        "PasPlaceIssue": "Hong Kong",
        "PasDateIssue": "2018-01-01",
        "PasDateExpire": "2028-01-01",
        "IDcardNr": None,
        "IDcardDateIssue": None,
    }
    result = transform_compliance_identity_documents(vp_row, person_ids, set(), report)
    assert len(result) == 1
    assert result[0]["id_type"] == "passport"
    assert result[0]["id_number"] == "K1234567"


def test_transform_compliance_identity_documents_skips_duplicate_of_identity_register():
    person_ids = {"LEUNGP": "p-uuid"}
    report = ReconciliationReport()
    vp_row = {
        "AddrCode": "LEUNGP",
        "PassportNr": "K1234567",
        "PasPlaceIssue": "Hong Kong",
        "PasDateIssue": "2018-01-01",
        "PasDateExpire": "2028-01-01",
        "IDcardNr": "A1234567",
        "IDcardDateIssue": "2015-06-01",
    }
    existing_doc_keys = {("p-uuid", "passport", "K1234567")}
    result = transform_compliance_identity_documents(vp_row, person_ids, existing_doc_keys, report)
    assert len(result) == 1
    assert result[0]["id_type"] == "hkid"
    assert result[0]["id_number"] == "A1234567"
    assert report.has_errors() is False


def test_transform_compliance_identity_documents_both_duplicates_returns_empty():
    person_ids = {"LEUNGP": "p-uuid"}
    report = ReconciliationReport()
    vp_row = {
        "AddrCode": "LEUNGP",
        "PassportNr": "K1234567",
        "PasPlaceIssue": "Hong Kong",
        "PasDateIssue": "2018-01-01",
        "PasDateExpire": "2028-01-01",
        "IDcardNr": "A1234567",
        "IDcardDateIssue": "2015-06-01",
    }
    existing_doc_keys = {
        ("p-uuid", "passport", "K1234567"),
        ("p-uuid", "hkid", "A1234567"),
    }
    result = transform_compliance_identity_documents(vp_row, person_ids, existing_doc_keys, report)
    assert result == []
    assert report.has_errors() is False


def test_transform_compliance_identity_documents_unresolved_person_returns_empty_and_logs():
    report = ReconciliationReport()
    vp_row = {
        "AddrCode": "GHOST",
        "PassportNr": "K1234567",
        "PasPlaceIssue": None,
        "PasDateIssue": None,
        "PasDateExpire": None,
        "IDcardNr": None,
        "IDcardDateIssue": None,
    }
    result = transform_compliance_identity_documents(vp_row, {}, set(), report)
    assert result == []
    assert report.has_errors() is True
    assert "GHOST" in report.errors[0]["message"]


def test_transform_entity_officer_maps_director():
    entity_ids = {"FACTORALIM": "e-uuid-1"}
    person_ids = {"LEUNGP": "p-uuid-1"}
    refcode_types = {"LEUNGP": "I"}
    report = ReconciliationReport()
    vp_row = {
        "EntCode": "FACTORALIM", "SeqNr": 1, "AddrCode": "LEUNGP",
        "OfficerType": "DIR", "Position": None,
        "DateAppoint": "2020-01-15", "DateResign": None, "ReasonResign": None,
    }
    result = transform_entity_officer(vp_row, entity_ids, person_ids, refcode_types, report)
    assert result["entity_id"] == "e-uuid-1"
    assert result["person_id"] == "p-uuid-1"
    assert result["party_type"] == "individual"
    assert result["role"] == "director"
    assert result["is_current"] is True
    assert report.has_errors() is False


def test_transform_entity_officer_resigned_is_not_current():
    entity_ids = {"E1": "e-uuid"}
    person_ids = {"P1": "p-uuid"}
    refcode_types = {"P1": "I"}
    report = ReconciliationReport()
    vp_row = {
        "EntCode": "E1", "SeqNr": 2, "AddrCode": "P1", "OfficerType": "DIR",
        "Position": None, "DateAppoint": "2019-01-01",
        "DateResign": "2021-01-01", "ReasonResign": "R",
    }
    result = transform_entity_officer(vp_row, entity_ids, person_ids, refcode_types, report)
    assert result["is_current"] is False
    assert result["resigned_date"] == "2021-01-01"


def test_transform_entity_officer_ambiguous_role_is_logged():
    entity_ids = {"E1": "e-uuid"}
    person_ids = {"P1": "p-uuid"}
    refcode_types = {"P1": "I"}
    report = ReconciliationReport()
    vp_row = {
        "EntCode": "E1", "SeqNr": 3, "AddrCode": "P1", "OfficerType": "RPD",
        "Position": None, "DateAppoint": None, "DateResign": None, "ReasonResign": None,
    }
    transform_entity_officer(vp_row, entity_ids, person_ids, refcode_types, report)
    assert report.has_errors() is True
    assert "RPD" in report.errors[0]["message"]


def test_transform_entity_officer_missing_entity_returns_none_and_logs():
    report = ReconciliationReport()
    refcode_types = {"P1": "I"}
    vp_row = {
        "EntCode": "GHOST", "SeqNr": 1, "AddrCode": "P1", "OfficerType": "DIR",
        "Position": None, "DateAppoint": None, "DateResign": None, "ReasonResign": None,
    }
    result = transform_entity_officer(vp_row, {}, {"P1": "p-uuid"}, refcode_types, report)
    assert result is None
    assert report.has_errors() is True


def test_transform_entity_officer_missing_person_returns_dict_with_none_person_id():
    entity_ids = {"E1": "e-uuid"}
    refcode_types = {"GHOSTPERSON": "I"}
    report = ReconciliationReport()
    vp_row = {
        "EntCode": "E1", "SeqNr": 4, "AddrCode": "GHOSTPERSON", "OfficerType": "DIR",
        "Position": None, "DateAppoint": None, "DateResign": None, "ReasonResign": None,
    }
    result = transform_entity_officer(vp_row, entity_ids, {}, refcode_types, report)
    assert result is not None
    assert result["entity_id"] == "e-uuid"
    assert result["person_id"] is None
    assert result["party_type"] == "individual"
    assert result["role"] == "director"
    assert report.has_errors() is True
    assert "GHOSTPERSON" in report.errors[0]["message"]


def test_transform_entity_officer_corporate_secretary_no_person_no_error():
    entity_ids = {"E1": "e-uuid"}
    person_ids = {}
    refcode_types = {"GETSTA": "C"}
    report = ReconciliationReport()
    vp_row = {
        "EntCode": "E1", "SeqNr": 5, "AddrCode": "GETSTA", "OfficerType": "SEC",
        "Position": None, "DateAppoint": "2020-01-01", "DateResign": None, "ReasonResign": None,
    }
    result = transform_entity_officer(vp_row, entity_ids, person_ids, refcode_types, report)
    assert result is not None
    assert result["entity_id"] == "e-uuid"
    assert result["party_type"] == "corporate"
    assert result["person_id"] is None
    assert result["corporate_name"] == "GETSTA"
    assert report.has_errors() is False


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


def test_transform_beneficial_owner_individual():
    entity_ids = {"E1": "e-uuid"}
    person_ids = {"P1": "p-uuid"}
    refcode_types = {"P1": "I"}
    report = ReconciliationReport()
    vp_row = {
        "EntCode": "E1", "SeqNr": 1, "RefCode": "P1", "EntOwnCountry": "HK",
        "PercInterest": 60.0, "PercVote": 60.0,
        "DateFrom": "2020-01-01", "DateTo": None,
    }
    result = transform_beneficial_owner(vp_row, entity_ids, person_ids, refcode_types, report)
    assert result["entity_id"] == "e-uuid"
    assert result["person_id"] == "p-uuid"
    assert result["party_type"] == "individual"
    assert result["percent_interest"] == 60.0
    assert result["is_current"] is True


def test_transform_beneficial_owner_corporate_has_no_person_id():
    entity_ids = {"E1": "e-uuid"}
    refcode_types = {"C1": "C"}
    report = ReconciliationReport()
    vp_row = {
        "EntCode": "E1", "SeqNr": 2, "RefCode": "C1", "EntOwnCountry": "HK",
        "PercInterest": 40.0, "PercVote": 40.0,
        "DateFrom": "2020-01-01", "DateTo": "2022-01-01",
    }
    result = transform_beneficial_owner(vp_row, entity_ids, {}, refcode_types, report)
    assert result["party_type"] == "corporate"
    assert result["person_id"] is None
    assert result["is_current"] is False


# ---- real creation dates on a fresh load ----------------------------------

def test_entity_created_at_comes_from_viewpoint_not_the_etl_run():
    """A fresh ETL must set the REAL creation date. Without this every migrated
    company shows the day the ETL happened to run (the DB default)."""
    from etl.transform.checkpoint_a import transform_entity
    from datetime import datetime

    row = {
        "EntCode": "ACME", "CompName": "Acme Limited", "Name": "Acme Limited",
        "DateEntered": datetime(2019, 7, 8), "IncorpNr": "123", "IncorpDate": None,
        "IncorpPlace": None, "Status": "L",
    }
    out = transform_entity(row, None)
    assert out["created_at"] == datetime(2019, 7, 8)


def test_person_created_at_comes_from_viewpoint():
    from etl.transform.checkpoint_a import transform_person
    from datetime import datetime

    row = {"RefCode": "SMITHJ", "Name": "SMITH, John",
           "DateEntered": datetime(2020, 1, 2)}
    out = transform_person(row)
    assert out["created_at"] == datetime(2020, 1, 2)
