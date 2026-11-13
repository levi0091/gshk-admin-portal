"""Who puts the OVERALL signature on an e-Signed ND2A: GSHK, or a director.

Levi, 2026-11-13: "when it is a change of corp secretary, we need to use the
director e-reg to sign and not GetStarted HK e-reg sign, because at that point
GSHK is still not related to the company."

  gshk      The signed-in staff member's own e-Service account (CR Credentials),
            for the company secretary after the form's changes — the signer
            NAR1 and every ND2 used until now (`nd2a_mapper.signatory`).
  director  A CURRENT director who stays on after the form, signing as
            "Director" with the e-Registry account stored on their own
            natural-person profile (`person_eservice_credentials`, the account
            their consent signatures already use). The form's signatory block
            then names that account (`selectPersonId` / `selectPersonName`), and
            the overall PinSign is computed with it.

THE DEFAULT. Director when the ND2A changes the company secretary AND some
director's account is complete; GSHK otherwise. A director with no complete
account can never be chosen — there is nothing to sign with.

ONE ANSWER PER FILING. Validating with CR stores the party it validated
(`pinned_for_validation`), and signing reads only the stored value (`for_sign`),
never the default: the signatory block is inside the XML CR checked, so the
account that signs must be the one that block names. Changing the choice after
validation supersedes the filing, so CR validates the new signer.

Only ND2A offers the choice. ND2B keeps the GSHK signer.

The quick paths read nothing from the database: a case already pinned to GSHK,
or one that does not touch the secretary and has no stored choice, resolves to
GSHK without asking for candidates.
"""
from __future__ import annotations

from db.supabase import get_supabase
from services.officer_changes import capacities, eservice, secretaries_after

GSHK = "gshk"
DIRECTOR = "director"
PARTIES = (GSHK, DIRECTOR)

#: The capacity a director signs the form in — CR's Individual vocabulary.
DIRECTOR_CAPACITY = "Director"


class SignerUnavailable(Exception):
    """The chosen director cannot sign: not a current director staying on, or
    no complete e-Registry account."""


def offered(case: dict) -> bool:
    return case.get("form_code") == "Nd2a"


def _ceased_director_ids(entries: list[dict]) -> tuple[set, set]:
    officers, people = set(), set()
    for e in entries or []:
        if e.get("kind") == "cessation" and capacities.acts_as_director(e.get("capacity")):
            if e.get("officer_id"):
                officers.add(e["officer_id"])
            if e.get("person_id"):
                people.add(e["person_id"])
    return officers, people


def candidates(case: dict, entries: list[dict]) -> list[dict]:
    """Every current natural-person director who is still a director once this
    form is filed, with whether their stored e-Registry account can sign.

    A director the form ceases is left out: they cannot sign for a board they
    are leaving. Alternates are left out: CR's note 6 says "a director".
    """
    sb = get_supabase()
    rows = (sb.table("entity_officers").select("*").eq("entity_id", case["entity_id"])
            .eq("role", capacities.DIRECTOR).eq("is_current", True).execute().data) or []
    gone_officers, gone_people = _ceased_director_ids(entries)
    seen, people_ids = set(), []
    for r in rows:
        pid = r.get("person_id")
        if not pid or pid in seen or r.get("id") in gone_officers or pid in gone_people:
            continue
        seen.add(pid)
        people_ids.append(pid)
    if not people_ids:
        return []
    people = {p["id"]: p for p in (sb.table("persons").select("id,full_name")
                                   .in_("id", people_ids).execute().data or [])}
    docs: dict[str, list[dict]] = {}
    for d in (sb.table("person_identity_documents").select("*")
              .in_("person_id", people_ids).execute().data or []):
        docs.setdefault(d["person_id"], []).append(d)
    accounts = eservice.metadata_for(people_ids)
    out = []
    for pid in people_ids:
        name = (people.get(pid) or {}).get("full_name") or "This director"
        account = accounts.get(pid) or {}
        if not account.get("eservice_user_id"):
            reason = "e-Registry not set up"
        elif not account.get("eservice_person_name"):
            reason = "The name on the e-Registry account is not recorded"
        elif not account.get("has_password"):
            reason = "The e-Registry password is not stored"
        else:
            reason = None
        out.append({
            "person_id": pid, "name": name,
            "eservice_user_id": account.get("eservice_user_id"),
            "eservice_person_name": account.get("eservice_person_name"),
            "ready": reason is None, "reason": reason,
            "profile_path": f"/persons/{pid}",
            # A warning, not a refusal: CR decides (Jacqueline, note 1).
            "id_mismatch": eservice.identity_mismatch(account, docs.get(pid, []), name=name),
        })
    out.sort(key=lambda c: (not c["ready"], c["name"].casefold()))
    return out


