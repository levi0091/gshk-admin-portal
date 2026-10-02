"""Writing a filed officer change to the profiles, and taking it back.

Spec B-5 (PRD Q10): the profiles change when the form is FILED — CR accepted
the e-filing, or the CR-portal filing was recorded — not when CR registers it
days later. A CR rejection after that is answered by *Undo profile update* on
the CR Status stage, which reverses exactly what this module recorded.

  * cessation  → the `entity_officers` row is marked former (is_current=false,
    resigned_date, resignation_reason from CR's reason), and so is the matching
    current `company_secretaries` row: the NAR1 mapper reads that register
    FIRST, so leaving it current would file a departed secretary on the next
    annual return.
  * appointment → a new `entity_officers` row (written to `entry.officer_id`),
    and the appointment's ND2B baseline, carrying the correspondence address
    the ND2A filed (spec B-15). No `company_secretaries` row is written: the
    mapper falls back to `entity_officers`, exactly as it does for every
    company created in the portal.
  * change → nothing on the profile (it is already right, answer 14); the
    baseline moves forward for the filed items only.

Each entry records what was written in `entry.applied`, which is what makes a
second run skip it (idempotence after a partial failure) and what Undo reads.
Nothing here raises once work has begun: errors are returned, because by then
CR already holds the form and a 500 would report a filing that succeeded as
one that failed.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from db.supabase import get_supabase
from services.officer_changes import particulars
from services.officer_changes.deadlines import _as_date

_CAPACITY = {"director": "director", "company_secretary": "company secretary"}
_REASON = {"R": "Resignation / Others", "D": "Deceased"}
_OFFICER_COLS = ("is_current", "resigned_date", "resignation_reason")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _name(entry: dict) -> str:
    return ((entry.get("party") or {}).get("name")) or "The officer"


def _party(entry: dict) -> dict:
    if entry.get("person_id"):
        return {"person_id": entry["person_id"]}
    return {"corporate_entity_id": entry.get("corporate_entity_id")}


def _day(value) -> str:
    when = _as_date(value)
    return f"{when.day} {when:%b %Y}" if when else "date not set"


def plan(case: dict, entries: list[dict]) -> list[dict]:
    """The `profile_changes` rows of C-4: what filing will write, and where."""
    company = {"kind": "company", "id": case.get("entity_id"),
               "name": case.get("company_name") or "this company"}
    rows = []
    for e in entries:
        capacity = _CAPACITY.get(e.get("capacity"), "officer")
        if e.get("kind") == "cessation":
            reason = f", {_REASON[e['cessation_reason']]}" if e.get("cessation_reason") else ""
            rows.append({"entry_id": e["id"], "target": company,
                         "text": f"Mark {_name(e)} as a former {capacity} "
                                 f"(ceased {_day(e.get('effective_date'))}{reason})"})
        elif e.get("kind") == "appointment":
            rows.append({"entry_id": e["id"], "target": company,
                         "text": f"Add {_name(e)} as a {capacity} from "
                                 f"{_day(e.get('effective_date'))}"})
        elif e.get("kind") == "change":
            filed = [i.get("label") or i["key"] for i in e.get("items") or []
                     if not i.get("omitted")]
            if not filed:
                continue
            kind = "person" if e.get("person_id") else "company"
            target = {"kind": kind,
                      "id": e.get("person_id") or e.get("corporate_entity_id"),
                      "name": _name(e)}
            rows.append({"entry_id": e["id"], "target": target,
                         "text": f"Record {', '.join(filed)} for {_name(e)} as filed "
                                 "with the Companies Registry"})
    return rows


def _secretary_rows(sb, case: dict, entry: dict) -> list[dict]:
    rows = (sb.table("company_secretaries").select("*").eq("entity_id", case["entity_id"])
            .eq("is_current", True).execute().data) or []
    if entry.get("person_id"):
        return [r for r in rows if r.get("person_id") == entry["person_id"]]
    # Whitespace-normalised, as `cases._secretary_registers` matches the same
    # rows: a register name with a doubled space is still that company.
    norm = lambda v: " ".join(str(v or "").split()).casefold()  # noqa: E731
    name = norm(_name(entry))
    return [r for r in rows if not r.get("person_id")
            and norm(r.get("secretary_name")) == name]


def _apply_cessation(sb, case, entry) -> dict:
    officer = (sb.table("entity_officers").select("*").eq("id", entry["officer_id"])
               .execute().data or [None])[0]
    if officer is None:
        raise LookupError("the officer row no longer exists")
    before = {k: officer.get(k) for k in _OFFICER_COLS}
    sb.table("entity_officers").update({
        "is_current": False, "resigned_date": entry.get("effective_date"),
        "resignation_reason": _REASON.get(entry.get("cessation_reason"))
        or officer.get("resignation_reason"),
        "updated_at": _now(),
    }).eq("id", officer["id"]).execute()
    secretaries = []
    if entry.get("capacity") == "company_secretary":
        for row in _secretary_rows(sb, case, entry):
            sb.table("company_secretaries").update({"is_current": False}) \
                .eq("id", row["id"]).execute()
            secretaries.append({"id": row["id"], "before": {"is_current": True}})
    return {"officer": {"id": officer["id"], "before": before},
            "company_secretaries": secretaries}


def _apply_appointment(sb, case, entry, user) -> dict:
    corporate = entry.get("party_type") == "corporate"
    party = _party(entry)
    before = particulars.baseline(case["entity_id"], **party)
    # The appointment's own correspondence address, when it differs from the
    # residential one — so the profile shows what CR was told (Jacqueline B4).
    correspondence_id = None
    if not corporate and entry.get("correspondence_same_as_residential") is False \
            and isinstance(entry.get("correspondence_address"), dict):
        address = {k: entry["correspondence_address"].get(k) for k in
                   ("line1", "line2", "line3", "city", "state_region", "postal_code",
                    "country")}
        correspondence_id = sb.table("addresses").insert(address).execute().data[0]["id"]
    row = sb.table("entity_officers").insert({
        "entity_id": case["entity_id"],
        "person_id": None if corporate else entry.get("person_id"),
        "corporate_entity_id": entry.get("corporate_entity_id") if corporate else None,
        "party_type": "corporate" if corporate else "individual",
        "corporate_name": _name(entry) if corporate else None,
        "role": entry["capacity"], "appointed_date": entry.get("effective_date"),
        "is_current": True, "correspondence_address_id": correspondence_id,
    }).execute().data[0]
    record = {"officer_id": row["id"], "baseline_before": before}
    # Recorded the moment the row exists, before anything else can fail: an
    # inserted officer with no `applied` record is one Undo cannot find, and a
    # retry would insert them a second time.
    sb.table("officer_change_entries").update({
        "officer_id": row["id"], "applied": {**record, "partial": True}}) \
        .eq("id", entry["id"]).execute()
    particulars.set_baseline(case["entity_id"],
                             particulars=_filed_view(case, entry, before, row["id"]),
                             source="nd2a_filed", user_id=user["id"], **party)
    return record


def _filed_view(case: dict, entry: dict, before: dict | None, new_officer_id: str) -> dict:
    """What CR holds about the appointee once the ND2A is filed.

    The ND2A filed the party's CURRENT particulars, so that is the baseline —
    unless the party still holds another current appointment in this company,
    whose baseline (with its unfiled changes) CR already holds for the same
    person and which the new appointment must not silently overwrite. A
    baseline left behind by an appointment that has since CEASED is not "what
    CR holds" any more: re-appointing someone files them afresh."""
    party = _party(entry)
    keep = before is not None and _holds_another_appointment(case, party, new_officer_id)
    snapshot = before if keep else particulars.snapshot_current(**party)
    if entry.get("party_type") != "corporate" \
            and entry.get("correspondence_same_as_residential") is False:
        snapshot = {**snapshot, "correspondence_address": entry.get("correspondence_address")}
    return snapshot


