"""The company secretaries as they stand once an ND2A is filed — who signs it.

An ND2A's page-3 signature is "a director or the company secretary" (CR's note
6). The NAR1 rule the ND2A borrowed reads the CURRENT register, so a form that
ceases Corpagent Online (HK) Limited and appoints Get Started HK Limited as
secretary printed "Corpagent Online (HK) Limited, Company Secretary" — the firm
the form itself removes (Jacqueline, PROD feedback 2026-11-12). The signer is
taken from the register AFTER the changes instead: a secretary this form ceases
is not a candidate, and one it appoints is.

Pure: rows in, rows out. `nd2a_mapper.after_changes` applies it to the form's
graph; `cases._signatory_row` to the rows the case screen reads, so the screen's
"signs as" and the printed form name the same party.
"""
from __future__ import annotations

#: Get Started HK Limited's BR number — `GSHK_BRN` in the appointment drawer.
#: An APPOINTED secretary has no register row yet, so no `is_gshk` flag; GSHK
#: still signs first (Q-030), and its BR is how it is recognised.
GSHK_BR = "67169839"

SECRETARY = "company_secretary"


def _norm(value) -> str:
    return " ".join(str(value or "").split()).casefold()


def ceased(entries: list[dict], corporate_names: dict[str, str]) -> dict:
    """What the form's secretary cessations remove. `corporate_names` maps a
    body corporate's id to its name, for the register, which holds it by name."""
    gone = {"officer_ids": set(), "person_ids": set(), "corporate_ids": set(), "names": set()}
    for entry in entries:
        if entry.get("kind") != "cessation" or entry.get("capacity") != SECRETARY:
            continue
        if entry.get("officer_id"):
            gone["officer_ids"].add(entry["officer_id"])
        if entry.get("person_id"):
            gone["person_ids"].add(entry["person_id"])
        elif entry.get("corporate_entity_id"):
            gone["corporate_ids"].add(entry["corporate_entity_id"])
            name = _norm(corporate_names.get(entry["corporate_entity_id"]))
            if name:
                gone["names"].add(name)
    return gone


def is_ceased(row: dict, gone: dict) -> bool:
    """A register (`company_secretaries`) or officer (`entity_officers`) row
    this form ceases."""
    if row.get("role") == SECRETARY and row.get("id") in gone["officer_ids"]:
        return True
    if row.get("person_id"):
        return row["person_id"] in gone["person_ids"]
    if row.get("corporate_entity_id") and row["corporate_entity_id"] in gone["corporate_ids"]:
        return True
    return _norm(row.get("secretary_name") or row.get("corporate_name")) in gone["names"]


def appointed(entries: list[dict]) -> list[dict]:
    """The form's secretary appointments, in the order the operator added them."""
    return [e for e in entries
            if e.get("kind") == "appointment" and e.get("capacity") == SECRETARY]


def changes_secretary(entries: list[dict]) -> bool:
    return any(e.get("capacity") == SECRETARY and e.get("kind") in ("cessation", "appointment")
               for e in entries)
