"""A person's identification and addresses, and which company files which.

Levi 2026-10-05: "maybe the residential address field can be a list of
addresses now and clicking on new button allows adding a new residential
address. and in each residential address in the list it shows which companies
is using those addresses. same design applied to correspondence address.. same
for identification maybe not a list.. now we are already storing multiple
identifications but one is primary... but different identifications can be
linked to different companies too".

THE BOOK is the union of what is recorded (`person_addresses`, migration 053)
and what is in use (the person's default residential address and every link on
their appointments). An address written by an older route before the book
existed is still listed, rather than silently orphaned.

WHO USES WHAT is `services.appointment_links`' rule, restated for display:

  residential      the appointment's link, else the person's default
  correspondence   the appointment's link, else "same as residential"
  identification   per document type, the appointment's linked document of
                   that type, else the person's primary one of that type

EVERY WRITE captures the ND2B baseline for each of the person's appointments
first (`particulars.capture_before_edit`), so moving a company onto a new
address or passport is reported as an ND2B for THAT company — and a company
left where it was reports nothing. The service never audits; the router does,
from the `changes` each write returns.
"""
from __future__ import annotations

from db.supabase import get_supabase
from services import address_service
from services.officer_changes import particulars

ROLES = ("director", "company_secretary")
KINDS = ("residential", "correspondence")
_ADDRESS_KEYS = ("line1", "line2", "line3", "city", "state_region", "postal_code", "country")
_LINK = {"residential": "residential_address_id", "correspondence": "correspondence_address_id"}


class Refused(Exception):
    """A write the service will not make: `status` (404/409/422) and a reason."""

    def __init__(self, status: int, message: str, reason: str):
        self.status, self.reason = status, reason
        super().__init__(message)


def _address(row: dict | None) -> dict | None:
    return {k: row.get(k) for k in _ADDRESS_KEYS} if row else None


def _person(sb, person_id: str) -> dict:
    rows = sb.table("persons").select("*").eq("id", person_id).execute().data or []
    if not rows:
        raise Refused(404, "Person not found", "not_found")
    return rows[0]


def _appointments(sb, person_id: str) -> list[dict]:
    rows = (sb.table("entity_officers").select("*").eq("person_id", person_id)
            .eq("is_current", True).execute().data) or []
    return [r for r in rows if r.get("role") in ROLES]


def _companies(sb, appointments: list[dict]) -> list[dict]:
    """One entry per company, in first-seen order; the first explicit link of
    each kind wins for a person holding two roles there."""
    out: dict[str, dict] = {}
    for row in appointments:
        company = out.setdefault(row["entity_id"], {
            "entity_id": row["entity_id"], "roles": [], "officer_ids": [],
            "residential_address_id": None, "correspondence_address_id": None,
            "identity_document_id": None})
        company["roles"].append(row["role"])
        company["officer_ids"].append(row["id"])
        for key in ("residential_address_id", "correspondence_address_id",
                    "identity_document_id"):
            if company[key] is None and row.get(key):
                company[key] = row[key]
    ids = list(out)
    if ids:
        names = {e["id"]: e.get("company_name") for e in (
            sb.table("entities").select("*").in_("id", ids).execute().data or [])}
        for company in out.values():
            company["company_name"] = names.get(company["entity_id"])
    return list(out.values())


def _documents(sb, person_id: str) -> list[dict]:
    return (sb.table("person_identity_documents").select("*").eq("person_id", person_id)
            .execute().data) or []


def _chosen(docs: list[dict], id_type: str, linked: dict | None) -> dict | None:
    if linked and linked.get("id_type") == id_type:
        return linked
    of_type = [d for d in docs if d.get("id_type") == id_type]
    return next((d for d in of_type if d.get("is_primary")), of_type[0] if of_type else None)


