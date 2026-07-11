"""PBI-40 Block 3 — Checkpoint D orchestrator.

Restores the RefMaster corporate-party superset:
  1. Backfill the 68 non-client corporate parties into `entities`
     (is_client=false; is_corporate_party=true when actually referenced).
  2. Flag the client entities that also act as a corporate party.
  3. Repoint entity_officers/beneficial_owners/shareholdings.corporate_name
     (a VP RefCode) to a real corporate_entity_id FK.

Idempotent (ON CONFLICT DO UPDATE + guarded UPDATEs). `--dry-run` validates and
reports intended writes without touching Supabase. Reconciliation reports DB
post-state counts (not per-run rowcounts) so a re-run does not read as a MISMATCH.
"""
import argparse
import os
from datetime import datetime, timezone

from sqlalchemy import text

from etl.db import get_viewpoint_engine, get_supabase_engine
from etl.reconciliation import ReconciliationReport
from etl.extract.checkpoint_d import (
    extract_nonclient_corporates,
    extract_nonclient_corporate_addresses,
    extract_corporate_party_refcodes,
)
from etl.transform.checkpoint_d import pick_current_address_nr, transform_nonclient_corporate
from etl.load.checkpoint_d import (
    load_corporate_entities, flag_corporate_parties, repoint_corporate_entity_ids,
    REPOINT_TABLES,
)


def _address_ids(engine) -> dict[str, str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT vp_source_key, id FROM addresses WHERE vp_source_key IS NOT NULL"))
        return {r.vp_source_key: str(r.id) for r in rows}


def _group_addresses(addr_rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for r in addr_rows:
        grouped.setdefault(r["RefCode"], []).append(r)
    return grouped


def _scalar(engine, sql: str, params: dict | None = None) -> int:
    with engine.connect() as conn:
        return conn.execute(text(sql), params or {}).scalar() or 0


def run(dry_run: bool) -> ReconciliationReport:
    vp = get_viewpoint_engine()
    sb = get_supabase_engine()
    report = ReconciliationReport()

    address_id_by_vp_key = _address_ids(sb)
    corporates = extract_nonclient_corporates(vp)
    addresses_by_refcode = _group_addresses(extract_nonclient_corporate_addresses(vp))
    party_refcodes = set(extract_corporate_party_refcodes(vp))

    # 1. Backfill non-client corporate parties into entities.
    entity_rows = [
        transform_nonclient_corporate(
            row,
            pick_current_address_nr(addresses_by_refcode.get(row["RefCode"], [])),
            address_id_by_vp_key,
            party_refcodes,
            report,
        )
        for row in corporates
    ]
    load_corporate_entities(sb, entity_rows, dry_run=dry_run)

    if dry_run:
        report.record_entity("nonclient_corporate_entities", len(corporates), len(entity_rows))
        report.record_entity("corporate_party_refcodes", len(party_refcodes), len(party_refcodes))
        print("  (dry-run) skipping flag + repoint UPDATEs — they mutate loaded rows")
        report.print_summary()
        return report

    # 2. Flag client entities that also act as a corporate party.
    flag_corporate_parties(sb, list(party_refcodes), dry_run=False)

    # 3. Repoint corporate_name -> corporate_entity_id.
    repoint_corporate_entity_ids(sb, dry_run=False)

    # --- reconciliation (DB post-state) ---
    loaded_corp = _scalar(sb, "SELECT count(*) FROM entities WHERE is_client = false")
    report.record_entity("nonclient_corporate_entities", len(corporates), loaded_corp)

    # every entity whose vp_source_key is a corporate-party RefCode should be flagged
    expected_flagged = _scalar(
        sb, "SELECT count(*) FROM entities WHERE vp_source_key = ANY(:codes)",
        {"codes": list(party_refcodes)})
    actual_flagged = _scalar(sb, "SELECT count(*) FROM entities WHERE is_corporate_party = true")
    report.record_entity("corporate_parties_flagged", expected_flagged, actual_flagged)

    for t in REPOINT_TABLES:
        with_name = _scalar(
            sb, f"SELECT count(*) FROM {t} WHERE party_type='corporate' AND corporate_name IS NOT NULL")
        linked = _scalar(
            sb, f"SELECT count(*) FROM {t} WHERE corporate_entity_id IS NOT NULL")
        report.record_entity(f"repoint_{t}", with_name, linked)
        # log corporate rows whose corporate_name resolves to no entity (RefType='O',
        # or a RefCode outside the backfilled set) — kept as corporate_name only.
        with sb.connect() as conn:
            unresolved = conn.execute(text(f"""
                SELECT DISTINCT corporate_name FROM {t}
                WHERE party_type='corporate' AND corporate_name IS NOT NULL
                  AND corporate_entity_id IS NULL
            """)).fetchall()
        for (code,) in unresolved:
            report.record_error(f"repoint_{t}", code, "corporate_name resolves to no entities row")

    report.print_summary()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="PBI-40 Viewpoint ETL — Checkpoint D (party master)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate and report intended writes without touching Supabase")
    args = parser.parse_args()

    report = run(dry_run=args.dry_run)

    os.makedirs("etl/reports", exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report.save(f"etl/reports/checkpoint_d_{timestamp}.json")

    # Non-zero exit only on a real run that logged errors (good rows still loaded);
    # dry-run always exits 0. Mirrors Checkpoints A-C.
    if not args.dry_run and report.has_errors():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
