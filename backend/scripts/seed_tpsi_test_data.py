"""Seed CR's TPSI TEST accounts, companies and officer associations into DEV.

Deliberately NOT an Alembic migration: migrations run in every environment, and
this data must never reach PROD. Idempotent — safe to re-run.

    cd backend && uv run python scripts/seed_tpsi_test_data.py [--dry-run]

Source: docs/TPSI260727100116.xlsx
  Accounts             3 individual TPSI logins (Director / Secretary / Reserve).
                       There are NO corporate login accounts: "corporate
                       officers" are companies acting as officers, they hold no
                       TPSI credentials, and CR forbids them from PIN-signing.
  Companies            5 test companies (4 local + 1 registered non-HK).
  Individual Officers  officer associations for the individual accounts.
  Corporate Officers   companies acting as officers of other companies.

The officer associations are not optional decoration. CR rejects a signature
from anyone not associated with the company as at the signature date
(ERR_MSG_SIGNATORY_NOT_AUTH), so without them the Block 4 signing flow cannot
be exercised against TEST at all.

Idempotency and the seed marker are the same thing: every row is written with
`vp_source_key = 'tpsi_test:<natural key>'`, which is the only unique
constraint on these tables besides the primary key. Re-running upserts in place;
finding seeded rows later is a `vp_source_key LIKE 'tpsi_test:%'` query.
"""
import os
import sys

from openpyxl import load_workbook

# Ensure `backend/` is importable when run as a script from that directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.supabase import get_supabase  # noqa: E402
from services.tpsi.config import get_config  # noqa: E402

SOURCE = "../docs/TPSI260727100116.xlsx"
MARKER = "tpsi_test:"

# Substrings that mean "this is production" in a connection string.
_PROD_MARKERS = ("prod", "-prd", "production")

# CR "Capacity" -> officer_role enum.
_ROLE = {
    "director": "director",
    "company secretary": "company_secretary",
    "secretary": "company_secretary",
    "reserve director": "reserve_director",
    "authorised representative": "authorised_rep",
    "authorized representative": "authorised_rep",
}


def assert_safe_environment() -> None:
    """Refuse to run anywhere that might be production.

    Two independent checks, because either one alone can be wrong: TPSI_ENV
    describes which CR environment we talk to, DATABASE_URL describes which
    database we write to, and a misconfigured deploy can mismatch them.
    """
    if get_config().env != "test":
        sys.exit("REFUSING: TPSI_ENV is not 'test'. This script never runs against PROD.")

    dsn = (os.environ.get("DATABASE_URL") or "").lower()
    if any(marker in dsn for marker in _PROD_MARKERS):
        sys.exit(
            "REFUSING: DATABASE_URL looks like production. "
            "Point it at DEV before seeding."
        )


def _rows(sheet):
    headers = [str(c.value).strip() if c.value is not None else "" for c in sheet[1]]
    for row in sheet.iter_rows(min_row=2, values_only=True):
        record = {
            headers[i]: ("" if v is None else str(v).strip())
            for i, v in enumerate(row)
            if i < len(headers)
        }
        if any(record.values()):
            yield record


def _date(value: str) -> str | None:
    """CR writes dd/mm/yyyy; Postgres wants ISO."""
    if not value or "/" not in value:
        return None
    day, month, year = value.split("/")[:3]
    return f"{year}-{month.zfill(2)}-{day.zfill(2)}"


def _upsert_by_source_key(table: str, payload: dict) -> dict:
    """Insert-or-update keyed on vp_source_key, without ON CONFLICT.

    The vp_source_key unique indexes on entities/persons/entity_officers are
    PARTIAL (`WHERE vp_source_key IS NOT NULL`). PostgREST's `on_conflict=`
    cannot target a partial index — it has no way to emit the matching
    `index_where` clause — so an upsert against them fails with 42P10,
    "no unique or exclusion constraint matching the ON CONFLICT
    specification". Select-then-write is the portable equivalent here, and this
    seed is small enough that the extra round trip does not matter.
    """
    supabase = get_supabase()
    key = payload["vp_source_key"]
    existing = (
        supabase.table(table).select("id").eq("vp_source_key", key).execute().data
    )
    if existing:
        row_id = existing[0]["id"]
        supabase.table(table).update(payload).eq("id", row_id).execute()
        return {"id": row_id}
    return supabase.table(table).insert(payload).execute().data[0]


