from datetime import datetime, timezone

from etl.reference_data import decode_id_type, decode_officer_role, AMBIGUOUS_OFFICER_CODES
from etl.reconciliation import ReconciliationReport
from services.tpsi.forms.cr_vocabularies import canonical_country


def _pack_address_lines(*parts: str | None) -> list[str | None]:
    """Viewpoint's five address lines -> the three CR gives us, losing nothing.

    CR's NAR1 has three free-text street slots (`flatFlrBlk`, `bldg`,
    `stEstLotVlg`), each capped at 60 characters. Viewpoint has five source
    lines. Two rules keep the result filable:

    1. COMPACT FIRST. Viewpoint frequently leaves `Address`/`Address2` empty
       and starts at `Address3`. Mapping positionally then left line1 and line2
       empty while line3 carried everything — that single mistake is why 874 of
       8,035 rows held a line over CR's limit while the source held only 25.

    2. MERGE ONLY WHEN FORCED, and merge the ADJACENT PAIR WITH THE SMALLEST
       COMBINED LENGTH. Three or fewer lines map one-to-one. Above that,
       something must join, and joining the shortest neighbours minimises the
       longest resulting line: over the real book that leaves 27 rows above 60
       versus 275 for the obvious "merge the tail" rule.

    Which fragment ends up under "Building" versus "Street" is therefore chosen
    by fit, not by meaning. CR validates length, not semantics, and a return
    that files beats one that is notionally better arranged and rejected.

    Never truncates: a single source line already over 60 is passed through
    whole, for the reconciliation report to name. Silently trimming a statutory
    address is worse than loading one a later validation catches.
    """
    lines = [p.strip() for p in parts if p and p.strip()]
    while len(lines) > 3:
        i = min(range(len(lines) - 1),
                key=lambda n: len(lines[n]) + len(lines[n + 1]))
        lines[i:i + 2] = [f"{lines[i]}, {lines[i + 1]}"]
    return lines + [None] * (3 - len(lines))


def _country(value):
    """Viewpoint's country code, rewritten to the one CR can file.

    Viewpoint carries sub-national and renamed codes CR has no entry for --
    'HK-CH' (its Chinese-labelled Hong Kong), 'GB-ENG', 'US-DE', 'ZR'. Passed
    through untouched, they load cleanly, pass every check on the profile, and
    kill the NAR1 weeks later at Data Verification with "no CR region code is
    known for country 'HK-CH'".

    Normalising HERE and not only in a backfill is the difference between
    fixing it once and fixing it after every reimport -- `reimport_addresses`
    rewrites this column from source. `canonical_country` returns None for
    anything it has no justified parent for, and those are left exactly as
    Viewpoint has them for the reconciliation report to name.
    """
    return canonical_country(value) or value


def transform_address(row: dict) -> dict:
    """VP Addresses row -> addresses insert dict."""
    country = (_country(row.get("Country")) or "").strip().upper()
    line1, line2, line3 = _pack_address_lines(
        row.get("Address"), row.get("Address2"), row.get("Address3"),
        row.get("Address4"), row.get("Address5"),
    )
    return {
        "vp_source_key": str(row["AddrNr"]),
        "line1": line1,
        "line2": line2,
        "line3": line3,
        "city": row.get("City"),
        "state_region": row.get("State"),
        "country": _country(row.get("Country")),
        "postal_code": row.get("PostalCode"),
        "line1_zh": row.get("AddressLoc1"),
        "line2_zh": row.get("AddressLoc2"),
        "city_zh": row.get("CityLoc"),
        "is_hk_address": country in ("HK", ""),
    }


# The import instant, fixed once per process so every row that needs it shares
# one timestamp instead of drifting across the run. Naive UTC on purpose: the
# other created_at values come straight from SQL Server as naive datetimes, and
# a batch mixing naive and aware values makes psycopg2 interpret rows
# inconsistently on the way into a timestamptz column (same trap as
# checkpoint_c's _MISSING_DATE_SENTINEL).
_IMPORTED_AT = datetime.now(timezone.utc).replace(tzinfo=None)


