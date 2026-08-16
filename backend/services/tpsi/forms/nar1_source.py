"""The one place BE-1 reads Supabase. Keeps nar1_mapper pure.

Six independent reads, issued concurrently: each Supabase round trip is ~200ms
(see the API-performance work), and serialising them would put a second of pure
latency in front of every filing.
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

    persons_rows, identity_rows = await asyncio.gather(
        q(lambda: sb.table("persons").select("*").in_("id", list(person_ids)).execute().data
          if person_ids else []),
        q(lambda: sb.table("person_identity_documents").select("*")
          .in_("person_id", list(person_ids)).execute().data if person_ids else []),
    )
    persons = {p["id"]: p for p in (persons_rows or [])}

    address_ids = {
        aid for aid in
        [entity.get("registered_address_id")]
        + [p.get("residential_address_id") for p in persons.values()]
        if aid
    }
    address_rows = await q(
        lambda: sb.table("addresses").select("*").in_("id", list(address_ids)).execute().data
        if address_ids else []
    )
    addresses = {a["id"]: a for a in (address_rows or [])}

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
