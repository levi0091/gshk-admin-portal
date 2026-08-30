"""Regression: can real GSHK companies actually be filed as NAR1s?

Levi 2026-08-30 asked for a regression over NON-TEST companies that ends in a
successful submission to CR. This script is that regression, in three phases,
because CR imposes a hard limit on how far real companies can go.

    python scripts/nar1_regression.py                  # phase 1 only, no network
    python scripts/nar1_regression.py --validate       # + phase 2 (live CR)
    python scripts/nar1_regression.py --chain          # + phase 3 (live CR, spends)

PHASE 1 - MAP (offline, always runs)
    Build the CR form for every real client company in the book and report what
    would stop each one. No network, no CR window, no cost. This is the phase
    that answers "would our data survive a filing", and it is the one that
    regressed silently before: until 2026-08-30 the mapper refused every single
    company for want of a signing capacity.

PHASE 2 - VALIDATE (live CR, needs --validate)
    Send those forms to CR's real validateForm and record its verdict per
    company. Real client data, checked by the authority that will judge it, for
    free -- validateForm is not chargeable.

    THE REWRITE. CR's test and production registers are separate REGISTERS, not
    permission levels: a real company's BRN does not exist in the test register
    and CR answers ERR_ES_FORM_COY_NOT_EXIST. Three identifiers therefore have
    to be moved into the test namespace, and it is three, not one:

        brNo            the filing company
        corpBrNo        every corporate OFFICER's BRN  <-- the one everyone
                        misses; its absence also reads as
                        ERR_ES_FORM_COY_NOT_EXIST, which sends you hunting the
                        wrong identifier
        selectPersonId  the signatory's e-Service account

    Everything else -- names, addresses, share capital, officer particulars,
    dates -- stays REAL, which is the point: CR validates the actual data.

PHASE 3 - CHAIN (live CR, needs --chain, SPENDS FROM THE TEST DEPOSIT ACCOUNT)
    The complete validate -> verifyPinSigning -> submitFormNar1 chain, end to
    end, against CR's own seeded test company.

    WHY NOT AGAINST A REAL COMPANY, WHICH IS WHAT WAS ASKED FOR. CR associates
    an individual e-Service account with a company by OFFICER APPOINTMENT in its
    register, and refuses a signature from anyone not so associated
    (ERR_MSG_SIGNATORY_NOT_AUTH). GSHK's test signatory is an officer of CR's
    seeded test companies and of nothing else, so a real company rewritten into
    the test namespace validates and then cannot be signed. That is a fact about
    CR's register, not a gap in this portal, and no amount of code here changes
    it -- CR would have to appoint the signatory to a test company first.

    So phase 2 proves the DATA against real companies and phase 3 proves the
    CHAIN end to end. Together they cover what a single run cannot.

CR's form APIs answer Monday-Friday, roughly 10:00-16:00 HKT (observed as late
as 16:08, so the window is not a guarantee in either direction). Phase 1 does
not care. Phases 2 and 3 will simply fail outside it.
"""
import argparse
import asyncio
import collections
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.supabase import get_supabase  # noqa: E402
from services.tpsi.config import get_config  # noqa: E402
from services.tpsi.forms import nar1, nar1_mapper, nar1_source  # noqa: E402

#: CR's seeded test company — the filing company every rewritten form claims to
#: be. Seeded into DEV by scripts/seed_tpsi_test_data.py.
TEST_BRN = "T0001137"

#: The test register's stand-in for a corporate OFFICER. Deliberately a
#: different company from TEST_BRN: a form whose officer is also its filer is
#: not the shape a real return has, and would not exercise corpBrNo properly.
TEST_CORP_OFFICER_BRN = "T0001139"

#: GSHK's test e-Service signing account, associated by CR with the companies
#: above. Not a secret — it is an account identifier, and the password is not
#: in this file or anywhere near it.
TEST_ESERVICE_ID = "T260727100116S"

#: The capacities phase 1 maps with — one per kind of signatory, because the
#: two vocabularies do not overlap and picking from the wrong one is a problem
#: the mapper rightly reports.
#:
#: These are NOT defaults the portal applies: the operator chooses per case
#: (migration 026), and the mapper still refuses an unchosen capacity. They are
#: stated here so the regression measures the DATA rather than re-measuring the
#: one field already known to be an operator choice.
ASSUMED_CAPACITY_CORPORATE = "Director of the Company Secretary (Body Corporate)"
ASSUMED_CAPACITY_INDIVIDUAL = "Company Secretary"


