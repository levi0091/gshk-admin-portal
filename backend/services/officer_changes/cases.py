"""ND2A / ND2B cases: creation, the change list, and the composite the page reads.

An officer-change case is a row in `nar1_cases` with `form_code` 'Nd2a' or
'Nd2b' (spec §3, B-1): the approval tokens, the filing ledger, the CR poller and
the dashboard view all work on it unchanged. What is new is the change list,
`officer_change_entries` — one row per officer on the form.

  * An ND2A carries `cessation` and `appointment` entries; an ND2B carries
    `change` entries only.
  * The change list is editable until the client has been sent the form. What
    the client approved is what gets filed; a correction afterwards is a
    restart of verification (`PATCH /officer-changes/{id}`), not an edit.
  * An ND2B entry's items come from the profile, never from the request
    (spec §4, answer 14): only an item's effective date and whether it is
    omitted are writable here.

The service raises `ValueError` for bad input and `CaseRefused` for a state
that refuses the request; routers turn them into 400 / 409 and do the auditing.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from db.supabase import get_supabase
from services import nar1_case_status, nar1_cases, soft_delete
from services.officer_changes import (
    apply, deadlines, documents, eservice, particulars, prepare, rules,
)
from services.tpsi.forms.cr_vocabularies import (
    CAPACITY_BODY_CORPORATE, CAPACITY_INDIVIDUAL, default_capacity,
)

FORM_CODES = ("Nd2a", "Nd2b")
_NAR1_TYPE = {"Nd2a": "appointment_and_resignation", "Nd2b": "change_of_particulars"}
_PREFIX = {"Nd2a": "ND2A", "Nd2b": "ND2B"}
_CAPACITIES = ("director", "company_secretary")
_CAPACITY_LABEL = {"director": "Director", "company_secretary": "Company Secretary"}
_REASON_LABEL = {"R": "Resignation / Others", "D": "Deceased"}
_ADDRESS_KEYS = ("line1", "line2", "line3", "city", "state_region", "postal_code",
                 "country")

#: The columns a request may set on an entry, by kind. Everything else on the
#: row is derived (the party of a cessation, the items of a change) or owned by
#: a later stage (KYC, consent, what filing applied).
_WRITABLE = {
    "cessation": {"effective_date", "cessation_reason"},
    "appointment": {"capacity", "effective_date", "correspondence_same_as_residential",
                    "correspondence_address", "section5_confirmed",
                    "consent_person_id", "consent_capacity"},
    "change": set(),
}


class CaseRefused(Exception):
    """A state that refuses the request; the router answers 409."""

    def __init__(self, reason: str, message: str):
        self.reason = reason
        self.message = message
        super().__init__(message)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


# -- the case row --------------------------------------------------------------------

def create_case(*, entity_id: str, form_code: str, user_id: str) -> tuple[dict, bool]:
    """`(case, reused)` — reuses the company's open, unsent case of that form
    (spec B-12), so *Report a change* adds to the form being prepared rather
    than starting a second one for the same company."""
    if form_code not in FORM_CODES:
        raise ValueError(f"{form_code!r} is not an officer-change form; "
                         f"expected one of {', '.join(FORM_CODES)}")
    sb = get_supabase()
    if soft_delete.is_deleted(sb, "entities", entity_id):
        raise ValueError("That company has been deleted. Restore it before opening "
                         "a case for it.")
    open_cases = (sb.table("nar1_cases").select("*").eq("entity_id", entity_id)
                  .eq("form_code", form_code).execute().data) or []
    for case in open_cases:
        if editable(case):
            return case, True
    prefix = f"{_PREFIX[form_code]}-{deadlines.hk_today().year}"
    case_no = sb.rpc("next_case_no", {"p_prefix": prefix}).execute().data
    row = sb.table("nar1_cases").insert({
        "entity_id": entity_id, "case_no": case_no, "form_code": form_code,
        "nar1_type": _NAR1_TYPE[form_code], "created_by": user_id,
        "assigned_to": user_id,
    }).execute().data[0]
    return row, False


def get_case(case_id: str) -> dict:
    """`LookupError` when absent or when the case is a NAR1."""
    rows = get_supabase().table("nar1_cases").select("*").eq("id", case_id).execute().data
    if not rows or rows[0].get("form_code") not in FORM_CODES:
        raise LookupError(f"no officer-change case {case_id}")
    return rows[0]


def editable(case: dict) -> bool:
    """Entries may change: not yet sent to the client, and not closed."""
    return not case.get("closed_at") and not case.get("verification_sent_at")


def _refuse_unless_editable(case: dict) -> None:
    if case.get("closed_at"):
        raise CaseRefused("case_closed", "This case is closed.")
    if not editable(case):
        raise CaseRefused(
            "not_editable",
            "The client has been sent this form. Restart verification to change it.")


def list_entries(case_id: str) -> list[dict]:
    rows = (get_supabase().table("officer_change_entries").select("*")
            .eq("case_id", case_id).execute().data) or []
    return sorted(rows, key=lambda r: (r.get("sort_order") or 0, r.get("created_at") or ""))


def _store_deadline(case_id: str) -> None:
    due = deadlines.filing_deadline(list_entries(case_id))
    get_supabase().table("nar1_cases").update(
        {"filing_deadline": _iso(due), "updated_at": _now()}).eq("id", case_id).execute()


# -- validating an entry -------------------------------------------------------------

def _current_officer(case: dict, officer_id: str | None) -> dict:
    if not officer_id:
        raise ValueError("Choose the officer this change is about")
    rows = (get_supabase().table("entity_officers").select("*").eq("id", officer_id)
            .execute().data) or []
    officer = rows[0] if rows else None
    if (not officer or officer.get("entity_id") != case["entity_id"]
            or officer.get("is_current") is False
            or officer.get("role") not in _CAPACITIES):
        raise ValueError("That is not a current officer of this company")
    return officer


def _normalise_name(value) -> str:
    return " ".join(str(value or "").split()).casefold()


def _resolve_corporate(name: str | None) -> tuple[str | None, str]:
    """The ONE live company called `name`: `(id, "ok")`, else `(None, why)`.

    The secretary register holds a body corporate by name only, and this is
    the rule `nar1_source._resolve_secretary_entities` applies to the same
    rows: a name matching two companies is never resolved to the first one,
    because the two have different addresses and BR numbers."""
    words = str(name or "").split()
    if not words:
        return None, "not_found"
    # Escaped, and any run of spaces matched loosely; the exact comparison
    # below is on the normalised name, so the pattern only narrows the read.
    escape = lambda w: w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")  # noqa: E731
    rows = (get_supabase().table("entities").select("*")
            .ilike("company_name", "%".join(escape(w) for w in words)).execute().data) or []
    live = [r for r in rows if not r.get("deleted_at")
            and _normalise_name(r.get("company_name")) == _normalise_name(name)]
    if len(live) == 1:
        return live[0]["id"], "ok"
    return None, "ambiguous" if live else "not_found"


def _secretary_registers(entity_id: str, officer_rows: list[dict],
                         corps: dict) -> tuple[dict[str, list[str]], list[dict]]:
    """`(twins, register_only)` for the current `company_secretaries` rows.

    The register the NAR1 mapper reads first, and the only place hundreds of
    companies hold their secretary. A register row is the twin of an officer
    row naming the same person, or — for a body corporate, which the register
    holds by name — the same company name. `twins` maps an officer row's id to
    its register rows' ids; `register_only` is every row with no twin."""
    rows = (get_supabase().table("company_secretaries").select("*")
            .eq("entity_id", entity_id).eq("is_current", True).execute().data) or []
    officer_secs = [r for r in officer_rows if r.get("role") == "company_secretary"]
    by_person = {r["person_id"]: r["id"] for r in officer_secs if r.get("person_id")}
    by_name = {_normalise_name((corps.get(r.get("corporate_entity_id") or "") or {})
                               .get("company_name") or r.get("corporate_name")): r["id"]
               for r in officer_secs if not r.get("person_id")}
    twins: dict[str, list[str]] = {}
    register_only = []
    for reg in rows:
        twin = (by_person.get(reg["person_id"]) if reg.get("person_id")
                else by_name.get(_normalise_name(reg.get("secretary_name"))))
        if twin:
            twins.setdefault(twin, []).append(reg["id"])
        else:
            register_only.append(reg)
    return twins, register_only


