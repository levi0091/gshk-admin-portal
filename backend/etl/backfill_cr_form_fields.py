"""Backfill the columns migration 028 added, from Viewpoint.

    python -m etl.backfill_cr_form_fields [--apply]

Dry run by default: prints what would change and writes nothing.

WHY A SLICE AND NOT `run_all`. `audit_log` is 706 MB of a 790 MB budget, and a
full run rewrites it. This touches three tables by primary key and nothing
else, which is the same discipline as `etl/reimport_addresses.py`.

WHAT IT CORRECTS

  share_classes.issued_amount   <- Share_Capital.StatedCap
      CR's "Total Amount". Never extracted until now, so the column has always
      been NULL while `total_issued` (a share COUNT) stood in for it. The two
      differ on 60 of Viewpoint's 5,740 rows.

  persons.former_name           <- Compliance.FormerName        (corrective)
  persons.former_name_zh        <- Compliance.ChnsFormerName
  persons.alias_en              <- Compliance.Aliases
  persons.alias_zh              <- Compliance.ChnsAliases
      The transform used to be `FormerName or Aliases` -- one column for two
      different facts. Where a person's `former_name` actually holds an alias,
      this moves it to `alias_en` and clears `former_name`. Nothing is lost:
      the value moves, it is not deleted.

Idempotent: re-running writes the same values. Chunked, because Postgres caps
a statement at 65,535 bind parameters.
"""
import argparse
from decimal import Decimal, ROUND_HALF_UP

from psycopg2.extras import execute_values
from sqlalchemy import text

from etl.db import get_supabase_engine, get_viewpoint_engine
from services.cr_forms.record_types import RECORD_TYPE_CODES

#: Rows per statement. Well under Postgres' 65,535 bind-parameter ceiling at
#: five params per row.
#:
#: These are bulk `UPDATE ... FROM (VALUES ...)` rather than one statement per
#: row on purpose. The first version issued ~10,000 single-row UPDATEs and took
#: an estimated 35 minutes, spending almost all of it "idle in transaction"
#: waiting on pooler round trips -- while holding a write transaction open on a
#: shared DEV database. Latency, not Postgres, was the cost.
CHUNK = 1000


#: What share_classes.issued_amount stores: numeric(20,4).
_STORED_PRECISION = Decimal("0.0001")


def _quantise(value):
    """A money value at the precision the column keeps, for comparison only."""
    if value is None:
        return None
    return Decimal(value).quantize(_STORED_PRECISION, rounding=ROUND_HALF_UP)


def _chunks(rows, size=CHUNK):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def _bulk_update(sb, sql: str, rows: list[tuple], template: str) -> None:
    """One UPDATE ... FROM (VALUES ...) per chunk, via psycopg2."""
    raw = sb.raw_connection()
    try:
        with raw.cursor() as cur:
            for chunk in _chunks(rows):
                execute_values(cur, sql, chunk, template=template)
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def backfill_share_capital(vp, sb, apply: bool) -> dict:
    with vp.connect() as conn:
        source = {
            f"{r.EntCode}:{r.ShareClass}": r.StatedCap
            for r in conn.execute(text(
                "SELECT EntCode, ShareClass, StatedCap FROM Share_Capital "
                "WHERE StatedCap IS NOT NULL"
            ))
        }

    with sb.connect() as conn:
        current = {
            r.vp_source_key: r.issued_amount
            for r in conn.execute(text(
                "SELECT vp_source_key, issued_amount FROM share_classes "
                "WHERE vp_source_key IS NOT NULL"
            ))
        }

    # Compare at the precision the column actually stores. Two Viewpoint rows
    # carry float representation error -- 1154999.999992784022 for what is
    # plainly HK$1,155,000 -- and numeric(20,4) rounds them on the way in. The
    # stored value is the more correct one; comparing against the raw source
    # would just rewrite the same two rows on every run, for ever.
    pending = [
        (key, value)
        for key, value in source.items()
        if key in current and _quantise(current[key]) != _quantise(value)
    ]
    if apply and pending:
        _bulk_update(
            sb,
            "UPDATE share_classes sc SET issued_amount = v.amount "
            "FROM (VALUES %s) AS v(key, amount) WHERE sc.vp_source_key = v.key",
            pending,
            "(%s, %s::numeric)",
        )
    return {"matched": len(source), "to_update": len(pending)}