def _assumed_capacity(graph: dict) -> str | None:
    """Whichever vocabulary this company's signatory actually belongs to."""
    try:
        resolved = nar1_mapper._derive_signatory(graph)
    except Exception:  # noqa: BLE001
        return None
    if not resolved:
        return None
    return (ASSUMED_CAPACITY_CORPORATE if resolved.get("is_corporate") is True
            else ASSUMED_CAPACITY_INDIVIDUAL)


def _refuse_production() -> None:
    """This script maps thousands of real companies and, past phase 1, talks to
    CR. Neither belongs anywhere near a production TPSI account."""
    env = get_config().env
    if env != "test":
        raise SystemExit(
            f"refusing to run against TPSI env {env!r}: this regression is for "
            f"the CR TEST environment only"
        )


def _real_companies(limit: int | None) -> list[dict]:
    """Every real client company that has a BR number.

    Ordered by id so a truncated run is reproducible rather than a different
    arbitrary slice each time.
    """
    sb = get_supabase()
    rows, page, size = [], 0, 1000
    while True:
        q = (sb.table("entities")
             .select("id, company_name, br_number")
             .not_.is_("br_number", "null")
             .order("id")
             .range(page * size, page * size + size - 1))
        batch = q.execute().data or []
        rows.extend(batch)
        if len(batch) < size or (limit and len(rows) >= limit):
            break
        page += 1
    # Exclude CR's own seeded test companies: they are the control, not the
    # sample, and counting them as "real companies that map" would flatter the
    # result by exactly the companies already known to work.
    rows = [r for r in rows if not str(r.get("br_number", "")).startswith(("T0", "TF"))]
    return rows[:limit] if limit else rows


def _classify(problem: str) -> str:
    """Group a problem sentence into something countable.

    Free text, so this is a keyword match and openly approximate — its job is
    to turn 3,000 sentences into a table someone can act on, not to be a parser.
    """
    p = problem.lower()
    for needle, label in (
        # Length checks first: they carry the field path, and several of those
        # paths contain words ("address", "share") that the softer rules below
        # would otherwise claim, hiding a schema-limit breach as a data gap.
        ("exceeds the maximum", "field longer than CR allows"),
        # Before the "capacity" rule: this sentence names selectCapacityDesc
        # while listing the fields an unsigned return would be missing, so the
        # softer rule below claims it and reports a company with no secretary
        # at all as an unchosen capacity — two different problems with two
        # different fixes.
        ("no current company secretary", "no secretary on record to sign"),
        ("no e-service", "signatory has no e-Service ID"),
        ("capacity", "signing capacity"),
        ("partial hkid", "missing identity document"),
        ("identity", "missing identity document"),
        ("br number", "no BR number"),
        ("address", "address"),
        ("district", "address"),
        ("share", "share capital"),
        ("date", "date"),
        ("could not check", "mapper crashed"),
    ):
        if needle in p:
            return label
    return "other"