def _officer_for_secretary(case: dict, secretary_id: str) -> tuple[dict, bool]:
    """The officer row for a secretary named by its REGISTER id: `(row, promoted)`.

    The company profile's Secretary tile reads the register, so its rows carry
    a register id. When an officer row already names the same secretary, that
    row is the answer. Otherwise the register row is given the `entity_officers`
    row an ND2 needs: every later step — the entry, the XML, filing's
    write-back and Undo — keys on an officer row. The mirror states nothing the
    register did not already say (the same person or company, the same
    appointment date, still current), which is why it is safe to write before
    the form is filed; filing then ends BOTH rows."""
    sb = get_supabase()
    rows = (sb.table("company_secretaries").select("*").eq("id", secretary_id)
            .execute().data) or []
    reg = rows[0] if rows else None
    if not reg or reg.get("entity_id") != case["entity_id"] or reg.get("is_current") is False:
        raise ValueError("That is not a current secretary of this company")
    officer_rows = (sb.table("entity_officers").select("*")
                    .eq("entity_id", case["entity_id"]).eq("is_current", True)
                    .execute().data) or []
    corps = _by_id("entities", [r.get("corporate_entity_id") for r in officer_rows])
    twins, _ = _secretary_registers(case["entity_id"], officer_rows, corps)
    for officer in officer_rows:
        if reg["id"] in twins.get(officer["id"], []):
            return officer, False
    row = {"entity_id": case["entity_id"], "role": "company_secretary",
           "is_current": True, "appointed_date": reg.get("appointed_date")}
    if reg.get("person_id"):
        row.update(person_id=reg["person_id"], party_type="individual")
    else:
        corp_id, why = _resolve_corporate(reg.get("secretary_name"))
        if not corp_id:
            raise ValueError(
                f"The secretary register names \"{reg.get('secretary_name') or '(no name)'}\", "
                + ("and more than one company on the registry has that name"
                   if why == "ambiguous" else "and no company on the registry has that name")
                + ". Link the secretary on the company profile first, so the form "
                  "can name the right company.")
        row.update(person_id=None, party_type="corporate", corporate_entity_id=corp_id,
                   corporate_name=reg.get("secretary_name"))
    return sb.table("entity_officers").insert(row).execute().data[0], True


