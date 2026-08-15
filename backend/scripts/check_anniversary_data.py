"""OQ-5 / F-6 gate check: is days-to-anniversary computable from DEV data today?

The PRD parks F-6 (the Date-to-Anniversary column on the Company listing) in
Workstream 1 only if the value can be derived from company data already in DEV.
W-3 goes further and wants a default that hides companies >60 days past their
anniversary "that still have no NAR1 renewal done" -- which needs a second fact:
whether a renewal exists for the current period.

Goes over PostgREST, not psycopg2: the direct db.*.supabase.co host does not
resolve from this machine (same DNS failure CLAUDE.md records for alembic).

Read-only. Prints counts and a date histogram, never rows.
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import httpx
from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND / ".env")

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
if not URL or not KEY:
    sys.exit("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing from backend/.env")

HEADERS = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
TODAY = date.today()


def count(client: httpx.Client, table: str, query: str = "") -> int | str:
    """Row count via PostgREST's Content-Range header — never pulls the rows."""
    url = f"{URL}/rest/v1/{table}?select=id&limit=1" + (f"&{query}" if query else "")
    r = client.get(url, headers={**HEADERS, "Prefer": "count=exact"})
    if r.status_code >= 400:
        return f"ERROR {r.status_code}: {r.text[:90]}"
    return int(r.headers.get("content-range", "*/0").split("/")[-1])


def page(client: httpx.Client, table: str, select: str, query: str = "") -> list[dict]:
    """Every row of one narrow projection, walked in PostgREST-sized pages."""
    rows: list[dict] = []
    step = 1000
    while True:
        url = f"{URL}/rest/v1/{table}?select={select}&limit={step}&offset={len(rows)}"
        if query:
            url += f"&{query}"
        r = client.get(url, headers=HEADERS)
        r.raise_for_status()
        batch = r.json()
        rows.extend(batch)
        if len(batch) < step:
            return rows


def days_to_anniversary(incorporated: date, today: date) -> int:
    """Days until the next anniversary of incorporation — negative never happens."""
    try:
        this_year = incorporated.replace(year=today.year)
    except ValueError:  # 29 Feb in a common year
        this_year = incorporated.replace(year=today.year, day=28)
    if this_year >= today:
        return (this_year - today).days
    try:
        nxt = incorporated.replace(year=today.year + 1)
    except ValueError:
        nxt = incorporated.replace(year=today.year + 1, day=28)
    return (nxt - today).days