def book(person_id: str) -> dict:
    """Everything the Person Profile's three cards show."""
    sb = get_supabase()
    person = _person(sb, person_id)
    companies = _companies(sb, _appointments(sb, person_id))
    default = person.get("residential_address_id")
    recorded = (sb.table("person_addresses").select("*").eq("person_id", person_id)
                .execute().data) or []

    ids = {kind: [] for kind in KINDS}

    def note(kind, address_id):
        if address_id and address_id not in ids[kind]:
            ids[kind].append(address_id)

    note("residential", default)
    for row in sorted(recorded, key=lambda r: str(r.get("created_at") or "")):
        if row.get("kind") in KINDS:
            note(row["kind"], row.get("address_id"))
    for company in companies:
        note("residential", company["residential_address_id"])
        note("correspondence", company["correspondence_address_id"])
    every = sorted({a for kind in KINDS for a in ids[kind]})
    rows = {}
    if every:
        rows = {a["id"]: a for a in (sb.table("addresses").select("*").in_("id", every)
                                     .execute().data or [])}

    residential = [{
        "address_id": a, "address": _address(rows.get(a)), "is_default": a == default,
        "used_by": [c["entity_id"] for c in companies
                    if (c["residential_address_id"] or default) == a],
    } for a in ids["residential"] if a in rows]
    correspondence = [{
        "address_id": a, "address": _address(rows.get(a)),
        "used_by": [c["entity_id"] for c in companies if c["correspondence_address_id"] == a],
    } for a in ids["correspondence"] if a in rows]

    docs = _documents(sb, person_id)
    by_id = {d["id"]: d for d in docs}
    used: dict[str, list[str]] = {d["id"]: [] for d in docs}
    for company in companies:
        linked = by_id.get(company["identity_document_id"] or "")
        for id_type in sorted({d.get("id_type") for d in docs}):
            chosen = _chosen(docs, id_type, linked)
            if chosen:
                used[chosen["id"]].append(company["entity_id"])
    identity = [{
        "document_id": d["id"], "id_type": d.get("id_type"), "id_number": d.get("id_number"),
        "issuing_country": d.get("issuing_country"), "is_primary": bool(d.get("is_primary")),
        "expiry_date": d.get("expiry_date"), "used_by": used[d["id"]],
    } for d in sorted(docs, key=lambda d: (str(d.get("id_type")), not d.get("is_primary")))]

    return {
        "companies": [{"entity_id": c["entity_id"], "company_name": c.get("company_name"),
                       "roles": c["roles"]} for c in companies],
        "default_residential_address_id": default,
        "residential": residential,
        "correspondence": correspondence,
        "correspondence_same_as_residential": [c["entity_id"] for c in companies
                                               if not c["correspondence_address_id"]],
        "identity": identity,
    }


# -- writes -----------------------------------------------------------------------------

def _capture(person_id: str, user_id) -> None:
    # Every appointment, before anything moves: a company left where it was
    # then reports nothing, and one moved reports exactly what moved.
    particulars.capture_before_edit(person_id=person_id, user_id=user_id)


def _check_companies(companies: list[dict], entity_ids: list[str]) -> dict[str, dict]:
    by_id = {c["entity_id"]: c for c in companies}
    unknown = [e for e in entity_ids if e not in by_id]
    if unknown:
        raise Refused(422, "That is not a company where this person is a current director "
                           "or company secretary.", "not_an_appointment")
    return by_id


def _new_address(sb, payload: dict) -> dict:
    try:
        address_service.validate(payload)
    except address_service.AddressError as exc:
        raise Refused(422, str(exc), "invalid_address") from exc
    columns = {k: (v or None) for k, v in address_service.normalise(payload).items()}
    return sb.table("addresses").insert(columns).execute().data[0]


def _record(sb, person_id: str, address_id: str, kind: str, user_id) -> None:
    have = (sb.table("person_addresses").select("*").eq("person_id", person_id)
            .eq("address_id", address_id).eq("kind", kind).execute().data) or []
    if not have:
        sb.table("person_addresses").insert({"person_id": person_id, "address_id": address_id,
                                             "kind": kind, "created_by": user_id}).execute()


