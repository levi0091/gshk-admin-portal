"""What CR holds for each appointment, and what has changed since (ND2B).

Spec §4 (Levi's answers 14 and 16, 2026-09-30). The operator never types a
changed value on an ND2B case: they edit the profile, and the case shows what
differs from what CR was last told. "What CR was last told" is one row of
`officer_cr_particulars` per appointment (company x officer), the BASELINE.

  * It is captured the first time a tracked field is about to change, from the
    values as they stand BEFORE the edit (`capture_before_edit`). A party nobody
    has edited has no baseline and therefore no pending change — the honest
    answer for thousands of rows that came out of Viewpoint (spec B-10).
  * Pending change = baseline != profile now, item by item, in CR's own items.
    Changing a value back makes the change disappear: nothing differs.
  * Dismissing ("this was data loading, not a real-world change") moves the
    baseline to now for every appointment of the party (spec B-11).
  * Filing an ND2B moves it forward for the FILED items only (`advance`); an
    omitted line stays pending, because CR has still not been told.

Shapes are the plan's contracts C-1 (snapshot) and C-2 (item). The service
never audits — the routers that call it do.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone

from db.supabase import get_supabase

#: A body corporate officer of more companies than this gets no baseline
#: (spec B-16). In practice that is GSHK Ltd, secretary of 5,603 companies: one
#: edit to the firm's own address would write 5,603 rows and raise 5,603 alerts,
#: and the bulk ND2B that would answer them is out of scope (spec §10).
MAX_APPOINTMENTS_CAPTURED = 200

#: Profile columns whose edit can change what CR holds. A route writing any of
#: them calls `capture_before_edit` first.
TRACKED_PERSON_FIELDS = frozenset({
    "surname", "given_names", "full_name", "full_name_zh", "alias_en",
    "alias_zh", "email", "residential_address_id", "tcsp_licence_no",
    "tcsp_exemption_reason",
})
TRACKED_ENTITY_FIELDS = frozenset({
    "company_name", "company_name_zh", "email", "registered_address_id",
    "tcsp_licence_no", "tcsp_exemption_reason",
})

_TABLE = "officer_cr_particulars"
_ROLES = ("director", "company_secretary")
_ADDRESS_KEYS = ("line1", "line2", "line3", "city", "state_region",
                 "postal_code", "country")

#: (key, CR item letter, label, capacity it applies to or None for both).
_PERSON_ITEMS = (
    ("name_zh", "a", "Name in Chinese", None),
    ("name_en", "b", "Name in English", None),
    ("alias", "c", "Alias", None),
    ("residential_address", "d", "Residential address", "director"),
    ("correspondence_address", "e", "Correspondence address", None),
    ("email", "f", "Email address", None),
    ("hkid", "g", "Hong Kong identity card number", None),
    ("passport", "h", "Passport", None),
    ("tcsp", "i", "TCSP licence", "company_secretary"),
)
_CORPORATE_ITEMS = (
    ("name", "a", "Name", None),
    ("address", "b", "Address", None),
    ("email", "c", "Email address", None),
    ("tcsp", "i", "TCSP licence", "company_secretary"),
)

#: Names compare case-insensitively: "chan" typed for "CHAN" is the same name to
#: CR, and reporting it would file a change nobody made.
_CASE_INSENSITIVE = {"name_en", "alias", "name", "email", "residential_address",
                     "correspondence_address", "address", "tcsp"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _s(value) -> str:
    return str(value or "").strip()


def _address(row: dict | None) -> dict | None:
    if not row:
        return None
    return {k: row.get(k) for k in _ADDRESS_KEYS}


# -- snapshots -------------------------------------------------------------------

def _primary(docs: list[dict], id_type: str) -> dict | None:
    of_type = [d for d in docs if d.get("id_type") == id_type and _s(d.get("id_number"))]
    if not of_type:
        return None
    return next((d for d in of_type if d.get("is_primary")), of_type[0])


def snapshot_person(person_id: str) -> dict:
    """C-1 PERSON snapshot of the profile as it stands now.

    `correspondence_address` is always None here: the profile holds no such
    field. An explicit one exists only on a baseline, set by the ND2A that
    appointed the officer (spec B-15).
    """
    sb = get_supabase()
    rows = sb.table("persons").select("*").eq("id", person_id).execute().data
    if not rows:
        raise LookupError(f"no person {person_id}")
    person = rows[0]
    home = None
    if person.get("residential_address_id"):
        found = (sb.table("addresses").select("*")
                 .eq("id", person["residential_address_id"]).execute().data)
        home = _address(found[0]) if found else None
    docs = (sb.table("person_identity_documents").select("*")
            .eq("person_id", person_id).execute().data) or []
    hkid = _primary(docs, "hkid")
    passport = _primary(docs, "passport")
    surname, given = _s(person.get("surname")), _s(person.get("given_names"))
    if not surname and not given:
        # A Viewpoint row with only a full name: CR's English name is then the
        # whole of it, which is what NAR1 files in the surname box too.
        surname = _s(person.get("full_name"))
    return {
        "party_type": "individual",
        "name_en": {"surname": surname, "given_names": given},
        "name_zh": _s(person.get("full_name_zh")),
        "alias": {"alias_en": _s(person.get("alias_en")),
                  "alias_zh": _s(person.get("alias_zh"))},
        "residential_address": home,
        "correspondence_address": None,
        "email": _s(person.get("email")),
        "hkid": _s(hkid.get("id_number")) if hkid else "",
        "passport": ({"number": _s(passport.get("id_number")),
                      "issuing_country": _s(passport.get("issuing_country"))}
                     if passport else None),
        "tcsp": {"licence_no": _s(person.get("tcsp_licence_no")),
                 "exemption_reason": _s(person.get("tcsp_exemption_reason"))},
    }


def snapshot_corporate(entity_id: str) -> dict:
    """C-1 CORPORATE snapshot: the body corporate's own name, office, email, TCSP."""
    sb = get_supabase()
    rows = sb.table("entities").select("*").eq("id", entity_id).execute().data
    if not rows:
        raise LookupError(f"no entity {entity_id}")
    entity = rows[0]
    office = None
    if entity.get("registered_address_id"):
        found = (sb.table("addresses").select("*")
                 .eq("id", entity["registered_address_id"]).execute().data)
        office = _address(found[0]) if found else None
    return {
        "party_type": "corporate",
        "name": {"name": _s(entity.get("company_name")),
                 "name_zh": _s(entity.get("company_name_zh"))},
        "address": office,
        "email": _s(entity.get("email")),
        "tcsp": {"licence_no": _s(entity.get("tcsp_licence_no")),
                 "exemption_reason": _s(entity.get("tcsp_exemption_reason"))},
    }


