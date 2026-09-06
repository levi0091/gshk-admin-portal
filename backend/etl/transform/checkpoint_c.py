from datetime import datetime

from etl.reconciliation import ReconciliationReport
from services.audit_changes import describe, render, status_change

# Sentinel for audit_log.created_at (NOT NULL) when the source VP date column
# is None. A fabricated "now()" would misrepresent legacy events as recent;
# this epoch sentinel unambiguously flags "date unknown" and is paired with
# metadata["vp_date_missing"] = True so it's queryable/filterable downstream.
# Kept tz-NAIVE to match Viewpoint's own DateEvent/DateChange (naive datetimes):
# a mixed naive/aware batch would make psycopg2 interpret rows inconsistently
# on insert into the timestamptz column. All audit_log rows are therefore naive
# and interpreted uniformly in the DB session timezone.
_MISSING_DATE_SENTINEL = datetime(1970, 1, 1)


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


def transform_form_filing(
    row: dict,
    entity_id_by_vp_key: dict[str, str],
    report: ReconciliationReport,
) -> dict | None:
    """VP FormQue row -> form_filings insert dict (singular). entity_id
    required (drop+log if unresolved). workflow decoded from FormCode
    (case-insensitive NAR1/NNC1 containment); status derived from the
    filed > signed > generated > queued ladder over the three date columns."""
    vp_key = row["FQnumber"]
    entcode = row["EntCode"]
    entity_id = entity_id_by_vp_key.get(entcode)
    if entity_id is None:
        report.record_error("form_filings", vp_key, f"unresolved entity_id for EntCode={entcode}")
        return None

    form_code = row.get("FormCode")
    code = (form_code or "").upper()
    if "NAR1" in code:
        workflow = "nar1"
    elif "NNC1" in code:
        workflow = "nnc1"
    else:
        workflow = None

    if row.get("DateFiled"):
        status = "filed"
    elif row.get("DateSigned"):
        status = "signed"
    elif row.get("DateGenerate"):
        status = "generated"
    else:
        status = "queued"

    field_details_raw = row.get("FieldDetails")
    field_details = {"vp_field_details": field_details_raw} if field_details_raw else None

    return {
        "vp_source_key": vp_key,
        "entity_id": entity_id,
        "form_code": form_code,
        "workflow": workflow,
        "status": status,
        "field_details": field_details,
        "generated_date": row.get("DateGenerate"),
        "signed_date": row.get("DateSigned"),
        "filed_date": row.get("DateFiled"),
        "file_deadline": row.get("DateFileDeadLine"),
        "filed_with_cr": bool(row.get("FiledROC")),
        "document_id": None,
        "source": "viewpoint_import",
    }


def parse_event_string(s: str | None) -> dict:
    """Parse a VP EventLog.EventString blob into a flat key/value dict.

    Pure; never raises. Format (pinned from a live row):
      '{SFMG\\x0cFQnumber=FQ025280\\x0c...\\x0cEventNr=181993\\x0c}'
    - Wrapped in '{' / '}' (tolerated if missing).
    - Tokens delimited by '\\x0c' (form-feed); empty tokens (consecutive
      delimiters) are skipped.
    - Every token is expected to contain '=' and is split on the FIRST '=';
      tokens without '=' are skipped — this covers the leading bare
      EventCode token (e.g. 'SFMG') and any other stray junk.
    - Later duplicate keys overwrite earlier ones.
    """
    if not s:
        return {}
    body = s.strip()
    if body.startswith("{"):
        body = body[1:]
    if body.endswith("}"):
        body = body[:-1]

    result: dict = {}
    for token in body.split("\x0c"):
        if not token:
            continue
        if "=" not in token:
            continue
        key, _, value = token.partition("=")
        result[key] = value
    return result


def _resolve_display_name(ucode, uname_by_ucode: dict[str, str]) -> str:
    """NOT-NULL fallback ladder: resolved uname -> raw Ucode -> literal
    'viewpoint' when there's no Ucode at all."""
    return uname_by_ucode.get(ucode) or ucode or "viewpoint"



