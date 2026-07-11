"""PBI-40 Block 3 — Checkpoint D load (idempotent writes to Supabase)."""
from sqlalchemy import text
from sqlalchemy.engine import Engine

from etl.upsert import upsert_rows

# Tables whose corporate rows carry a corporate_name (= VP RefCode) that we
# repoint to a real entities row. beneficial_owners is included for completeness
# (its single corporate row has a NULL corporate_name in VP, so it repoints 0).
REPOINT_TABLES = ["entity_officers", "beneficial_owners", "shareholdings"]


def load_corporate_entities(engine: Engine, rows: list[dict], dry_run: bool = False) -> int:
    """Upsert the backfilled non-client corporate parties into `entities`
    (ON CONFLICT (vp_source_key) DO UPDATE — reuses the migration-004 index)."""
    return upsert_rows(engine, "entities", rows, dry_run=dry_run)


def flag_corporate_parties(engine: Engine, refcodes: list[str], dry_run: bool = False) -> int:
    """Set entities.is_corporate_party=true for every entity whose vp_source_key
    is a corporate-party RefCode (the 219 client entities; non-clients are already
    flagged at insert). Idempotent — a re-run flips 0 rows."""
    if dry_run or not refcodes:
        return 0
    sql = text("""
        UPDATE entities
        SET is_corporate_party = true
        WHERE vp_source_key = ANY(:codes)
          AND is_corporate_party = false
    """)
    with engine.begin() as conn:
        return conn.execute(sql, {"codes": list(refcodes)}).rowcount or 0


def repoint_corporate_entity_ids(engine: Engine, dry_run: bool = False) -> dict[str, int]:
    """Set <table>.corporate_entity_id from the resolved corporate_name → the
    matching entities.vp_source_key, for corporate-party rows. corporate_name is
    retained for traceability. Idempotent (IS DISTINCT FROM guard). Returns the
    per-table number of rows changed this run."""
    if dry_run:
        return {t: 0 for t in REPOINT_TABLES}
    counts: dict[str, int] = {}
    with engine.begin() as conn:
        for t in REPOINT_TABLES:
            sql = text(f"""
                UPDATE {t} x
                SET corporate_entity_id = e.id
                FROM entities e
                WHERE x.party_type = 'corporate'
                  AND x.corporate_name IS NOT NULL
                  AND x.corporate_name = e.vp_source_key
                  AND x.corporate_entity_id IS DISTINCT FROM e.id
            """)
            counts[t] = conn.execute(sql).rowcount or 0
    return counts