def _snapshot(person_id, corporate_entity_id) -> dict:
    if person_id:
        return snapshot_person(person_id)
    return snapshot_corporate(corporate_entity_id)


def snapshot_current(*, person_id: str | None = None,
                     corporate_entity_id: str | None = None) -> dict:
    """The party's profile as it stands now — what an ND2A appointment files."""
    return _snapshot(person_id, corporate_entity_id)


# -- comparing --------------------------------------------------------------------

def _norm_text(value, *, fold: bool) -> str:
    text = re.sub(r"\s+", " ", _s(value))
    return text.casefold() if fold else text


def _norm_hkid(value) -> str:
    # "A123456(3)" and "A1234563" are one card; CR splits the check digit out
    # itself, so the brackets are presentation.
    return re.sub(r"[\s()]", "", _s(value)).upper()


def _norm(key: str, value):
    fold = key in _CASE_INSENSITIVE
    if key == "hkid":
        return _norm_hkid(value)
    if isinstance(value, dict) or value is None:
        if key in ("residential_address", "correspondence_address", "address"):
            if not value or not any(_s(value.get(k)) for k in _ADDRESS_KEYS):
                return None
            return tuple(_norm_text(value.get(k), fold=True) for k in _ADDRESS_KEYS)
        if key == "passport":
            if not value or not _s(value.get("number")):
                return None
            return (_s(value.get("number")).upper(),
                    _s(value.get("issuing_country")).upper())
        if value is None:
            return None
        return tuple(sorted((k, _norm_text(v, fold=fold)) for k, v in value.items()))
    return _norm_text(value, fold=fold)