def main() -> None:
    with httpx.Client(timeout=90) as c:
        print(f"today = {TODAY}\n")
        print("── counts ─────────────────────────────────────────────")
        checks = [
            ("entities: total", "entities", ""),
            ("entities: is_client", "entities", "is_client=is.true"),
            ("entities: incorporation_date present", "entities", "incorporation_date=not.is.null"),
            ("entities: is_client AND incorporation_date", "entities",
             "is_client=is.true&incorporation_date=not.is.null"),
            ("nar1_cases: total", "nar1_cases", ""),
            ("form_filings: total", "form_filings", ""),
            ("form_filings: form_code ilike %NAR%", "form_filings", "form_code=ilike.*NAR*"),
            ("form_filings: filed_date present", "form_filings", "filed_date=not.is.null"),
        ]
        for label, table, query in checks:
            print(f"{label:48} {count(c, table, query)}")

        print("\n── NAR1 renewal evidence (W-3 needs this) ─────────────")
        codes = Counter(
            (r.get("form_code") or "(null)")
            for r in page(c, "form_filings", "form_code")
        )
        print(f"{'form_filings distinct form_code':48} "
              f"{dict(codes.most_common(8)) if codes else '(table empty)'}")

        print("\n── can we tell a NAR1 was actually filed, and when? ───")
        for label, query in [
            ("NAR1 filings: generated_date present", "form_code=ilike.*NAR1*&generated_date=not.is.null"),
            ("NAR1 filings: signed_date present", "form_code=ilike.*NAR1*&signed_date=not.is.null"),
            ("NAR1 filings: filed_date present", "form_code=ilike.*NAR1*&filed_date=not.is.null"),
            ("NAR1 filings: filed_with_cr true", "form_code=ilike.*NAR1*&filed_with_cr=is.true"),
            ("NAR1 filings: file_deadline present", "form_code=ilike.*NAR1*&file_deadline=not.is.null"),
        ]:
            print(f"{label:48} {count(c, 'form_filings', query)}")

        nar1 = page(c, "form_filings", "generated_date,status", "form_code=ilike.*NAR1*")
        years = Counter(
            (r["generated_date"] or "")[:4] or "(null)" for r in nar1
        )
        print(f"{'NAR1 generated_date by year':48} {dict(sorted(years.items())[-8:])}")
        print(f"{'NAR1 status values':48} "
              f"{dict(Counter(r.get('status') or '(null)' for r in nar1).most_common(6))}")

        print("\n── days-to-anniversary distribution (client cos) ──────")
        rows = page(c, "entities", "incorporation_date",
                    "is_client=is.true&incorporation_date=not.is.null")
        gaps = [days_to_anniversary(date.fromisoformat(r["incorporation_date"]), TODAY)
                for r in rows]
        buckets = [
            ("computable at all", lambda d: True),
            ("anniversary in <= 30 days", lambda d: d <= 30),
            ("anniversary in <= 60 days", lambda d: d <= 60),
            ("anniversary in <= 90 days", lambda d: d <= 90),
            ("anniversary > 305 days away (just passed)", lambda d: d > 305),
        ]
        for label, pred in buckets:
            print(f"{label:48} {sum(1 for d in gaps if pred(d))}")

        # W-3's default hides ">60 days past anniversary AND no NAR1 renewal
        # done". There is no "filed" fact to read (2 rows), so the only usable
        # proxy is "a NAR1 was generated on or after the last anniversary".
        # How much of the list would that default hide?
        print("\n── what W-3's default 60-day cutoff would hide ────────")
        latest: dict[str, str] = {}
        for r in page(c, "form_filings", "entity_id,generated_date",
                      "form_code=ilike.*NAR1*&generated_date=not.is.null"):
            eid, gen = r["entity_id"], r["generated_date"]
            if eid and (eid not in latest or gen > latest[eid]):
                latest[eid] = gen

        cos = page(c, "entities", "id,incorporation_date,status",
                   "is_client=is.true&incorporation_date=not.is.null")
        print(f"{'client-co status mix':48} "
              f"{dict(Counter(r.get('status') or '(null)' for r in cos).most_common(6))}")
        live = [r for r in cos if r.get("status") == "live"]
        print(f"{'live client cos with an incorporation_date':48} {len(live)}")
        cos = live
        overdue60 = renewed = unrenewed = no_filing_at_all = 0
        for co in cos:
            inc = date.fromisoformat(co["incorporation_date"])
            last_anniv = date(TODAY.year, inc.month, min(inc.day, 28))
            if last_anniv > TODAY:
                last_anniv = date(TODAY.year - 1, inc.month, min(inc.day, 28))
            if (TODAY - last_anniv).days <= 60:
                continue
            overdue60 += 1
            gen = latest.get(co["id"])
            if gen is None:
                no_filing_at_all += 1
                unrenewed += 1
            elif date.fromisoformat(gen) >= last_anniv:
                renewed += 1
            else:
                unrenewed += 1
        print(f"{'client cos >60 days past anniversary':48} {overdue60}")
        print(f"{'  .. NAR1 generated since that anniversary':48} {renewed}")
        print(f"{'  .. no NAR1 since  -> HIDDEN by the default':48} {unrenewed}")
        print(f"{'  .. of those, never had any NAR1 at all':48} {no_filing_at_all}")
        print(f"{'companies left visible by default':48} {len(cos) - unrenewed}")


if __name__ == "__main__":
    main()