def _party_of(officer: dict) -> dict:
    # `party_type` first: a Viewpoint corporate row may carry only a
    # corporate_name, with no corporate_entity_id — counting it as a natural
    # person would let it satisfy "a natural-person director remains".
    corporate = not officer.get("person_id") and (
        officer.get("party_type") == "corporate" or bool(officer.get("corporate_entity_id")))
    return {"party_type": "corporate" if corporate else "individual",
            "person_id": officer.get("person_id"),
            "corporate_entity_id": officer.get("corporate_entity_id") if corporate else None,
            "capacity": officer["role"], "officer_id": officer["id"]}


def _check_address(address) -> dict:
    if not isinstance(address, dict) or not str(address.get("line1") or "").strip() \
            or not str(address.get("country") or "").strip():
        raise ValueError("A correspondence address needs at least its first line "
                         "and its country")
    return {k: (str(address.get(k)).strip() if address.get(k) is not None else None)
            for k in _ADDRESS_KEYS}


def _check_appointment(case: dict, row: dict, entries: list[dict],
                       exclude_id: str | None = None) -> None:
    if row.get("capacity") not in _CAPACITIES:
        raise ValueError("The capacity must be Director or Company Secretary "
                         "(alternate directors are not offered)")
    if not row.get("effective_date"):
        raise ValueError("Enter the date of appointment")
    if row.get("party_type") == "corporate":
        if row.get("capacity") == "director" and not (
                row.get("consent_person_id") and str(row.get("consent_capacity") or "").strip()):
            raise ValueError("A body corporate director needs the person who signs its "
                             "consent and their capacity")
    elif row.get("correspondence_same_as_residential") is False:
        row["correspondence_address"] = _check_address(row.get("correspondence_address"))
    party_col = "person_id" if row.get("person_id") else "corporate_entity_id"
    sitting = (get_supabase().table("entity_officers").select("*")
               .eq("entity_id", case["entity_id"]).eq(party_col, row[party_col])
               .eq("role", row["capacity"]).eq("is_current", True).execute().data) or []
    if sitting:
        raise ValueError("That party is already a current "
                         f"{_CAPACITY_LABEL[row['capacity']].lower()} of this company")
    for e in entries:
        if (e["id"] != exclude_id and e.get("kind") == "appointment"
                and e.get(party_col) == row[party_col] and e.get("capacity") == row["capacity"]):
            raise ValueError("That appointment is already on this form")


