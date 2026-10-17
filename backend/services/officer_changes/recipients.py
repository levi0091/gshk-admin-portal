"""Who the client-verification email goes to for an officer change.

Spec B-6 (PRD Q3/Q4 proposals): an ND2A goes to every current director — the
people answerable for the board's composition — and to every director it
appoints, who should see their own particulars before CR does. An ND2B goes to
the officer whose particulars changed, and only to them.

The shape is NAR1's (`nar1_cases.default_recipients`) so the same chips and the
same send route handle it: one row per person, those with no address kept and
carrying the reason, because a board silently shown one short is the failure
that shape exists to prevent.
"""
from __future__ import annotations

from db.supabase import get_supabase
from services import nar1_cases

_NO_EMAIL = "no email address is on record for this officer"
_CORPORATE = ("a body corporate has no address on record here; add the person "
              "who acts for it")


def _people(person_ids: list[str]) -> dict[str, dict]:
    if not person_ids:
        return {}
    rows = (get_supabase().table("persons").select("id,full_name,given_names")
            .in_("id", person_ids).execute().data) or []
    return {r["id"]: r for r in rows}


def _corporates(entity_ids: list[str]) -> dict[str, dict]:
    if not entity_ids:
        return {}
    rows = (get_supabase().table("entities").select("id,company_name")
            .in_("id", entity_ids).execute().data) or []
    return {r["id"]: r for r in rows}


def _rows_for(entries: list[dict], role: str) -> list[dict]:
    person_ids = sorted({e["person_id"] for e in entries if e.get("person_id")})
    corp_ids = sorted({e["corporate_entity_id"] for e in entries
                       if not e.get("person_id") and e.get("corporate_entity_id")})
    people, corps = _people(person_ids), _corporates(corp_ids)
    emails = nar1_cases._person_emails(person_ids)
    out = []
    for pid in person_ids:
        person = people.get(pid) or {}
        email = emails.get(pid)
        out.append({
            "person_id": pid, "name": person.get("full_name") or "(unnamed officer)",
            "given_names": (person.get("given_names") or "").strip() or None,
            "email": email, "role": role, "party_type": "individual",
            "reason": None if email else _NO_EMAIL,
        })
    for cid in corp_ids:
        # A body corporate's mailbox is not where a statutory notice to the
        # client belongs; NAR1 draws the same line.
        out.append({
            "person_id": None, "corporate_entity_id": cid,
            "name": (corps.get(cid) or {}).get("company_name") or "(unnamed body corporate)",
            "given_names": None, "email": None, "role": role,
            "party_type": "corporate", "reason": _CORPORATE,
        })
    return out


def default_recipients(case: dict, entries: list[dict]) -> list[dict]:
    """`[{person_id, name, email, role, reason, ...}]`; no-address rows kept."""
    if case.get("form_code") == "Nd2b":
        out = _rows_for([e for e in entries if e.get("kind") == "change"], "officer")
    else:
        out = [{**r, "role": "director"}
               for r in nar1_cases.default_recipients(case["entity_id"])]
        incoming = [e for e in entries
                    if e.get("kind") == "appointment" and e.get("capacity") == "director"]
        out += _rows_for(incoming, "incoming director")
    seen, unique = set(), []
    for row in out:
        key = row.get("person_id") or ("corporate", row.get("corporate_entity_id"), row["name"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique
