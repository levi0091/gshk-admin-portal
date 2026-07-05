import argparse
import os
from datetime import datetime, timezone

from sqlalchemy import text

from etl.db import get_viewpoint_engine, get_supabase_engine
from etl.reconciliation import ReconciliationReport
from etl.extract.checkpoint_a import (
    extract_addresses, extract_persons, extract_entities,
    extract_principal_business_names, extract_identity_documents,
    extract_compliance_identity_documents,
    extract_officers, extract_beneficial_owners,
)
from etl.transform.checkpoint_a import (
    transform_address, transform_person, transform_entity,
    transform_identity_document, transform_compliance_identity_documents,
    transform_entity_officer,
    transform_company_secretary, transform_beneficial_owner,
)
from etl.load.checkpoint_a import (
    load_addresses, load_persons, load_entities, load_identity_documents,
    load_entity_officers, load_company_secretaries, load_beneficial_owners,
)


def _vp_key_to_id(engine, table: str) -> dict[str, str]:
    with engine.connect() as conn:
        rows = conn.execute(text(f"SELECT vp_source_key, id FROM {table} WHERE vp_source_key IS NOT NULL"))
        return {r.vp_source_key: str(r.id) for r in rows}


def _refcode_types(engine) -> dict[str, str]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT RefCode, RefType FROM RefMaster"))
        return {r.RefCode: r.RefType for r in rows}


def run(dry_run: bool) -> ReconciliationReport:
    vp_engine = get_viewpoint_engine()
    sb_engine = get_supabase_engine()
    report = ReconciliationReport()

    # 1. addresses (no FK deps)
    vp_addresses = extract_addresses(vp_engine)
    address_rows = [transform_address(r) for r in vp_addresses]
    loaded = load_addresses(sb_engine, address_rows, dry_run=dry_run)
    report.record_entity("addresses", len(vp_addresses), loaded if not dry_run else len(address_rows))

    # 2. persons (no FK deps — residential_address_id filled in Checkpoint C)
    vp_persons = extract_persons(vp_engine)
    person_rows = [transform_person(r) for r in vp_persons]
    loaded = load_persons(sb_engine, person_rows, dry_run=dry_run)
    report.record_entity("persons", len(vp_persons), loaded if not dry_run else len(person_rows))

    # 3. entities (needs principal BusNames row per EntCode)
    vp_entities = extract_entities(vp_engine)
    bus_names_by_entcode = extract_principal_business_names(vp_engine)
    for tied_code in bus_names_by_entcode.get("_ties", set()):
        report.record_error("entities", tied_code, "multiple PrincipleBNR=1 BusNames rows — picked most recent DateRegistration")
    entity_rows = [
        transform_entity(r, bus_names_by_entcode.get(r["EntCode"]))
        for r in vp_entities
    ]
    loaded = load_entities(sb_engine, entity_rows, dry_run=dry_run)
    report.record_entity("entities", len(vp_entities), loaded if not dry_run else len(entity_rows))

    if dry_run:
        # Dry-run stops here for FK-dependent entities: without real writes,
        # there are no target UUIDs yet to resolve person_id/entity_id against.
        report.print_summary()
        return report

    # Resolve FK lookup dicts against what was actually written.
    person_id_by_vp_key = _vp_key_to_id(sb_engine, "persons")
    entity_id_by_vp_key = _vp_key_to_id(sb_engine, "entities")
    refcode_types = _refcode_types(vp_engine)

    # 4. person_identity_documents (needs persons loaded)
    # Primary source: IdentityRegister.
    vp_ids = extract_identity_documents(vp_engine)
    id_doc_rows = []
    for r in vp_ids:
        transformed = transform_identity_document(r, person_id_by_vp_key, report)
        if transformed is None:
            continue
        id_doc_rows.append(transformed)
    loaded = load_identity_documents(sb_engine, id_doc_rows, dry_run=dry_run)
    report.record_entity("person_identity_documents", len(vp_ids), loaded)

    # Secondary source: Compliance (passport/HKID columns), deduped against
    # what IdentityRegister already produced above. Recorded as a SEPARATE
    # reconciliation line (not folded into "person_identity_documents") so each
    # source table stays attributable. source_count is the number of
    # Compliance-sourced docs handed to the loader (after per-field null-guards
    # and dedup against IdentityRegister) — NOT the number of Compliance rows
    # scanned. A Compliance row fans out to 0/1/2 docs, so counting scanned rows
    # against loaded docs would flag a false MISMATCH on every healthy run;
    # counting produced-docs vs loaded-docs keeps discrepancy at 0 unless a load
    # genuinely drops rows. (Compliance rows scanned: len(vp_compliance_ids).)
    existing_doc_keys = {(r["person_id"], r["id_type"], r["id_number"]) for r in id_doc_rows}
    vp_compliance_ids = extract_compliance_identity_documents(vp_engine)
    compliance_id_doc_rows = []
    for r in vp_compliance_ids:
        compliance_id_doc_rows.extend(
            transform_compliance_identity_documents(r, person_id_by_vp_key, existing_doc_keys, report)
        )
    loaded = load_identity_documents(sb_engine, compliance_id_doc_rows, dry_run=dry_run)
    report.record_entity("person_identity_documents_compliance", len(compliance_id_doc_rows), loaded)

    # 5. entity_officers (needs entities + persons loaded)
    vp_officers = extract_officers(vp_engine)
    officer_rows = []
    secretary_rows = []
    for r in vp_officers:
        transformed = transform_entity_officer(r, entity_id_by_vp_key, person_id_by_vp_key, refcode_types, report)
        if transformed is None:
            continue
        officer_rows.append(transformed)
        if transformed["role"] == "company_secretary":
            secretary_rows.append(transform_company_secretary(transformed))
    loaded = load_entity_officers(sb_engine, officer_rows, dry_run=dry_run)
    report.record_entity("entity_officers", len(vp_officers), loaded)

    # 6. company_secretaries (derived from entity_officers, loaded separately)
    loaded = load_company_secretaries(sb_engine, secretary_rows, dry_run=dry_run)
    report.record_entity("company_secretaries", len(secretary_rows), loaded)

    # 7. beneficial_owners (needs entities + persons + RefMaster type lookup)
    vp_owners = extract_beneficial_owners(vp_engine)
    owner_rows = []
    for r in vp_owners:
        transformed = transform_beneficial_owner(r, entity_id_by_vp_key, person_id_by_vp_key, refcode_types, report)
        if transformed is not None:
            owner_rows.append(transformed)
    loaded = load_beneficial_owners(sb_engine, owner_rows, dry_run=dry_run)
    report.record_entity("beneficial_owners", len(vp_owners), loaded)

    report.print_summary()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="PBI-38 Viewpoint ETL — Checkpoint A")
    parser.add_argument("--dry-run", action="store_true", help="Validate and log intended writes without touching Supabase")
    args = parser.parse_args()

    report = run(dry_run=args.dry_run)

    os.makedirs("etl/reports", exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report.save(f"etl/reports/checkpoint_a_{timestamp}.json")

    # Only exit non-zero on actual runs with errors; dry-run always exits 0 (validation is informational)
    if not args.dry_run and report.has_errors():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
