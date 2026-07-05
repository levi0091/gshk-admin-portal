import argparse
import os
from datetime import datetime, timezone

from sqlalchemy import text

from etl.db import get_viewpoint_engine, get_supabase_engine
from etl.reconciliation import ReconciliationReport
from etl.extract.checkpoint_b import (
    extract_share_capital, extract_business_names, extract_entity_name_changes,
    extract_share_transactions, extract_share_certificates,
)
from etl.transform.checkpoint_b import (
    transform_share_classes, transform_business_name, transform_entity_name_change,
    transform_share_transaction, transform_share_certificate, derive_shareholdings,
)
from etl.load.checkpoint_b import (
    load_share_classes, load_business_names, load_entity_name_changes,
    load_share_transactions, load_share_certificates, load_shareholdings,
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

    # Parents (entities, persons) already loaded by Checkpoint A — resolvable now.
    entity_id_by_vp_key = _vp_key_to_id(sb_engine, "entities")
    person_id_by_vp_key = _vp_key_to_id(sb_engine, "persons")
    refcode_types = _refcode_types(vp_engine)

    # 1. share_classes (needs entities)
    vp_share_capital = extract_share_capital(vp_engine)
    share_class_rows = transform_share_classes(vp_share_capital, entity_id_by_vp_key, report)
    loaded = load_share_classes(sb_engine, share_class_rows, dry_run=dry_run)
    report.record_entity("share_classes", len(vp_share_capital), loaded if not dry_run else len(share_class_rows))

    # 2. business_names (needs entities)
    vp_bus = extract_business_names(vp_engine)
    bus_rows = [r for r in (transform_business_name(x, entity_id_by_vp_key, report) for x in vp_bus) if r is not None]
    loaded = load_business_names(sb_engine, bus_rows, dry_run=dry_run)
    report.record_entity("business_names", len(vp_bus), loaded if not dry_run else len(bus_rows))

    # 3. entity_name_changes (needs entities)
    vp_nc = extract_entity_name_changes(vp_engine)
    nc_rows = [r for r in (transform_entity_name_change(x, entity_id_by_vp_key, report) for x in vp_nc) if r is not None]
    loaded = load_entity_name_changes(sb_engine, nc_rows, dry_run=dry_run)
    report.record_entity("entity_name_changes", len(vp_nc), loaded if not dry_run else len(nc_rows))

    if dry_run:
        # share_class_id for the detail tables resolves against the share_classes
        # rows written THIS run — unavailable in dry-run. Stop here (mirrors
        # Checkpoint A's dry-run short-circuit before self-produced FKs).
        report.print_summary()
        return report

    # Resolve share_class_id from what was actually written.
    share_class_id_by_vp_key = _vp_key_to_id(sb_engine, "share_classes")

    # 4. share_transactions (full ledger) — reused by shareholdings derivation
    vp_tx = extract_share_transactions(vp_engine)
    tx_rows = [
        r for r in (
            transform_share_transaction(x, entity_id_by_vp_key, person_id_by_vp_key,
                                        refcode_types, share_class_id_by_vp_key, report)
            for x in vp_tx
        ) if r is not None
    ]
    loaded = load_share_transactions(sb_engine, tx_rows, dry_run=dry_run)
    report.record_entity("share_transactions", len(vp_tx), loaded)

    # 5. share_certificates
    vp_cert = extract_share_certificates(vp_engine)
    cert_rows = [
        r for r in (
            transform_share_certificate(x, entity_id_by_vp_key, person_id_by_vp_key,
                                        refcode_types, share_class_id_by_vp_key, report)
            for x in vp_cert
        ) if r is not None
    ]
    loaded = load_share_certificates(sb_engine, cert_rows, dry_run=dry_run)
    report.record_entity("share_certificates", len(vp_cert), loaded)

    # 6. shareholdings (derived from the raw transaction ledger). source_count is
    # the number of derived holding rows (produced-vs-loaded convention, same as
    # Checkpoint A's Compliance ID-doc line) — the raw transaction count would
    # false-flag MISMATCH on every healthy run due to the many-to-one fan-in.
    holding_rows = derive_shareholdings(
        vp_tx, entity_id_by_vp_key, person_id_by_vp_key, refcode_types,
        share_class_id_by_vp_key, report)
    loaded = load_shareholdings(sb_engine, holding_rows, dry_run=dry_run)
    report.record_entity("shareholdings", len(holding_rows), loaded)

    report.print_summary()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="PBI-38 Viewpoint ETL — Checkpoint B")
    parser.add_argument("--dry-run", action="store_true", help="Validate and log intended writes without touching Supabase")
    args = parser.parse_args()

    report = run(dry_run=args.dry_run)

    os.makedirs("etl/reports", exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report.save(f"etl/reports/checkpoint_b_{timestamp}.json")

    # Only exit non-zero on actual runs with errors; dry-run always exits 0.
    if not args.dry_run and report.has_errors():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
