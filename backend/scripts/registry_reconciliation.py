"""What GSHK has to fix by hand once this PRD ships.

    python scripts/registry_reconciliation.py [--out FILE]

READ ONLY. Every statement here is a SELECT; nothing is written, and it is
safe to run against any database. It needs credentials, so it runs from a
checkout that has `.env` -- never in CI.

WHY THIS EXISTS. Blocks 0-6 make the portal refuse or highlight data that CR
would refuse. That is the right behaviour and it is also a bill: 453 companies
cannot open a case from the day it ships, and 31 identity documents carry a
number that is not what its type says it is. None of that is a defect this
codebase can fix -- somebody at GSHK has to look at each one -- so the least
this can do is hand them the list instead of letting them discover it a
company at a time.

ASCII output only: this console is cp1252 and a Chinese name or an em dash
raises UnicodeEncodeError halfway through the report.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text                          # noqa: E402

from etl.db import get_supabase_engine               # noqa: E402
from services.hkid import is_valid_hkid, split_hkid  # noqa: E402
from services.cr_forms.record_types import RECORD_TYPES  # noqa: E402
from services.cr_forms.readiness import filing_problems  # noqa: E402

#: Names suggesting a company really is limited by guarantee. Used to SUGGEST,
#: never to decide -- the share-capital derivation was tested and rejected
#: because it would have stamped ~214 private companies as guarantee companies
#: on a statutory return (PRD section 7.4).
GUARANTEE_HINTS = ("ASSOCIATION", "SOCIETY", "SCHOOL", "FOUNDATION", "CHARIT",
                   "INSTITUTE", "CHURCH", "COUNCIL", "FEDERATION", "ALUMNI")


def _rows(conn, sql, **params):
    return list(conn.execute(text(sql), params))


def ascii_safe(value) -> str:
    """A value this cp1252 console can actually print.

    My own prose being ASCII is not enough: the DATA is company and person
    names, and plenty of them are Chinese. Losing the whole report to one
    name is worse than transliterating it, so non-encodable characters become
    '?' and the row still names the record by its number.
    """
    return str(value if value is not None else "-").encode(
        "ascii", "replace").decode("ascii")


def is_mainland_id(number: str) -> bool:
    """An 18-character Mainland China resident identity number.

    The last character is a check character that may be 'X', which is why
    `isdigit()` on the whole string is the wrong test -- it undercounts, and
    the ones it misses are exactly the ones that look most like a typo.
    """
    number = (number or "").strip().upper()
    return (len(number) == 18
            and number[:17].isdigit()
            and (number[17].isdigit() or number[17] == "X"))


def identity_documents(conn, out):
    """The 31 rows the HKID check digit would refuse (PRD section 11.2)."""
    rows = _rows(conn, """
        SELECT d.id, d.person_id, d.id_number, p.full_name
          FROM person_identity_documents d
          JOIN persons p ON p.id = d.person_id
         WHERE d.id_type = 'hkid' AND d.id_number IS NOT NULL
    """)

    wrong_digit, unparseable = [], []
    for row in rows:
        number = (row.id_number or "").strip()
        if is_valid_hkid(number):
            continue
        # Split tells the two apart: a number that PARSES as an HKID but fails
        # its check digit is a typo. One that does not parse at all is
        # usually a different document filed under the wrong type.
        (wrong_digit if split_hkid(number) else unparseable).append(row)

    mainland = [r for r in unparseable if is_mainland_id(r.id_number)]

    out(f"IDENTITY DOCUMENTS - {len(rows)} stored as id_type='hkid'")
    out(f"  pass the check digit      {len(rows) - len(wrong_digit) - len(unparseable)}")
    out(f"  FAIL the check digit      {len(wrong_digit)}")
    out(f"  do not parse as an HKID   {len(unparseable)}"
        f"   (of which {len(mainland)} are 18-digit Mainland China IDs)")
    out("")
    out("  None of these is frozen: validation runs only when the number is")
    out("  itself being written (D4), so every other field stays editable.")
    out("")

    if wrong_digit:
        out("  WRONG CHECK DIGIT - retype the number:")
        for r in wrong_digit:
            out(f"    {ascii_safe(r.id_number):22} {ascii_safe(r.full_name)}")
        out("")
    if mainland:
        out("  MAINLAND CHINA ID FILED AS HKID - change the document type to")
        out("  'china_id'; the number itself is probably correct:")
        for r in mainland:
            out(f"    {ascii_safe(r.id_number):22} {ascii_safe(r.full_name)}")
        out("")
    other = [r for r in unparseable if r not in mainland]
    if other:
        out("  NEITHER - look at each one:")
        for r in other:
            out(f"    {ascii_safe(r.id_number)[:22]:22} {ascii_safe(r.full_name)}")
        out("")


def filing_blockers(conn, out):
    """Who cannot open a case from the day this ships (section 11.1 / OQ-2).

    Runs the API's OWN `filing_problems` over every client company rather
    than reimplementing the rule in SQL. A report that counts blocked
    companies differently from the code that blocks them is worse than no
    report -- and the first draft of this did exactly that, missing 4
    companies whose share class lacks only `issued_amount`.
    """
    companies = _rows(conn, """
        SELECT e.id, e.company_name, e.br_number, a.country
          FROM entities e
          LEFT JOIN addresses a ON a.id = e.registered_address_id
         WHERE e.is_client
         ORDER BY e.company_name
    """)
    classes: dict[str, list[dict]] = {}
    for row in _rows(conn, """
        SELECT s.entity_id, s.class_name, s.currency,
               s.total_issued, s.issued_amount, s.total_paid
          FROM share_classes s
          JOIN entities e ON e.id = s.entity_id
         WHERE e.is_client
    """):
        classes.setdefault(str(row.entity_id), []).append(dict(row._mapping))

    blocked, by_field = [], {}
    for company in companies:
        problems = filing_problems({
            "registered_address": {"country": company.country} if company.country else None,
            "share_classes": classes.get(str(company.id), []),
        })
        if not problems:
            continue
        blocked.append((company, problems))
        for problem in problems:
            by_field.setdefault(problem["field"], []).append(company)

    total = len(companies)
    out(f"CANNOT OPEN A CASE - {len(blocked)} of {total} client companies "
        f"({100 * len(blocked) / max(total, 1):.1f}%)")
    for field, rows in sorted(by_field.items(), key=lambda kv: -len(kv[1])):
        out(f"  {field:34} {len(rows)}")
    overlap = sum(len(v) for v in by_field.values()) - len(blocked)
    out(f"  (counts overlap by {overlap}: a company can fail more than one)")
    out("")
    out("  This is the intended effect of OQ-2. Each of these genuinely cannot")
    out("  produce a valid return, so the block converts a failure discovered")
    out("  at CR -- after a chargeable, irreversible submit -- into one visible")
    out("  on the profile.")
    out("")
    for field, rows in sorted(by_field.items(), key=lambda kv: -len(kv[1])):
        _sample(out, f"  {field}", rows)


def ownership_gap(conn, out):
    """OQ-1 -- and whose gap it is."""
    rows = _rows(conn, """
        SELECT e.id, e.company_name, e.vp_source_key
          FROM entities e
         WHERE e.is_client
           AND NOT EXISTS (SELECT 1 FROM share_classes s WHERE s.entity_id = e.id)
           AND NOT EXISTS (SELECT 1 FROM shareholdings h WHERE h.entity_id = e.id)
         ORDER BY e.company_name
    """)
    hinted = [r for r in rows
              if any(h in (r.company_name or "").upper() for h in GUARANTEE_HINTS)]

    out(f"NO OWNERSHIP DATA AT ALL - {len(rows)} client companies")
    out("  No share classes AND no shareholdings. Checked upstream during")
    out("  Block 3: Viewpoint holds no ShareCapital rows for these either, so")
    out("  this is a data-entry gap at GSHK, not something the ETL dropped.")
    out("")
    out(f"  Of these, {len(hinted)} carry a name suggesting a company limited by")
    out("  guarantee. Listed for a human to confirm -- company_type is NEVER")
    out("  derived as 'G', because the share-capital rule that looked sound")
    out("  would have mislabelled ~214 private companies (PRD section 7.4).")
    for r in hinted:
        out(f"    {ascii_safe(r.company_name)}")
    out("")


def hand_entered_fields(conn, out):
    """The fields that ship empty because nobody has the data (PRD section 7.5)."""
    counts = _rows(conn, """
        SELECT
          count(*) FILTER (WHERE coalesce(btrim(business_nature_code), '') <> '')
            AS nature,
          count(*) FILTER (WHERE coalesce(btrim(mortgages_total), '') <> '')
            AS mortgages,
          count(*) FILTER (WHERE company_type IN ('P', 'N', 'G')) AS cr_type,
          count(*) FILTER (WHERE coalesce(btrim(company_type), '') <> ''
                             AND company_type NOT IN ('P', 'N', 'G')) AS legacy_type,
          count(*) FILTER (WHERE coalesce(btrim(company_type), '') = '') AS no_type,
          count(*) AS total
          FROM entities WHERE is_client
    """)[0]

    out(f"FIELDS WITH NO SOURCE - of {counts.total} client companies")
    out(f"  business nature recorded   {counts.nature}"
        "   (Viewpoint holds none: BusNames.BusNature is empty on all 5,028 rows)")
    out(f"  mortgages total recorded   {counts.mortgages}"
        "   (no Viewpoint column matches)")
    out("")
    out("  Both are hand-entered by design. Neither is Mandatory=Y on either")
    out("  form, so neither blocks a filing however empty it stays.")
    out("")
    out("COMPANY TYPE")
    out(f"  CR code (P/N/G)            {counts.cr_type}")
    out(f"  legacy free text           {counts.legacy_type}"
        "   (still saveable; only a NEW value must be CR's)")
    out(f"  none recorded              {counts.no_type}")
    out("")


def record_locations(conn, out):
    """NAR1 s16 coverage after Block 3's seed (OQ-3)."""
    rows = _rows(conn, """
        SELECT record_type, count(*) AS n,
               count(*) FILTER (WHERE address_id IS NOT NULL) AS located
          FROM entity_record_locations
         GROUP BY record_type
    """)
    seeded = {r.record_type: r for r in rows}

    out("STATUTORY RECORD LOCATIONS - NAR1 s16")
    for code, label in RECORD_TYPES:
        row = seeded.get(code)
        located = row.located if row else 0
        out(f"  {code}  {label:46} {located}")
    out("")
    out("  A register with no address is shown on the profile as 'Not")
    out("  recorded' rather than omitted: an unanswered question must not")
    out("  render as an answered one.")
    out("")


def _sample(out, title, rows, limit=25, fmt=None):
    if not rows:
        return
    fmt = fmt or (lambda r: f"{ascii_safe(r.br_number):>10}  {ascii_safe(r.company_name)}")
    out(f"{title} ({len(rows)})")
    for r in rows[:limit]:
        out(f"    {fmt(r)}")
    if len(rows) > limit:
        out(f"    ... and {len(rows) - limit} more")
    out("")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", help="write the report to a file as well")
    args = parser.parse_args()

    lines: list[str] = []

    def out(line=""):
        lines.append(line)
        print(line)

    out("REGISTRY RECONCILIATION")
    out("What has to be fixed by hand, and by whom. Read only.")
    out("=" * 72)
    out("")

    engine = get_supabase_engine()
    with engine.connect() as conn:
        identity_documents(conn, out)
        out("=" * 72)
        out("")
        filing_blockers(conn, out)
        out("=" * 72)
        out("")
        ownership_gap(conn, out)
        out("=" * 72)
        out("")
        hand_entered_fields(conn, out)
        out("=" * 72)
        out("")
        record_locations(conn, out)

    if args.out:
        Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
