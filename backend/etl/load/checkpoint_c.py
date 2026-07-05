from sqlalchemy.engine import Engine
from etl.upsert import upsert_rows


def load_contacts(engine: Engine, rows: list[dict], dry_run: bool = False) -> int:
    return upsert_rows(engine, "contacts", rows, dry_run=dry_run)


def load_charges(engine: Engine, rows: list[dict], dry_run: bool = False) -> int:
    return upsert_rows(engine, "charges", rows, dry_run=dry_run)


def load_tasks(engine: Engine, rows: list[dict], dry_run: bool = False) -> int:
    return upsert_rows(engine, "tasks", rows, dry_run=dry_run)