def _link(sb, company: dict, column: str, value) -> None:
    for officer_id in company["officer_ids"]:
        sb.table("entity_officers").update({column: value}).eq("id", officer_id).execute()


def _in_book(data: dict, kind: str, address_id: str) -> dict:
    row = next((r for r in data[kind] if r["address_id"] == address_id), None)
    if row is None:
        raise Refused(404, "That address is not one of this person's "
                           f"{kind} addresses.", "not_found")
    return row


def add_address(person_id: str, *, kind: str, payload: dict, entity_ids: list[str],
                make_default: bool, user_id) -> dict:
    """A new address in the book, used by `entity_ids` (and the default, if
    asked). Returns `{"address", "changes": [{field, entity_id, old, new}]}`."""
    if kind not in KINDS:
        raise Refused(422, "kind is 'residential' or 'correspondence'", "bad_kind")
    if make_default and kind != "residential":
        raise Refused(422, "Only a residential address can be the default.", "bad_default")
    sb = get_supabase()
    person = _person(sb, person_id)
    companies = _companies(sb, _appointments(sb, person_id))
    by_id = _check_companies(companies, entity_ids)
    _capture(person_id, user_id)
    row = _new_address(sb, payload)
    _record(sb, person_id, row["id"], kind, user_id)
    changes = []
    if make_default:
        sb.table("persons").update({"residential_address_id": row["id"]}) \
            .eq("id", person_id).execute()
        changes.append({"field": "default_residential_address", "entity_id": None,
                        "old": person.get("residential_address_id"), "new": row["id"]})
    # A company given the new DEFAULT follows it (NULL) rather than being
    # pinned to it, or it would stay behind when the default next moves
    # (review finding 1).
    value = None if make_default else row["id"]
    for entity_id in entity_ids:
        company = by_id[entity_id]
        if company[_LINK[kind]] == value:
            continue
        _link(sb, company, _LINK[kind], value)
        changes.append({"field": f"{kind}_address", "entity_id": entity_id,
                        "old": company[_LINK[kind]], "new": value})
    return {"address": {"id": row["id"], **_address(row)}, "changes": changes}


def correct_address(person_id: str, address_id: str, *, payload: dict, user_id) -> dict:
    """Correct an address everywhere THIS person uses it. Copy-on-write: a new
    row, and this person's default, links and book entries move to it — a
    relative sharing the old row keeps it."""
    sb = get_supabase()
    data = book(person_id)
    kinds = [k for k in KINDS if any(r["address_id"] == address_id for r in data[k])]
    if not kinds:
        raise Refused(404, "That address is not one of this person's addresses.", "not_found")
    _capture(person_id, user_id)
    old = next(r["address"] for k in kinds for r in data[k] if r["address_id"] == address_id)
    row = _new_address(sb, payload)
    if (_person(sb, person_id).get("residential_address_id")) == address_id:
        sb.table("persons").update({"residential_address_id": row["id"]}) \
            .eq("id", person_id).execute()
    for officer in _appointments(sb, person_id):
        moved = {col: row["id"] for col in _LINK.values() if officer.get(col) == address_id}
        if moved:
            sb.table("entity_officers").update(moved).eq("id", officer["id"]).execute()
    for kind in kinds:
        _record(sb, person_id, row["id"], kind, user_id)
        sb.table("person_addresses").delete().eq("person_id", person_id) \
            .eq("address_id", address_id).eq("kind", kind).execute()
    used = sorted({e for k in kinds for r in data[k] if r["address_id"] == address_id
                   for e in r["used_by"]})
    return {"address": {"id": row["id"], **_address(row)},
            "changes": [{"field": "address_corrected", "entity_id": None, "old": old,
                         "new": _address(row), "companies": used}]}