#: Baseline key: the explicit correspondence address on this baseline is not
#: one the officer gave (that is set by the appointing ND2A and never reported,
#: spec B-15) but the old residential address CR still holds because an ND2B
#: filed (d) and omitted (e). It keeps following the residential address, so
#: (e) stays pending until it is filed.
FOLLOWS_RESIDENTIAL = "correspondence_follows_residential"


def _effective_correspondence(snapshot: dict):
    explicit = snapshot.get("correspondence_address")
    return explicit if explicit is not None else snapshot.get("residential_address")


def describe(key: str, value) -> str:
    """A snapshot value as staff read it. Never "None"."""
    dash = "—"
    if value is None or value == "":
        return dash
    if key in ("residential_address", "correspondence_address", "address"):
        parts = [_s(value.get(k)) for k in _ADDRESS_KEYS]
        return ", ".join(p for p in parts if p) or dash
    if key == "name_en":
        return " ".join(p for p in (_s(value.get("surname")),
                                    _s(value.get("given_names"))) if p) or dash
    if key == "alias":
        return " / ".join(p for p in (_s(value.get("alias_en")),
                                      _s(value.get("alias_zh"))) if p) or dash
    if key == "name":
        return " / ".join(p for p in (_s(value.get("name")),
                                      _s(value.get("name_zh"))) if p) or dash
    if key == "passport":
        number = _s(value.get("number"))
        if not number:
            return dash
        country = _s(value.get("issuing_country"))
        return f"{number} ({country})" if country else number
    if key == "tcsp":
        licence = _s(value.get("licence_no"))
        if licence:
            return licence
        reason = _s(value.get("exemption_reason"))
        return f"Exempt: {reason}" if reason else dash
    return _s(value) or dash


def _item(key, cr_item, label, old, new) -> dict:
    return {"key": key, "cr_item": cr_item, "label": label,
            "old": old, "new": new,
            "old_text": describe(key, old), "new_text": describe(key, new),
            "effective_date": None, "omitted": False}


def diff(baseline: dict, current: dict, *, capacity: str) -> list[dict]:
    """Pure. C-2 items for what differs, in CR's item order.

    The correspondence rule: either side with no explicit correspondence
    address files the residential one in that slot, so a moved residential
    address is item (e) as well — and also (d) for a director, the only officer
    whose residential address CR holds. `current["correspondence_address"]` is
    the APPOINTMENT's own (`entity_officers.correspondence_address_id`), which
    the Person Profile edits since Jacqueline's AQ5/B4 — so an explicit one is
    compared like any other value (it used to be skipped: nothing edited it).
    """
    corporate = baseline.get("party_type") == "corporate"
    out = []
    for key, cr_item, label, only_for in (_CORPORATE_ITEMS if corporate else _PERSON_ITEMS):
        if only_for and only_for != capacity:
            continue
        if key == "correspondence_address":
            old = _effective_correspondence(baseline)
            new = _effective_correspondence(current)
        else:
            old, new = baseline.get(key), current.get(key)
        if _norm(key, old) != _norm(key, new):
            out.append(_item(key, cr_item, label, old, new))
    return out


# -- appointments and baselines ----------------------------------------------------

def _party_filter(query, person_id, corporate_entity_id):
    if person_id:
        return query.eq("person_id", person_id)
    return query.eq("corporate_entity_id", corporate_entity_id)