def _holds_another_appointment(case: dict, party: dict, new_officer_id: str) -> bool:
    """A current officer row for the party in this company, other than the one
    this filing just inserted."""
    key, value = next(iter(party.items()))
    rows = (get_supabase().table("entity_officers").select("*")
            .eq("entity_id", case["entity_id"]).eq(key, value).eq("is_current", True)
            .execute().data) or []
    return any(r.get("id") != new_officer_id for r in rows)


def _apply_change(sb, case, entry, user) -> dict:
    party = _party(entry)
    before = particulars.baseline(case["entity_id"], **party)
    filed = [i for i in entry.get("items") or [] if not i.get("omitted")]
    particulars.advance(case["entity_id"], items=filed, user_id=user["id"],
                        capacity=entry.get("capacity"), **party)
    return {"baseline_before": before, "items": [i["key"] for i in filed]}


async def apply_changes(case: dict, entries: list[dict], *, user: dict) -> dict:
    """`{"applied": [...], "errors": [str]}`. Idempotent."""
    sb = get_supabase()
    applied, errors = [], []
    texts = {r["entry_id"]: r["text"] for r in plan(case, entries)}
    for entry in entries:
        record = entry.get("applied") or {}
        if record and not record.get("partial"):
            continue
        if record.get("partial") and entry["kind"] == "appointment":
            # A retry after the officer row went in but the baseline did not:
            # finish THAT row rather than insert the appointee a second time.
            try:
                party = _party(entry)
                particulars.set_baseline(
                    case["entity_id"], source="nd2a_filed", user_id=user["id"],
                    particulars=_filed_view(case, entry, record.get("baseline_before"),
                                            record["officer_id"]), **party)
                done = {k: v for k, v in record.items() if k != "partial"}
                sb.table("officer_change_entries").update(
                    {"applied": {**done, "applied_at": _now()}}).eq("id", entry["id"]).execute()
                applied.append({"entry_id": entry["id"], "text": texts.get(entry["id"], "")})
            except Exception as exc:  # noqa: BLE001
                print(f"officer change apply retry failed for {entry.get('id')}: {exc!r}",
                      file=sys.stderr)
                errors.append(f"{_name(entry)}: {exc}")
            continue
        try:
            if entry["kind"] == "cessation":
                record = _apply_cessation(sb, case, entry)
            elif entry["kind"] == "appointment":
                record = _apply_appointment(sb, case, entry, user)
            else:
                record = _apply_change(sb, case, entry, user)
            record["applied_at"] = _now()
            sb.table("officer_change_entries").update({"applied": record}) \
                .eq("id", entry["id"]).execute()
            applied.append({"entry_id": entry["id"], "text": texts.get(entry["id"], "")})
        except Exception as exc:  # noqa: BLE001 — see module docstring
            print(f"officer change apply failed for {entry.get('id')}: {exc!r}",
                  file=sys.stderr)
            errors.append(f"{_name(entry)}: {exc}")
    if not errors:
        sb.table("nar1_cases").update({"changes_applied_at": _now(),
                                       "updated_at": _now()}).eq("id", case["id"]).execute()
    return {"applied": applied, "errors": errors}


