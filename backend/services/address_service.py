"""Address writes, with copy-on-write and CR's own limits.

TWO RULES, AND BOTH EXIST BECAUSE OF MEASURED DATA.

1. REFUSE WHAT CR WOULD REFUSE. Every address line CR accepts is capped at 60
   characters, and for a Hong Kong address its District is a controlled code
   rather than free text. Until now nothing in the portal could edit an
   address at all, and the ETL wrote 874 rows with a line over the cap; the
   fix is worth little if the new form can type the same data straight back
   in. So this mirrors `nar1_mapper._address` exactly: what fails here is what
   would have failed at CR, one round trip and one frozen snapshot later.

2. NEVER REWRITE A SHARED ROW. `addresses` rows are shared: 4,446 companies
   point at GSHK's registered office, because GSHK provides registered-office
   services and its clients' registered office really is that address. Editing
   that row in place to fix ONE company would silently change the registered
   office of 4,445 others. So a row with more than one referent is copied and
   repointed, and only a row this record alone uses is edited in place.
"""
from typing import Optional

from services.tpsi.forms.cr_vocabularies import resolve_country, resolve_district

#: CR's per-line cap — `nar1_schema.json` gives max_length 60 for flatFlrBlk,
#: bldg, stEstLotVlg and dstCtyStatePostal alike.
LIMIT = 60

LINE_FIELDS = ("line1", "line2", "line3")

#: The columns the district slot is built from, in the order `nar1_mapper`
#: joins them. Kept in one place so the two cannot drift.
DISTRICT_FIELDS = ("city", "state_region", "postal_code")

#: What `resolve_country` returns for Hong Kong however it was typed — "HK",
#: "HKG" and "Hong Kong" all land here. Compare against THIS, never the raw
#: stored string.
HKG_CR_CODE = "HKG"

#: Kept for callers that still import it. The alpha-2 the column mostly holds.
HKG = "HK"


class AddressError(ValueError):
    """Refused before any write. Surfaces as a 422."""


def district_of(payload: dict) -> str:
    """The single value CR receives as `dstCtyStatePostal`.

    G-FlowDesk stores three columns where CR has one box, so the check has to
    run on the joined value — exactly as `nar1_mapper._address` builds it.
    """
    return " ".join(
        part for part in (payload.get(f) for f in DISTRICT_FIELDS)
        if part and str(part).strip()
    ).strip()


def validate(payload: dict) -> None:
    """Raise AddressError on anything CR would reject. Names the offender."""
    for field in LINE_FIELDS:
        value = payload.get(field) or ""
        if len(value) > LIMIT:
            raise AddressError(
                f"{field} is {len(value)} characters; the Companies Registry "
                f"accepts at most {LIMIT}. Move the extra words onto another "
                f"address line rather than shortening them."
            )

    country = (payload.get("country") or "").strip()
    if not country:
        raise AddressError(
            "country is required — the Companies Registry will not accept an "
            "address without one."
        )

    # The country must be one CR HAS A CODE FOR, not merely present.
    #
    # Being non-empty was the only check, and it let 'HK-CH' through — a
    # Viewpoint code for 香港 that CR has never heard of. The address saved
    # cleanly and the return died weeks later at Data Verification, which is
    # precisely the failure this service exists to move forward in time.
    cr_code = resolve_country(country)
    if cr_code is None:
        raise AddressError(
            f"{country!r} is not a country or region the Companies Registry "
            "has a code for. Pick one from the list — CR's own Country & "
            "Region sheet is the only set it accepts, and a filing sent with "
            "anything else is refused after the fee is taken."
        )

    district = district_of(payload)
    if len(district) > LIMIT:
        raise AddressError(
            f"district is {len(district)} characters; the Companies Registry "
            f"accepts at most {LIMIT}."
        )

    # Only Hong Kong. Everywhere else CR really does take free text, and
    # validating an overseas address against HK's district list would reject
    # every foreign director — which is most of the ones that need fixing.
    #
    # Compared on the RESOLVED code: this used to test the raw string against
    # "HK", so an address stored as "HKG" or "Hong Kong" — 7 real rows —
    # skipped the district check altogether.
    if cr_code == HKG_CR_CODE and district and resolve_district(district) is None:
        raise AddressError(
            f"{district!r} is not a Hong Kong district the Companies Registry "
            "recognises. Pick one of its District codes — they are the name "
            "with the spaces removed, so 'Wan Chai' is 'WANCHAI'."
        )


def normalise(payload: dict) -> dict:
    """Store what CR wants, accept what a person types.

    CR's District code is the district name with its spaces removed, so
    "Wan Chai" resolves perfectly well to "WANCHAI" — refusing it would make
    the operator guess CR's spelling. Resolving it on the way in means the
    stored value is already the one that will be filed, and `nar1_mapper` has
    nothing left to fix up.

    Only for Hong Kong: elsewhere the district is free text with no code to
    resolve to, and normalising "Nicosia" would corrupt it.
    """
    out = dict(payload)
    country = (out.get("country") or "").strip().upper()
    if country != HKG:
        return out

    district = district_of(out)
    code = resolve_district(district) if district else None
    if code:
        # The district lives across three columns; the resolved code is one
        # value, so it goes in the first and the others are cleared rather
        # than left to re-join into something CR never saw.
        out["city"] = code
        out["state_region"] = None
        out["postal_code"] = None
    return out


def plan(reference_count: int) -> str:
    """`update` to edit the row in place, `copy` to make a new one.

    Zero referents means this record has no address yet, which is also a copy:
    there is nothing to edit.
    """
    return "update" if reference_count == 1 else "copy"


def count_references(sb, address_id: Optional[str]) -> int:
    """How many companies and people point at this address row."""
    if not address_id:
        return 0
    entities = (
        sb.table("entities").select("id", count="exact")
        .eq("registered_address_id", address_id).limit(1).execute()
    )
    persons = (
        sb.table("persons").select("id", count="exact")
        .eq("residential_address_id", address_id).limit(1).execute()
    )
    return (entities.count or 0) + (persons.count or 0)


def save(sb, *, owner_table: str, owner_id: str, owner_column: str,
         current_address_id: Optional[str], payload: dict) -> dict:
    """Write the address for one company or person.

    Returns the new address row plus the facts the audit trail needs to explain
    what happened: `copied_from` is the row that was left alone, and
    `shared_by` is how many records still use it. Without those, the trail
    shows an address changing with no account of why its other referents did
    not change too.
    """
    validate(payload)

    columns = {k: (v or None) for k, v in normalise(payload).items()}
    references = count_references(sb, current_address_id)

    if plan(references) == "update":
        row = (
            sb.table("addresses").update(columns)
            .eq("id", current_address_id).execute()
        ).data[0]
        return {"address": row, "copied_from": None, "shared_by": references}

    row = sb.table("addresses").insert(columns).execute().data[0]
    sb.table(owner_table).update({owner_column: row["id"]}).eq("id", owner_id).execute()
    return {
        "address": row,
        "copied_from": current_address_id,
        "shared_by": references,
    }