def _register_rows_naming(sb, corporate_entity_id: str) -> list[dict]:
    """Current secretary-register rows that name this body corporate.

    Matched on the normalised name, and only when no OTHER live company has
    that name: the rule `nar1_source._resolve_secretary_entities` applies to
    the same rows. A name two companies share belongs to neither."""
    rows = sb.table("entities").select("*").eq("id", corporate_entity_id).execute().data
    name = " ".join(str((rows or [{}])[0].get("company_name") or "").split())
    if not name:
        return []
    norm = lambda v: " ".join(str(v or "").split()).casefold()  # noqa: E731
    pattern = "%".join(w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                       for w in name.split())
    namesakes = [e for e in (sb.table("entities").select("*").ilike("company_name", pattern)
                             .execute().data or [])
                 if not e.get("deleted_at") and norm(e.get("company_name")) == norm(name)]
    if any(e.get("id") != corporate_entity_id for e in namesakes):
        return []
    register = (sb.table("company_secretaries").select("*").is_("person_id", "null")
                .eq("is_current", True).ilike("secretary_name", pattern)
                .execute().data) or []
    return [r for r in register if norm(r.get("secretary_name")) == norm(name)]


def _appointments(person_id=None, corporate_entity_id=None) -> list[dict]:
    """Every CURRENT directorship and secretaryship of the party:
    `[{entity_id, capacity, officer_id}]`.

    Secretaryships are read from `company_secretaries` as well as
    `entity_officers`, because the NAR1 mapper reads that register first. The
    register holds a body corporate by NAME only (no corporate party id,
    migration 007), so a body corporate's register rows are matched by its
    name — and only while that name belongs to it alone (`_register_rows_naming`).
    """
    sb = get_supabase()
    officers = _party_filter(sb.table("entity_officers").select("*"),
                             person_id, corporate_entity_id)
    rows = officers.eq("is_current", True).execute().data or []
    seen, out = set(), []
    for row in rows:
        if row.get("role") not in _ROLES:
            continue
        key = (row["entity_id"], row["role"])
        if key not in seen:
            seen.add(key)
            out.append({"entity_id": row["entity_id"], "capacity": row["role"],
                        "officer_id": row.get("id"),
                        "correspondence_address_id": row.get("correspondence_address_id"),
                        # What THIS company files (migration 053).
                        "residential_address_id": row.get("residential_address_id"),
                        "identity_document_id": row.get("identity_document_id")})
    if person_id:
        secs = (sb.table("company_secretaries").select("*")
                .eq("person_id", person_id).eq("is_current", True).execute().data) or []
    else:
        secs = _register_rows_naming(sb, corporate_entity_id)
    if secs:
        for row in secs:
            key = (row["entity_id"], "company_secretary")
            if key not in seen:
                seen.add(key)
                # No officer row: the alert starts an ND2B with `secretary_id`,
                # which `cases._officer_for_secretary` resolves.
                out.append({"entity_id": row["entity_id"],
                            "capacity": "company_secretary", "officer_id": None,
                            "secretary_id": row["id"]})
    return out