def collapse_uniform_kv(value):
    """"AdNrS1=2311; AdNrS2=2311; ... AdNrSU=2311" is 15 fields all set to the
    same value — one change, not fifteen. Collapse it to "2311"; the full map is
    still in metadata. Leaves genuinely multi-valued strings untouched."""
    if not value or "=" not in value:
        return value
    vals = {part.split("=", 1)[1].strip() for part in value.split(";") if "=" in part}
    if len(vals) == 1:
        only = vals.pop()
        return only or value
    return value


#: Viewpoint subject kind -> the G-FlowDesk module it belongs to. Only two,
#: and that is not an omission: Viewpoint has no NAR1 case workflow and no CR
#: e-Filing transport, so an imported row is never labelled post_incorporation
#: or cr_filing. Mirrors services/audit_subject._MODULE_FOR_KIND, which is the
#: same rule the native side applies — the module follows the subject, which is
#: why a document has none of its own. A NULL module renders as a dash, which
#: is the truth about a system that did not record one.
_MODULE_FOR_KIND = {"company": "body_corporate", "person": "natural_person"}


def audit_context(event_code, key_code, label_by_code, subject_by_vp_key):
    """The context every audit row carries, whatever its source.

    The generic action name (never the per-record description), and WHICH RECORD
    the event is about — its kind, its id, its name and the reference a human
    quotes. `source_keycode` on its own is a Viewpoint RefCode, which is exactly
    what the trail used to print when the subject did not resolve.

    `subject_by_vp_key` accepts either the rich mapping built by
    `run_checkpoint_c._subjects` or a plain RefCode -> name dict, so a caller
    that only has names still produces a valid (if barer) row.
    """
    subject = (subject_by_vp_key or {}).get(key_code)
    if isinstance(subject, str):
        subject = {"name": subject}
    subject = subject or {}
    kind = subject.get("kind")
    return {
        "action_label": (label_by_code or {}).get(event_code),
        "company_name": subject.get("name"),
        "subject_kind": kind,
        "subject_id": subject.get("id"),
        "subject_ref": subject.get("ref"),
        "module": _MODULE_FOR_KIND.get(kind),
    }


def transform_event_log_row(
    row: dict,
    entity_id_by_vp_key: dict[str, str],
    uname_by_ucode: dict[str, str],
    label_by_code: dict[str, str] | None = None,
    subject_by_vp_key: dict | None = None,
    field_labels: dict[str, str] | None = None,
    address_labels: dict[str, str] | None = None,
) -> dict:
    """VP EventLog row -> audit_log insert dict (singular). No drops — every
    EventLog row imports, including ShowInLog=0 rows, per Levi's explicit
    decision. audit_log is insert-only (PBI-11): loaded via
    insert_rows_ignore_conflicts, never upsert_rows."""
    event_nr = int(row["EventNr"])
    vp_key = f"EL:{event_nr}"

    key_code = row.get("KeyCode")
    record_id = row.get("RecordID")
    ucode = row.get("Ucode")
    event_class = row.get("EventClass")
    date_event = row.get("DateEvent")
    description = row.get("Description")

    parsed = parse_event_string(row.get("EventString"))
    event_code = row.get("EventCode")

    metadata: dict = dict(parsed)
    if description is not None:
        metadata["description"] = description
    if date_event is None:
        metadata["vp_date_missing"] = True

    # What actually changed, decoded out of the EventString blob. Reading the
    # blob raw is why the trail was unusable: the change is in there, buried
    # under unchanged context and Viewpoint's internal checklist flags.
    changes = describe(event_code, parsed, field_labels, address_labels)
    before_state = {c["field"]: c["old"] for c in changes if c["old"]} or None
    after_state = {c["field"]: c["new"] for c in changes if c["new"]} or None

    return {
        **audit_context(event_code, key_code, label_by_code, subject_by_vp_key),
        "changed_fields": changes or None,
        "vp_source_key": vp_key,
        "created_at": date_event if date_event is not None else _MISSING_DATE_SENTINEL,
        "event_code": event_code,
        "source_keycode": key_code,
        "case_id": entity_id_by_vp_key.get(key_code),
        "entity_type": str(event_class) if event_class is not None else "vp",
        "entity_id": record_id or key_code or "unknown",
        "user_display_name": _resolve_display_name(ucode, uname_by_ucode),
        "created_by": ucode,
        "actioned_by": ucode,
        "action_type": "LEGACY_VP_EVENT",
        "source": "viewpoint_import",
        "form_type": "na",
        "user_id": None,
        "metadata": metadata or None,
        "before_state": before_state,
        "after_state": after_state,
        "old_value": render(changes, "old"),
        "new_value": render(changes, "new"),
    }


