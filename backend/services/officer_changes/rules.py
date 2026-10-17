"""Company rules an officer change must not breach.

PRD §4 and §8 (E-2 … E-14), from CR's notes for completion and the Companies
Ordinance. Each check has a stable `code` the screen and the tests key on, and
a `level`:

  * `rule` — a breach CR would reject or the Ordinance forbids. Any rule that
    fails makes the case `blocking`: it cannot be sent to the client, because
    asking a client to approve a form that cannot be filed wastes their time
    and ours. The reason prints beside the disabled button (S-08b).
  * `notice` — worth saying, never in the way: no date of birth on record, no
    identity document, a deadline already passed (late filing is an offence
    but carries no fee, so the case stays fileable — PRD E-13).

Pure: the caller passes the officers as they stand now, the entries, the
company and the dates.
"""
from __future__ import annotations

from datetime import date

from services.officer_changes.deadlines import _as_date, hk_today
from services.tpsi.forms.cr_vocabularies import to_alpha2

_ROLES = ("director", "company_secretary")


def _key(row: dict):
    if row.get("person_id"):
        return ("person", row["person_id"])
    return ("corporate", row.get("corporate_entity_id"))


def _check(code: str, ok: bool, text: str, level: str = "rule") -> dict:
    return {"code": code, "ok": bool(ok), "text": text, "level": level}


def _is_hk(address: dict | None) -> bool:
    country = (address or {}).get("country")
    return bool(country) and (to_alpha2(country) or str(country).upper()) == "HK"


def _age_on(born: date, on: date) -> int:
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def board_after(officers_now: list[dict], entries: list[dict]) -> list[dict]:
    """The directors and secretaries once every cessation and appointment on
    the case has happened: `[{role, key, party_type}]`."""
    ceased_ids = {e.get("officer_id") for e in entries
                  if e.get("kind") == "cessation" and e.get("officer_id")}
    ceased_keys = {(e.get("capacity"), _key(e)) for e in entries
                   if e.get("kind") == "cessation"}
    board = [
        {"role": o["role"], "key": _key(o), "party_type": o.get("party_type"),
         "name": o.get("name") or "", "new": False}
        for o in officers_now
        if o.get("role") in _ROLES
        and o.get("officer_id") not in ceased_ids
        and (o["role"], _key(o)) not in ceased_keys
    ]
    for e in entries:
        if e.get("kind") == "appointment":
            board.append({"role": e.get("capacity"), "key": _key(e),
                          "party_type": e.get("party_type"),
                          "name": (e.get("party") or {}).get("name") or "", "new": True})
    return board


