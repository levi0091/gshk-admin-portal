"""The data an ND2A / ND2B is mapped from: the company graph NAR1 already loads,
plus every party the change list names that is not (yet) an officer.

An appointee is by definition not on the officer register, and a body corporate
director's consent signer may be nobody's officer at all, so
`nar1_source.load_entity_graph` alone would leave them out. Keeping the loader
here and the mappers pure is the split NAR1 draws.
"""
from __future__ import annotations

import asyncio

from db.supabase import get_supabase
from services.officer_changes import eservice
from services.tpsi.forms import nar1_source


async def load_graph(entity_id: str, entries: list[dict]) -> dict:
    graph = await nar1_source.load_entity_graph(entity_id)
    sb = get_supabase()

    def q(fn):
        return asyncio.to_thread(fn)

    persons = graph.setdefault("persons", {})
    corporates = graph.setdefault("entities", {})
    addresses = graph.setdefault("addresses", {})
    identity = graph.setdefault("identity_documents", {})

    person_ids = sorted({pid for e in entries
                         for pid in (e.get("person_id"), e.get("consent_person_id"))
                         if pid and pid not in persons})
    corp_ids = sorted({e["corporate_entity_id"] for e in entries
                       if e.get("corporate_entity_id")
                       and e["corporate_entity_id"] not in corporates})
    new_people, new_docs, new_corps = await asyncio.gather(
        q(lambda: sb.table("persons").select("*").in_("id", person_ids).execute().data
          if person_ids else []),
        q(lambda: sb.table("person_identity_documents").select("*")
          .in_("person_id", person_ids).execute().data if person_ids else []),
        q(lambda: sb.table("entities").select("*").in_("id", corp_ids).execute().data
          if corp_ids else []),
    )
    for row in new_people or []:
        persons[row["id"]] = row
    for row in new_docs or []:
        identity.setdefault(row["person_id"], []).append(row)
    for row in new_corps or []:
        corporates[row["id"]] = row

    address_ids = sorted({aid for aid in
                          [p.get("residential_address_id") for p in persons.values()]
                          + [c.get("registered_address_id") for c in corporates.values()]
                          if aid and aid not in addresses})
    if address_ids:
        rows = await q(lambda: sb.table("addresses").select("*")
                       .in_("id", address_ids).execute().data)
        for row in rows or []:
            addresses[row["id"]] = row

    signers = [e.get("consent_person_id") or e.get("person_id") for e in entries
               if e.get("kind") == "appointment" and e.get("capacity") == "director"]
    graph["eservice"] = await q(lambda: eservice.metadata_for([s for s in signers if s]))
    return graph
