"""Who puts the OVERALL signature on an e-Signed ND2A: GSHK, or a director.

Levi, 2026-11-13: "when it is a change of corp secretary, we need to use the
director e-reg to sign and not GetStarted HK e-reg sign, because at that point
GSHK is still not related to the company."

  gshk      The signed-in staff member's own e-Service account (CR Credentials),
            for the company secretary after the form's changes — the signer
            NAR1 and every ND2 used until now (`nd2a_mapper.signatory`).
  director  A CURRENT director — one this form ceases included — signing as
            "Director" with the e-Registry account stored on their own
            natural-person profile (`person_eservice_credentials`, the account
            their consent signatures already use). The form's signatory block
            then names that account (`selectPersonId` / `selectPersonName`), and
            the overall PinSign is computed with it.

THE DEFAULT. Director when the ND2A changes the company secretary AND some
director's account is complete; GSHK otherwise. A director with no complete
account can never be chosen — there is nothing to sign with.

GSHK CANNOT SIGN FOR A SECRETARY THE FORM APPOINTS (DEV, 2026-11-13). CR checks
the signer's association "as at the date of signature", and the incoming
secretary has none until CR registers the form: validating an ND2A that appoints
Get Started HK Limited came back "The user has no association with this
company". So when the secretary who would sign is one this form appoints, the
GSHK option is unavailable (`gshk_problem`) and a director must sign.

A RESIGNING DIRECTOR MAY SIGN. CR's own portal lists the director the form
ceases among the signatories (Brian Yiu, CR portal, 2026-11-13): they are still
a director on the day they sign. They are listed, and marked as leaving.

GSHK's TPSI account still presents, validates, pays and submits on either route.
Only the PIN signature is the director's: CR computes it from the signatory's
own user ID and e-Service password (TPSIT User Guideline 3.3: "User ID and
e-Service Password (not TPSI password) of the signatory"), so there is no way
to sign as a director with GSHK's credential.

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


def gshk_problem(case: dict, entries: list[dict]) -> str | None:
    """Why the GSHK option cannot sign this ND2A, or None when it can."""
    if not offered(case) or not secretaries_after.changes_secretary(entries):
        return None
    from services.officer_changes import cases  # cases imports this module
    (name, _corp, _pid), joins = cases._signatory_pick(case["entity_id"], entries)
    if not joins:
        return None
    return (f"{name or 'The new secretary'} becomes the company secretary only when CR "
            "registers this form, so CR refuses its signature until then (\"The user has "
            "no association with this company\"). A director signs instead.")


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
    """Every current natural-person director, with whether their stored
    e-Registry account can sign.

    A director the form ceases is INCLUDED and marked `ceasing`: CR's portal
    offers them as a signatory, since they are a director on the day they sign.
    Alternates are left out: CR's note 6 says "a director".
    """
    sb = get_supabase()
    rows = (sb.table("entity_officers").select("*").eq("entity_id", case["entity_id"])
            .eq("role", capacities.DIRECTOR).eq("is_current", True).execute().data) or []
    gone_officers, gone_people = _ceased_director_ids(entries)
    leaving = set(gone_people) | {r.get("person_id") for r in rows
                                  if r.get("id") in gone_officers}
    seen, people_ids = set(), []
    for r in rows:
        pid = r.get("person_id")
        if not pid or pid in seen:
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
            "ceasing": pid in leaving,
            "profile_path": f"/persons/{pid}",
            # A warning, not a refusal: CR decides (Jacqueline, note 1).
            "id_mismatch": eservice.identity_mismatch(account, docs.get(pid, []), name=name),
        })
    # Ready first; among those, a director who stays before one who leaves.
    out.sort(key=lambda c: (not c["ready"], c["ceasing"], c["name"].casefold()))
    return out


def default_party(entries: list[dict], options: list[dict],
                  gshk_blocked: bool = False) -> str:
    if gshk_blocked:
        return DIRECTOR
    if secretaries_after.changes_secretary(entries) and any(c["ready"] for c in options):
        return DIRECTOR
    return GSHK


def resolve(case: dict, entries: list[dict], options: list[dict] | None = None) -> dict:
    """`{party, stored, default, director, candidates, changes_secretary, gshk_problem}`.

    `director` is the candidate who signs when the party is director — the
    stored one, else the first whose account is complete — or None when nobody
    can. `candidates` is None on a quick path, where nothing was read."""
    changes = secretaries_after.changes_secretary(entries)
    stored = case.get("signing_party") if case.get("signing_party") in PARTIES else None
    base = {"stored": stored is not None, "changes_secretary": changes, "gshk_problem": None}
    if not offered(case):
        return {**base, "party": GSHK, "default": GSHK, "director": None, "candidates": None}
    if options is None and stored != DIRECTOR and not changes:
        # No secretary change: the secretary who signs is on the register today.
        return {**base, "party": GSHK, "default": GSHK, "director": None, "candidates": None}
    problem = gshk_problem(case, entries) if changes else None
    base["gshk_problem"] = problem
    if options is None and stored == GSHK and problem is None:
        return {**base, "party": GSHK, "default": GSHK, "director": None, "candidates": None}
    options = candidates(case, entries) if options is None else options
    default = default_party(entries, options, gshk_blocked=problem is not None)
    # GSHK cannot sign while it is not yet associated, so a stored GSHK yields.
    party = DIRECTOR if problem else (stored or default)
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
                "No director has a complete e-Registry account to sign with. Set one up "
                "on a director's profile"
                + (", or file the form by the Manual route." if choice["gshk_problem"]
                   else ", or choose GSHK e-Service."))
        return {"signing_party": DIRECTOR,
                "signing_director_person_id": choice["director"]["person_id"]}
    if choice["gshk_problem"]:
        raise SignerUnavailable(choice["gshk_problem"])
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
        "gshk": {"available": choice["gshk_problem"] is None,
                 "reason": choice["gshk_problem"],
                 "signs_for": gshk_signatory.get("name"),
                 "capacity": gshk_signatory.get("selected_capacity")
                             or gshk_signatory.get("default_capacity"),
                 "eservice_user_id": staff_account},
    }