def _new_row(case: dict, payload: dict, entries: list[dict], user_id) -> dict:
    kind = payload.get("kind")
    form = case.get("form_code")
    if form == "Nd2a" and kind not in ("cessation", "appointment"):
        raise ValueError("An ND2A reports cessations and appointments; use an ND2B "
                         "for a change of particulars")
    if form == "Nd2b" and kind != "change":
        raise ValueError("An ND2B reports changes of particulars; use an ND2A for "
                         "appointments and cessations")
    base = {"case_id": case["id"], "kind": kind, "created_by": user_id,
            "sort_order": len(entries), "items": []}

    if kind in ("cessation", "change"):
        promoted = None
        if payload.get("secretary_id") and not payload.get("officer_id"):
            if kind == "cessation":
                # Validated BEFORE any officer row is written, so a missing
                # date or reason never leaves a promotion behind.
                reg = (get_supabase().table("company_secretaries").select("*")
                       .eq("id", payload["secretary_id"]).execute().data or [None])[0] or {}
                if not payload.get("effective_date"):
                    raise ValueError("Enter the date of cessation")
                if reg.get("person_id") and payload.get("cessation_reason") not in ("R", "D"):
                    raise ValueError("Choose the reason for cessation: Resignation / "
                                     "Others, or Deceased")
            officer, was_promoted = _officer_for_secretary(case, payload["secretary_id"])
            if was_promoted:
                promoted = {"secretary_id": payload["secretary_id"], "officer_id": officer["id"]}
            payload = {**payload, "officer_id": officer["id"]}
        officer = _current_officer(case, payload.get("officer_id"))
        party = _party_of(officer)
        if any(e.get("officer_id") == officer["id"] and e.get("kind") == kind
               for e in entries):
            raise ValueError("That officer is already on this form")
        row = {**base, **party}
        if kind == "cessation":
            if not payload.get("effective_date"):
                raise ValueError("Enter the date of cessation")
            row["effective_date"] = payload["effective_date"]
            if party["party_type"] == "individual":
                if payload.get("cessation_reason") not in ("R", "D"):
                    raise ValueError("Choose the reason for cessation: Resignation / "
                                     "Others, or Deceased")
                row["cessation_reason"] = payload["cessation_reason"]
            else:
                row["cessation_reason"] = None
            if promoted:
                # Not a column: `add_entry` lifts it off before the insert and
                # hands it to the router, which puts it in the audit row.
                row["_promoted"] = promoted
            return row
        party_key = ({"person_id": party["person_id"]} if party["person_id"]
                     else {"corporate_entity_id": party["corporate_entity_id"]})
        row["items"] = particulars.pending_for_officer(
            case["entity_id"], capacity=party["capacity"], **party_key)
        row["registered"] = particulars.registered_view(case["entity_id"], **party_key)
        if promoted:
            row["_promoted"] = promoted
        return row

    # appointment
    corporate = payload.get("party_type") == "corporate"
    party_id = payload.get("corporate_entity_id" if corporate else "person_id")
    if not party_id:
        raise ValueError("Choose the person or body corporate being appointed")
    row = {**base,
           "party_type": "corporate" if corporate else "individual",
           "person_id": None if corporate else party_id,
           "corporate_entity_id": party_id if corporate else None}
    for key in _WRITABLE["appointment"]:
        if key in payload:
            row[key] = payload[key]
    row.setdefault("correspondence_same_as_residential", True)
    _check_appointment(case, row, entries)
    return row


# -- changing the list --------------------------------------------------------------

def _entry(case: dict, entry_id: str) -> dict:
    rows = (get_supabase().table("officer_change_entries").select("*")
            .eq("id", entry_id).eq("case_id", case["id"]).execute().data) or []
    if not rows:
        raise LookupError(f"no entry {entry_id} on case {case['id']}")
    return rows[0]


def add_entry(case: dict, payload: dict, *, user_id) -> dict:
    _refuse_unless_editable(case)
    row = _new_row(case, payload, list_entries(case["id"]), user_id)
    promoted = row.pop("_promoted", None)
    created = get_supabase().table("officer_change_entries").insert(row).execute().data[0]
    _store_deadline(case["id"])
    if promoted:
        created = {**created, "promoted_from_register": promoted}
    return created


def _merge_items(current: list[dict], requested: list[dict]) -> list[dict]:
    """Only `effective_date` and `omitted` of an existing item may move."""
    wanted = {r.get("key"): r for r in requested or [] if isinstance(r, dict)}
    out = []
    for item in current or []:
        ask = wanted.get(item["key"])
        if ask is not None:
            item = dict(item)
            if "effective_date" in ask:
                item["effective_date"] = ask["effective_date"] or None
            if "omitted" in ask:
                item["omitted"] = ask["omitted"] is True
        out.append(item)
    return out


