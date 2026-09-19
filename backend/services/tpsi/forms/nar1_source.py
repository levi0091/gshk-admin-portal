"""The one place BE-1 reads Supabase. Keeps nar1_mapper pure.

Independent reads are issued concurrently: each Supabase round trip is ~200ms
(see the API-performance work), and serialising them would put a second of pure
latency in front of every filing. Three waves, because each depends on ids the
previous one returned:

  1. entity, officers, secretaries, share classes, shareholdings
  2. persons + their identity documents, and the CORPORATE PARTY entities
     reached through entity_officers/shareholdings.corporate_entity_id
  3. every address any of the above points at

Wave 2's corporate-party read is what stops a corporate officer or corporate
shareholder being filed with the FILING company's registered office. Migration
007 (PBI-40) added `corporate_entity_id` to both tables precisely so the real
address is reachable; when it does not resolve, this loader attaches None and
lets nar1_mapper raise, rather than substituting an address that is wrong on a
statutory return and that CR would accept.
"""
import asyncio

from db.supabase import get_supabase


def _normalise_name(value) -> str:
    return " ".join(str(value or "").split()).casefold()


def _index_by_name(entities) -> dict[str, list]:
    """Live entities by normalised name. A DELETED company is not a candidate
    for anybody's secretary (migration 049) -- and leaving it out is what turns
    an "ambiguous" name back into a resolved one once a duplicate profile, like
    Payward Limited's second, is deleted."""
    index: dict[str, list] = {}
    for entity in entities:
        if entity.get("deleted_at"):
            continue
        index.setdefault(_normalise_name(entity.get("company_name")), []) \
             .append(entity)
    return index


async def _resolve_secretary_entities(q, sb, secretaries: list[dict],
                                      corporate_entities: dict) -> None:
    """Attach the corporate secretary's own entity to each register row.

    Sets `corporate_entity_id` and `corporate_entity_resolution` -- "ok",
    "not_found" or "ambiguous". The mapper turns the latter two into a
    MappingError: a secretary we cannot place blocks the filing rather than
    borrowing an address that belongs to somebody else.

    Matched on NAME, because a name is all the register holds. Entities already
    loaded for the corporate officers and shareholders are tried first and cost
    nothing -- the GSHK secretary is normally among them, since it is usually
    also an entity_officers row. The extra query runs only for a name that
    those did not cover, which on DEV is the 796 companies whose officer
    register names a different firm from their secretary register.

    A name matching TWO companies is never resolved to the first one found. The
    two have different addresses and different BR numbers, and picking one
    would put a plausible, unverifiable, possibly wrong company on a statutory
    return -- the same class of mistake as the fallback this replaces.
    """
    by_name = _index_by_name(corporate_entities.values())
    unmatched = set()
    for sec in secretaries:
        matches = by_name.get(_normalise_name(sec.get("secretary_name")), [])
        if len(matches) == 1:
            sec["corporate_entity_id"] = matches[0]["id"]
            sec["corporate_entity_resolution"] = "ok"
        elif matches:
            sec["corporate_entity_resolution"] = "ambiguous"
        elif sec.get("secretary_name"):
            unmatched.add(sec["secretary_name"])
        else:
            sec["corporate_entity_resolution"] = "not_found"

    if not unmatched:
        return

    rows = await q(lambda: sb.table("entities").select("*")
                   .in_("company_name", sorted(unmatched)).execute().data)
    # Only live candidates: a deleted namesake is nobody's secretary, and
    # adding it to `corporate_entities` would report it as a deleted PARTY.
    rows = [r for r in rows or [] if not r.get("deleted_at")]
    for entity in rows:
        corporate_entities.setdefault(entity["id"], entity)
    found = _index_by_name(rows or [])
    for sec in secretaries:
        if sec.get("corporate_entity_resolution"):
            continue
        matches = found.get(_normalise_name(sec.get("secretary_name")), [])
        if len(matches) == 1:
            sec["corporate_entity_id"] = matches[0]["id"]
            sec["corporate_entity_resolution"] = "ok"
        else:
            sec["corporate_entity_resolution"] = (
                "ambiguous" if matches else "not_found")