def _join(names: list[str]) -> str:
    """"A", "A and B", "A, B and C"."""
    names = [n for n in names if n]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def dates_missing(entries: list[dict]) -> list[str]:
    """Who still has no effective date: an officer's name, or for an ND2B line
    "name — item". Omitted ND2B lines are not filed and so need none.

    Since Jacqueline's A1 a draft may go out undated; this is the list the
    Signing stage asks for, and the one the filing routes refuse on."""
    out = []
    for e in entries:
        name = (e.get("party") or {}).get("name") or e.get("capacity") or "an officer"
        if e.get("kind") == "change":
            for item in e.get("items") or []:
                if not item.get("omitted") and not item.get("effective_date"):
                    out.append(f"{name} — {item.get('label') or item.get('key')}")
        elif not e.get("effective_date"):
            out.append(name)
    return out


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def evaluate(officers_now: list[dict], entries: list[dict], *, company: dict,
             today: date | None = None, deadline: date | None = None) -> dict:
    """Pure. `{"summary": str, "checks": [{"code", "ok", "text", "level"}],
    "blocking": bool}`."""
    today = today or hk_today()
    checks: list[dict] = []
    nd2b = any(e.get("kind") == "change" for e in entries)

    # -- something to file, with its dates -----------------------------------------
    if nd2b:
        lines = [(e, i) for e in entries for i in (e.get("items") or [])
                 if not i.get("omitted")]
        checks.append(_check("has_changes", bool(lines),
                             "Every change on this form has been omitted — there is "
                             "nothing left to file." if not lines else
                             "There are changes to file."))
        undated = [i.get("label") or i.get("key") for _, i in lines
                   if not i.get("effective_date")]
        dates = [_as_date(i.get("effective_date")) for _, i in lines]
    else:
        checks.append(_check("has_changes", bool(entries),
                             "Add at least one cessation or appointment." if not entries
                             else "There are changes to file."))
        undated = [e.get("capacity") for e in entries if not e.get("effective_date")]
        dates = [_as_date(e.get("effective_date")) for e in entries]
    # A NOTICE since Jacqueline's A1: the client may be sent the draft with the
    # date blank, and it is entered at Signing (`dates_missing` gates filing).
    checks.append(_check(
        "dates_present", not undated,
        "Every change has the date it took effect." if not undated else
        f"{_plural(len(undated), 'change has', 'changes have')} no effective date yet — "
        "the client is told it will be confirmed when we file; enter it at Signing.",
        level="notice"))
    future = sorted(d for d in dates if d and d > today)
    checks.append(_check(
        "no_future_dates", not future,
        "No change is dated after today." if not future else
        f"A change is dated {future[0]:%d %b %Y}, after today. CR records what has "
        "happened; file it once the date has passed."))

    # -- the board after the change (ND2A only changes who is on it) ---------------
    board = board_after(officers_now, entries)
    directors = [b for b in board if b["role"] == "director"]
    natural = [b for b in directors if b["party_type"] == "individual"]
    secretaries = [b for b in board if b["role"] == "company_secretary"]
    private = (company.get("company_type") or "P") == "P"
    if nd2b:
        # An ND2B changes nobody's appointment, so the board cannot breach a
        # rule it did not already breach — and a stale register must not hold
        # up a change of address.
        pass
    elif private:
        checks.append(_check(
            "natural_director", bool(natural),
            "At least one director is a natural person." if natural else
            "A private company must keep at least one director who is a natural "
            "person. Add the replacement to this form."))
        sole = directors[0]["key"] if len(directors) == 1 else None
        clash = sole is not None and any(s["key"] == sole for s in secretaries)
        checks.append(_check(
            "sole_director_not_secretary", not clash,
            "The sole director is not also the company secretary." if not clash else
            "A private company's sole director may not also be its company secretary."))
    else:
        checks.append(_check(
            "two_directors", len(directors) >= 2,
            "The company keeps at least two directors." if len(directors) >= 2 else
            "A public company or a company limited by guarantee must have at least "
            "two directors."))
    if not nd2b:
        checks.append(_check(
            "has_secretary", bool(secretaries),
            "The company keeps a company secretary." if secretaries else
            "The company would be left without a company secretary. Add the "
            "replacement to this form."))

    # -- each appointment ----------------------------------------------------------
    underage, no_dob, not_hk, no_section5, no_id = [], [], [], [], []
    for e in (e for e in entries if e.get("kind") == "appointment"):
        party = e.get("party") or {}
        name = party.get("name") or "the appointee"
        individual = e.get("party_type") == "individual"
        if individual and e.get("capacity") == "director":
            born = _as_date(party.get("date_of_birth"))
            on = _as_date(e.get("effective_date")) or today
            if born is None:
                no_dob.append(name)
            elif _age_on(born, on) < 18:
                underage.append(name)
        if e.get("capacity") == "company_secretary":
            if individual:
                address = (party.get("residential_address")
                           if e.get("correspondence_same_as_residential", True)
                           else e.get("correspondence_address"))
                if not _is_hk(address):
                    not_hk.append(name)
                if not e.get("section5_confirmed"):
                    no_section5.append(name)
            elif not _is_hk(party.get("address")):
                not_hk.append(name)
        if individual and not party.get("hkid") and not (party.get("passport") or {}).get("number"):
            no_id.append(name)

    if underage:
        checks.append(_check("director_age", False,
                             f"{', '.join(underage)} would be under 18 on the date of "
                             "appointment; a director must be at least 18."))
    elif no_dob:
        checks.append(_check("director_age", False,
                             f"No date of birth on record for {', '.join(no_dob)}; "
                             "confirm they are at least 18.", level="notice"))
    else:
        checks.append(_check("director_age", True, "Every new director is at least 18."))

    problems = []
    if not_hk:
        problems.append(f"{', '.join(not_hk)} must have a Hong Kong address to act "
                        "as company secretary")
    if no_section5:
        problems.append(f"confirm that {', '.join(no_section5)} ordinarily resides "
                        "in Hong Kong (Section 5)")
    checks.append(_check(
        "secretary_hong_kong", not problems,
        "Every new company secretary meets the Hong Kong requirements." if not problems
        else "; ".join(problems).capitalize() + "."))

    checks.append(_check(
        "identity_document", not no_id,
        "Every new officer has an identity document." if not no_id else
        f"No HKID or passport on record for {', '.join(no_id)}; the form will "
        "carry NIL.", level="notice"))

    overdue = deadline is not None and deadline < today
    checks.append(_check(
        "deadline", not overdue,
        "Within the 15-day filing window." if not overdue else
        f"The filing deadline was {deadline:%d %b %Y}. Late filing is an offence; "
        "file as soon as possible.", level="notice"))

    summary = (f"After these changes the company will have "
               f"{_plural(len(directors), 'director', 'directors')} "
               f"({_plural(len(natural), 'natural person', 'natural persons')}) and "
               f"{_plural(len(secretaries), 'secretary', 'secretaries')}.")
    # Jacqueline A6: the three lines the team reads; the checks sit behind them.
    directors_line = (f"Directors: {_join([d['name'] for d in directors])}." if directors
                      else "No director would remain.")
    if not secretaries:
        secretary_line = "No company secretary would remain."
    elif any(s_["new"] for s_ in secretaries):
        secretary_line = (f"Company secretary: {_join([s_['name'] for s_ in secretaries])} "
                          "(appointed on this form).")
    else:
        secretary_line = (f"A company secretary remains — "
                          f"{_join([s_['name'] for s_ in secretaries])}.")
    return {"summary": summary, "checks": checks,
            "lines": [summary, directors_line, secretary_line],
            "board": {"directors": [{"name": d["name"], "party_type": d["party_type"]}
                                    for d in directors],
                      "secretaries": [{"name": s_["name"], "new": s_["new"]}
                                      for s_ in secretaries]},
            "blocking": any(not c["ok"] and c["level"] == "rule" for c in checks)}