def backfill_person_names(vp, sb, apply: bool) -> dict:
    with vp.connect() as conn:
        source = {
            r.AddrCode: r for r in conn.execute(text(
                "SELECT AddrCode, FormerName, ChnsFormerName, Aliases, ChnsAliases "
                "FROM Compliance WHERE AddrCode IS NOT NULL"
            ))
        }

    with sb.connect() as conn:
        current = list(conn.execute(text(
            "SELECT vp_source_key, former_name, former_name_zh, alias_en, alias_zh "
            "FROM persons WHERE vp_source_key IS NOT NULL"
        )))

    def clean(value):
        value = (value or "").strip()
        return value or None

    pending, unmerged = [], 0
    for row in current:
        vp_row = source.get(row.vp_source_key)
        if vp_row is None:
            continue
        want = {
            "former_name": clean(vp_row.FormerName),
            "former_name_zh": clean(vp_row.ChnsFormerName),
            "alias_en": clean(vp_row.Aliases),
            "alias_zh": clean(vp_row.ChnsAliases),
        }
        have = {
            "former_name": row.former_name, "former_name_zh": row.former_name_zh,
            "alias_en": row.alias_en, "alias_zh": row.alias_zh,
        }
        if want == have:
            continue
        # The old conflation showing itself: former_name holds what Viewpoint
        # calls an alias, and Viewpoint has no FormerName for this person.
        if have["former_name"] and not want["former_name"] \
                and have["former_name"] == want["alias_en"]:
            unmerged += 1
        pending.append((row.vp_source_key, want["former_name"],
                        want["former_name_zh"], want["alias_en"],
                        want["alias_zh"]))

    if apply and pending:
        _bulk_update(
            sb,
            "UPDATE persons p SET former_name = v.former_name, "
            "former_name_zh = v.former_name_zh, alias_en = v.alias_en, "
            "alias_zh = v.alias_zh "
            "FROM (VALUES %s) AS v(key, former_name, former_name_zh, "
            "alias_en, alias_zh) WHERE p.vp_source_key = v.key",
            pending,
            "(%s, %s::text, %s::text, %s::text, %s::text)",
        )
    return {"matched": len(current), "to_update": len(pending),
            "alias_unmerged_from_former_name": unmerged}


#: NAR1 s16 asks where the company's RECORDS are kept. The list -- and the
#: reasoning about which of Viewpoint's address types are registers and which
#: are seals or the company's own addresses -- lives in
#: `services/cr_forms/record_types.py`, because the API validates writes
#: against the same set and a second copy here would drift from it.
RECORD_LOCATION_ROLES = RECORD_TYPE_CODES


#: Country columns the profile screens render from CR's own list, and which
#: therefore have to HOLD one of its keys. `addresses.country` is already
#: alpha-2 in every one of DEV's 141 distinct values; these three were not.
_COUNTRY_COLUMNS = (
    ("entities", "incorporation_place"),
    ("person_identity_documents", "issuing_country"),
    ("addresses", "country"),
)