def seed(dry_run: bool = False) -> dict:
    assert_safe_environment()

    book = load_workbook(SOURCE, data_only=True)
    accounts = list(_rows(book["Accounts"]))
    companies = list(_rows(book["Companies"]))
    ind_officers = list(_rows(book["Individual Officers"]))
    corp_officers = list(_rows(book["Corporate Officers"]))

    summary = {
        "accounts": len(accounts),
        "companies": len(companies),
        "individual_officers": len(ind_officers),
        "corporate_officers": len(corp_officers),
    }
    print(f"source: {SOURCE}")
    for key, count in summary.items():
        print(f"  {count:>3} {key.replace('_', ' ')}")

    if dry_run:
        print("dry run - nothing written")
        return summary

    # 1. Companies -> entities.
    entity_by_brn: dict[str, str] = {}
    for company in companies:
        brn = company.get("BRN", "")
        if not brn:
            continue
        name_en = company.get("Company Name (Eng)", "")
        name_zh = company.get("Company Name (Chi)", "")
        row = _upsert_by_source_key(
            "entities",
            {
                    "vp_source_key": f"{MARKER}{brn}",
                    "br_number": brn,
                    "company_name": name_en or brn,
                    "company_name_zh": name_zh or None,
                    "name_language": "bilingual" if (name_en and name_zh) else "english",
                    "status": "live",
                    "incorporation_date": _date(company.get("Date of Incorporation", "")),
                    "incorporation_place": company.get("Place of Incorporation") or "Hong Kong",
            },
        )
        entity_by_brn[brn] = row["id"]

    # 2. The 3 individual TPSI login accounts -> persons.
    #    These are the only parties that can PIN-sign. Their TPSI/e-Service
    #    passwords are NOT stored here — presenter credentials belong in
    #    tpsi_presenter_credentials, set per user through the API.
    person_by_userid: dict[str, str] = {}
    person_by_hkid: dict[str, str] = {}
    for account in accounts:
        user_id = account.get("User ID", "")
        if not user_id:
            continue
        surname = account.get("Surname", "")
        given = account.get("Other Name in English", "")
        row = _upsert_by_source_key(
            "persons",
            {
                    "vp_source_key": f"{MARKER}{user_id}",
                    "full_name": f"{surname}, {given}".strip(", ") or user_id,
                    "surname": surname or None,
                    "given_names": given or None,
                    "full_name_zh": account.get("Name in Chinese") or None,
            },
        )
        person_by_userid[user_id] = row["id"]
        hkid = account.get("HKID", "")
        if hkid:
            person_by_hkid[hkid] = row["id"]

    # 3. Officer associations. Without these, CR rejects every signature.
    linked = 0
    for officer in ind_officers:
        brn = officer.get("BRN", "")
        entity_id = entity_by_brn.get(brn)
        person_id = person_by_hkid.get(officer.get("HKID", ""))
        if not (entity_id and person_id):
            continue
        capacity = officer.get("Capacity", "").strip().lower()
        _upsert_by_source_key(
            "entity_officers",
            {
                "vp_source_key": f"{MARKER}ind:{brn}:{officer.get('HKID')}:{capacity}",
                "entity_id": entity_id,
                "person_id": person_id,
                "party_type": "individual",
                "role": _ROLE.get(capacity, "director"),
                "appointed_date": _date(officer.get("Association Date", "")),
                "is_current": True,
            },
        )
        linked += 1

    for officer in corp_officers:
        brn = officer.get("BRN", "")
        entity_id = entity_by_brn.get(brn)
        if not entity_id:
            continue
        capacity = officer.get("Capacity", "").strip().lower()
        officer_brn = officer.get("Officer BRN", "")
        _upsert_by_source_key(
            "entity_officers",
            {
                "vp_source_key": f"{MARKER}corp:{brn}:{officer_brn}:{capacity}",
                "entity_id": entity_id,
                "person_id": None,
                "party_type": "corporate",
                "corporate_name": officer.get("Company Name (Eng)") or officer_brn,
                "role": _ROLE.get(capacity, "director"),
                "appointed_date": _date(officer.get("Association Date", "")),
                "is_current": True,
            },
        )
        linked += 1

    summary["linked"] = linked
    print(f"seeded ({linked} officer associations). Re-running is safe - every write is an upsert.")
    return summary


if __name__ == "__main__":
    seed(dry_run="--dry-run" in sys.argv)
