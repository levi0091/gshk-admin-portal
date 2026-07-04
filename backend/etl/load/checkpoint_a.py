from sqlalchemy.engine import Engine
from etl.upsert import upsert_rows


def load_addresses(engine: Engine, rows: list[dict], dry_run: bool = False) -> int:
    return upsert_rows(engine, "addresses", rows, dry_run=dry_run)


def load_persons(engine: Engine, rows: list[dict], dry_run: bool = False) -> int:
    return upsert_rows(engine, "persons", rows, dry_run=dry_run)


def load_entities(engine: Engine, rows: list[dict], dry_run: bool = False) -> int:
    return upsert_rows(engine, "entities", rows, dry_run=dry_run)


def load_identity_documents(engine: Engine, rows: list[dict], dry_run: bool = False) -> int:
    return upsert_rows(engine, "person_identity_documents", rows, dry_run=dry_run)


def load_entity_officers(engine: Engine, rows: list[dict], dry_run: bool = False) -> int:
    return upsert_rows(engine, "entity_officers", rows, dry_run=dry_run)


def load_company_secretaries(engine: Engine, rows: list[dict], dry_run: bool = False) -> int:
    return upsert_rows(engine, "company_secretaries", rows, dry_run=dry_run)