def normalise_country_columns(sb, apply: bool) -> dict:
    """Store the alpha-2 CR resolves to, wherever a country is spelt some
    other way.

    "Hong Kong" and "HKG" both FILE correctly -- `resolve_country` takes
    either -- so this is not a correctness fix for CR. It is a fix for the
    screen: the dropdowns are keyed by alpha-2, so 251 companies holding the
    literal "Hong Kong" rendered as "Hong Kong (not in list)", which invites
    an operator to "correct" a value that was never wrong.

    Values CR cannot resolve at all are LEFT ALONE, deliberately. 'HK-CH' is
    not a spelling of anything -- it is Viewpoint's code for a country CR has
    no code for, and it needs a human to re-pick it, not a guess from here.
    """
    from services.tpsi.forms.cr_vocabularies import to_alpha2

    changed, unresolvable = [], []
    with sb.connect() as conn:
        for table, column in _COUNTRY_COLUMNS:
            rows = conn.execute(text(
                f"SELECT id, {column} AS value FROM {table} "
                f"WHERE coalesce(btrim({column}), '') <> ''"
            ))
            for row in rows:
                alpha2 = to_alpha2(row.value)
                if alpha2 is None:
                    unresolvable.append((table, column, row.value))
                elif alpha2 != (row.value or "").strip():
                    changed.append((table, column, str(row.id), alpha2))

        if apply and changed:
            for table, column in _COUNTRY_COLUMNS:
                rows = [(rid, value) for t, c, rid, value in changed
                        if t == table and c == column]
                for chunk in _chunks(rows):
                    conn.execute(
                        text(f"UPDATE {table} AS t SET {column} = v.value "
                             f"FROM (SELECT unnest(:ids)::uuid AS id, "
                             f"unnest(:values) AS value) AS v "
                             f"WHERE t.id = v.id"),
                        {"ids": [r[0] for r in chunk],
                         "values": [r[1] for r in chunk]},
                    )
            conn.commit()

    return {"to_normalise": len(changed),
            "left_for_a_human": len(unresolvable)}


def backfill_company_type(sb, apply: bool) -> dict:
    """entities.company_type -> 'P' where the company HAS share capital.

    There is no Viewpoint source column for this. `Entity.EntType` is a
    GSHK-custom classification absent from every lookup, and `CW14` companies
    hold share capital, so it does not encode guarantee either.

    WHAT IS SAFE TO INFER, AND WHAT IS NOT. Having share capital rules out a
    company limited by guarantee, and no company in the book has more than 50
    members, which is what would make it public. So `P` is a verifiable
    inference for exactly those companies.

    The reverse is NOT. "No share capital => G" was tested and rejected: it
    yields ~219 guarantee companies, of which only a couple carry a name
    suggesting a real one, so it would stamp ~214 private companies as
    limited by guarantee on a statutory return. Those rows are LEFT NULL and
    surfaced through the profile highlighting instead -- their real defect is
    missing shareholders, and inventing a type would hide it.

    Only fills where the column is empty: a value someone has typed, legacy
    free text included, is never overwritten by a guess.
    """
    sql = """
        UPDATE entities e
           SET company_type = 'P'
         WHERE e.is_client
           AND coalesce(btrim(e.company_type), '') = ''
           AND EXISTS (SELECT 1 FROM share_classes s WHERE s.entity_id = e.id)
    """
    with sb.connect() as conn:
        pending = conn.execute(text(
            "SELECT count(*) FROM entities e WHERE e.is_client "
            "AND coalesce(btrim(e.company_type), '') = '' "
            "AND EXISTS (SELECT 1 FROM share_classes s WHERE s.entity_id = e.id)"
        )).scalar()
        left_null = conn.execute(text(
            "SELECT count(*) FROM entities e WHERE e.is_client "
            "AND coalesce(btrim(e.company_type), '') = '' "
            "AND NOT EXISTS (SELECT 1 FROM share_classes s WHERE s.entity_id = e.id)"
        )).scalar()
        if apply and pending:
            conn.execute(text(sql))
            conn.commit()
    return {"to_set_P": pending, "left_null_no_share_capital": left_null}


