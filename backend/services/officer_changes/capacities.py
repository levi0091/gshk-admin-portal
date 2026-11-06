"""The offices an officer-change form deals in, in one place.

Until 2026-11-04 the answer to "which offices?" was the pair `("director",
"company_secretary")`, spelt out in a dozen modules. Jacqueline's PBI-70 ruling
("Alternate directors are not out of scope. We can still provide the service if
client requests.") adds a third, and a third spelt out in a dozen places is how
one of them gets missed. The three questions the modules actually ask are
answered here:

  * which offices can an entry name?                     `ALL`
  * which of them ACT AS A DIRECTOR on a form?           `DIRECTORS`
  * what does CR call each (`cpty`)?                     `CPTY`

`DIRECTORS` is about what CR's forms do, not about who counts towards a
company's minimum board. An alternate director consents to act, has a
residential address CR holds, and is reported by `cpty = AD` -- all things a
director does -- but is NOT a director for the rules ("a private company must
keep a natural-person director", "a public company needs two"). Callers that
mean the statutory minimum compare `== "director"` on purpose; callers that
mean "signs a consent / has a residential address" use `DIRECTORS`.

A leaf module: no imports, so any of the services can use it.
"""
from __future__ import annotations

DIRECTOR = "director"
ALTERNATE = "alternate_director"
SECRETARY = "company_secretary"

#: Every office an entry may name.
ALL = (DIRECTOR, SECRETARY, ALTERNATE)

#: The offices that act as a director on CR's forms (consent, residential address).
DIRECTORS = (DIRECTOR, ALTERNATE)

#: CR's `cpty`.
CPTY = {DIRECTOR: "D", SECRETARY: "S", ALTERNATE: "AD"}

LABEL = {DIRECTOR: "Director", SECRETARY: "Company Secretary", ALTERNATE: "Alternate Director"}


def acts_as_director(capacity: str | None) -> bool:
    return capacity in DIRECTORS