def _links_by_entity(appointments: list[dict]) -> dict[str, dict]:
    """entity_id -> what the person's appointment there files, as linked on the
    officer row: `{"correspondence": address | None ("same as residential"),
    "residential": address | None (the person's default), "document": identity
    document | None (the person's primary)}` (migration 053; Levi 2026-10-05).
    A party holding two roles in one company gives CR one set of particulars
    there, so the first explicit link of each kind wins."""
    sb = get_supabase()
    address_ids = sorted({a[k] for a in appointments
                          for k in ("correspondence_address_id", "residential_address_id")
                          if a.get(k)})
    addresses = {}
    if address_ids:
        addresses = {r["id"]: r for r in (sb.table("addresses").select("*")
                                          .in_("id", address_ids).execute().data or [])}
    doc_ids = sorted({a["identity_document_id"] for a in appointments
                      if a.get("identity_document_id")})
    documents = {}
    if doc_ids:
        documents = {d["id"]: d for d in (sb.table("person_identity_documents").select("*")
                                          .in_("id", doc_ids).execute().data or [])}
    out: dict[str, dict] = {}
    for a in appointments:
        link = out.setdefault(a["entity_id"], {"correspondence": None, "residential": None,
                                               "document": None})
        if link["correspondence"] is None:
            link["correspondence"] = _address(
                addresses.get(a.get("correspondence_address_id") or ""))
        if link["residential"] is None:
            link["residential"] = _address(addresses.get(a.get("residential_address_id") or ""))
        if link["document"] is None:
            link["document"] = documents.get(a.get("identity_document_id") or "")
    return out


def _current_for(current: dict, entity_id: str, links: dict) -> dict:
    """The party's snapshot as ONE appointment files it: a person's
    correspondence address is the appointment's, and so — when linked — are
    their residential address and their identity document of that type."""
    if current.get("party_type") == "corporate":
        return current
    link = links.get(entity_id) or {}
    out = {**current, "correspondence_address": link.get("correspondence")}
    if link.get("residential") is not None:
        out["residential_address"] = link["residential"]
    document = link.get("document")
    if document and _s(document.get("id_number")):
        if document.get("id_type") == "hkid":
            out["hkid"] = _s(document["id_number"])
        elif document.get("id_type") == "passport":
            out["passport"] = {"number": _s(document["id_number"]),
                               "issuing_country": _s(document.get("issuing_country"))}
    return out


def appointment_correspondence(person_id: str) -> list[dict]:
    """`[{officer_id, entity_id, role, address}]` for each current directorship and
    secretaryship on the officer list — what the Person Profile shows and edits
    (Jacqueline B4: "the correspondence address part and residential address
    part are not shown separately")."""
    sb = get_supabase()
    rows = [r for r in (sb.table("entity_officers").select("*").eq("person_id", person_id)
                        .eq("is_current", True).execute().data or [])
            if r.get("role") in _ROLES]
    ids = sorted({r["correspondence_address_id"] for r in rows
                  if r.get("correspondence_address_id")})
    found = {}
    if ids:
        found = {a["id"]: a for a in (sb.table("addresses").select("*").in_("id", ids)
                                      .execute().data or [])}
    return [{"officer_id": r["id"], "entity_id": r["entity_id"], "role": r["role"],
             "address": _address(found.get(r.get("correspondence_address_id") or ""))}
            for r in rows]


def _baseline_row(entity_id, person_id=None, corporate_entity_id=None) -> dict | None:
    query = get_supabase().table(_TABLE).select("*").eq("entity_id", entity_id)
    rows = _party_filter(query, person_id, corporate_entity_id).execute().data
    return rows[0] if rows else None


def baseline(entity_id: str, *, person_id: str | None = None,
             corporate_entity_id: str | None = None) -> dict | None:
    row = _baseline_row(entity_id, person_id, corporate_entity_id)
    return row["particulars"] if row else None


def set_baseline(entity_id: str, *, person_id: str | None = None,
                 corporate_entity_id: str | None = None, particulars: dict,
                 source: str, user_id) -> None:
    """Insert or replace one appointment's baseline.

    Select-then-write rather than an upsert: the uniqueness is two PARTIAL
    indexes (migration 050), which PostgREST's `on_conflict` cannot name.
    """
    sb = get_supabase()
    row = _baseline_row(entity_id, person_id, corporate_entity_id)
    payload = {"particulars": particulars, "source": source,
               "captured_by": user_id, "captured_at": _now()}
    if row:
        sb.table(_TABLE).update(payload).eq("id", row["id"]).execute()
        return
    sb.table(_TABLE).insert({
        "entity_id": entity_id, "person_id": person_id,
        "corporate_entity_id": corporate_entity_id, **payload,
    }).execute()


