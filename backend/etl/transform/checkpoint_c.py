from etl.reconciliation import ReconciliationReport


def _resolve_party(
    refcode: str,
    entity_id_by_vp_key: dict[str, str],
    person_id_by_vp_key: dict[str, str],
    refcode_type_by_vp_key: dict[str, str],
) -> tuple[str | None, str | None]:
    """Route a RefCode to (entity_id, person_id) — exactly one populated on
    success, both None if unresolved."""
    if refcode_type_by_vp_key.get(refcode) == "I":
        return None, person_id_by_vp_key.get(refcode)
    return entity_id_by_vp_key.get(refcode), None


def transform_contact(
    row: dict,
    entity_id_by_vp_key: dict[str, str],
    person_id_by_vp_key: dict[str, str],
    refcode_type_by_vp_key: dict[str, str],
    report: ReconciliationReport,
) -> dict | None:
    """VP RefContacts row -> contacts insert dict (singular).

    Routes RefCode to entity or person via refcode_types; drops+logs if
    neither resolves (a contact needs at least one party)."""
    refcode = row["RefCode"]
    vp_key = f"{refcode}:{row['SeqNr']}"
    entity_id, person_id = _resolve_party(
        refcode, entity_id_by_vp_key, person_id_by_vp_key, refcode_type_by_vp_key)
    if entity_id is None and person_id is None:
        report.record_error("contacts", vp_key, f"unresolved entity/person for RefCode={refcode}")
        return None
    return {
        "vp_source_key": vp_key,
        "entity_id": entity_id,
        "person_id": person_id,
        "contact_type": row.get("cType"),
        "contact_value": row.get("cText"),
        "is_preferred": bool(row.get("Preferred")),
    }


def transform_charge(
    row: dict,
    entity_id_by_vp_key: dict[str, str],
    report: ReconciliationReport,
) -> dict | None:
    """VP Charges row -> charges insert dict (singular). entity_id required
    (drop+log if unresolved)."""
    entcode = row["EntCode"]
    vp_key = f"{entcode}:{row['ChargeNr']}"
    entity_id = entity_id_by_vp_key.get(entcode)
    if entity_id is None:
        report.record_error("charges", vp_key, f"unresolved entity_id for EntCode={entcode}")
        return None
    mortgagee = row.get("MortgageeDescr") or row.get("MortgageeAddrCode")
    return {
        "vp_source_key": vp_key,
        "entity_id": entity_id,
        "charge_ref": row.get("ChargeRef"),
        "charge_type": row.get("ChargeType"),
        "mortgagee": mortgagee,
        "registration_date": row.get("DateRegistration"),
        "discharge_date": row.get("DateDischarge"),
        "property_description": row.get("PropertyDescr"),
        "currency": row.get("Currency"),
    }


def transform_task(
    row: dict,
    entity_id_by_vp_key: dict[str, str],
    person_id_by_vp_key: dict[str, str],
    refcode_type_by_vp_key: dict[str, str],
    report: ReconciliationReport,
) -> dict | None:
    """VP ToDoList (joined to ToDoCodes) row -> tasks insert dict (singular).

    Routes RefCode to entity or person via refcode_types; drops+logs if
    neither resolves. description is ToDoCodes.Description + (" — " + Remark)
    when Remark is non-empty; None if both are blank."""
    refcode = row["RefCode"]
    vp_key = f"{refcode}:{row['SeqNr']}"
    entity_id, person_id = _resolve_party(
        refcode, entity_id_by_vp_key, person_id_by_vp_key, refcode_type_by_vp_key)
    if entity_id is None and person_id is None:
        report.record_error("tasks", vp_key, f"unresolved entity/person for RefCode={refcode}")
        return None

    description = (row.get("Description") or "").strip()
    remark = (row.get("Remark") or "").strip()
    if description and remark:
        description = f"{description} — {remark}"
    elif remark:
        description = remark
    description = description or None

    return {
        "vp_source_key": vp_key,
        "entity_id": entity_id,
        "person_id": person_id,
        "task_code": row.get("ToDoCode"),
        "description": description,
        "due_date": row.get("DueDate"),
        "is_done": bool(row.get("IsDone")),
        "completed_date": None,
        "assigned_to": None,
    }


def transform_address_assignment(
    row: dict,
    entity_id_by_vp_key: dict[str, str],
    person_id_by_vp_key: dict[str, str],
    refcode_type_by_vp_key: dict[str, str],
    address_id_by_vp_key: dict[str, str],
    report: ReconciliationReport,
) -> dict | None:
    """VP RefAddress row -> address_assignments insert dict (singular).

    address_id is NOT NULL in the target — unresolved AddrNr drops+logs.
    Routes RefCode to entity or person via refcode_types; drops+logs if
    neither resolves (target CHECK requires entity_id OR person_id)."""
    refcode = row["RefCode"]
    vp_key = f"{refcode}:{row['SeqNr']}"
    address_id = address_id_by_vp_key.get(str(row["AddrNr"]))
    if address_id is None:
        report.record_error("address_assignments", vp_key, f"unresolved address_id for AddrNr={row['AddrNr']}")
        return None

    entity_id, person_id = _resolve_party(
        refcode, entity_id_by_vp_key, person_id_by_vp_key, refcode_type_by_vp_key)
    if entity_id is None and person_id is None:
        report.record_error("address_assignments", vp_key, f"unresolved entity/person for RefCode={refcode}")
        return None

    party_type = "person" if refcode_type_by_vp_key.get(refcode) == "I" else "entity"
    cancelled_date = row.get("Cancelled")
    return {
        "vp_source_key": vp_key,
        "address_id": address_id,
        "party_type": party_type,
        "entity_id": entity_id,
        "person_id": person_id,
        "address_role": row.get("AddrType"),
        "effective_date": row.get("Effective"),
        "cancelled_date": cancelled_date,
        "is_current": cancelled_date is None,
    }
