"""The "NAR1 return data · sourced from company profile" card (wireframe_v11 s20).

WHAT THIS IS FOR. The Data Verification stage in v11 opens with a read-only
summary of the return CR is about to be shown: name, BR number, return date,
registered office, directors, secretary, members, share classes. The shipped
screen had no such card, so the first time an operator learned anything about
the return was a red box after pressing "Validate with CR" — and if the company
could not be mapped at all, the first thing they learned was that it could not
be mapped, with no sight of the data that failed.

WHY IT REPORTS `problems` TOO. `nar1_mapper.map_entity` already collects every
reason a company cannot become a NAR1, and `POST /tpsi/filings/prepare` already
returns them. But prepare is a WRITE (`tpsi:write`) that opens a filing row, so
it cannot be used to answer "would this work?". This runs the identical mapper
over the identical graph and throws the result away, which makes the blockers a
property of the screen rather than of having pressed the button.

WHY IT IS NOT BUILT FROM THE MAPPER'S OUTPUT. `map_entity` returns CR's schema
— `roAddr`, `dstCtyStatePostal`, `noOfShareIssuedOnThisCls`. Those are the wire
format, and rendering them would show the operator a transliteration of their
own data rather than their data. Worse, `map_entity` RAISES when the company
cannot be filed, so a card built from its output would go blank in exactly the
case it most needs to be readable. So the card is built from the graph and the
mapper is consulted only for its verdict.

Read-only. Opens no filing, calls no CR endpoint, writes nothing.
"""
from datetime import datetime, timedelta, timezone

from services.tpsi.forms import nar1_mapper
from services.tpsi.forms.cr_vocabularies import (
    CAPACITY_BODY_CORPORATE, CAPACITY_INDIVIDUAL,
)


def _hk_year() -> int:
    """Hong Kong's year, not UTC's — the same rule prepare_filing uses.

    For the first eight hours of every HK working day UTC is still on
    yesterday's date, and on 1 January that is the wrong year on a statutory
    form.
    """
    return (datetime.now(timezone.utc) + timedelta(hours=8)).year


def _address_line(addr: dict | None) -> str | None:
    if not addr:
        return None
    parts = [
        addr.get("line1"), addr.get("line2"), addr.get("line3"),
        addr.get("district"), addr.get("city"), addr.get("country"),
    ]
    return ", ".join(p.strip() for p in parts if p and str(p).strip()) or None


def _party_name(row: dict, persons: dict, entities: dict) -> str | None:
    """A row in `entity_officers` is either a person or a body corporate."""
    if row.get("person_id"):
        person = persons.get(row["person_id"]) or {}
        return person.get("full_name") or None
    if row.get("corporate_entity_id"):
        corp = entities.get(row["corporate_entity_id"]) or {}
        return corp.get("company_name") or row.get("corporate_name") or None
    return row.get("corporate_name") or None


def summarise(graph: dict, *, year: int | None = None,
              signatory_capacity: str | None = None) -> dict:
    """The card's rows, plus whether this company can be filed at all.

    `signatory_capacity` is the operator's stored choice on the case. It is fed
    to the mapper so the verdict below reflects the return as it would actually
    be prepared — without it, every GSHK-managed company reports the "no
    capacity chosen" problem forever, including the ones where the operator has
    already chosen one.
    """
    year = year or _hk_year()
    entity = graph.get("entity") or {}
    persons = graph.get("persons") or {}
    # load_entity_graph keys corporate parties into `addresses`/`persons` only;
    # the corporate rows it resolved carry `corporate_name` on the officer row
    # itself, which _party_name falls back to.
    entities = graph.get("entities") or {}

    officers = graph.get("officers") or []
    directors = [
        name for row in officers
        if row.get("role") in ("director", "reserve_director")
        and (name := _party_name(row, persons, entities))
    ]
    secretaries = [
        name for row in officers
        if row.get("role") == "company_secretary"
        and (name := _party_name(row, persons, entities))
    ]

    share_classes = graph.get("share_classes") or []
    holdings = graph.get("shareholdings") or []

    # The signer CR will be asked to accept. Reported here because "who signs
    # this?" is the single most common reason a NAR1 cannot be filed, and the
    # operator should see the answer beside the data rather than infer it from
    # a rejection.
    try:
        signatory = nar1_mapper._derive_signatory(graph)
    except Exception:  # noqa: BLE001
        signatory = None

    problems: list[str] = []
    try:
        nar1_mapper.map_entity(graph, year=year,
                               signatory_capacity=signatory_capacity)
    except nar1_mapper.MappingError as exc:
        problems = list(exc.problems)
    except Exception as exc:  # noqa: BLE001
        # A mapper crash is not a company-data problem and must not be dressed
        # up as one, but it must not blank the card either.
        problems = [f"could not check this company: {exc}"]

    return {
        "year": year,
        "company_name": entity.get("company_name"),
        "company_name_zh": entity.get("company_name_zh"),
        "br_number": entity.get("br_number"),
        "cr_number": entity.get("cr_number"),
        "company_type": entity.get("company_type"),
        "incorporation_date": entity.get("incorporation_date"),
        "registered_office": _address_line(graph.get("registered_address")),
        "directors": directors,
        "secretaries": secretaries,
        "signatory": (
            {"name": signatory.get("name"),
             # The operator's stored choice wins over the derived one, because
             # it is the value that will actually be filed.
             "capacity": signatory_capacity or signatory.get("capacity"),
             "person_id": signatory.get("person_id"),
             "is_corporate": signatory.get("is_corporate") is True}
            if signatory else None
        ),
        # Which of CR's two vocabularies applies to THIS signatory. The screen
        # renders a picker from this rather than holding its own copy of a CR
        # list that would drift the first time CR revised it.
        "signatory_capacity": signatory_capacity,
        "signatory_capacity_options": sorted(
            CAPACITY_BODY_CORPORATE
            if (signatory or {}).get("is_corporate") is True
            else CAPACITY_INDIVIDUAL
        ) if signatory else [],
        "member_count": len({h.get("holder_person_id") or h.get("holder_entity_id")
                             or h.get("id") for h in holdings}),
        "share_classes": [
            {"name": sc.get("class_name"),
             "total_issued": sc.get("total_issued"),
             "currency": sc.get("currency") or "HKD"}
            for sc in share_classes
        ],
        "problems": problems,
    }