def capture_before_edit(*, person_id: str | None = None,
                        corporate_entity_id: str | None = None,
                        user_id: str | None, entity_id: str | None = None) -> int:
    """Store a baseline for every current appointment of the party that has
    none, from the profile as it stands BEFORE the edit — each with that
    appointment's own correspondence address. `entity_id` limits it to one
    company (an edit of one appointment's correspondence address). Returns how
    many.

    Never raises: it runs in front of an ordinary profile edit, and losing an
    ND2B alert is a smaller failure than refusing to save a phone number.
    """
    try:
        appointments = _appointments(person_id, corporate_entity_id)
        if entity_id:
            appointments = [a for a in appointments if a["entity_id"] == entity_id]
        if corporate_entity_id and len(appointments) > MAX_APPOINTMENTS_CAPTURED:
            print(f"officer_cr_particulars: {corporate_entity_id} holds "
                  f"{len(appointments)} appointments; not captured (spec B-16)",
                  file=sys.stderr)
            return 0
        sb = get_supabase()
        have = {r["entity_id"] for r in (
            _party_filter(sb.table(_TABLE).select("entity_id"),
                          person_id, corporate_entity_id).execute().data or [])}
        missing = sorted({a["entity_id"] for a in appointments} - have)
        if not missing:
            return 0
        snapshot = _snapshot(person_id, corporate_entity_id)
        links = _links_by_entity(appointments)
        now = _now()
        sb.table(_TABLE).insert([
            {"entity_id": company, "person_id": person_id,
             "corporate_entity_id": corporate_entity_id,
             "particulars": _current_for(snapshot, company, links), "source": "first_edit",
             "captured_by": user_id, "captured_at": now}
            for company in missing
        ]).execute()
        return len(missing)
    except Exception as exc:  # noqa: BLE001 — see docstring
        print(f"officer_cr_particulars capture failed: {exc!r}", file=sys.stderr)
        return 0


def registered_view(entity_id: str, *, person_id: str | None = None,
                    corporate_entity_id: str | None = None) -> dict:
    """The officer as CR holds them: the baseline, else the profile now."""
    held = baseline(entity_id, person_id=person_id,
                    corporate_entity_id=corporate_entity_id)
    return held if held is not None else _snapshot(person_id, corporate_entity_id)


def pending_for_officer(entity_id: str, *, person_id: str | None = None,
                        corporate_entity_id: str | None = None,
                        capacity: str) -> list[dict]:
    held = baseline(entity_id, person_id=person_id,
                    corporate_entity_id=corporate_entity_id)
    if held is None:
        return []
    current = _snapshot(person_id, corporate_entity_id)
    if person_id:
        links = _links_by_entity(
            [a for a in _appointments(person_id, None) if a["entity_id"] == entity_id])
        current = _current_for(current, entity_id, links)
    return diff(held, current, capacity=capacity)


def _open_nd2b_cases(person_id=None, corporate_entity_id=None) -> dict[str, dict]:
    """entity_id -> {id, case_no} of an unfinished ND2B already naming the party."""
    sb = get_supabase()
    entries = _party_filter(sb.table("officer_change_entries").select("*"),
                            person_id, corporate_entity_id).execute().data or []
    case_ids = sorted({e["case_id"] for e in entries if e.get("kind") == "change"})
    if not case_ids:
        return {}
    cases = (sb.table("nar1_cases").select("*").in_("id", case_ids)
             .eq("form_code", "Nd2b").execute().data) or []
    return {c["entity_id"]: {"id": c["id"], "case_no": c.get("case_no")}
            for c in cases
            if c.get("closed_at") is None and c.get("changes_applied_at") is None}


def _pending(person_id=None, corporate_entity_id=None) -> list[dict]:
    appointments = _appointments(person_id, corporate_entity_id)
    if not appointments:
        return []
    sb = get_supabase()
    held = {r["entity_id"]: r["particulars"] for r in (
        _party_filter(sb.table(_TABLE).select("*"),
                      person_id, corporate_entity_id).execute().data or [])}
    if not held:
        return []
    current = _snapshot(person_id, corporate_entity_id)
    links = _links_by_entity(appointments)
    rows = []
    for appointment in appointments:
        base = held.get(appointment["entity_id"])
        if base is None:
            continue
        items = diff(base, _current_for(current, appointment["entity_id"], links),
                     capacity=appointment["capacity"])
        if items:
            rows.append({**appointment, "items": items})
    if not rows:
        return []
    ids = sorted({r["entity_id"] for r in rows})
    names = {e["id"]: e.get("company_name") for e in (
        sb.table("entities").select("*").in_("id", ids).execute().data or [])}
    open_cases = _open_nd2b_cases(person_id, corporate_entity_id)
    for row in rows:
        row["company_name"] = names.get(row["entity_id"])
        row["open_case"] = open_cases.get(row["entity_id"])
    return rows


def pending_for_person(person_id: str) -> list[dict]:
    """The `changes` rows of `GET /persons/{id}/particulars-changes`."""
    return _pending(person_id=person_id)


def pending_for_corporate(entity_id: str) -> list[dict]:
    """The `changes` rows of `GET /companies/{id}/particulars-changes`."""
    return _pending(corporate_entity_id=entity_id)


def _keep_correspondence(old: dict | None, new: dict) -> dict:
    """A new baseline taken from the profile keeps the old explicit
    correspondence address: the profile has none to give, and dropping it would
    make CR's registered address silently 'follow' the residential one."""
    if old and old.get("correspondence_address") is not None \
            and not old.get(FOLLOWS_RESIDENTIAL):
        return {**new, "correspondence_address": old["correspondence_address"]}
    return new


def dismiss(*, person_id: str | None = None, corporate_entity_id: str | None = None,
            user_id, entity_id: str | None = None) -> int:
    """Baseline := current for every appointment that has one (spec B-11) —
    or, with `entity_id`, for that company's appointment only (Jacqueline BQ2:
    "we would not assume that the change applies to all the companies")."""
    sb = get_supabase()
    rows = _party_filter(sb.table(_TABLE).select("*"),
                         person_id, corporate_entity_id).execute().data or []
    if entity_id:
        rows = [r for r in rows if r.get("entity_id") == entity_id]
    if not rows:
        return 0
    current = _snapshot(person_id, corporate_entity_id)
    links = _links_by_entity(_appointments(person_id, None)) if person_id else {}
    now = _now()
    for row in rows:
        new = (_current_for(current, row["entity_id"], links) if person_id
               else _keep_correspondence(row["particulars"], current))
        sb.table(_TABLE).update({
            "particulars": new,
            "source": "dismissed", "captured_by": user_id, "captured_at": now,
        }).eq("id", row["id"]).execute()
    return len(rows)


