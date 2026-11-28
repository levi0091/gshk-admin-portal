"""Which correspondence address an ND2A appointment files (Levi 2026-11-28).

The "Add appointment" drawer used to ask "Correspondence address is the same as
the residential address". Unticked, it made staff re-type an address the profile
already holds, and filing inserted a duplicate `addresses` row. ND2A now follows
the Natural Person profile exactly as NAR1 and ND2B do: the staff member does
not type an address, they at most CHOOSE one the profile already has.

THE RULE, a pure function (`resolve`) over a loader's output (`for_persons`):

  CHOICES are the person's distinct correspondence addresses, deduplicated by
  CONTENT, not by id (the old drawer left the same text in several rows). They
  come from (a) the links on the person's CURRENT director / company-secretary /
  alternate-director rows, and (b) `person_addresses` rows of kind
  'correspondence'. A choice records which companies use it.

  1. the entry names an address and its content matches a choice -> "chosen"
  2. exactly one distinct address is IN USE                       -> "in_use"
  3. none in use and exactly one distinct address is RECORDED     -> "recorded"
  4. no choices at all                                            -> "none"
  5. anything else                                                -> "ambiguous"

WHAT IS PRINTED in `indvCorrAddr`: the person's home address when they file
residential or there is no choice at all ("none"); the resolved address for
chosen / in_use / recorded; NOTHING for an ambiguous profile (the mapper reports
it as a problem, so a wrong address is never guessed onto a public form).

An id that is not one of the person's choices is not an error HERE: the rule
falls through as though none had been named. The write path (`cases.py`) is
where a foreign id is refused.
"""
from __future__ import annotations

from db.supabase import get_supabase
from services import appointment_links

ADDRESS_KEYS = ("line1", "line2", "line3", "city", "state_region", "postal_code", "country")
_ROLES = ("director", "company_secretary", "alternate_director")
_CHUNK = 150


def _clean(value) -> str:
    return str(value).strip().casefold() if value is not None else ""


def content_key(address: dict | None) -> tuple:
    """What makes two addresses the same address: the seven printed lines,
    trimmed and case-folded, an empty line being the same as an absent one."""
    address = address or {}
    return tuple(_clean(address.get(k)) for k in ADDRESS_KEYS)


def normalised(address: dict | None) -> dict:
    """The address as exactly the seven keys a form prints."""
    address = address or {}
    return {k: address.get(k) for k in ADDRESS_KEYS}


def choices_for(officer_rows: list[dict], recorded_rows: list[dict], addresses: dict) -> list[dict]:
    """One person's choices. `addresses` maps id -> row; a link to a row that is
    gone is skipped. In-use choices come first, then recorded-only ones."""
    groups: dict[tuple, dict] = {}

    def group(address_id):
        row = addresses.get(address_id)
        if row is None or not any(content_key(row)):
            return None
        return groups.setdefault(content_key(row), {
            "address": normalised(row), "uses": {}, "used_by": [], "recorded": set()})

    for officer in officer_rows:
        g = group(officer.get("correspondence_address_id"))
        if g is None:
            continue
        aid = officer["correspondence_address_id"]
        g["uses"][aid] = g["uses"].get(aid, 0) + 1
        if officer.get("entity_id") not in g["used_by"]:
            g["used_by"].append(officer.get("entity_id"))
    for row in recorded_rows:
        g = group(row.get("address_id"))
        if g is not None:
            g["recorded"].add(row["address_id"])

    def build(g):
        if g["uses"]:
            # the id most officer rows already use; a tie takes the smallest
            rep = sorted(g["uses"], key=lambda a: (-g["uses"][a], str(a)))[0]
        else:
            rep = sorted(g["recorded"], key=str)[0]
        ids = {rep, *g["uses"], *g["recorded"]}
        return {"address_id": rep, "address": g["address"],
                "address_ids": [rep, *sorted(ids - {rep}, key=str)],
                "used_by": g["used_by"]}

    in_use = [build(g) for g in groups.values() if g["uses"]]
    only_recorded = [build(g) for g in groups.values() if not g["uses"]]
    return in_use + only_recorded


def _match(choices: list[dict], address_id):
    if address_id is None:
        return None
    return next((c for c in choices if address_id in c["address_ids"]), None)


def resolve(person: dict | None, choices: list[dict], chosen_id=None, home: dict | None = None) -> dict:
    """The rule. `home` is the person's default residential address."""
    in_use = [c for c in choices if c["used_by"]]
    picked = _match(choices, chosen_id)
    if picked is not None:
        status, found = "chosen", picked
    elif len(in_use) == 1:
        status, found = "in_use", in_use[0]
    elif not in_use and len(choices) == 1:
        status, found = "recorded", choices[0]
    elif not choices:
        status, found = "none", None
    else:
        status, found = "ambiguous", None

    if appointment_links.files_residential(person) or status == "none":
        kind, printed = "residential", (normalised(home) if home else None)
    elif found is not None:
        kind, printed = "correspondence", found["address"]
    else:
        kind, printed = None, None
    return {"status": status,
            "address_id": found["address_id"] if found else None,
            "address": found["address"] if found else None,
            "choices": choices, "printed_kind": kind, "printed_address": printed}


def _in(sb, table, column, values, apply=None):
    rows = []
    values = list(values)
    for i in range(0, len(values), _CHUNK):
        q = sb.table(table).select("*").in_(column, values[i:i + _CHUNK])
        rows += (apply(q) if apply else q).execute().data or []
    return rows


def for_persons(person_ids) -> dict:
    """person_id -> that person's choices, in a few queries. An unknown person
    maps to `[]`."""
    ids = list(dict.fromkeys(p for p in person_ids or [] if p))
    if not ids:
        return {}
    sb = get_supabase()
    officers = [o for o in _in(sb, "entity_officers", "person_id", ids,
                               lambda q: q.eq("is_current", True).in_("role", list(_ROLES)))
                if o.get("correspondence_address_id")]
    recorded = _in(sb, "person_addresses", "person_id", ids,
                   lambda q: q.eq("kind", "correspondence"))
    wanted = {o["correspondence_address_id"] for o in officers} | {
        r["address_id"] for r in recorded if r.get("address_id")}
    addresses = {a["id"]: a for a in _in(sb, "addresses", "id", wanted)} if wanted else {}
    return {pid: choices_for([o for o in officers if o["person_id"] == pid],
                             [r for r in recorded if r["person_id"] == pid], addresses)
            for pid in ids}