def update_entry(case: dict, entry_id: str, patch: dict, *, user_id) -> tuple[dict, dict]:
    """`(before, after)`."""
    _refuse_unless_editable(case)
    before = _entry(case, entry_id)
    changes = {k: v for k, v in (patch or {}).items()
               if k in _WRITABLE.get(before["kind"], set())}
    if before["kind"] == "change" and "items" in (patch or {}):
        changes["items"] = _merge_items(before.get("items"), patch["items"])
    if not changes:
        raise ValueError("Nothing on this entry can be changed that way")
    merged = {**before, **changes}
    if before["kind"] == "cessation":
        if not merged.get("effective_date"):
            raise ValueError("Enter the date of cessation")
        if merged.get("party_type") == "individual" and merged.get("cessation_reason") not in ("R", "D"):
            raise ValueError("Choose the reason for cessation")
    if before["kind"] == "appointment":
        others = [e for e in list_entries(case["id"]) if e["id"] != entry_id]
        _check_appointment(case, merged, others, exclude_id=entry_id)
        if "correspondence_address" in merged:
            changes["correspondence_address"] = merged["correspondence_address"]
    after = (get_supabase().table("officer_change_entries")
             .update({**changes, "updated_at": _now()}).eq("id", entry_id)
             .execute().data[0])
    _store_deadline(case["id"])
    return before, after


def remove_entry(case: dict, entry_id: str) -> dict:
    _refuse_unless_editable(case)
    gone = _entry(case, entry_id)
    get_supabase().table("officer_change_entries").delete().eq("id", entry_id).execute()
    _store_deadline(case["id"])
    return gone


def set_kyc(case: dict, entry_id: str, cleared: bool, *, user_id) -> dict:
    """KYC is ticked at Data Verification, after the send, so it is gated on
    the case being open rather than on the change list being editable."""
    if case.get("closed_at"):
        raise CaseRefused("case_closed", "This case is closed.")
    _entry(case, entry_id)
    return (get_supabase().table("officer_change_entries").update({
        "kyc_cleared": bool(cleared),
        "kyc_cleared_at": _now() if cleared else None,
        "kyc_cleared_by": user_id if cleared else None,
        "updated_at": _now(),
    }).eq("id", entry_id).execute().data[0])


def refresh_items(case: dict, entries: list[dict]) -> list[dict]:
    """Re-diff every `change` entry against the profile, keeping the dates and
    omissions of surviving items (Review Focus 3).

    Editing a value back on the profile makes its line disappear here, which is
    the whole of answer 14's "they can go back to the person profile and change
    it back ... and see that the change is gone".
    """
    if not editable(case):
        return entries
    out = []
    for entry in entries:
        if entry.get("kind") != "change":
            out.append(entry)
            continue
        party = ({"person_id": entry["person_id"]} if entry.get("person_id")
                 else {"corporate_entity_id": entry.get("corporate_entity_id")})
        fresh = particulars.pending_for_officer(
            case["entity_id"], capacity=entry["capacity"], **party)
        kept = {i["key"]: i for i in entry.get("items") or []}
        items = [{**item, "effective_date": kept[item["key"]].get("effective_date"),
                  "omitted": kept[item["key"]].get("omitted", False)}
                 if item["key"] in kept else item for item in fresh]
        registered = particulars.registered_view(case["entity_id"], **party)
        if items != entry.get("items") or registered != entry.get("registered"):
            entry = (get_supabase().table("officer_change_entries")
                     .update({"items": items, "registered": registered,
                              "updated_at": _now()})
                     .eq("id", entry["id"]).execute().data[0])
        out.append(entry)
    if out != entries:
        _store_deadline(case["id"])
    return out


# -- reading: officers, parties, signatory ------------------------------------------

def _by_id(table: str, ids, cols: str = "*") -> dict[str, dict]:
    ids = sorted({i for i in ids if i})
    if not ids:
        return {}
    rows = get_supabase().table(table).select(cols).in_("id", ids).execute().data or []
    return {r["id"]: r for r in rows}