def advance(entity_id: str, *, person_id: str | None = None,
            corporate_entity_id: str | None = None, items: list[dict],
            user_id, capacity: str | None = None, source: str = "nd2b_filed") -> None:
    """Write only the given items' `new` values into the baseline.

    Correspondence (e) needs care because the baseline stores it as "same as
    residential" (None) until CR is told otherwise. If, after the filed items,
    the new correspondence address IS the baseline's residential one, it stays
    None. A secretary has no registered residential address at all, so filing
    their (e) moves the baseline's residential with it and keeps following.
    Only a director whose (d) was omitted ends up with an explicit one — which
    is exactly what CR then holds.
    """
    held = baseline(entity_id, person_id=person_id,
                    corporate_entity_id=corporate_entity_id)
    base = dict(held) if held is not None else _snapshot(person_id, corporate_entity_id)
    correspondence = None
    residential_filed = False
    for item in items:
        if item.get("omitted"):
            continue
        if item["key"] == "correspondence_address":
            correspondence = item
            continue
        if item["key"] == "residential_address":
            residential_filed = True
        base[item["key"]] = item["new"]
    if (residential_filed and correspondence is None
            and held is not None and held.get("correspondence_address") is None):
        # (d) filed, (e) not: CR now holds the NEW residential address and still
        # the OLD correspondence one. While the baseline says "correspondence
        # follows residential", moving the residential would silently move the
        # correspondence too — and the omitted (e) would vanish from the next
        # diff while CR still holds the old address. Pin it explicitly, marked
        # as following the residential address so `diff` keeps reporting (e).
        base["correspondence_address"] = held.get("residential_address")
        base[FOLLOWS_RESIDENTIAL] = True
    if correspondence is not None:
        new = correspondence["new"]
        if capacity == "company_secretary" and base.get("correspondence_address") is None:
            base["residential_address"] = new
        elif _norm("residential_address", new) == _norm(
                "residential_address", base.get("residential_address")):
            base["correspondence_address"] = None
            base.pop(FOLLOWS_RESIDENTIAL, None)
        else:
            base["correspondence_address"] = new
            # The profile has no correspondence address of its own, so what was
            # just filed IS "the residential one": it keeps following it.
            base[FOLLOWS_RESIDENTIAL] = True
    if base.get(FOLLOWS_RESIDENTIAL) and _norm(
            "residential_address", base.get("correspondence_address")) == _norm(
            "residential_address", base.get("residential_address")):
        # Caught up: CR holds the same address in both slots again.
        base["correspondence_address"] = None
        base.pop(FOLLOWS_RESIDENTIAL, None)
    set_baseline(entity_id, person_id=person_id,
                 corporate_entity_id=corporate_entity_id, particulars=base,
                 source=source, user_id=user_id)


def dismiss_filed_elsewhere(*, person_id: str | None = None,
                            corporate_entity_id: str | None = None,
                            filed_entity_id: str, items: list[dict], user_id) -> list[dict]:
    """Levi 2026-10-05: "We will dismiss the change not yet filed warning after
    it has been filed with at least one company."

    After an ND2B has filed `items` for `filed_entity_id`, the SAME change —
    the same CR item with the same new value — stops being reported for the
    party's other companies: their baselines move forward for those items,
    `source = 'dismissed'`. Anything else still pending there stays pending,
    and a company with its own open ND2B is left to that ND2B. Returns
    `[{entity_id, company_name, capacity, items: [label], baseline_before}]` —
    the last for Undo only; it holds particulars and never goes in an audit row.
    """
    filed = [i for i in items if not i.get("omitted")]
    if not filed:
        return []
    out: dict[str, dict] = {}
    for row in _pending(person_id, corporate_entity_id):
        if row["entity_id"] == filed_entity_id or row.get("open_case"):
            continue
        same = [i for i in row["items"] if any(
            f.get("key") == i["key"] and _norm(i["key"], f.get("new")) == _norm(i["key"], i["new"])
            for f in filed)]
        if not same:
            continue
        # One entry per COMPANY (a director who is also secretary there is two
        # appointments and one baseline), its before-state taken before the
        # first move so Undo can put it back (review finding 2).
        entry = out.setdefault(row["entity_id"], {
            "entity_id": row["entity_id"], "company_name": row.get("company_name"),
            "capacity": row["capacity"], "items": [],
            "baseline_before": baseline(row["entity_id"], person_id=person_id,
                                        corporate_entity_id=corporate_entity_id)})
        advance(row["entity_id"], person_id=person_id,
                corporate_entity_id=corporate_entity_id, items=same, user_id=user_id,
                capacity=row["capacity"], source="dismissed")
        entry["items"] += [i["label"] for i in same if i["label"] not in entry["items"]]
    return list(out.values())
