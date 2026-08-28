"""NAR1 case rows — the GSHK-side half of the case (D-6).

This module owns the client facts and the off-portal facts. It never writes a CR
fact: tpsi_filings owns those, and nar1_case_status.derive() reads both to
produce the badge.
"""
import asyncio
from datetime import datetime, timezone

from db.supabase import get_supabase
from services import nar1_case_status
from services.tpsi import filings as tpsi_filings
from services.tpsi.filings import form_status

_TABLE = "nar1_cases"

#: R1 ships NAR1 only. NNC1 cases arrive with R3 and their own workflow.
SUPPORTED_FORM_CODES = ("Nar1",)


def _escape_filter_value(term: str) -> str:
    """One `ilike` value for a PostgREST `or_()` expression, safely.

    PostgREST splits an or_() on commas and dots, so those characters in a user
    term become grammar rather than data. Double-quoting the value makes
    PostgREST read it as a single literal; the escapes below stop the term from
    closing that quote early. `%` wildcards are added OUTSIDE the quotes'
    content deliberately -- they are ours, not the user's.
    """
    cleaned = term.replace("\\", "\\\\").replace('"', '\\"')
    return f'"%{cleaned}%"'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_case(case_id: str) -> dict:
    rows = get_supabase().table(_TABLE).select("*").eq("id", case_id).execute().data
    if not rows:
        raise LookupError(f"no NAR1 case {case_id}")
    return rows[0]


def create_case(*, entity_id: str, form_code: str, user_id: str) -> dict:
    """Open a case. The case number is allocated by the DB, not here -- two
    concurrent creates must not be handed the same NAR-2026-0041."""
    if form_code not in SUPPORTED_FORM_CODES:
        raise ValueError(
            f"{form_code} cases are not supported yet — R1 is NAR1 only"
        )
    sb = get_supabase()
    prefix = f"NAR-{datetime.now(timezone.utc).year}"
    case_no = sb.rpc("next_case_no", {"p_prefix": prefix}).execute().data
    return (
        sb.table(_TABLE)
        .insert({
            "entity_id": entity_id,
            "case_no": case_no,
            "nar1_type": "annual_return",
            "created_by": user_id,
            "assigned_to": user_id,
        })
        .execute()
        .data[0]
    )


def update_case(case_id: str, patch: dict) -> dict:
    patch = {**patch, "updated_at": _now()}
    return (
        get_supabase().table(_TABLE).update(patch).eq("id", case_id).execute().data[0]
    )


def claim_manual_submission(case_id: str, patch: dict) -> dict | None:
    """Record the off-portal submission, but ONLY if none is recorded yet.

    Returns the updated row, or None when another request got there first.

    The router's read-then-write was TOCTOU: two concurrent requests both saw
    manual_receipt NULL and both wrote. Last write wins on one row, so there was
    never a second statutory record — but the trail got two
    NAR1_MANUAL_SUBMISSION_RECORDED entries for one return (and audit_log is
    insert-only, so neither can be taken back), and the stored receipt might not
    be the one the first response reported. The condition belongs in the UPDATE,
    where Postgres settles it.
    """
    patch = {**patch, "updated_at": _now()}
    rows = (
        get_supabase().table(_TABLE)
        .update(patch)
        .eq("id", case_id)
        .is_("manual_receipt", None)
        .execute()
        .data
    )
    return rows[0] if rows else None


def current_filing(case_id: str) -> dict | None:
    """The filing that represents this case right now.

    Newest first and superseded rows excluded: a Restart marks the old attempt
    'superseded' and opens a new one, and the badge must follow the live attempt,
    not whichever row happens to sort first.
    """
    rows = (
        get_supabase().table("tpsi_filings")
        .select("*")
        .eq("nar1_case_id", case_id)
        .neq("stage", tpsi_filings.STAGE_SUPERSEDED)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# The manual (wet-signature, off-portal) path — BE-6
# ---------------------------------------------------------------------------
#
# The receipt fields a manual entry must carry. A SUBSET of tpsi_filings'
# RECEIPT_FIELDS by construction (test_the_manual_receipt_shape_matches_the_
# e_signed_one enforces it), because Confirmation renders one template for both
# paths -- and a manual receipt missing a field an e-Signed one has would render
# a blank box that looks like missing data rather than a different route.
#
# chiCoyName, docCodesWithBarcode and refNo are NOT required: a company with no
# Chinese name genuinely has none, and neither the barcode string nor refNo is
# printed on the paper receipt.
RECEIPT_REQUIRED = (
    "caseNo", "brNo", "accNo", "engCoyName", "pymtNo", "pymtRefNo",
    "transactionDate", "transactionTime", "pymtMtd", "totalAmount",
)
RECEIPT_LINE_REQUIRED = ("rcptNo", "revCode", "docShtFrm", "amtChrg")

#: The KEY NAMES a receipt may carry -- CR's own vocabulary, nothing else. A key
#: outside it is a problem, not a silently-dropped one: manual_receipt is a
#: statutory record rendered by the same template as CR's, and audit_service
#: scrubs `metadata` but not `after_state`, so arbitrary caller JSON must never
#: reach either.
#:
#: This constrains names ONLY. RECEIPT_SCALARS below constrains the values,
#: because a legitimate key is otherwise a wide-open door: a `caseNo` whose value
#: is {"password": "hunter2"} passes every name check there is.
RECEIPT_ALLOWED = set(tpsi_filings.RECEIPT_FIELDS) | {"paymentRcptList"}
RECEIPT_LINE_ALLOWED = set(tpsi_filings.RECEIPT_LINE_FIELDS)

#: A receipt field holds one printed value. CR's own parser yields strings; a UI
#: posting JSON numbers, booleans or nulls is not smuggling anything, so those
#: pass too. Only STRUCTURES are refused -- they are the shape that carries a
#: payload past a name check. (bool is a subclass of int; named anyway so the
#: intent survives a future reader.)
RECEIPT_SCALARS = (str, int, float, bool, type(None))

#: Stages that mean CR already holds this return. Recording an off-portal
#: submission on top would put a second statutory filing in the register for one
#: return, and nothing downstream could say which one CR actually has.
CR_FILED_STAGES = (
    tpsi_filings.STAGE_SUBMITTED,
    tpsi_filings.STAGE_REGISTERED,
    tpsi_filings.STAGE_EDRIVE,
)


def blocking_filing(case_id: str) -> dict | None:
    """The filing that decides whether the manual path is still open.

    Deliberately NOT current_filing(). That returns the NEWEST non-superseded
    attempt, and nothing stops POST /tpsi/filings/prepare opening a second draft
    against a case that has already been submitted — no restart marks the old
    row superseded today, so the fresh draft would sort first and hide a filing
    CR is already holding. The manual gate asks "has this return been filed?",
    which is a question about ANY attempt, not the latest one.

    Falls back to the current attempt so the 'signed' guard still sees a live
    e-Sign chain.
    """
    filed = (
        get_supabase().table("tpsi_filings")
        .select("*")
        .eq("nar1_case_id", case_id)
        .in_("stage", list(CR_FILED_STAGES))
        .limit(1)
        .execute()
        .data
    )
    return filed[0] if filed else current_filing(case_id)


def validate_receipt(receipt: dict) -> list[str]:
    """Every problem at once — the user is copying off a paper receipt and
    should not discover the fields one round trip at a time."""
    problems = [
        f"{field}: required" for field in RECEIPT_REQUIRED
        if not str(receipt.get(field) or "").strip()
    ]
    problems += [
        f"{key}: not a receipt field"
        for key in sorted(set(receipt) - RECEIPT_ALLOWED)
    ]
    # The names above, the VALUES here. A name check alone is a wide-open door:
    # `caseNo` holding {"password": "hunter2"} satisfies every one of them, and
    # the receipt goes whole into manual_receipt and into after_state, which
    # audit_service does not scrub.
    problems += [
        f"{key}: must be a single receipt value, not a {type(value).__name__}"
        for key, value in sorted(receipt.items())
        if key in RECEIPT_ALLOWED and key != "paymentRcptList"
        and not isinstance(value, RECEIPT_SCALARS)
    ]

    lines = receipt.get("paymentRcptList") or []
    if not lines:
        problems.append("paymentRcptList: at least one payment line is required")
    # A shape check before the field checks. This endpoint's whole contract is
    # "every problem at once, as a 400", and a list of strings, an unwrapped
    # single line, or a bare number used to raise AttributeError/TypeError out of
    # it as a 500 -- `line or {}` guards None, not a non-mapping.
    if lines and not isinstance(lines, list):
        problems.append("paymentRcptList: must be a list of payment lines")
        lines = []
    for index, line in enumerate(lines):
        if line is not None and not isinstance(line, dict):
            problems.append(f"paymentRcptList[{index}]: must be a payment line object")
            continue
        line = line or {}
        problems += [
            f"paymentRcptList[{index}].{field}: required"
            for field in RECEIPT_LINE_REQUIRED
            if not str(line.get(field) or "").strip()
        ]
        problems += [
            f"paymentRcptList[{index}].{key}: not a receipt field"
            for key in sorted(set(line) - RECEIPT_LINE_ALLOWED)
        ]
        problems += [
            f"paymentRcptList[{index}].{key}: must be a single receipt value, "
            f"not a {type(value).__name__}"
            for key, value in sorted(line.items())
            if key in RECEIPT_LINE_ALLOWED
            and not isinstance(value, RECEIPT_SCALARS)
        ]
    return problems


def manual_conflict(filing: dict | None, *, step: str) -> str | None:
    """Why the manual path must not run against this filing, or None.

    `step` is "sign" (uploading the wet-signed form) or "submit" (declaring the
    return filed off-portal). The two are gated differently on purpose.
    """
    stage = (filing or {}).get("stage")

    if stage in CR_FILED_STAGES:
        return (
            f"this case is already filed with CR (form status '{stage}') — "
            "recording an off-portal submission as well would put two filings "
            "in the register for one return"
        )

    # 'signed' is the loaded gun. filings._check_gate PASSES on a signed row, so
    # a case completed on paper while a signed filing sits live is ONE
    # chargeable, irreversible call away from filing the same return twice. The
    # upload is harmless preparation and stays allowed; the declaration is not.
    if step == "submit" and stage == tpsi_filings.STAGE_SIGNED:
        return (
            "a CR-signed filing is waiting to be submitted — completing this "
            "case on paper would leave that filing one chargeable call away "
            "from filing the same return again. Restart the filing first."
        )
    return None


# ---------------------------------------------------------------------------
# The case dashboard — BE-7
# ---------------------------------------------------------------------------

#: The relation, not the table: `nar1_case_registry` (migration 024) is
#: nar1_cases joined to company_registry and to the filing the badge is about,
#: with days_to_anniversary and the workflow badge as real columns. It has to be
#: a relation because the dashboard paginates: sorting or filtering the 50 rows
#: the server happened to send answers the wrong question, and PostgREST cannot
#: order or filter on an expression.
_REGISTRY = "nar1_case_registry"

#: Signed: negative means the anniversary has passed and the return is still
#: inside the 42-day statutory window. Same vocabulary as the company listing
#: (routers/companies.py), which already ships this filter over the same column.
_ANNIV_OPS = {"lte", "gte", "eq"}

#: Columns a table header may sort by. Whitelisted -- `sort` reaches PostgREST's
#: order clause, so it must never be caller-controlled free text.
_SORTABLE = {
    "case_no", "company_name", "br_number", "case_status", "filing_stage",
    "workflow_status", "days_to_anniversary", "created_at", "updated_at",
    # The display name, not the uuid: sorting by `created_by` would order the
    # dashboard by a value nobody can read off the screen.
    "created_by_name",
}

#: The deadline is the reason this screen exists, so it is the default order:
#: soonest first, and negative (already past, still filable) sorts ahead of that.
_DEFAULT_SORT = "days_to_anniversary"
_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 200

_LIST_COLS = (
    "id, case_no, entity_id, company_name, company_name_zh, br_number, "
    "cr_number, case_type, nar1_type, case_status, signing_method, assigned_to, "
    "created_by, created_by_name, "
    "filing_id, filing_stage, verification_sent_at, client_response_at, "
    "client_approved, manual_receipt_present, manual_submitted_at, created_at, "
    "updated_at, days_to_anniversary, workflow_status, workflow_off_portal, "
    "workflow_overdue"
)


async def list_dashboard(
    *,
    search: str | None = None,
    workflow_status: str | None = None,
    anniv_op: str | None = None,
    anniv_days: int | None = None,
    sort: str | None = None,
    direction: str = "asc",
    page: int = 1,
    page_size: int = _DEFAULT_PAGE_SIZE,
) -> dict:
    """One row per case, filtered, counted and sorted IN THE DATABASE.

    The routers validate these arguments and answer 422; the whitelists are
    re-checked here anyway. `anniv_op` becomes a method name and `sort` becomes
    a PostgREST order clause, so a caller that skipped the router must not be
    able to reach either -- the same reasoning that put the manual-submission
    interlock in the service rather than the route (Task 10).
    """
    if anniv_op is not None and anniv_op not in _ANNIV_OPS:
        raise ValueError(f"Unknown comparison '{anniv_op}'")
    if (anniv_op is None) != (anniv_days is None):
        raise ValueError("anniv_op and anniv_days must be supplied together")
    if workflow_status is not None and workflow_status not in nar1_case_status.WORKFLOW_STATUSES:
        raise ValueError(f"Unknown workflow status '{workflow_status}'")
    if sort is not None and sort not in _SORTABLE:
        raise ValueError(f"Cannot sort by '{sort}'")

    sb = get_supabase()

    def base(cols: str, count: str | None = None):
        """Every filter EXCEPT the status tab — applied to the count queries too.

        Filtering only the page query would leave the pager quoting a total for
        a set the user is not looking at. The status tab is deliberately outside
        this: the per-status counts are what the tabs render, and applying the
        selected tab to them would collapse every other tab to zero.
        """
        q = (sb.table(_REGISTRY).select(cols, count=count) if count
             else sb.table(_REGISTRY).select(cols))
        if search:
            # PostgREST's or_() takes a COMMA-SEPARATED, DOT-DELIMITED filter
            # grammar, so a search term containing either character is not data
            # -- it is more grammar. `a,b.eq.c` adds a filter clause nobody
            # asked for, and an unbalanced `)` 400s the whole listing. Neither
            # is a data breach (the view is service-role only) but a search box
            # must not be able to rewrite the query it appears in.
            term = _escape_filter_value(search)
            q = q.or_(
                f"company_name.ilike.{term},"
                f"case_no.ilike.{term},"
                f"br_number.ilike.{term}"
            )
        if anniv_op:
            col = "days_to_anniversary"
            q = getattr(q, anniv_op)(col, anniv_days)
            # A company with no incorporation_date has a NULL day count and
            # cannot answer a numeric question. PostgREST would drop it anyway;
            # being explicit means the intent survives the next edit.
            q = q.not_.is_(col, "null")
        return q

    def count_of(status: str | None = None) -> int:
        # An exact COUNT, never len(rows): PostgREST caps returned rows at 1000,
        # so counting fetched rows silently under-reports once the registry grows.
        q = base("id", count="exact")
        if status:
            q = q.eq("workflow_status", status)
        return q.limit(1).execute().count or 0

    # Eight independent counts. Sequentially that is 8 x ~200ms of pure
    # round-trip latency on every dashboard load (the measurement that drove the
    # same change in routers/companies.py).
    values = await asyncio.gather(
        asyncio.to_thread(count_of),
        *[asyncio.to_thread(lambda s=s: count_of(s))
          for s in nar1_case_status.WORKFLOW_STATUSES],
    )
    counts = {"all": values[0]}
    counts.update(zip(nar1_case_status.WORKFLOW_STATUSES, values[1:]))

    # Derived from the counts rather than a ninth query — it is the same number.
    total = counts[workflow_status] if workflow_status else counts["all"]

    q = base(_LIST_COLS)
    if workflow_status:
        q = q.eq("workflow_status", workflow_status)
    start = (page - 1) * page_size
    rows = (
        # nullsfirst=False explicitly: Postgres puts NULLs FIRST on a DESC sort,
        # which would open "furthest from anniversary" with every company that
        # has no incorporation date and therefore no answer.
        q.order(sort or _DEFAULT_SORT, desc=(direction == "desc"), nullsfirst=False)
        .range(start, start + page_size - 1)
        .execute().data
    ) or []

    for row in rows:
        # The badge in derive()'s shape, so a case on the dashboard and the same
        # case on its detail screen agree on key names as well as values. Read
        # back, never re-derived — re-deriving would paper over exactly the
        # divergence tests/test_migration_024.py exists to expose.
        row["workflow_status"] = nar1_case_status.badge_from_row(row)

    return {"rows": rows, "total": total, "page": page,
            "page_size": page_size, "counts": counts}


#: Facts the case header shows that live on the COMPANY, not on the case.
#: `nar1_cases` holds only `entity_id`, so a detail read straight off the table
#: has no company name, no BR number and no anniversary — which is exactly what
#: the v11 header is made of. The dashboard never had this problem because it
#: reads `nar1_case_registry` (024), which already joins them; the detail read
#: did not, so the same case rendered fully on the list and half-empty one click
#: later. Read the SAME view rather than re-joining `entities` here: a second
#: join is a second definition of days_to_anniversary, and 019 pins that to
#: Asia/Hong_Kong for a reason.
_HEADER_COLS = (
    "company_name", "company_name_zh", "br_number", "cr_number",
    "days_to_anniversary", "case_type",
)


def _company_header(case_id: str) -> dict:
    """The company-side header fields, from the registry view.

    Deliberately NOT fatal. This decorates a case that has already been read;
    if the view is unreachable the case detail should still render with the
    facts the case itself owns, not 500.
    """
    try:
        rows = (
            get_supabase()
            .table(_REGISTRY)
            .select(", ".join(_HEADER_COLS))
            .eq("id", case_id)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception:  # noqa: BLE001
        return {}
    return rows[0] if rows else {}


def composite(case_id: str) -> dict:
    """The case plus BOTH statuses — the shape the v11 case header needs."""
    case = get_case(case_id)
    filing = current_filing(case_id)
    return {
        **case,
        # Before the explicit keys below, never after: the view carries a
        # `workflow_status` STRING of its own, and letting it land on top of
        # derive()'s composite object is precisely the React-#31 blank page
        # this header already shipped once.
        **_company_header(case_id),
        # Named explicitly, not left to **case: the signed-form pointer is only
        # resolvable as (document_id, version) — upload_document versions the
        # SAME documents row every year — and the Confirmation screen reads the
        # key unconditionally. A missing key and a null version are different
        # failures to debug.
        "manual_signed_document_version": case.get("manual_signed_document_version"),
        "filing_id": (filing or {}).get("id"),
        "workflow_status": nar1_case_status.derive(case, filing),
        "form_status": form_status(filing) if filing else None,
        "receipt": (filing or {}).get("receipt") or case.get("manual_receipt"),
    }


# ---------------------------------------------------------------------------
# BE-3 — who the verification email goes to, and what it says
# ---------------------------------------------------------------------------

#: `contacts` has NO `email` column. It is the Viewpoint shape:
#: (contact_type, contact_value), and the type vocabulary is VP's own codes --
#: measured on DEV: 'phone', 'TM' (telephone mobile), 'TB' (telephone business),
#: 'EB' (email business), and 14 rows with a NULL type. So the type cannot be
#: trusted as the test, and the VALUE is what decides: an address contains '@'.
#: The type only breaks ties.
_EMAIL_TYPE_HINTS = ("email", "e-mail", "mail")


def _looks_like_an_address(value: str) -> bool:
    """Deliberately weak. This picks a candidate out of a messy ETL column; the
    router validates the address it is actually about to mail."""
    value = (value or "").strip()
    return "@" in value and " " not in value and value.count("@") == 1


def _email_rank(row: dict) -> tuple:
    """Preferred first, then a type that admits to being email, then oldest --
    so the answer is stable rather than whatever PostgREST happened to return."""
    ctype = (row.get("contact_type") or "").strip().lower()
    typed_email = ctype.startswith("e") or any(h in ctype for h in _EMAIL_TYPE_HINTS)
    return (
        0 if row.get("is_preferred") else 1,
        0 if typed_email else 1,
        row.get("created_at") or "",
    )


def recipient_email(entity_id: str) -> str | None:
    """The address on record for this company, or None.

    None is a legitimate answer and the caller must treat it as one: plenty of
    ETL'd companies carry no email at all. Guessing would mail a statutory
    return -- carrying directors' residential addresses and identity numbers --
    to whoever happened to be first in the table.
    """
    rows = (
        get_supabase()
        .table("contacts")
        .select("contact_type,contact_value,is_preferred,created_at")
        .eq("entity_id", entity_id)
        .execute()
        .data
        or []
    )
    candidates = [r for r in rows if _looks_like_an_address(r.get("contact_value"))]
    if not candidates:
        return None
    return sorted(candidates, key=_email_rank)[0]["contact_value"].strip()


#: Who is asked to approve the return, by default. Directors only -- they are
#: the officers whose particulars the NAR1 declares and who carry the
#: consequence of filing it. The secretary prepares the return; a reserve
#: director has no appointment to confirm until the sole director dies. Either
#: can still be added by hand on the send screen, which is what "add a
#: recipient" is for.
_VERIFICATION_ROLES = ("director",)


def _person_emails(person_ids: list[str]) -> dict[str, str]:
    """One address per person, best-first, from BOTH places one can live.

    `persons.email` is the populated column (measured on DEV: 4,398 of 6,853
    persons carry one, against 9 person-scoped `contacts` rows in the entire
    database). But `contacts` is where the portal writes a corrected address, so
    a contact row WINS over the ETL'd column -- otherwise fixing a bounced
    address in the UI would change nothing about where the mail goes.
    """
    if not person_ids:
        return {}
    sb = get_supabase()

    found: dict[str, str] = {}
    rows = (
        sb.table("persons")
        .select("id,email")
        .in_("id", person_ids)
        .execute()
        .data
        or []
    )
    for row in rows:
        if _looks_like_an_address(row.get("email")):
            found[row["id"]] = row["email"].strip()

    contacts = (
        sb.table("contacts")
        .select("person_id,contact_type,contact_value,is_preferred,created_at")
        .in_("person_id", person_ids)
        .execute()
        .data
        or []
    )
    by_person: dict[str, list[dict]] = {}
    for row in contacts:
        if _looks_like_an_address(row.get("contact_value")):
            by_person.setdefault(row["person_id"], []).append(row)
    for person_id, rows in by_person.items():
        found[person_id] = sorted(rows, key=_email_rank)[0]["contact_value"].strip()

    return found


def default_recipients(entity_id: str) -> list[dict]:
    """Every current director of this company, and where to write to them.

    Returns one entry PER DIRECTOR -- including the ones with no address, whose
    `email` is None and whose `reason` says why. A director silently dropped
    from the list is the failure this shape exists to prevent: the operator
    would see two chips for a three-director board and have nothing telling them
    a third person was never asked.

    Ordering is stable (appointment date, then name) so the same board produces
    the same list on every load; the send screen shows these as removable chips,
    so an unstable order would move the chip under the operator's cursor.
    """
    officers = (
        get_supabase()
        .table("entity_officers")
        .select("person_id,party_type,corporate_name,role,appointed_date,created_at")
        .eq("entity_id", entity_id)
        .eq("is_current", True)
        .in_("role", list(_VERIFICATION_ROLES))
        .execute()
        .data
        or []
    )
    if not officers:
        return []

    person_ids = [o["person_id"] for o in officers if o.get("person_id")]
    names: dict[str, str] = {}
    if person_ids:
        for row in (
            get_supabase()
            .table("persons")
            .select("id,full_name")
            .in_("id", person_ids)
            .execute()
            .data
            or []
        ):
            names[row["id"]] = row.get("full_name") or ""
    emails = _person_emails(person_ids)

    out = []
    for officer in officers:
        person_id = officer.get("person_id")
        corporate = (officer.get("party_type") or "individual") != "individual"
        name = (officer.get("corporate_name") if corporate
                else names.get(person_id or "")) or "(unnamed officer)"
        email = emails.get(person_id or "")
        if corporate:
            # A body corporate has no mailbox of its own in this schema, and
            # inventing one from its own officer list would mail a client's
            # statutory return to a third company's staff.
            reason = ("a corporate director has no address on record; add the "
                      "person who acts for it")
        elif not email:
            reason = "no email address is on record for this director"
        else:
            reason = None
        out.append({
            "person_id": person_id,
            "name": name,
            "email": email,
            "role": officer.get("role") or "director",
            "party_type": "corporate" if corporate else "individual",
            "reason": reason,
        })

    out.sort(key=lambda r: (r.get("name") or "").lower())
    return out


def entity_for(entity_id: str) -> dict:
    """The company the email is about. Raises LookupError so the router 404s."""
    rows = (
        get_supabase()
        .table("entities")
        .select("id,company_name,company_name_zh,br_number,cr_number")
        .eq("id", entity_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise LookupError(f"no entity {entity_id}")
    return rows[0]
