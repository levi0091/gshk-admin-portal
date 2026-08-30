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
        if not row.get("corporate_name"):
            row["corporate_name"] = party.get("company_name")

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
    }
