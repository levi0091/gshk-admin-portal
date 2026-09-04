"""What an audit row is ABOUT, and which surface it came from.

The trail already recorded *what happened* ("Change Master File Details") and
*who did it*. What it could not reliably say is **which record** — a great many
rows rendered with a blank Company/Case cell, or with a Viewpoint key nobody can
read, and nothing at all distinguished a company edit from a person edit from a
NAR1 workflow step. This module supplies the two answers, denormalized onto
every row so they survive a deleted record and can be filtered without a join:

    module        which surface the change belongs to — the SAME five names the
                  sidebar uses, because that is the vocabulary the operator
                  already has.
    subject_*     the record the change is about: its kind, its id (so the cell
                  is a link), its name, and the identifier a human quotes.

THE SUBJECT IS RENDERED AS "name (ref)" — one shape, three readings:

    case      NAR1-2026-0042 (Kanenas Holding Limited)   <- ref is the CASE NO
    company   Kanenas Holding Limited (69123456)          <- ref is the BRN
    person    Ilze TSERKEZIS (A123456(7))                 <- ref is the ID NUMBER

Note the case reading inverts: the case number leads and the company qualifies
it, because a workflow row is about one filing of one year, not about the
company in general. `audit_log.company_name` carries the NAME half in all three
cases — it has always held the person's name on person rows, so this only writes
down what the column already meant.

BACKWARD COMPATIBLE WITH VIEWPOINT BY CONSTRUCTION. Nothing here is invented for
an imported row: a Viewpoint event's KeyCode already resolves to an entity or a
person (`etl/run_checkpoint_c._subjects`), which gives kind, id, name and ref,
and the module follows from the kind. What Viewpoint has no equivalent of — the
NAR1 case workflow, the document store, CR e-Filing — simply never appears on an
imported row, which is the truth rather than a gap.

`audit_log.case_id` KEEPS ITS MEANING and is not what `subject_id` holds. It is
the ENTITY id (see `routers/cases.py::_audit_target`), which is how a company's
whole trail is queried; `subject_id` is the id of whatever the row is about, and
for a NAR1 workflow row that is the case, not the company.
"""
from __future__ import annotations

from typing import Any, Optional

# --------------------------------------------------------------------------- #
#  Modules — the portal's own navigation, not a new taxonomy.
#
#  These strings reach PostgREST as filter values and are mirrored by
#  frontend/src/lib/auditVocabulary.js. `tests/test_audit_subject.py` and
#  AuditLogPage.test.jsx both pin the list, so the two cannot drift into a
#  filter option that matches nothing.
# --------------------------------------------------------------------------- #
POST_INCORPORATION = "post_incorporation"
BODY_CORPORATE = "body_corporate"
NATURAL_PERSON = "natural_person"
DOCUMENTS = "documents"
CR_FILING = "cr_filing"

MODULES: tuple[str, ...] = (
    POST_INCORPORATION, BODY_CORPORATE, NATURAL_PERSON, DOCUMENTS, CR_FILING,
)

MODULE_LABELS: dict[str, str] = {
    POST_INCORPORATION: "Post-incorporation",
    BODY_CORPORATE: "Body Corporate",
    NATURAL_PERSON: "Natural Person",
    DOCUMENTS: "Documents",
    CR_FILING: "CR Filing",
}

# --------------------------------------------------------------------------- #
#  Subject kinds
# --------------------------------------------------------------------------- #
CASE = "case"
COMPANY = "company"
PERSON = "person"

SUBJECT_KINDS: tuple[str, ...] = (CASE, COMPANY, PERSON)

#: The keys every helper below returns, so a caller can spread one dict.
KEYS = ("module", "subject_kind", "subject_id", "subject_ref")

# --------------------------------------------------------------------------- #
#  Fallback derivation
#
#  Roughly fifty call sites write audit rows and none of them should have to
#  restate what `entity_type` already says. `audit_service` runs this over every
#  row it builds, and an explicit value from the caller always wins — so a route
#  that knows better (a person's address, a document owned by a person) says so
#  and everything else is classified for free.
#
#  A `None` kind here means "this entity_type does not determine it" — the
#  polymorphic ones. They are resolved by the caller, and `_infer_kind` below is
#  the last-resort guess for anything that slips through.
# --------------------------------------------------------------------------- #
_BY_ENTITY_TYPE: dict[str, tuple[Optional[str], Optional[str]]] = {
    "nar1_case": (POST_INCORPORATION, CASE),
    "entity": (BODY_CORPORATE, COMPANY),
    "share_class": (BODY_CORPORATE, COMPANY),
    "entity_record_location": (BODY_CORPORATE, COMPANY),
    "person": (NATURAL_PERSON, PERSON),
    # Polymorphic: an address hangs off a company OR a person, and a document
    # off a company, a person or a case.
    "address": (None, None),
    "document": (DOCUMENTS, None),
    # CR e-Filing is its own surface — the CR Credentials screen and the
    # transport behind the workflow's last step. Kept apart from
    # post_incorporation on purpose: "did anything go to CR today" and "what did
    # we do to this case today" are different questions, and folding the first
    # into the second makes it unaskable.
    "tpsi": (CR_FILING, None),
    "tpsi_filing": (CR_FILING, None),
    # Not about a company or a person at all — a user's own CR credential.
    "tpsi_credential": (CR_FILING, None),
}