def backfill_correspondence_addresses(sb, apply: bool) -> dict:
    """entity_officers.correspondence_address_id from the RC assignments.

    Already in Postgres -- `address_assignments` imported Viewpoint's address
    roles, and `RC` (Correspondence Address) is its most populated: 8,049 for
    persons, 5,745 for entities. Nothing read it, so the NAR1 mapper filed the
    RESIDENTIAL address into CR's correspondence slot.
    """
    # A natural-person officer takes the person's RC; a body corporate takes
    # its own. Only current assignments, and only where the officer has none.
    sql = """
        UPDATE entity_officers eo
           SET correspondence_address_id = aa.address_id
          FROM address_assignments aa
         WHERE aa.address_role = 'RC'
           AND aa.is_current
           AND eo.correspondence_address_id IS NULL
           AND (
                 (eo.person_id IS NOT NULL AND aa.person_id = eo.person_id)
              OR (eo.person_id IS NULL AND eo.corporate_entity_id IS NOT NULL
                  AND aa.entity_id = eo.corporate_entity_id)
               )
    """
    with sb.connect() as conn:
        would = conn.execute(text("""
            SELECT count(DISTINCT eo.id)
              FROM entity_officers eo
              JOIN address_assignments aa
                ON aa.address_role = 'RC' AND aa.is_current
               AND ((eo.person_id IS NOT NULL AND aa.person_id = eo.person_id)
                 OR (eo.person_id IS NULL AND eo.corporate_entity_id IS NOT NULL
                     AND aa.entity_id = eo.corporate_entity_id))
             WHERE eo.correspondence_address_id IS NULL
        """)).scalar()

    if apply and would:
        with sb.begin() as conn:
            conn.execute(text(sql))
    return {"to_link": would}


def backfill_record_locations(sb, apply: bool) -> dict:
    """entity_record_locations from the statutory address assignments (s16)."""
    roles = ", ".join(f"'{r}'" for r in RECORD_LOCATION_ROLES)
    with sb.connect() as conn:
        would = conn.execute(text(f"""
            SELECT count(*) FROM (
                SELECT DISTINCT aa.entity_id, aa.address_role
                  FROM address_assignments aa
                 WHERE aa.address_role IN ({roles})
                   AND aa.is_current AND aa.entity_id IS NOT NULL
                   AND NOT EXISTS (
                       SELECT 1 FROM entity_record_locations erl
                        WHERE erl.entity_id = aa.entity_id
                          AND erl.record_type = aa.address_role)
            ) x
        """)).scalar()

    if apply and would:
        with sb.begin() as conn:
            # DISTINCT ON picks one address per (entity, register); the unique
            # constraint would reject a second, and Viewpoint occasionally
            # carries duplicates for the same role.
            conn.execute(text(f"""
                INSERT INTO entity_record_locations (entity_id, record_type, address_id)
                SELECT DISTINCT ON (aa.entity_id, aa.address_role)
                       aa.entity_id, aa.address_role, aa.address_id
                  FROM address_assignments aa
                 WHERE aa.address_role IN ({roles})
                   AND aa.is_current AND aa.entity_id IS NOT NULL
                 ORDER BY aa.entity_id, aa.address_role, aa.id
                ON CONFLICT (entity_id, record_type) DO NOTHING
            """))
    return {"to_insert": would}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="write the changes (default: dry run)")
    args = parser.parse_args()

    vp, sb = get_viewpoint_engine(), get_supabase_engine()
    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"[{mode}] backfilling migration 028 columns from Viewpoint\n")

    for name, fn in (("share_classes.issued_amount", backfill_share_capital),
                     ("persons name fields", backfill_person_names)):
        stats = fn(vp, sb, args.apply)
        detail = "  ".join(f"{k}={v}" for k, v in stats.items())
        print(f"  {name:32} {detail}")

    # These two read `address_assignments`, which already holds Viewpoint's
    # address roles -- no Viewpoint round trip needed.
    for name, fn in (("officer correspondence address", backfill_correspondence_addresses),
                     ("entity_record_locations (s16)", backfill_record_locations),
                     ("entities.company_type", backfill_company_type),
                     ("country columns -> alpha-2", normalise_country_columns)):
        stats = fn(sb, args.apply)
        detail = "  ".join(f"{k}={v}" for k, v in stats.items())
        print(f"  {name:32} {detail}")

    if not args.apply:
        print("\nnothing written. re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