def _without_unknown_created_at(record: dict) -> dict:
    """Substitute the import instant when Viewpoint has no DateEntered for a ref.

    entities.created_at and persons.created_at are NOT NULL DEFAULT now(), and
    handing psycopg2 an explicit None defeats that default and aborts the whole
    batched insert -- a single ref without a DateEntered (GEMMAL, 1 of 12,827 on
    2026-09-06) took down the entire PROD load at Checkpoint A.

    The key has to stay PRESENT: upsert_rows sends each chunk as one multi-row
    INSERT, and SQLAlchemy compiles the column list from the first row, so a row
    that merely omits created_at raises CompileError ("a Python-side value or SQL
    expression is required"). So the fallback is supplied here rather than left
    to the column default -- same value the default would have produced, just
    computed Python-side where the batch can stay homogeneous.

    Deliberately NOT the 1970 sentinel checkpoint_c uses for audit_log. That one
    describes a historical EVENT and is paired with metadata["vp_date_missing"]
    so it stays queryable; a live 2024 company dated 1970 would just render as a
    wrong creation date with nothing alongside it to say why.

    upsert_rows keeps created_at out of the ON CONFLICT SET, so a re-run never
    moves a date that was set correctly the first time.
    """
    if record.get("created_at") is None:
        record["created_at"] = _IMPORTED_AT
    return record


def transform_person(row: dict) -> dict:
    """Joined RefMaster (RefType='I') + Compliance row -> persons insert dict."""
    full_name = (row.get("Name") or row.get("SearchName") or "UNKNOWN").strip()
    return _without_unknown_created_at({
        "vp_source_key": row["RefCode"],
        "full_name": full_name,
        "given_names": row.get("GivenNames"),
        "surname": None,
        "full_name_zh": row.get("ChnsName"),
        # Previous name and alias are DIFFERENT facts and CR asks for them in
        # different fields: indvPrevEngName is a name you no longer use,
        # indvAlsEngName one you also use. This used to be
        # `FormerName or Aliases` -- one column for both -- which filed a
        # person's current alias as a name they had abandoned.
        "former_name": row.get("FormerName"),
        "former_name_zh": row.get("ChnsFormerName"),
        "alias_en": row.get("Aliases"),
        "alias_zh": row.get("ChnsAliases"),
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
        # Real creation date, not the moment the ETL happened to run. Viewpoint
        # records it as RefMaster.DateEntered; without this every migrated row
        # would show the ETL run date. (updated_at cannot be known here — it is
        # derived from the imported EventLog once Checkpoint C has loaded it.)
        "created_at": row.get("DateEntered"),
        "residential_address_id": None,  # backfilled in Checkpoint C from RefAddress
    })


def transform_entity(row: dict, bus_name: dict | None) -> dict:
    """Entity JOIN RefMaster row (+ optional principal BusNames row) -> entities insert dict."""
    status_code = (row.get("Status") or "").strip().upper()
    ceased = status_code == "C" or bool(bus_name and bus_name.get("DateCessation"))
    company_name = row.get("CompName") or row.get("Name") or "UNKNOWN"
    notes = ", ".join(n for n in (row.get("Note"), row.get("AccountNote")) if n)
    return _without_unknown_created_at({
        "vp_source_key": row["EntCode"],
        "company_name": company_name,
        "company_name_zh": (bus_name or {}).get("ChineseBusName"),
        "br_number": (bus_name or {}).get("BusRegNr"),
        "cr_number": row.get("IncorpNr"),
        "status": "ceased" if ceased else "live",
        # Real creation date, not the moment the ETL happened to run. Viewpoint
        # records it as RefMaster.DateEntered; without this every migrated row
        # would show the ETL run date. (updated_at cannot be known here — it is
        # derived from the imported EventLog once Checkpoint C has loaded it.)
        "created_at": row.get("DateEntered"),
        "registered_address_id": None,  # backfilled in Checkpoint C from RefAddress
        "incorporation_date": row.get("IncorpDate"),
        # Canonicalised on the way in. The default used to be the literal
        # "Hong Kong", which FILES but cannot be selected in a dropdown
        # keyed by alpha-2 -- 251 companies rendered as "Hong Kong (not in
        # list)" and a backfill had to go back for them.
        "incorporation_place": _country(row.get("IncorpPlace")) or "HK",
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
    })


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
        "issuing_country": _country(row.get("Country")),
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
            "issuing_country": _country(row.get("PasPlaceIssue")),
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
