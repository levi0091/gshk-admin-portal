"""What ONE appointment files: its own identity document and residential address.

Levi 2026-10-05, on Jacqueline's ND2B question 2: "We do have clients holding 2
passports, say French and US passports. The same situation might apply to
addresses too. The client might use different addresses for different
companies. It seems you need to build a link between person's identification
and person's residential and correspondence address with different companies."

The link lives on the officer row (migration 053):

  entity_officers.identity_document_id    the document THIS company files. It
                                          replaces the person's primary document
                                          OF ITS TYPE; the other type is
                                          untouched (a HKID linked here does not
                                          hide the passport, nor the reverse).
  entity_officers.residential_address_id  the residential address THIS company
                                          files.
  entity_officers.correspondence_address_id  (already there, migration 028)

NULL means "the person's default" — `persons.residential_address_id` and the
primary document of each type — which is exactly what every reader did before
links existed, so a party nobody has linked files byte-for-byte as before.

PURE, and outside `services.officer_changes` on purpose: the NAR1 loader calls
it, and importing that package from `nar1_source` would close an import cycle.
"""
from __future__ import annotations


def documents_for(docs: list[dict], linked_id) -> list[dict]:
    """The person's identity documents as one appointment files them.

    The linked document is moved to the FRONT of its type and marked primary,
    the others of its type are marked not primary; documents of the other type
    keep their order and flags. NAR1's mapper takes the first document of a
    type and the ND2 mappers the primary one, so both see the linked document.
    With no link, or a link to a document that no longer exists, the SAME list
    comes back, untouched.
    """
    if not linked_id:
        return docs
    linked = next((d for d in docs or [] if d.get("id") == linked_id), None)
    if linked is None:
        return docs
    kind = linked.get("id_type")
    same = [{**linked, "is_primary": True}] + [
        {**d, "is_primary": False} for d in docs
        if d.get("id_type") == kind and d.get("id") != linked_id]
    others = [d for d in docs if d.get("id_type") != kind]
    return same + others


def person_for(person: dict, officer: dict | None) -> dict:
    """The person with the appointment's residential address, when it has one.
    The SAME dict comes back when it has none."""
    linked = (officer or {}).get("residential_address_id")
    if not linked or linked == person.get("residential_address_id"):
        return person
    return {**person, "residential_address_id": linked}


def _linked_officers(officers: list[dict]):
    for officer in officers or []:
        if officer.get("is_current", True) and officer.get("person_id") and (
                officer.get("residential_address_id") or officer.get("identity_document_id")):
            yield officer


def extra_address_ids(officers: list[dict]) -> set[str]:
    """Residential addresses the appointments link to — for a loader to fetch."""
    return {o["residential_address_id"] for o in officers or []
            if o.get("person_id") and o.get("residential_address_id")}


def apply_to_graph(persons: dict, identity_documents: dict, officers: list[dict]) -> None:
    """Rewrite one COMPANY's graph in place so each linked person reads as that
    company files them. A graph is one company, so this is unambiguous — except
    for a person holding two roles there, where the first linked row wins (CR
    holds one set of particulars per person per company)."""
    done_address, done_document = set(), set()
    for officer in _linked_officers(officers):
        pid = officer["person_id"]
        person = persons.get(pid)
        if person is None:
            continue
        if officer.get("residential_address_id") and pid not in done_address:
            persons[pid] = person_for(person, officer)
            done_address.add(pid)
        if officer.get("identity_document_id") and pid not in done_document:
            identity_documents[pid] = documents_for(identity_documents.get(pid) or [],
                                                    officer["identity_document_id"])
            done_document.add(pid)
