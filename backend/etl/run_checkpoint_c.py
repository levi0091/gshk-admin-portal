import argparse
import os
from datetime import datetime, timezone

from sqlalchemy import text

from etl.db import get_viewpoint_engine, get_supabase_engine
from etl.reconciliation import ReconciliationReport
from etl.extract.checkpoint_c import (
    extract_contacts, extract_charges, extract_tasks, extract_address_assignments,
    extract_form_filings, extract_event_log, extract_ref_status, extract_vp_users,
    extract_events_form,
)
from etl.transform.checkpoint_c import (
    transform_contact, transform_charge, transform_task, transform_address_assignment,
    transform_form_filing, transform_event_log_row, transform_ref_status_row,
    transform_audit_form_filing,
)
from etl.load.checkpoint_c import (
    load_contacts, load_charges, load_tasks, load_address_assignments,
    load_form_filings, load_audit_log, load_audit_form_filings,
    backfill_primary_addresses,
)


def _vp_key_to_id(engine, table: str) -> dict[str, str]:
    with engine.connect() as conn:
        rows = conn.execute(text(f"SELECT vp_source_key, id FROM {table} WHERE vp_source_key IS NOT NULL"))
        return {r.vp_source_key: str(r.id) for r in rows}


def _refcode_types(engine) -> dict[str, str]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT RefCode, RefType FROM RefMaster"))
        return {r.RefCode: r.RefType for r in rows}


def _audit_ids(engine) -> dict[str, str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT vp_source_key, id FROM audit_log WHERE vp_source_key IS NOT NULL")
        )
        return {r.vp_source_key: str(r.id) for r in rows}


def run(dry_run: bool) -> ReconciliationReport:
    vp_engine = get_viewpoint_engine()
    sb_engine = get_supabase_engine()
    report = ReconciliationReport()

    # Parents (entities, persons, addresses) already loaded by Checkpoints A/B.
    entity_id_by_vp_key = _vp_key_to_id(sb_engine, "entities")
    person_id_by_vp_key = _vp_key_to_id(sb_engine, "persons")
    address_id_by_vp_key = _vp_key_to_id(sb_engine, "addresses")
    refcode_types = _refcode_types(vp_engine)
    uname_by_ucode = extract_vp_users(vp_engine)

    # 1. contacts (needs entities/persons)
    vp_contacts = extract_contacts(vp_engine)
    contact_rows = [
        r for r in (
            transform_contact(x, entity_id_by_vp_key, person_id_by_vp_key, refcode_types, report)
            for x in vp_contacts
        ) if r is not None
    ]
    loaded = load_contacts(sb_engine, contact_rows, dry_run=dry_run)
    report.record_entity("contacts", len(vp_contacts), loaded if not dry_run else len(contact_rows))

    # 2. charges (needs entities)
    vp_charges = extract_charges(vp_engine)
    charge_rows = [
        r for r in (transform_charge(x, entity_id_by_vp_key, report) for x in vp_charges)
        if r is not None
    ]
    loaded = load_charges(sb_engine, charge_rows, dry_run=dry_run)
    report.record_entity("charges", len(vp_charges), loaded if not dry_run else len(charge_rows))

    # 3. tasks (needs entities/persons)
    vp_tasks = extract_tasks(vp_engine)
    task_rows = [
        r for r in (
            transform_task(x, entity_id_by_vp_key, person_id_by_vp_key, refcode_types, report)
            for x in vp_tasks
        ) if r is not None
    ]
    loaded = load_tasks(sb_engine, task_rows, dry_run=dry_run)
    report.record_entity("tasks", len(vp_tasks), loaded if not dry_run else len(task_rows))

    # 4. address_assignments (needs entities/persons/addresses)
    vp_addr = extract_address_assignments(vp_engine)
    addr_rows = [
        r for r in (
            transform_address_assignment(
                x, entity_id_by_vp_key, person_id_by_vp_key, refcode_types,
                address_id_by_vp_key, report)
            for x in vp_addr
        ) if r is not None
    ]
    loaded = load_address_assignments(sb_engine, addr_rows, dry_run=dry_run)
    report.record_entity("address_assignments", len(vp_addr), loaded if not dry_run else len(addr_rows))

    # 5. form_filings (needs entities)
    vp_forms = extract_form_filings(vp_engine)
    form_rows = [
        r for r in (transform_form_filing(x, entity_id_by_vp_key, report) for x in vp_forms)
        if r is not None
    ]
    loaded = load_form_filings(sb_engine, form_rows, dry_run=dry_run)
    report.record_entity("form_filings", len(vp_forms), loaded if not dry_run else len(form_rows))

    # 6. audit_log (EventLog + RefStatus) — no drops, insert-only via DO NOTHING.
    vp_events = extract_event_log(vp_engine)
    audit_rows = [transform_event_log_row(r, entity_id_by_vp_key, uname_by_ucode) for r in vp_events]
    vp_ref_status = extract_ref_status(vp_engine)
    audit_rows += [transform_ref_status_row(r, entity_id_by_vp_key, uname_by_ucode) for r in vp_ref_status]
    inserted = load_audit_log(sb_engine, audit_rows, dry_run=dry_run)
    # Honest DO-NOTHING convention: source=produced rows this run, loaded=newly
    # inserted. On a re-run against already-imported history, loaded legitimately
    # drops to 0 (or partial) — that is NOT a failure; reconcile against the DB
    # total instead of expecting loaded == source on every run. See README.
    report.record_entity("audit_log", len(audit_rows), inserted if not dry_run else len(audit_rows))

    if dry_run:
        # audit_form_filings and the address backfill both need FKs that only
        # exist once THIS run's rows are actually written (audit_log ids,
        # form_filings ids, address_assignments rows) — unavailable in
        # dry-run. Stop here (mirrors Checkpoints A/B's dry-run short-circuit).
        print("  (dry-run) skipping audit_form_filings + address backfill — need this run's writes")
        report.print_summary()
        return report

    # 7. audit_form_filings (needs this run's audit_log + form_filings ids)
    audit_ids = _audit_ids(sb_engine)
    filing_ids = _vp_key_to_id(sb_engine, "form_filings")
    vp_events_form = extract_events_form(vp_engine)
    aff_rows = [
        r for r in (
            transform_audit_form_filing(x, audit_ids, filing_ids, report)
            for x in vp_events_form
        ) if r is not None
    ]
    loaded = load_audit_form_filings(sb_engine, aff_rows, dry_run=dry_run)
    report.record_entity("audit_form_filings", len(vp_events_form), loaded)

    # 8. backfill primary addresses (needs this run's address_assignments)
    counts = backfill_primary_addresses(sb_engine, dry_run=False)
    report.record_entity(
        "entities_registered_address_backfill", counts["entities_updated"], counts["entities_updated"])
    report.record_entity(
        "persons_residential_address_backfill", counts["persons_updated"], counts["persons_updated"])

    report.print_summary()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="PBI-38 Viewpoint ETL — Checkpoint C")
    parser.add_argument("--dry-run", action="store_true", help="Validate and log intended writes without touching Supabase")
    args = parser.parse_args()

    report = run(dry_run=args.dry_run)

    os.makedirs("etl/reports", exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report.save(f"etl/reports/checkpoint_c_{timestamp}.json")

    # Only exit non-zero on actual runs with errors; dry-run always exits 0.
    if not args.dry_run and report.has_errors():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