def transform_ref_status_row(
    row: dict,
    entity_id_by_vp_key: dict[str, str],
    uname_by_ucode: dict[str, str],
    label_by_code: dict[str, str] | None = None,
    subject_by_vp_key: dict | None = None,
) -> dict:
    """VP RefStatus row -> audit_log insert dict (singular). No drops.
    audit_log is insert-only (PBI-11): loaded via insert_rows_ignore_conflicts,
    never upsert_rows."""
    ref_code = row["RefCode"]
    seq_nr = int(row["SeqNr"])
    vp_key = f"RS:{ref_code}:{seq_nr}"

    ucode = row.get("Ucode")
    date_change = row.get("DateChange")

    metadata = {"stype": row.get("SType"), "descr": row.get("CDescr")}
    metadata = {k: v for k, v in metadata.items() if v is not None}
    if date_change is None:
        metadata["vp_date_missing"] = True

    # Viewpoint stores the status as a bare code; "0 -> 8" is not a status trail.
    changes = status_change(row.get("OldStat"), row.get("NewStat"))

    return {
        **audit_context("STATUS", ref_code, label_by_code, subject_by_vp_key),
        "vp_source_key": vp_key,
        "event_code": "STATUS",
        "changed_fields": changes or None,
        "old_value": render(changes, "old"),
        "new_value": render(changes, "new"),
        "created_at": date_change if date_change is not None else _MISSING_DATE_SENTINEL,
        "case_id": entity_id_by_vp_key.get(ref_code),
        "source_keycode": ref_code,
        "entity_type": "status",
        "entity_id": ref_code,
        "metadata": metadata or None,
        "user_display_name": _resolve_display_name(ucode, uname_by_ucode),
        "created_by": ucode,
        "actioned_by": ucode,
        "action_type": "LEGACY_VP_EVENT",
        "source": "viewpoint_import",
        "form_type": "na",
        "user_id": None,
        "before_state": None,
        "after_state": None,
    }


def transform_audit_form_filing(
    row: dict,
    audit_id_by_vp_key: dict[str, str],
    filing_id_by_vp_key: dict[str, str],
    report: ReconciliationReport,
) -> dict | None:
    """VP EventsForm row -> audit_form_filings insert dict (singular).

    PK is (EventNr, FQNumber); EventNr arrives as a float. Both FKs are
    nullable in the target: if neither audit_log nor form_filing resolves,
    drop+log; if exactly one resolves, still return the row with the other
    FK NULL (and log which side missed); if both resolve, return the row
    with no error."""
    event_nr = int(row["EventNr"])
    fq_number = row["FQNumber"]
    vp_key = f"{event_nr}:{fq_number}"

    audit_log_id = audit_id_by_vp_key.get(f"EL:{event_nr}")
    form_filing_id = filing_id_by_vp_key.get(fq_number)

    if audit_log_id is None and form_filing_id is None:
        report.record_error(
            "audit_form_filings", vp_key,
            f"neither audit_log nor form_filing resolved for EventNr={event_nr}, FQNumber={fq_number}",
        )
        return None

    if audit_log_id is None:
        report.record_error(
            "audit_form_filings", vp_key,
            f"unresolved audit_log_id for EventNr={event_nr} (EL:{event_nr})",
        )
    elif form_filing_id is None:
        report.record_error(
            "audit_form_filings", vp_key,
            f"unresolved form_filing_id for FQNumber={fq_number}",
        )

    return {
        "vp_source_key": vp_key,
        "audit_log_id": audit_log_id,
        "form_filing_id": form_filing_id,
        "vp_event_nr": str(event_nr),
        "vp_fq_number": fq_number,
    }