def _current_officers(entity_id: str, entries: list[dict]) -> list[dict]:
    """The pickers' list: current directors and secretaries, named."""
    rows = (get_supabase().table("entity_officers").select("*")
            .eq("entity_id", entity_id).eq("is_current", True).execute().data) or []
    rows = [r for r in rows if r.get("role") in _CAPACITIES]
    people = _by_id("persons", [r.get("person_id") for r in rows])
    corps = _by_id("entities", [r.get("corporate_entity_id") for r in rows])
    on_case = {e.get("officer_id") for e in entries if e.get("officer_id")}
    twins, register = _secretary_registers(entity_id, rows, corps)
    out = []
    for r in rows:
        party = _party_of(r)
        person = people.get(r.get("person_id") or "") or {}
        corp = corps.get(r.get("corporate_entity_id") or "") or {}
        out.append({
            "officer_id": r["id"], "role": r["role"],
            "party_type": party["party_type"], "person_id": party["person_id"],
            "corporate_entity_id": party["corporate_entity_id"],
            "name": (person.get("full_name") if party["person_id"]
                     else corp.get("company_name") or r.get("corporate_name")) or "(unnamed)",
            "appointed_date": r.get("appointed_date"),
            "date_of_death": person.get("date_of_death"),
            "pending": r["id"] in on_case,
            # The secretary-register rows naming the same secretary, so a Cease
            # pressed on the profile's Secretary tile (which reads the register)
            # finds this officer.
            "secretary_ids": twins.get(r["id"], []),
        })
    reg_people = _by_id("persons", [r.get("person_id") for r in register])
    for r in register:
        person = reg_people.get(r.get("person_id") or "") or {}
        corp_id = None if r.get("person_id") else _resolve_corporate(r.get("secretary_name"))[0]
        out.append({
            # No officer row yet: an entry posts `secretary_id`, and
            # `_officer_for_secretary` gives it one.
            "officer_id": None, "secretary_id": r["id"], "register_only": True,
            "role": "company_secretary",
            "party_type": "individual" if r.get("person_id") else "corporate",
            "person_id": r.get("person_id"), "corporate_entity_id": corp_id,
            "name": (person.get("full_name") if r.get("person_id")
                     else r.get("secretary_name")) or "(unnamed)",
            "appointed_date": r.get("appointed_date"),
            "date_of_death": person.get("date_of_death"),
            "pending": False, "secretary_ids": [r["id"]],
        })
    out.sort(key=lambda o: (o["role"], (o["name"] or "").lower()))
    return out


def _parties(entries: list[dict]) -> dict:
    """Everything the page and the rules read about each party, in one pass."""
    person_ids = [e.get("person_id") for e in entries] + \
                 [e.get("consent_person_id") for e in entries]
    people = _by_id("persons", person_ids)
    corps = _by_id("entities", [e.get("corporate_entity_id") for e in entries])
    address_ids = [p.get("residential_address_id") for p in people.values()] + \
                  [c.get("registered_address_id") for c in corps.values()]
    addresses = _by_id("addresses", address_ids)
    ids = sorted(people)
    docs = (get_supabase().table("person_identity_documents").select("*")
            .in_("person_id", ids).execute().data or []) if ids else []
    return {"people": people, "corps": corps, "addresses": addresses, "docs": docs}


def _party_view(entry: dict, ctx: dict) -> dict:
    if entry.get("person_id"):
        person = ctx["people"].get(entry["person_id"]) or {}
        home = ctx["addresses"].get(person.get("residential_address_id") or "")
        docs = [d for d in ctx["docs"] if d.get("person_id") == entry["person_id"]]
        hkid = next((d for d in docs if d.get("id_type") == "hkid"), None)
        passport = next((d for d in docs if d.get("id_type") == "passport"), None)
        missing = []
        if not (person.get("surname") or person.get("given_names") or person.get("full_name")):
            missing.append("English name")
        if not home:
            missing.append("residential address")
        if not person.get("email"):
            missing.append("email address")
        if not hkid and not passport:
            missing.append("HKID or passport")
        return {
            "name": person.get("full_name") or "(unnamed person)",
            "name_zh": person.get("full_name_zh") or "",
            "email": person.get("email") or "",
            "profile_path": f"/persons/{entry['person_id']}",
            "missing": missing,
            "date_of_birth": person.get("date_of_birth"),
            "residential_address": home,
            "hkid": (hkid or {}).get("id_number") or "",
            "passport": ({"number": passport.get("id_number"),
                          "issuing_country": passport.get("issuing_country")}
                         if passport else None),
        }
    corp = ctx["corps"].get(entry.get("corporate_entity_id") or "") or {}
    office = ctx["addresses"].get(corp.get("registered_address_id") or "")
    missing = [label for label, ok in (("registered office address", office),
                                       ("email address", corp.get("email"))) if not ok]
    return {
        "name": corp.get("company_name") or "(unnamed body corporate)",
        "name_zh": corp.get("company_name_zh") or "",
        "email": corp.get("email") or "",
        "profile_path": f"/companies/{entry.get('corporate_entity_id')}",
        "missing": missing,
        "address": office,
    }


def _day(value) -> str:
    when = deadlines._as_date(value)
    return f"{when.day} {when:%b %Y}" if when else "date not set"