def _restore_baseline(sb, case, entry, before, user) -> None:
    party = _party(entry)
    if before is not None:
        particulars.set_baseline(case["entity_id"], particulars=before, source="undo",
                                 user_id=user["id"], **party)
        return
    query = sb.table("officer_cr_particulars").delete().eq("entity_id", case["entity_id"])
    key, value = next(iter(party.items()))
    query.eq(key, value).execute()


async def undo_changes(case: dict, entries: list[dict], *, user: dict) -> dict:
    """Reverse exactly what `applied` records. Same shape as `apply_changes`."""
    sb = get_supabase()
    undone, errors = [], []
    for entry in entries:
        record = entry.get("applied")
        if not record:
            continue
        try:
            if entry["kind"] == "cessation":
                officer = record["officer"]
                sb.table("entity_officers").update({**officer["before"], "updated_at": _now()}) \
                    .eq("id", officer["id"]).execute()
                for row in record.get("company_secretaries") or []:
                    sb.table("company_secretaries").update(row["before"]) \
                        .eq("id", row["id"]).execute()
            elif entry["kind"] == "appointment":
                sb.table("entity_officers").delete().eq("id", record["officer_id"]).execute()
                sb.table("officer_change_entries").update({"officer_id": None}) \
                    .eq("id", entry["id"]).execute()
                _restore_baseline(sb, case, entry, record.get("baseline_before"), user)
            else:
                _restore_baseline(sb, case, entry, record.get("baseline_before"), user)
            sb.table("officer_change_entries").update({"applied": None}) \
                .eq("id", entry["id"]).execute()
            undone.append({"entry_id": entry["id"]})
        except Exception as exc:  # noqa: BLE001
            print(f"officer change undo failed for {entry.get('id')}: {exc!r}",
                  file=sys.stderr)
            errors.append(f"{_name(entry)}: {exc}")
    if not errors:
        sb.table("nar1_cases").update({"changes_undone_at": _now(),
                                       "updated_at": _now()}).eq("id", case["id"]).execute()
    return {"applied": undone, "errors": errors}
