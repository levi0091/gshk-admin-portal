"""Re-run the address slice of Checkpoint A against Viewpoint.

    python -m etl.reimport_addresses              # dry run, writes nothing
    python -m etl.reimport_addresses --apply      # writes to DATABASE_URL

WHY THIS EXISTS, AND WHY IT IS NOT A REPAIR SCRIPT. `transform_address` used
to join Viewpoint's `Address3`, `Address4` and `Address5` into a single
`line3`. CR caps every address line at 60 characters, so that one join left
874 of 8,035 stored addresses unfilable while the Viewpoint source held only
25 such lines -- the corruption was manufactured entirely by the loader.

A script that patched the 874 rows would only ever prove that the patch works.
Re-running the fixed loader over the real book proves the LOADER works, which
is what PROD depends on when it is first loaded. So the damaged rows are not
repaired; they are re-derived from source.

WHY ONLY ADDRESSES, AND NOT `python -m etl.run_all`. DEV is 790 MB and
`audit_log` is 706 MB of it. A full run rewrites that table from ~182k
EventLog rows for no benefit to this fix, and it is exactly the table that
previously took DEV read-only on its disk quota. Addresses carry no FK
dependencies (`run_checkpoint_a` loads them first, before anything points at
them), and the derived steps -- `backfill_timestamps`, `backfill_audit_context`
-- never read them. So this slice stands alone.

WHY IT DOES NOT MOVE ANY FOREIGN KEY. `load_addresses` upserts
`ON CONFLICT (vp_source_key) DO UPDATE`, so a row keeps its id;
`entities.registered_address_id` and `persons.residential_address_id` go on
pointing at the same rows. Nothing is deleted and nothing is re-keyed. Rows
with no `vp_source_key` -- the 3 created through Add Company, and the seeded
`tpsi_test:` fixtures -- carry keys Viewpoint does not have, so the upsert
cannot reach them.
"""
import argparse
import os
import sys

from dotenv import load_dotenv

from etl.config import get_viewpoint_conn_str
from etl.db import get_supabase_engine
from etl.extract.checkpoint_a import extract_addresses
from etl.load.checkpoint_a import load_addresses
from etl.transform.checkpoint_a import transform_address

from sqlalchemy import create_engine

#: CR's per-line cap. `nar1_schema.json` gives max_length 60 for flatFlrBlk,
#: bldg, stEstLotVlg and dstCtyStatePostal alike.
LIMIT = 60

#: Substrings that mean "this is production" in a connection string. Same
#: guard as scripts/seed_tpsi_test_data.py -- one spelling of the rule.
_PROD_MARKERS = ("prod", "-prd", "production")

_LINE_COLUMNS = ("line1", "line2", "line3")


def lines_over_limit(row: dict) -> list[str]:
    """Which of a transformed row's street lines exceed CR's cap."""
    return [c for c in _LINE_COLUMNS if len(row.get(c) or "") > LIMIT]


def summarise(rows: list[dict]) -> dict:
    """Counts for the before/after comparison — rows, not lines.

    A row with two over-long lines is one unfilable address, not two, and
    counting lines would overstate the problem and then overstate the fix.
    """
    over = [r for r in rows if lines_over_limit(r)]
    longest = max(
        (len(r.get(c) or "") for r in rows for c in _LINE_COLUMNS),
        default=0,
    )
    return {
        "total": len(rows),
        "over_limit": len(over),
        "over_limit_keys": [r["vp_source_key"] for r in over],
        "longest": longest,
    }


def assert_safe_target(database_url: str) -> None:
    """Refuse to write anywhere that might be production.

    An unset URL is refused too: "no marker found" must not read as "not
    production, carry on".
    """
    if not database_url:
        sys.exit("REFUSING: DATABASE_URL is not set.")
    if any(marker in database_url.lower() for marker in _PROD_MARKERS):
        sys.exit(
            "REFUSING: DATABASE_URL looks like production. PROD is loaded by "
            "`etl.run_all` at cutover, with the fixed transform, and never by "
            "this script."
        )


def main(apply: bool = False) -> dict:
    load_dotenv()
    database_url = os.environ.get("DATABASE_URL", "")
    assert_safe_target(database_url)

    vp_engine = create_engine(get_viewpoint_conn_str())
    source = extract_addresses(vp_engine)
    rows = [transform_address(r) for r in source]

    stats = summarise(rows)
    print(f"source rows            {stats['total']}")
    print(f"lines over {LIMIT} chars   {stats['over_limit']}")
    print(f"longest line           {stats['longest']}")

    if stats["over_limit_keys"]:
        # Named, not merely counted. These are rows where a SINGLE Viewpoint
        # line already exceeds the cap, so no packing rule can fix them --
        # they need a human on the Company or Person profile. Leaving them
        # unnamed is how they stay unfixed.
        print(
            f"\nAddrNr values still over {LIMIT} after re-derivation "
            f"(fix these by hand):\n  "
            + ", ".join(stats["over_limit_keys"])
        )

    if not apply:
        # Plain ASCII: this prints to a cp1252 console on the machine that
        # holds the Viewpoint connection, and an em-dash arrives as mojibake.
        print("\ndry run - nothing written. Re-run with --apply to load.")
        return stats

    loaded = load_addresses(get_supabase_engine(), rows, dry_run=False)
    print(f"\nupserted {loaded} address rows")
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="write to DATABASE_URL (default is a dry run)",
    )
    main(apply=parser.parse_args().apply)
