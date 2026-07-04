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