def _summary(entry: dict) -> str:
    capacity = _CAPACITY_LABEL.get(entry.get("capacity"), "Officer")
    if entry.get("kind") == "cessation":
        bits = [capacity, f"ceases {_day(entry.get('effective_date'))}"]
        if entry.get("cessation_reason"):
            bits.append(_REASON_LABEL[entry["cessation_reason"]])
        return " · ".join(bits)
    if entry.get("kind") == "appointment":
        return f"{capacity} · appointed {_day(entry.get('effective_date'))}"
    filed = [i for i in entry.get("items") or [] if not i.get("omitted")]
    if not entry.get("items"):
        return f"{capacity} · no changes on the profile since CR was last told"
    return f"{capacity} · {len(filed)} of {len(entry['items'])} change(s) to file"


def _signatory_party(entity_id: str) -> tuple[str, bool]:
    """`(name, is_corporate)` of whoever signs, in the ORDER the XML takes them
    (`nar1_mapper._signatory_candidates`): the secretary REGISTER first, a
    GSHK-flagged row before any other, then a secretary on the officer list.

    Reading the officer list alone named nobody for a company whose secretary
    is on the register only — and offered a natural-person secretary CR's Body
    Corporate capacities, a value that does not fit the signer the XML then
    names."""
    sb = get_supabase()
    register = (sb.table("company_secretaries").select("*").eq("entity_id", entity_id)
                .eq("is_current", True).execute().data) or []
    register.sort(key=lambda r: not r.get("is_gshk"))
    officers = (sb.table("entity_officers").select("*").eq("entity_id", entity_id)
                .eq("role", "company_secretary").eq("is_current", True).execute().data) or []
    candidates = register + officers
    people = _by_id("persons", [r.get("person_id") for r in candidates])
    corps = _by_id("entities", [r.get("corporate_entity_id") for r in candidates])
    for row in candidates:
        person = people.get(row.get("person_id") or "")
        if person:
            return person.get("full_name") or person.get("full_name_zh") or "", False
        name = (row.get("secretary_name") or row.get("corporate_name")
                or (corps.get(row.get("corporate_entity_id") or "") or {}).get("company_name"))
        if name:
            return name, True
    return "", True


def _signatory(entity_id: str, case: dict) -> dict:
    """Who signs the form-level declaration: the company secretary, as NAR1's
    `_signatory_block` derives it — for nearly every GSHK client, GSHK Ltd."""
    name, is_corporate = _signatory_party(entity_id)
    choices = sorted(CAPACITY_BODY_CORPORATE if is_corporate else CAPACITY_INDIVIDUAL)
    return {"name": name, "is_corporate": is_corporate, "capacities": choices,
            "default_capacity": default_capacity(is_corporate=is_corporate),
            "selected_capacity": case.get("signatory_capacity")}


# -- the composite -----------------------------------------------------------------

def _soft(problems: list[str], what: str, fn, default):
    """Run one optional part of the composite; a failure is a problem line, not
    a 500 — the page must render the case it can, and say what it cannot."""
    try:
        return fn()
    except NotImplementedError as exc:
        problems.append(f"{what} is not available yet ({exc})")
    except Exception as exc:  # noqa: BLE001 — see docstring
        print(f"officer-change composite: {what} failed: {exc!r}", file=sys.stderr)
        problems.append(f"{what} could not be loaded")
    return default


async def _soft_async(problems: list[str], what: str, coro_fn, default):
    try:
        return await coro_fn()
    except NotImplementedError as exc:
        problems.append(f"{what} is not available yet ({exc})")
    except Exception as exc:  # noqa: BLE001
        print(f"officer-change composite: {what} failed: {exc!r}", file=sys.stderr)
        problems.append(f"{what} could not be loaded")
    return default


