from sqlalchemy.engine import Engine
from etl.upsert import upsert_rows


def load_addresses(engine: Engine, rows: list[dict], dry_run: bool = False) -> int:
    return upsert_rows(engine, "addresses", rows, dry_run=dry_run)