def set_address_companies(person_id: str, address_id: str, *, kind: str,
                          entity_ids: list[str], user_id) -> list[dict]:
    """Exactly `entity_ids` use this address. A company listed moves onto it; a
    company linked to it and not listed goes back to the default (residential)
    or to "same as residential" (correspondence)."""
    if kind not in KINDS:
        raise Refused(422, "kind is 'residential' or 'correspondence'", "bad_kind")
    sb = get_supabase()
    data = book(person_id)
    _in_book(data, kind, address_id)
    companies = _companies(sb, _appointments(sb, person_id))
    _check_companies(companies, entity_ids)
    column = _LINK[kind]
    # Using the DEFAULT residential address is following it — no link of its
    # own — so a company moved onto it is UNlinked, and one already following
    # it is not touched. Pinning it instead would leave it behind on the old
    # address the day the default changes (review finding 1).
    target = None if (kind == "residential"
                      and address_id == data["default_residential_address_id"]) else address_id
    plan = []
    for company in companies:
        current = company[column]
        if company["entity_id"] in entity_ids and current != target:
            plan.append((company, target))
        elif company["entity_id"] not in entity_ids and current == address_id:
            plan.append((company, None))
    if plan:
        _capture(person_id, user_id)
    changes = []
    for company, value in plan:
        _link(sb, company, column, value)
        changes.append({"field": f"{kind}_address", "entity_id": company["entity_id"],
                        "old": company[column], "new": value})
    return changes


def make_default(person_id: str, address_id: str, *, user_id) -> list[dict]:
    sb = get_supabase()
    data = book(person_id)
    _in_book(data, "residential", address_id)
    old = data["default_residential_address_id"]
    if old == address_id:
        return []
    _capture(person_id, user_id)
    sb.table("persons").update({"residential_address_id": address_id}) \
        .eq("id", person_id).execute()
    return [{"field": "default_residential_address", "entity_id": None, "old": old,
             "new": address_id}]


def remove_address(person_id: str, address_id: str, *, kind: str) -> list[dict]:
    """Out of the book — never while it is the default or a company uses it."""
    if kind not in KINDS:
        raise Refused(422, "kind is 'residential' or 'correspondence'", "bad_kind")
    sb = get_supabase()
    data = book(person_id)
    row = _in_book(data, kind, address_id)
    if row.get("is_default"):
        raise Refused(409, "This is the default residential address. Make another address "
                           "the default first.", "default")
    if row["used_by"]:
        raise Refused(409, "A company still uses this address. Move it to another address "
                           "first.", "in_use")
    sb.table("person_addresses").delete().eq("person_id", person_id) \
        .eq("address_id", address_id).eq("kind", kind).execute()
    return [{"field": "address_removed", "entity_id": None, "old": row["address"],
             "new": None, "kind": kind}]


def set_document_companies(person_id: str, document_id: str, *, entity_ids: list[str],
                           user_id) -> list[dict]:
    """Exactly `entity_ids` file this document (in place of the person's primary
    one of its type). A company linked to it and not listed goes back to the
    primary."""
    sb = get_supabase()
    docs = {d["id"]: d for d in _documents(sb, person_id)}
    if document_id not in docs:
        raise Refused(404, "That identity document is not this person's.", "not_found")
    companies = _companies(sb, _appointments(sb, person_id))
    _check_companies(companies, entity_ids)
    # Filing the PRIMARY is following it — no link — for the same reason as
    # the default address above: a renewed passport made primary must reach
    # every company that was simply following the old one (review finding 1).
    target = None if docs[document_id].get("is_primary") else document_id
    plan = []
    for company in companies:
        current = company["identity_document_id"]
        if company["entity_id"] in entity_ids and current != target:
            plan.append((company, target))
        elif company["entity_id"] not in entity_ids and current == document_id:
            plan.append((company, None))
    if plan:
        _capture(person_id, user_id)
    changes = []
    for company, value in plan:
        _link(sb, company, "identity_document_id", value)
        changes.append({"field": "identity_document", "entity_id": company["entity_id"],
                        "old": company["identity_document_id"], "new": value})
    return changes