async def composite(case_id: str, *, user: dict) -> dict:
    """C-4: everything the officer-change page reads, in one response."""
    case = get_case(case_id)
    problems: list[str] = []
    base = _soft(problems, "The case header", lambda: nar1_cases.composite(case_id),
                 dict(case))
    entries = list_entries(case_id)
    entity = (_by_id("entities", [case["entity_id"]]).get(case["entity_id"]) or {})
    officers = _current_officers(case["entity_id"], entries)
    ctx = _parties(entries)
    eservice_meta = _soft(problems, "e-Registry credentials", lambda: eservice.metadata_for(
        [e.get("person_id") for e in entries if e.get("kind") == "appointment"]
        + [e.get("consent_person_id") for e in entries]), {})
    docs = _soft(problems, "Supporting documents",
                 lambda: documents.list_for_case(case_id, entries), [])

    view = []
    for entry in entries:
        consent = ctx["people"].get(entry.get("consent_person_id") or "") or {}
        signer = entry.get("consent_person_id") or entry.get("person_id")
        needs_consent = entry.get("kind") == "appointment" and entry.get("capacity") == "director"
        view.append({
            **entry,
            "party": _party_view(entry, ctx),
            "consent_person_name": consent.get("full_name"),
            "summary": _summary(entry),
            "eservice": (eservice_meta.get(signer) or {"configured": False,
                                                       "has_password": False,
                                                       "eservice_user_id": None})
                        if needs_consent else None,
            "documents": [d for d in docs if d.get("entry_id") == entry["id"]],
        })

    due = deadlines.filing_deadline(entries)
    today = deadlines.hk_today()
    rule_result = rules.evaluate(officers, view, company=entity, today=today, deadline=due)
    consents = await _soft_async(problems, "The consent-signature plan",
                                 lambda: prepare.consent_plan(case, entries), [])
    problems += await _soft_async(problems, "The CR form",
                                  lambda: prepare.mapping_problems(case, entries), [])
    profile_changes = _soft(problems, "The profile-update plan", lambda: apply.plan(
        {**case, "company_name": entity.get("company_name")}, view), [])
    reasons = [c.get("reason") for c in consents if not c.get("ready") and c.get("reason")]
    esign = not reasons
    filing = _soft(problems, "The CR filing", lambda: nar1_cases.current_filing(case_id), None)

    return {
        **case,
        **base,
        "workflow_status": base.get("workflow_status") or nar1_case_status.derive(case, filing),
        "form_code": case["form_code"],
        "case_type": _PREFIX[case["form_code"]],
        "company_name": entity.get("company_name") or base.get("company_name"),
        "br_number": entity.get("br_number") or base.get("br_number"),
        "editable": editable(case),
        "deadline": {"date": _iso(due), "days": (due - today).days if due else None,
                     "overdue": bool(due and due < today and not case.get("manual_receipt")
                                     and not case.get("changes_applied_at")),
                     "basis": "Earliest change on the form + 15 days"},
        "reply_by_default": _iso(deadlines.reply_by_default(due, today)),
        "entries": view,
        "rules": rule_result,
        "route": {"esign_available": esign, "reasons": reasons,
                  "selected": case.get("signing_method"),
                  "default": "esign" if esign else "manual", "consents": consents},
        "officers": officers,
        "documents": docs,
        "signatory": _signatory(case["entity_id"], case),
        "profile_changes": profile_changes,
        "problems": problems,
        "filing": ({k: filing.get(k) for k in ("id", "stage", "validated_at",
                                                "signed_at", "submitted_at")}
                   if filing else None),
        "applied_at": case.get("changes_applied_at"),
        "undone_at": case.get("changes_undone_at"),
    }


def open_cases_for(*, entity_id: str | None = None,
                   person_id: str | None = None) -> list[dict]:
    """The `cases` rows of `GET /officer-changes/pending`: unfinished officer
    changes for a company, or naming a person (as officer or consent signer)."""
    sb = get_supabase()
    if person_id:
        named = (sb.table("officer_change_entries").select("*")
                 .eq("person_id", person_id).execute().data or []) + \
                (sb.table("officer_change_entries").select("*")
                 .eq("consent_person_id", person_id).execute().data or [])
        ids = sorted({e["case_id"] for e in named})
        rows = (sb.table("nar1_cases").select("*").in_("id", ids).execute().data or []) \
            if ids else []
    else:
        rows = sb.table("nar1_cases").select("*").eq("entity_id", entity_id).execute().data or []
    rows = [r for r in rows if r.get("form_code") in FORM_CODES
            and not r.get("closed_at") and not r.get("changes_applied_at")
            and not r.get("manual_receipt")]
    if not rows:
        return []
    names = _by_id("entities", [r["entity_id"] for r in rows])
    out = []
    for case in sorted(rows, key=lambda r: r.get("case_no") or ""):
        entries = list_entries(case["id"])
        ctx = _parties(entries)
        out.append({
            "id": case["id"], "case_no": case.get("case_no"),
            "form_code": case["form_code"], "case_type": _PREFIX[case["form_code"]],
            "workflow_status": nar1_case_status.derive(case, None),
            "entity_id": case["entity_id"],
            "company_name": (names.get(case["entity_id"]) or {}).get("company_name"),
            "entries": [{"id": e["id"], "kind": e["kind"], "capacity": e["capacity"],
                         "party_name": _party_view(e, ctx)["name"],
                         "person_id": e.get("person_id"),
                         "corporate_entity_id": e.get("corporate_entity_id"),
                         "officer_id": e.get("officer_id")} for e in entries],
        })
    return out
