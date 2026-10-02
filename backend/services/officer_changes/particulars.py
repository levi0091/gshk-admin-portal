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

    The correspondence rule (plan C-2): a baseline with no explicit
    correspondence address files the residential one in that slot, so a moved
    residential address is item (e) as well — and also (d) for a director, the
    only officer whose residential address CR holds. An explicit one is never
    reported, because nothing on the profile edits it (spec B-15).
    """
    corporate = baseline.get("party_type") == "corporate"
    out = []
    for key, cr_item, label, only_for in (_CORPORATE_ITEMS if corporate else _PERSON_ITEMS):
        if only_for and only_for != capacity:
            continue
        if key == "correspondence_address":
            if baseline.get("correspondence_address") is not None:
                continue
            old = baseline.get("residential_address")
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


def _appointments(person_id=None, corporate_entity_id=None) -> list[dict]:
    """Every CURRENT directorship and secretaryship of the party:
    `[{entity_id, capacity, officer_id}]`.

    A person's secretaryships are read from `company_secretaries` as well as
    `entity_officers`, because the NAR1 mapper reads that register first and
    most of GSHK's secretaries live only there. `company_secretaries` carries no
    corporate party id (migration 007), so a body corporate's appointments come
    from `entity_officers` alone.
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
                        "officer_id": row.get("id")})
    if person_id:
        secs = (sb.table("company_secretaries").select("*")
                .eq("person_id", person_id).eq("is_current", True).execute().data) or []
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
                        user_id: str | None) -> int:
    """Store a baseline for every current appointment of the party that has
    none, from the profile as it stands BEFORE the edit. Returns how many.

    Never raises: it runs in front of an ordinary profile edit, and losing an
    ND2B alert is a smaller failure than refusing to save a phone number.
    """
    try:
        appointments = _appointments(person_id, corporate_entity_id)
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
        now = _now()
        sb.table(_TABLE).insert([
            {"entity_id": entity_id, "person_id": person_id,
             "corporate_entity_id": corporate_entity_id,
             "particulars": snapshot, "source": "first_edit",
             "captured_by": user_id, "captured_at": now}
            for entity_id in missing
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
    return diff(held, _snapshot(person_id, corporate_entity_id), capacity=capacity)


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
    rows = []
    for appointment in appointments:
        base = held.get(appointment["entity_id"])
        if base is None:
            continue
        items = diff(base, current, capacity=appointment["capacity"])
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
    if old and old.get("correspondence_address") is not None:
        return {**new, "correspondence_address": old["correspondence_address"]}
    return new


def dismiss(*, person_id: str | None = None, corporate_entity_id: str | None = None,
            user_id) -> int:
    """Baseline := current for every appointment that has one (spec B-11)."""
    sb = get_supabase()
    rows = _party_filter(sb.table(_TABLE).select("*"),
                         person_id, corporate_entity_id).execute().data or []
    if not rows:
        return 0
    current = _snapshot(person_id, corporate_entity_id)
    now = _now()
    for row in rows:
        sb.table(_TABLE).update({
            "particulars": _keep_correspondence(row["particulars"], current),
            "source": "dismissed", "captured_by": user_id, "captured_at": now,
        }).eq("id", row["id"]).execute()
    return len(rows)


def advance(entity_id: str, *, person_id: str | None = None,
            corporate_entity_id: str | None = None, items: list[dict],
            user_id, capacity: str | None = None) -> None:
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
    for item in items:
        if item.get("omitted"):
            continue
        if item["key"] == "correspondence_address":
            correspondence = item
            continue
        base[item["key"]] = item["new"]
    if correspondence is not None:
        new = correspondence["new"]
        if capacity == "company_secretary" and base.get("correspondence_address") is None:
            base["residential_address"] = new
        elif _norm("residential_address", new) == _norm(
                "residential_address", base.get("residential_address")):
            base["correspondence_address"] = None
        else:
            base["correspondence_address"] = new
    set_baseline(entity_id, person_id=person_id,
                 corporate_entity_id=corporate_entity_id, particulars=base,
                 source="nd2b_filed", user_id=user_id)
