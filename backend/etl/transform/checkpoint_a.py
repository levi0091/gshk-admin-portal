from etl.reference_data import decode_id_type, decode_officer_role, AMBIGUOUS_OFFICER_CODES
from etl.reconciliation import ReconciliationReport


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


def transform_identity_document(
    row: dict,
    person_id_by_vp_key: dict[str, str],
    report: ReconciliationReport,
) -> dict | None:
    """IdentityRegister row (RefType='I' only) -> person_identity_documents insert dict.
    Returns None (and logs) if the parent person wasn't loaded, or if the row is
    missing its mandatory id_number (IdCode) — person_identity_documents.id_number
    is NOT NULL, so a null IdCode must be dropped-and-logged rather than allowed
    to abort the whole batched insert."""
    vp_key = f"{row['RefCode']}:{row['SeqNr']}"
    person_id = person_id_by_vp_key.get(row["RefCode"])
    if person_id is None:
        report.record_error("person_identity_documents", vp_key, f"unresolved person_id for RefCode={row['RefCode']}")
        return None
    id_number = row.get("IdCode")
    if not id_number:
        report.record_error("person_identity_documents", vp_key, "missing id_number (IdCode is null)")
        return None
    return {
        "vp_source_key": vp_key,
        "person_id": person_id,
        "id_type": decode_id_type(row.get("IdType")),
        "id_number": id_number,
        "issuing_country": row.get("Country"),
        "issue_date": row.get("FromDate"),
        "expiry_date": row.get("ToDate"),
        "is_primary": False,
        "scan_document_id": None,  # documents are greenfield, never migrated
    }


def transform_compliance_identity_documents(
    row: dict,
    person_id_by_vp_key: dict[str, str],
    existing_doc_keys: set[tuple],
    report: ReconciliationReport,
) -> list[dict]:
    """Compliance row -> up to 2 person_identity_documents insert dicts
    (passport, hkid). This is a SECONDARY source alongside IdentityRegister
    (see transform_identity_document) — some persons only ever had their ID
    captured on the Compliance record, never in IdentityRegister, and were
    being missed entirely. `existing_doc_keys` is the set of
    (person_id, id_type, id_number) tuples already produced from
    IdentityRegister; candidates matching a key in that set are skipped as
    legitimate duplicates (not logged as errors). Returns [] (and logs) if
    the parent person wasn't loaded."""
    person_id = person_id_by_vp_key.get(row["AddrCode"])
    if person_id is None:
        report.record_error(
            "person_identity_documents", row["AddrCode"],
            f"unresolved person_id for Compliance AddrCode={row['AddrCode']}",
        )
        return []

    candidates = []
    if row.get("PassportNr"):
        candidates.append({
            "vp_source_key": f"{row['AddrCode']}:compliance-passport",
            "person_id": person_id,
            "id_type": "passport",
            "id_number": row["PassportNr"],
            "issuing_country": row.get("PasPlaceIssue"),
            "issue_date": row.get("PasDateIssue"),
            "expiry_date": row.get("PasDateExpire"),
            "is_primary": False,
            "scan_document_id": None,
        })
    if row.get("IDcardNr"):
        candidates.append({
            "vp_source_key": f"{row['AddrCode']}:compliance-hkid",
            "person_id": person_id,
            "id_type": "hkid",
            "id_number": row["IDcardNr"],
            "issuing_country": None,
            "issue_date": row.get("IDcardDateIssue"),
            "expiry_date": None,
            "is_primary": False,
            "scan_document_id": None,
        })

    return [
        c for c in candidates
        if (c["person_id"], c["id_type"], c["id_number"]) not in existing_doc_keys
    ]


