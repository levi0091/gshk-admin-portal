from etl.reference_data import decode_id_type


def _collapse_line3(*parts: str | None) -> str | None:
    non_empty = [p.strip() for p in parts if p and p.strip()]
    return ", ".join(non_empty) if non_empty else None


def transform_address(row: dict) -> dict:
    """VP Addresses row -> addresses insert dict."""
    country = (row.get("Country") or "").strip().upper()
    return {
        "vp_source_key": str(row["AddrNr"]),
        "line1": row.get("Address"),
        "line2": row.get("Address2"),
        "line3": _collapse_line3(row.get("Address3"), row.get("Address4"), row.get("Address5")),
        "city": row.get("City"),
        "state_region": row.get("State"),
        "country": row.get("Country"),
        "postal_code": row.get("PostalCode"),
        "line1_zh": row.get("AddressLoc1"),
        "line2_zh": row.get("AddressLoc2"),
        "city_zh": row.get("CityLoc"),
        "is_hk_address": country in ("HK", ""),
    }


def transform_person(row: dict) -> dict:
    """Joined RefMaster (RefType='I') + Compliance row -> persons insert dict."""
    full_name = (row.get("Name") or row.get("SearchName") or "UNKNOWN").strip()
    former_name = row.get("FormerName") or row.get("Aliases")
    return {
        "vp_source_key": row["RefCode"],
        "full_name": full_name,
        "given_names": row.get("GivenNames"),
        "surname": None,
        "full_name_zh": row.get("ChnsName"),
        "former_name": former_name,
        "email": row.get("Email"),
        "phone": None,
        "date_of_birth": row.get("BirthDate"),
        "gender": row.get("Gender"),
        "nationality": row.get("Nationality"),
        "nationality_code": row.get("NationalityCode"),
        "occupation": row.get("Occupation"),
        "place_of_birth": row.get("PlaceBirth"),
        "marital_status": row.get("MaritalStatus"),
        "date_of_death": row.get("DateDeath"),
        "residential_address_id": None,  # backfilled in Checkpoint C from RefAddress
    }


def transform_entity(row: dict, bus_name: dict | None) -> dict:
    """Entity JOIN RefMaster row (+ optional principal BusNames row) -> entities insert dict."""
    status_code = (row.get("Status") or "").strip().upper()
    ceased = status_code == "C" or bool(bus_name and bus_name.get("DateCessation"))
    company_name = row.get("CompName") or row.get("Name") or "UNKNOWN"
    notes = ", ".join(n for n in (row.get("Note"), row.get("AccountNote")) if n)
    return {
        "vp_source_key": row["EntCode"],
        "company_name": company_name,
        "company_name_zh": (bus_name or {}).get("ChineseBusName"),
        "br_number": (bus_name or {}).get("BusRegNr"),
        "cr_number": row.get("IncorpNr"),
        "status": "ceased" if ceased else "live",
        "registered_address_id": None,  # backfilled in Checkpoint C from RefAddress
        "incorporation_date": row.get("IncorpDate"),
        "incorporation_place": row.get("IncorpPlace") or "Hong Kong",
        "ar_last_date": row.get("DateLastAnRe"),
        "ar_next_date": row.get("DateNextAnRe"),
        "ar_due_date": row.get("DateDueAnRe"),
        "agm_next_date": row.get("DateNextAGM"),
        "aoa_director_min": row.get("MA_DirMin"),
        "aoa_director_max": row.get("MA_DirMax"),
        "aoa_agm_waived": bool(row.get("MA_AgmWaived")),
        "previous_name": row.get("PrevEntName"),
        "date_name_changed": row.get("DateNameChanged"),
        "case_notes": notes or None,
        "assigned_to": None,  # no VP admin-code -> new-user mapping (confirmed)
    }


def transform_identity_document(row: dict, person_id_by_vp_key: dict[str, str]) -> dict | None:
    """IdentityRegister row (RefType='I' only) -> person_identity_documents insert dict.
    Returns None if the parent person wasn't loaded (caller logs this as an error)."""
    person_id = person_id_by_vp_key.get(row["RefCode"])
    if person_id is None:
        return None
    return {
        "vp_source_key": f"{row['RefCode']}:{row['SeqNr']}",
        "person_id": person_id,
        "id_type": decode_id_type(row.get("IdType")),
        "id_number": row.get("IdCode"),
        "issuing_country": row.get("Country"),
        "issue_date": row.get("FromDate"),
        "expiry_date": row.get("ToDate"),
        "is_primary": False,
        "scan_document_id": None,  # documents are greenfield, never migrated
    }