def default_party(entries: list[dict], options: list[dict]) -> str:
    if secretaries_after.changes_secretary(entries) and any(c["ready"] for c in options):
        return DIRECTOR
    return GSHK


def resolve(case: dict, entries: list[dict], options: list[dict] | None = None) -> dict:
    """`{party, stored, default, director, candidates, changes_secretary}`.

    `director` is the candidate who signs when the party is director — the
    stored one, else the first whose account is complete — or None when nobody
    can. `candidates` is None on a quick path, where nothing was read."""
    changes = secretaries_after.changes_secretary(entries)
    stored = case.get("signing_party") if case.get("signing_party") in PARTIES else None
    base = {"stored": stored is not None, "changes_secretary": changes}
    if not offered(case):
        return {**base, "party": GSHK, "default": GSHK, "director": None, "candidates": None}
    if options is None and (stored == GSHK or (stored is None and not changes)):
        return {**base, "party": GSHK, "default": GSHK, "director": None, "candidates": None}
    options = candidates(case, entries) if options is None else options
    default = default_party(entries, options)
    party = stored or default
    director = None
    if party == DIRECTOR:
        wanted = case.get("signing_director_person_id")
        if wanted:
            director = next((c for c in options if c["person_id"] == wanted and c["ready"]), None)
        else:
            director = next((c for c in options if c["ready"]), None)
    return {**base, "party": party, "default": default, "director": director,
            "candidates": options}


def form_signatory(director: dict) -> dict:
    """The explicit signatory `nar1_mapper._signatory_block` takes for a
    director: a natural person, named as their e-Registry account names them —
    CR checks `selectPersonName` against the account, as on the consents."""
    return {"name": director.get("eservice_person_name") or director.get("name"),
            "capacity": DIRECTOR_CAPACITY,
            "person_id": director.get("eservice_user_id"),
            "is_corporate": False, "date": None}


def pinned_for_validation(case: dict, entries: list[dict]) -> dict:
    """What validating stores on the case: `{signing_party, signing_director_person_id}`.
    Raises `SignerUnavailable` when the party is director and nobody can sign."""
    choice = resolve(case, entries)
    if choice["party"] == DIRECTOR:
        if choice["director"] is None:
            raise SignerUnavailable(
                "No director who stays on after this form has a complete e-Registry "
                "account to sign with. Set one up on the director's profile, or choose "
                "GSHK e-Service at Signing.")
        return {"signing_party": DIRECTOR,
                "signing_director_person_id": choice["director"]["person_id"]}
    return {"signing_party": GSHK, "signing_director_person_id": None}


def for_sign(case: dict) -> str | None:
    """The director's person id when the VALIDATED form is signed by a director,
    else None (GSHK). Reads the stored value only — never the default."""
    if offered(case) and case.get("signing_party") == DIRECTOR:
        return case.get("signing_director_person_id") or ""
    return None


def view(case: dict, entries: list[dict], *, staff_account: str | None,
         gshk_signatory: dict) -> dict:
    """What the Signing stage draws."""
    if not offered(case):
        return {"offered": False}
    choice = resolve(case, entries, candidates(case, entries))
    return {
        "offered": True,
        "party": choice["party"],
        "stored": choice["stored"],
        "default": choice["default"],
        "changes_secretary": choice["changes_secretary"],
        "director_person_id": (choice["director"] or {}).get("person_id")
                              or (case.get("signing_director_person_id")
                                  if choice["party"] == DIRECTOR else None),
        "director_ready": choice["director"] is not None,
        "candidates": choice["candidates"] or [],
        "gshk": {"signs_for": gshk_signatory.get("name"),
                 "capacity": gshk_signatory.get("selected_capacity")
                             or gshk_signatory.get("default_capacity"),
                 "eservice_user_id": staff_account},
    }
