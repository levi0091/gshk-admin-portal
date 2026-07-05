from sqlalchemy.engine import Engine
from etl.upsert import upsert_rows


def load_share_classes(engine: Engine, rows: list[dict], dry_run: bool = False) -> int:
    return upsert_rows(engine, "share_classes", rows, dry_run=dry_run)
