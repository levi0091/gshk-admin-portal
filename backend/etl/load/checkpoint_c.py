from sqlalchemy.engine import Engine
from etl.upsert import upsert_rows


def load_contacts(engine: Engine, rows: list[dict], dry_run: bool = False) -> int:
    return upsert_rows(engine, "contacts", rows, dry_run=dry_run)


def load_charges(engine: Engine, rows: list[dict], dry_run: bool = False) -> int:
    return upsert_rows(engine, "charges", rows, dry_run=dry_run)


def load_tasks(engine: Engine, rows: list[dict], dry_run: bool = False) -> int:
    return upsert_rows(engine, "tasks", rows, dry_run=dry_run)


def load_address_assignments(engine: Engine, rows: list[dict], dry_run: bool = False) -> int:
    return upsert_rows(engine, "address_assignments", rows, dry_run=dry_run)


def load_form_filings(engine: Engine, rows: list[dict], dry_run: bool = False) -> int:
    return upsert_rows(engine, "form_filings", rows, dry_run=dry_run)


def backfill_primary_addresses(engine: Engine, dry_run: bool = False) -> dict:
    """Point entities.registered_address_id at the current Registered Office
    assignment and persons.residential_address_id at the current Residential
    Address assignment (latest effective_date wins). Runs after the
    address_assignments load; Viewpoint's own ContactAddrCode/ResAddress are
    blank in all live rows, so this history-derived linkage is the only source."""
    if dry_run:
        return {"entities_updated": 0, "persons_updated": 0}
    from sqlalchemy import text
    entities_sql = text("""
        UPDATE entities e SET registered_address_id = pick.address_id
        FROM (
            SELECT DISTINCT ON (entity_id) entity_id, address_id
            FROM address_assignments
            WHERE party_type = 'entity' AND address_role = 'RO' AND cancelled_date IS NULL
            ORDER BY entity_id, effective_date DESC NULLS LAST
        ) pick
        WHERE e.id = pick.entity_id
    """)
    persons_sql = text("""
        UPDATE persons p SET residential_address_id = pick.address_id
        FROM (
            SELECT DISTINCT ON (person_id) person_id, address_id
            FROM address_assignments
            WHERE party_type = 'person' AND address_role = 'RA' AND cancelled_date IS NULL
            ORDER BY person_id, effective_date DESC NULLS LAST
        ) pick
        WHERE p.id = pick.person_id
    """)
    with engine.begin() as conn:
        e_count = conn.execute(entities_sql).rowcount or 0
        p_count = conn.execute(persons_sql).rowcount or 0
    return {"entities_updated": e_count, "persons_updated": p_count}