async def load_entity_graph(entity_id: str) -> dict:
    sb = get_supabase()

    def q(fn):
        return asyncio.to_thread(fn)

    entity_rows, officers, secretaries, share_classes, shareholdings = await asyncio.gather(
        q(lambda: sb.table("entities").select("*").eq("id", entity_id).execute().data),
        q(lambda: sb.table("entity_officers").select("*")
          .eq("entity_id", entity_id).eq("is_current", True).execute().data),
        q(lambda: sb.table("company_secretaries").select("*")
          .eq("entity_id", entity_id).eq("is_current", True).execute().data),
        q(lambda: sb.table("share_classes").select("*")
          .eq("entity_id", entity_id).execute().data),
        q(lambda: sb.table("shareholdings").select("*")
          .eq("entity_id", entity_id).eq("is_current", True).execute().data),
    )
    if not entity_rows:
        raise LookupError(f"no entity {entity_id}")
    entity = entity_rows[0]

    person_ids = {
        row["person_id"]
        for row in (officers or []) + (secretaries or []) + (shareholdings or [])
        if row.get("person_id")
    }

    # Corporate officers and corporate shareholders are entities in their own
    # right (migration 007). Their own registered office is the address that
    # belongs on the return.
    corporate_rows = (officers or []) + (shareholdings or [])
    corporate_ids = {
        row["corporate_entity_id"] for row in corporate_rows
        if row.get("corporate_entity_id")
    }

    persons_rows, identity_rows, corporate_rows_data = await asyncio.gather(
        q(lambda: sb.table("persons").select("*").in_("id", list(person_ids)).execute().data
          if person_ids else []),
        q(lambda: sb.table("person_identity_documents").select("*")
          .in_("person_id", list(person_ids)).execute().data if person_ids else []),
        q(lambda: sb.table("entities").select("*")
          .in_("id", list(corporate_ids)).execute().data if corporate_ids else []),
    )
    persons = {p["id"]: p for p in (persons_rows or [])}
    corporate_entities = {c["id"]: c for c in (corporate_rows_data or [])}

    # A corporate company secretary's own entity. `company_secretaries` has no
    # corporate_entity_id -- migration 007 put that FK on entity_officers /
    # shareholdings / beneficial_owners only -- so the register holds a NAME
    # and nothing else: no address, no BR number, no Chinese name. The mapper
    # used to fill the gap with the FILING COMPANY's registered office, which
    # is wrong for 1,043 of 5,604 companies on DEV. Resolving it here keeps
    # nar1_mapper pure and gives that block the same shape as an officer's.
    corporate_secretaries = [s for s in (secretaries or [])
                             if not s.get("person_id")]
    if corporate_secretaries:
        await _resolve_secretary_entities(q, sb, corporate_secretaries,
                                          corporate_entities)

    address_ids = {
        aid for aid in
        [entity.get("registered_address_id")]
        + [p.get("residential_address_id") for p in persons.values()]
        + [c.get("registered_address_id") for c in corporate_entities.values()]
        if aid
    }
    address_rows = await q(
        lambda: sb.table("addresses").select("*").in_("id", list(address_ids)).execute().data
        if address_ids else []
    )
    addresses = {a["id"]: a for a in (address_rows or [])}

    # Attach each corporate party's OWN details to its officer / shareholding
    # row, so nar1_mapper stays pure and never has to resolve an id itself.
    # `corporate_address` is deliberately set even when it resolves to None:
    # the mapper turns a missing one into a MappingError.
    for row in corporate_rows:
        cid = row.get("corporate_entity_id")
        if not cid:
            continue
        party = corporate_entities.get(cid)
        if party is None:
            row["corporate_address"] = None
            continue
        row["corporate_address"] = addresses.get(party.get("registered_address_id"))
        row["corporate_br_no"] = party.get("br_number")
        row["corporate_name_zh"] = party.get("company_name_zh")
        # The body corporate's OWN email (migration 045) -- CR's corpEmailAddr,
        # which it holds in its own database and diffs the filed return against.
        # `.get` rather than `[...]`: a deployment whose 045 has not been run yet
        # returns rows without the key, and a filing must not 500 over a field
        # CR marks optional.
        row["corporate_email"] = party.get("email")
        # The body corporate's OWN TCSP licence -- the value the profile's
        # Company Secretary tile shows and the source the CR form contract
        # names for corpTcspNo. An `entity_officers` secretary had no other
        # route to a licence: a profile created in the portal has no
        # `company_secretaries` row, so Payward Limited's second profile
        # filed an empty Licence No. box on PROD (2026-09-19).
        row["corporate_tcsp_licence_no"] = party.get("tcsp_licence_no")
        # THE LINKED ENTITY'S NAME WINS. `corporate_name` on the officer and
        # shareholding rows holds Viewpoint's entity CODE, not a company name --
        # "GETSTA", "CHEAPI", "57THST", "BLACKANDWH" -- for 5,604 of 5,606
        # current corporate officers and all 213 corporate shareholdings on DEV.
        # This used to be preferred over the entity whenever it was non-empty,
        # so a rendered NAR1 named a body corporate by its Viewpoint code: a
        # reserve director as "GETSTA", a Schedule 1 member as "57THST".
        # The code is kept only when the linked entity has no name to give.
        if party.get("company_name"):
            row["corporate_name"] = party["company_name"]

    # The same attachment for the secretary register, whose entity was resolved
    # by name above rather than through a FK it does not have.
    for sec in corporate_secretaries:
        party = corporate_entities.get(sec.get("corporate_entity_id"))
        sec["corporate_address"] = (
            addresses.get(party.get("registered_address_id")) if party else None
        )
        if party:
            sec["corporate_br_no"] = party.get("br_number")
            sec["corporate_name_zh"] = party.get("company_name_zh")
            sec["corporate_email"] = party.get("email")
            sec["corporate_tcsp_licence_no"] = party.get("tcsp_licence_no")

    identity_documents: dict[str, list] = {}
    for doc in identity_rows or []:
        identity_documents.setdefault(doc["person_id"], []).append(doc)

    return {
        "entity": entity,
        "registered_address": addresses.get(entity.get("registered_address_id")),
        "officers": officers or [],
        "secretaries": secretaries or [],
        "share_classes": share_classes or [],
        "shareholdings": shareholdings or [],
        "persons": persons,
        "addresses": addresses,
        "identity_documents": identity_documents,
        # The corporate parties, keyed by id. nar1_return_data._party_name has
        # always looked for this to name a body corporate, and never found it --
        # the key was simply never returned -- so the card fell through to
        # `corporate_name` and showed Viewpoint's code ("GETSTA") as the
        # company secretary on the Data Verification screen.
        "entities": corporate_entities,
        # CURRENT parties whose own record has been deleted (migration 049).
        # Deleting one is refused while it holds a current role, so this is
        # only ever a re-import or a race getting round that -- and the mapper
        # then refuses the return rather than filing without them or with a
        # record nobody can see.
        "deleted_parties": sorted(
            {p.get("full_name") or p["id"]
             for p in persons.values() if p.get("deleted_at")}
            | {c.get("company_name") or c["id"]
               for c in corporate_entities.values() if c.get("deleted_at")}),
    }