def _infer_kind(module: Optional[str], case_id: Optional[str]) -> Optional[str]:
    """Last resort for the polymorphic types, from what the row already carries.

    `case_id` holds an ENTITY id, so its presence means a company is involved;
    a person-owned document is written with no case_id at all. This is a guess,
    and it is only reached when the caller supplied no kind.
    """
    if module == DOCUMENTS:
        return COMPANY if case_id else PERSON
    return COMPANY if case_id else None


def derive(
    *,
    entity_type: Optional[str],
    case_id: Optional[str] = None,
    entity_id: Optional[str] = None,
    module: Optional[str] = None,
    subject_kind: Optional[str] = None,
    subject_id: Optional[str] = None,
    subject_ref: Optional[str] = None,
) -> dict[str, Any]:
    """Fill in whatever the caller did not say. Never raises, never overrides.

    Returns only the keys that end up with a value, so `_build_row` can merge it
    without writing columns full of nulls it did not mean to write.
    """
    fallback_module, fallback_kind = _BY_ENTITY_TYPE.get(entity_type or "", (None, None))
    module = module or fallback_module
    subject_kind = subject_kind or fallback_kind or _infer_kind(module, case_id)

    if subject_id is None:
        if subject_kind == PERSON:
            # persons.py writes the person id into entity_id (and, for an
            # address edit, into case_id as well).
            subject_id = entity_id or case_id
        elif subject_kind == CASE:
            # cases.py: entity_id is the nar1_cases.id, case_id the entity's.
            subject_id = entity_id
        elif subject_kind == COMPANY:
            subject_id = case_id

    out: dict[str, Any] = {}
    if module:
        out["module"] = module
    if subject_kind:
        out["subject_kind"] = subject_kind
    if subject_id and _looks_like_uuid(subject_id):
        # A TEXT entity_id can hold "shared" (the shared CR credential) or a
        # Viewpoint key. subject_id is a uuid column; a non-uuid there fails the
        # insert, and an audit write must never be the thing that breaks a save.
        out["subject_id"] = str(subject_id)
    if subject_ref:
        out["subject_ref"] = str(subject_ref)
    return out


def _looks_like_uuid(value: Any) -> bool:
    text = str(value)
    return len(text) == 36 and text.count("-") == 4


# --------------------------------------------------------------------------- #
#  Call-site helpers — one per kind. Each returns the subject keys and nothing
#  else, so a route spreads it beside the `company_name` it already passes.
# --------------------------------------------------------------------------- #
def for_company(company: Optional[dict], *, module: str = BODY_CORPORATE) -> dict[str, Any]:
    """A row about a body corporate: `company name (BRN)`.

    `company` is an `entities` row the caller already loaded — no query is made
    here, because audit context must never add a round trip to a write path.
    """
    company = company or {}
    return {
        "module": module,
        "subject_kind": COMPANY,
        "subject_id": company.get("id"),
        "subject_ref": company.get("br_number"),
    }


def for_person(
    person: Optional[dict],
    *,
    id_number: Optional[str] = None,
    module: str = NATURAL_PERSON,
) -> dict[str, Any]:
    """A row about a natural person: `person name (identity number)`.

    `id_number` is the person's primary identity document, which lives in
    `person_identity_documents` rather than on the person — pass it if the route
    has it (see `primary_id_number`), and the cell falls back to the name alone
    if not.
    """
    person = person or {}
    return {
        "module": module,
        "subject_kind": PERSON,
        "subject_id": person.get("id"),
        "subject_ref": id_number or person.get("primary_id_number"),
    }


def for_case(case: Optional[dict], *, module: str = POST_INCORPORATION) -> dict[str, Any]:
    """A NAR1 workflow row: `case no (company name)`.

    The case number leads, so `subject_ref` holds it and `company_name` (set by
    the caller) holds the company. That inversion is deliberate — see the module
    docstring.
    """
    case = case or {}
    return {
        "module": module,
        "subject_kind": CASE,
        "subject_id": case.get("id"),
        "subject_ref": case.get("case_no"),
    }


def primary_id_number(sb, person_id: Optional[str]) -> Optional[str]:
    """The identity number a person is quoted by — the primary one, else oldest.

    One query, on the write paths that edit a person. Ordered exactly like
    `person_registry`'s lateral join (migration 009) so the audit trail quotes
    the same document the registry screen shows. Swallows every failure: a
    missing reference makes a poorer trail, never a failed save.
    """
    if not person_id:
        return None
    try:
        rows = (
            sb.table("person_identity_documents")
            .select("id_number, is_primary, created_at")
            .eq("person_id", person_id)
            .order("is_primary", desc=True)
            .order("created_at", desc=False)
            .limit(1)
            .execute()
        ).data or []
    except Exception:  # noqa: BLE001
        return None
    return (rows[0] or {}).get("id_number") if rows else None