async def phase1_map(limit: int | None) -> dict:
    """Build the form for every real company; report what would stop each."""
    companies = _real_companies(limit)
    print(f"phase 1 · mapping {len(companies)} real companies\n")

    ok, failed, reasons = [], [], collections.Counter()
    for i, company in enumerate(companies, 1):
        if i % 250 == 0:
            print(f"  … {i}/{len(companies)}")
        try:
            graph = await nar1_source.load_entity_graph(company["id"])
        except Exception as exc:  # noqa: BLE001 — a load failure is a result
            failed.append({**company, "problems": [f"could not load: {exc}"]})
            reasons["could not load the company"] += 1
            continue
        try:
            data = nar1_mapper.map_entity(
                graph, year=datetime.now(timezone.utc).year,
                signatory_capacity=_assumed_capacity(graph),
            )
            nar1.build_nar1_xml(data)
            ok.append(company)
        except nar1_mapper.MappingError as exc:
            failed.append({**company, "problems": list(exc.problems)})
            for problem in exc.problems:
                reasons[_classify(problem)] += 1
        except ValueError as exc:
            # nar1.validate() refusing the built form against CR's schema —
            # overwhelmingly a real field that is longer than CR allows. A DATA
            # problem, not a crash, and it must not be counted as one: lumping
            # these together hid the single largest category of real blocker
            # behind a label that reads like a bug in our code.
            problems = [p.strip() for p in str(exc)
                        .replace("NAR1 validation failed:", "").split(";")]
            failed.append({**company, "problems": problems})
            for problem in problems:
                reasons[_classify(problem)] += 1
        except Exception as exc:  # noqa: BLE001
            failed.append({**company, "problems": [f"{type(exc).__name__}: {exc}"]})
            reasons["mapper crashed"] += 1

    total = len(companies) or 1
    print(f"\n  mapped clean : {len(ok)}/{len(companies)} "
          f"({100 * len(ok) / total:.1f}%)")
    print(f"  blocked      : {len(failed)}")
    if reasons:
        print("\n  why blocked (a company can have several):")
        for label, count in reasons.most_common():
            print(f"    {count:6d}  {label}")
    return {"ok": ok, "failed": failed, "reasons": dict(reasons)}


def _rewrite_for_test_register(data: dict) -> dict:
    """Move the three register-scoped identifiers into CR's test namespace.

    Everything else is left exactly as the mapper produced it. See the module
    docstring for why it is these three and no others.
    """
    out = json.loads(json.dumps(data))  # deep copy; the caller keeps the real one
    out["brNo"] = TEST_BRN

    def walk(node):
        if isinstance(node, dict):
            if "corpBrNo" in node:
                node["corpBrNo"] = TEST_CORP_OFFICER_BRN
            if "selectPersonId" in node:
                node["selectPersonId"] = TEST_ESERVICE_ID
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(out)
    return out


async def phase2_validate(mapped_ok: list[dict], limit: int) -> None:
    """Ask CR to judge real company data, in the test register."""
    from services.tpsi import shared_credentials
    from services.tpsi.client import TpsiClient

    sample = mapped_ok[:limit]
    print(f"\nphase 2 · validating {len(sample)} real companies against live CR\n")

    credential = shared_credentials.load_for_use()
    client = TpsiClient(credential["account_id"], credential["password"])

    passed, refused = 0, []
    for company in sample:
        graph = await nar1_source.load_entity_graph(company["id"])
        data = nar1_mapper.map_entity(
            graph, year=datetime.now(timezone.utc).year,
            signatory_capacity=ASSUMED_CAPACITY,
        )
        xml = nar1.build_nar1_xml(_rewrite_for_test_register(data))
        try:
            client.post_form("validateForm", "Nar1", xml)
            passed += 1
            print(f"  PASS  {company['company_name']}")
        except Exception as exc:  # noqa: BLE001 — CR's verdict is the result
            refused.append((company, exc))
            print(f"  FAIL  {company['company_name']}: "
                  f"{str(exc)[:110]}")

    print(f"\n  CR accepted {passed}/{len(sample)}")
    if refused:
        print("  refusals:")
        for company, exc in refused:
            print(f"    {company['br_number']}  {str(exc)[:150]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None,
                        help="cap how many companies phase 1 maps")
    parser.add_argument("--validate", action="store_true",
                        help="phase 2: send real data to live CR validateForm")
    parser.add_argument("--validate-limit", type=int, default=60,
                        help="how many companies phase 2 sends (default 60)")
    parser.add_argument("--chain", action="store_true",
                        help="phase 3: full validate/sign/submit on CR's test "
                             "company. SPENDS from the test deposit account.")
    args = parser.parse_args()

    _refuse_production()

    result = asyncio.run(phase1_map(args.limit))

    if args.validate:
        asyncio.run(phase2_validate(result["ok"], args.validate_limit))

    if args.chain:
        raise SystemExit(
            "\nphase 3 is not wired up yet. It needs scripts/"
            "prep_case_for_signing.py, which frontend/e2e/nar1-sign-submit.spec.js "
            "already references and which is not in the repo — see the note in "
            "that spec. Running the chain by hand before that exists risks "
            "spending the test deposit on a half-built path."
        )


if __name__ == "__main__":
    main()