def transform_entity_officer(
    row: dict,
    entity_id_by_vp_key: dict[str, str],
    person_id_by_vp_key: dict[str, str],
    refcode_type_by_vp_key: dict[str, str],
    report: ReconciliationReport,
) -> dict | None:
    """Officers row -> entity_officers insert dict. Returns None (and logs) if
    the parent entity is unresolved — the child row is never silently dropped
    without a trace (PRD key test case: 'a child row whose parent failed to
    load is caught and logged, not silently dropped').

    An officer can be an individual or a corporate entity (e.g. GSHK itself as
    company secretary), determined by looking up the officer's AddrCode in
    RefMaster.RefType ('I' = individual, else corporate) — mirrors
    transform_beneficial_owner."""
    vp_key = f"{row['EntCode']}:{row['SeqNr']}"
    entity_id = entity_id_by_vp_key.get(row["EntCode"])
    if entity_id is None:
        report.record_error("entity_officers", vp_key, f"unresolved entity_id for EntCode={row['EntCode']}")
        return None

    ref_type = refcode_type_by_vp_key.get(row["AddrCode"])
    is_individual = ref_type == "I"
    person_id = person_id_by_vp_key.get(row["AddrCode"]) if is_individual else None
    if is_individual and person_id is None:
        report.record_error("entity_officers", vp_key, f"unresolved person_id for AddrCode={row['AddrCode']}")

    officer_type = (row.get("OfficerType") or "").strip().upper()
    if officer_type in AMBIGUOUS_OFFICER_CODES:
        report.record_error(
            "entity_officers", vp_key,
            f"ambiguous OfficerType={officer_type!r} mapped to "
            f"{decode_officer_role(officer_type)!r} — confirm with GSHK",
        )

    return {
        "vp_source_key": vp_key,
        "entity_id": entity_id,
        "person_id": person_id,
        "party_type": "individual" if is_individual else "corporate",
        "corporate_name": None if is_individual else row["AddrCode"],
        "role": decode_officer_role(officer_type),
        "position": row.get("Position"),
        "appointed_date": row.get("DateAppoint"),
        "resigned_date": row.get("DateResign"),
        "resignation_reason": row.get("ReasonResign"),
        "is_current": row.get("DateResign") is None,
    }


def transform_company_secretary(entity_officer_row: dict) -> dict:
    """Takes a transform_entity_officer() output row already filtered to
    role == 'company_secretary' and reshapes it for company_secretaries.
    GSHK (TCSP TC000807) is the default corporate secretary per field-mapping.md;
    an individual secretary still carries person_id."""
    return {
        "vp_source_key": entity_officer_row["vp_source_key"],
        "entity_id": entity_officer_row["entity_id"],
        "is_gshk": True,
        "secretary_name": "Get Started HK Limited",
        "tcsp_number": "TC000807",
        "person_id": entity_officer_row["person_id"],
        "appointed_date": entity_officer_row["appointed_date"],
        "is_current": entity_officer_row["is_current"],
    }


def transform_beneficial_owner(
    row: dict,
    entity_id_by_vp_key: dict[str, str],
    person_id_by_vp_key: dict[str, str],
    refcode_type_by_vp_key: dict[str, str],
    report: ReconciliationReport,
) -> dict | None:
    """EntityOwners row -> beneficial_owners insert dict. A beneficial owner
    can be an individual or a corporate entity, determined by looking up the
    owner's RefCode in RefMaster.RefType ('I' = individual, else corporate).
    Returns None (and logs) if the parent entity is unresolved."""
    vp_key = f"{row['EntCode']}:{row['SeqNr']}"
    entity_id = entity_id_by_vp_key.get(row["EntCode"])
    if entity_id is None:
        report.record_error("beneficial_owners", vp_key, f"unresolved entity_id for EntCode={row['EntCode']}")
        return None

    ref_type = refcode_type_by_vp_key.get(row["RefCode"])
    is_individual = ref_type == "I"
    person_id = person_id_by_vp_key.get(row["RefCode"]) if is_individual else None
    if is_individual and person_id is None:
        report.record_error("beneficial_owners", vp_key, f"unresolved person_id for RefCode={row['RefCode']}")

    return {
        "vp_source_key": vp_key,
        "entity_id": entity_id,
        "person_id": person_id,
        "party_type": "individual" if is_individual else "corporate",
        "corporate_name": None if is_individual else row["RefCode"],
        "owner_type": None,
        "percent_interest": row.get("PercInterest"),
        "percent_vote": row.get("PercVote"),
        "date_from": row.get("DateFrom"),
        "date_to": row.get("DateTo"),
        "is_current": row.get("DateTo") is None,
    }
